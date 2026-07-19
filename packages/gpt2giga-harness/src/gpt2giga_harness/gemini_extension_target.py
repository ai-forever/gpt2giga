"""Gemini extension lifecycle over documented native CLI surfaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from gpt2giga_harness.integration_installer import (
    InstallationConflictError,
    InstallationScopeError,
)
from gpt2giga_harness.integration_packages import (
    ExtensionTargetDescriptor,
    ExtensionTargetPlugin,
    InstallationScope,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationTrustDecision,
    IntegrationTrustEvidence,
    IntegrationTrustKind,
    IntegrationTrustStatus,
    assess_integration_package,
    integration_package_semantic_hash,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.types import redact_secrets


GEMINI_EXTENSION_TARGET_ID = "gemini-extension"
GEMINI_EXTENSION_TARGET_REVISION = "1"
GEMINI_EXTENSION_COMMAND_TIMEOUT_SECONDS = 30.0
MAX_GEMINI_EXTENSION_OUTPUT_CHARS = 128_000
MAX_GEMINI_EXTENSION_FILES = 512
MAX_GEMINI_EXTENSION_FILE_BYTES = 16 * 1024 * 1024
MAX_GEMINI_EXTENSION_TOTAL_BYTES = 64 * 1024 * 1024
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_EXTENSION_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9._-]+)?\Z")
_PLAN_RE = re.compile(r"plan_[0-9a-f]{64}\Z")


class GeminiExtensionSourceKind(str, Enum):
    """Documented Gemini extension source families."""

    LOCAL = "local"
    GIT = "git"
    GALLERY = "gallery"


class GeminiExtensionTargetError(RuntimeError):
    """Base error for Gemini extension target operations."""


class GeminiExtensionCommandError(GeminiExtensionTargetError):
    """Raised when a bounded native Gemini command cannot prove its result."""


class GeminiExtensionPolicyError(GeminiExtensionTargetError):
    """Raised when policy or explicit native consent denies an action."""


@dataclass(frozen=True)
class GeminiExtensionSource:
    """One explicit local, immutable Git, or gallery extension source."""

    kind: GeminiExtensionSourceKind
    location: str
    ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GeminiExtensionSourceKind):
            raise ValueError("Gemini extension source kind is invalid")
        if not isinstance(self.location, str) or not self.location.strip():
            raise ValueError("Gemini extension source location is invalid")
        _validate_secret_free(self.location, "Gemini extension source location")
        if self.kind is GeminiExtensionSourceKind.LOCAL:
            if self.ref is not None:
                raise ValueError("local Gemini extension sources cannot use a Git ref")
        elif self.kind is GeminiExtensionSourceKind.GIT:
            if self.ref is None:
                raise ValueError(
                    "Git Gemini extension sources require an immutable ref"
                )
            _validate_identity(self.ref, "Gemini extension source ref")
            object.__setattr__(self, "location", _canonical_git_source(self.location))
        else:
            if self.ref is not None:
                raise ValueError("Gemini gallery entries do not select an install ref")
            object.__setattr__(
                self, "location", _canonical_gallery_source(self.location)
            )


@dataclass(frozen=True)
class GeminiExtensionRequest:
    """One immutable integration projected to an explicit Gemini scope."""

    package: IntegrationPackage
    scope: InstallationScope
    root: Path
    source: GeminiExtensionSource
    extension_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("Gemini extension request requires an IntegrationPackage")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("Gemini extension request scope is invalid")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.source, GeminiExtensionSource):
            raise TypeError("Gemini extension request source is invalid")
        _validate_extension_name(self.extension_name, "Gemini extension name")
        if not any(
            item.type is IntegrationComponentType.EXTENSION
            for item in self.package.components
        ):
            raise ValueError(
                "Gemini extension request package has no extension component"
            )
        if self.scope not in self.package.scopes:
            raise ValueError(
                "Gemini extension request package does not support the scope"
            )
        if not any(
            item.target_id == GEMINI_EXTENSION_TARGET_ID
            for item in self.package.compatibility
        ):
            raise ValueError(
                "Gemini extension request package is not target-compatible"
            )
        if self.source.kind is GeminiExtensionSourceKind.LOCAL:
            if self.package.source_type is not IntegrationSourceType.LOCAL:
                raise ValueError("local Gemini source requires a local package source")
            if _absolute_path(Path(self.package.source)) != _absolute_path(
                Path(self.source.location)
            ):
                raise ValueError("Gemini extension source does not match the package")
        elif self.source.kind is GeminiExtensionSourceKind.GIT:
            if self.package.source_type is not IntegrationSourceType.GIT:
                raise ValueError("Git Gemini source requires a Git package source")
            if _canonical_git_source(self.package.source) != self.source.location:
                raise ValueError("Gemini extension source does not match the package")
            if self.package.immutable_ref != self.source.ref:
                raise ValueError(
                    "Gemini extension ref does not match the immutable package"
                )
        else:
            if (
                self.package.source_type
                is not IntegrationSourceType.PROVIDER_MARKETPLACE
            ):
                raise ValueError("Gemini gallery source requires a marketplace package")
            if _canonical_gallery_source(self.package.source) != self.source.location:
                raise ValueError("Gemini gallery source does not match the package")


@dataclass(frozen=True)
class GeminiExtensionApproval:
    """Explicit authority for one exact provider-native mutation preview."""

    plan_id: str
    authority: str
    native_consent_acknowledged: bool = False
    source_trust_acknowledged: bool = False
    allow_network: bool = False
    allow_user_home: bool = False

    def __post_init__(self) -> None:
        if not _PLAN_RE.fullmatch(self.plan_id):
            raise ValueError("Gemini extension approval plan_id is invalid")
        _validate_identity(self.authority, "Gemini extension approval authority")
        for field_name in (
            "native_consent_acknowledged",
            "source_trust_acknowledged",
            "allow_network",
            "allow_user_home",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(
                    f"Gemini extension approval {field_name} must be a boolean"
                )


@dataclass(frozen=True)
class GeminiExtensionPlan:
    """Content-free preview bound to source, native state, policy, and restart."""

    action: str
    plan_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    extension_name: str
    source_sha256: str
    scope: InstallationScope
    root: Path
    native_scope: str
    expected_version: str | None
    expected_enabled: bool | None
    expected_source_sha256: str | None
    network_required: bool
    native_consent_required: bool
    source_trust_required: bool
    restart_required: bool
    policy_status: str
    command_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeminiExtensionProbe:
    """Bounded installed-Gemini capability evidence."""

    status: str
    version: str | None
    command: str
    capabilities: tuple[str, ...]
    gallery_automation: str
    evidence: str


@dataclass(frozen=True)
class GeminiExtensionInstallation:
    """Content-free native Gemini extension discovery projection."""

    name: str
    version: str
    source_kind: str
    source_sha256: str
    scope: InstallationScope
    root: Path
    enabled: bool


@dataclass(frozen=True)
class GeminiExtensionHealth:
    """Exact package identity and native source evidence."""

    extension_name: str
    package_id: str
    version: str
    enabled: bool
    exact_version: bool
    exact_source: bool
    status: str


@dataclass(frozen=True)
class GeminiExtensionResult:
    """Content-free terminal evidence for one documented native CLI action."""

    action: str
    status: str
    extension_name: str
    package_id: str
    version: str | None
    scope: InstallationScope
    enabled: bool
    restart_required: bool
    consent_owner: str = "gemini_cli"


@dataclass(frozen=True)
class GeminiExtensionHandoff:
    """Truthful provider-owned transition without undocumented state writes."""

    action: str
    extension_name: str
    command: tuple[str, ...]
    interaction: str
    consent_owner: str
    restart_required: bool
    reason: str


@dataclass(frozen=True)
class GeminiExtensionCommandResult:
    """Bounded subprocess result returned by an injected command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


GeminiExtensionCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float],
    GeminiExtensionCommandResult,
]
GeminiExtensionPolicy = Callable[[str, IntegrationPackage, InstallationScope], bool]


GEMINI_EXTENSION_TARGET_DESCRIPTOR = ExtensionTargetDescriptor(
    id=GEMINI_EXTENSION_TARGET_ID,
    revision=GEMINI_EXTENSION_TARGET_REVISION,
    component_types=(IntegrationComponentType.EXTENSION,),
    scopes=(
        InstallationScope.MANAGED_HOME,
        InstallationScope.PROJECT,
        InstallationScope.USER_HOME,
    ),
    capabilities=(
        "documented_cli_install",
        "documented_cli_uninstall",
        "gallery_handoff",
        "git_source",
        "local_source",
        "native_discovery",
        "native_enable_disable",
        "native_validation",
        "policy_deny",
        "project_scope",
        "restart_required",
        "rollback_handoff",
        "update",
    ),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="gemini-extension-documented-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="google-gemini-cli-docs",
            revision="2026-07-19",
        ),
    ),
)


@dataclass(frozen=True)
class _GeminiExecutionContext:
    config_home: Path
    cwd: Path
    native_scope: str


class GeminiExtensionTargetDriver:
    """Operate Gemini extensions only through documented native CLI commands."""

    descriptor = GEMINI_EXTENSION_TARGET_DESCRIPTOR

    def __init__(
        self,
        data_dir: str | Path,
        *,
        managed_roots: Sequence[str | Path] = (),
        project_roots: Sequence[str | Path] = (),
        source_roots: Sequence[str | Path] = (),
        user_home_root: str | Path | None = None,
        allow_user_home: bool = False,
        executable: Sequence[str] = ("gemini",),
        command_runner: GeminiExtensionCommandRunner | None = None,
        policy: GeminiExtensionPolicy | None = None,
        target_active: Callable[[Path], bool] | None = None,
    ) -> None:
        self.data_dir = _absolute_path(Path(data_dir))
        self.locks_root = self.data_dir / "integrations" / "gemini-extension" / "locks"
        native_root = self.data_dir / "native"
        self.managed_roots = _normalize_roots(managed_roots)
        for root in self.managed_roots:
            if not _is_relative_to(root, native_root):
                raise ValueError(
                    "managed Gemini extension roots must be Harness-native"
                )
        self.project_roots = _normalize_roots(project_roots)
        self.source_roots = _normalize_roots(source_roots)
        self.user_home_root = (
            _absolute_path(Path(user_home_root)) if user_home_root is not None else None
        )
        self.allow_user_home = allow_user_home
        self.executable = tuple(str(item) for item in executable)
        if not self.executable or any(not item for item in self.executable):
            raise ValueError("Gemini extension executable is invalid")
        self.command_runner = command_runner or _run_command
        self.policy = policy or (lambda _action, _package, _scope: True)
        if not callable(self.policy):
            raise TypeError("Gemini extension policy must be callable")
        self.target_active = target_active or (lambda _root: False)

    def probe_target(self) -> GeminiExtensionProbe:
        """Probe documented extension surfaces in an isolated temporary home."""
        with tempfile.TemporaryDirectory(
            prefix="gigaloom-gemini-extension-probe-"
        ) as raw:
            home = Path(raw)
            context = _GeminiExecutionContext(home, home, "user")
            commands = (
                ("--version",),
                ("extensions", "--help"),
                ("extensions", "validate", "--help"),
                ("extensions", "install", "--help"),
                ("extensions", "list", "--help"),
                ("extensions", "update", "--help"),
                ("extensions", "uninstall", "--help"),
                ("extensions", "enable", "--help"),
                ("extensions", "disable", "--help"),
            )
            results = tuple(self._run(context, args) for args in commands)
        version = _first_line(results[0].stdout or results[0].stderr)
        texts = tuple(_bounded_output(item) for item in results[1:])
        expectations = (
            ("extension_validate", "validate <path>", texts[1]),
            ("extension_install_ref", "--ref", texts[2]),
            ("extension_install_consent", "--consent", texts[2]),
            ("extension_list_json", "--output-format", texts[3]),
            ("extension_update", "--all", texts[4]),
            ("extension_uninstall", "--all", texts[5]),
            ("extension_enable_scope", "--scope", texts[6]),
            ("extension_disable_scope", "--scope", texts[7]),
        )
        capabilities = tuple(
            name for name, needle, value in expectations if needle in value
        )
        supported = (
            all(item.returncode == 0 for item in results)
            and len(capabilities) == len(expectations)
            and _supported_gemini_version(version)
        )
        return GeminiExtensionProbe(
            status="supported" if supported else "unsupported",
            version=version,
            command=str(redact_secrets(self.executable[0])),
            capabilities=capabilities,
            gallery_automation="provider_handoff_required",
            evidence="bounded --version and documented extensions help probes",
        )

    def discover_installed(self) -> tuple[GeminiExtensionInstallation, ...]:
        """Discover extensions through native JSON for all admitted roots."""
        contexts: list[tuple[InstallationScope, Path, _GeminiExecutionContext]] = []
        contexts.extend(
            (
                InstallationScope.MANAGED_HOME,
                root,
                self._context(root, InstallationScope.MANAGED_HOME),
            )
            for root in self.managed_roots
            if root.is_dir() and not root.is_symlink()
        )
        contexts.extend(
            (
                InstallationScope.PROJECT,
                root,
                self._context(root, InstallationScope.PROJECT),
            )
            for root in self.project_roots
            if root.is_dir() and not root.is_symlink()
        )
        if (
            self.allow_user_home
            and self.user_home_root is not None
            and self.user_home_root.is_dir()
        ):
            contexts.append(
                (
                    InstallationScope.USER_HOME,
                    self.user_home_root,
                    self._context(self.user_home_root, InstallationScope.USER_HOME),
                )
            )
        found: list[GeminiExtensionInstallation] = []
        for scope, root, context in contexts:
            for item in self._list(context):
                found.append(_installation_from_item(item, scope=scope, root=root))
        return tuple(sorted(found, key=lambda item: (str(item.root), item.name)))

    def preview_install(self, request: GeminiExtensionRequest) -> GeminiExtensionPlan:
        """Preview documented native installation or an explicit gallery handoff."""
        return self._preview(request, action="install")

    def install(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
    ) -> GeminiExtensionResult | GeminiExtensionHandoff:
        """Install through Gemini CLI, or return a visible gallery handoff."""
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            if plan.policy_status == "provider_handoff_required":
                self._authorize_handoff(request, plan, approval, action="install")
                return self._gallery_handoff(request)
            self._authorize(request, plan, approval, action="install")
            self._require_inactive(root, "install")
            args = ["extensions", "install", request.source.location]
            if request.source.kind is GeminiExtensionSourceKind.GIT:
                args.extend(("--ref", str(request.source.ref)))
            args.extend(("--consent", "--skip-settings"))
            try:
                self._command(context, tuple(args), trust_workspace=True)
                health = self.verify(request)
                if health.status != "healthy":
                    raise GeminiExtensionCommandError(
                        "Gemini extension install did not produce exact native discovery"
                    )
            except Exception:
                self._best_effort_uninstall(context, request.extension_name)
                raise
        return self._result("install", "installed", request, health)

    def verify(self, request: GeminiExtensionRequest) -> GeminiExtensionHealth:
        """Verify exact identity through native JSON without reading CLI caches."""
        _root, context = self._admit(request)
        current = self._current(context, request.extension_name)
        if current is None:
            return GeminiExtensionHealth(
                extension_name=request.extension_name,
                package_id=request.package.id,
                version="unknown",
                enabled=False,
                exact_version=False,
                exact_source=False,
                status="missing",
            )
        version = _required_string(current, "version", "Gemini extension version")
        exact_version = version == request.package.version
        exact_source = _native_source_matches(current, request.source)
        enabled = current.get("isActive") is True
        return GeminiExtensionHealth(
            extension_name=request.extension_name,
            package_id=request.package.id,
            version=version,
            enabled=enabled,
            exact_version=exact_version,
            exact_source=exact_source,
            status="healthy" if exact_version and exact_source else "degraded",
        )

    def health(self, request: GeminiExtensionRequest) -> GeminiExtensionHealth:
        """Alias native exact-discovery verification."""
        return self.verify(request)

    def preview_enable(self, request: GeminiExtensionRequest) -> GeminiExtensionPlan:
        """Preview native extension enablement."""
        return self._preview(request, action="enable")

    def enable(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
    ) -> GeminiExtensionResult:
        """Enable through the documented native CLI after exact approval."""
        return self._set_enabled(request, plan, approval, enabled=True)

    def preview_disable(self, request: GeminiExtensionRequest) -> GeminiExtensionPlan:
        """Preview native extension disablement."""
        return self._preview(request, action="disable")

    def disable(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
    ) -> GeminiExtensionResult:
        """Disable through the documented native CLI after exact approval."""
        return self._set_enabled(request, plan, approval, enabled=False)

    def preview_update(self, request: GeminiExtensionRequest) -> GeminiExtensionPlan:
        """Preview a reviewed source refresh or native handoff."""
        return self._preview(request, action="update")

    def update(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
    ) -> GeminiExtensionResult | GeminiExtensionHandoff:
        """Update local sources; hand immutable Git replacement to Gemini."""
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            if plan.policy_status == "provider_handoff_required":
                self._authorize_handoff(request, plan, approval, action="update")
                return GeminiExtensionHandoff(
                    action="update",
                    extension_name=request.extension_name,
                    command=self.executable
                    + (
                        "extensions",
                        "install",
                        request.source.location,
                        "--ref",
                        str(request.source.ref),
                    ),
                    interaction=(
                        "review the immutable replacement, uninstall the current "
                        "extension, then install the selected ref"
                    ),
                    consent_owner="gemini_cli",
                    restart_required=True,
                    reason=(
                        "Gemini exposes ref selection only during install, not as an "
                        "atomic version-selecting update"
                    ),
                )
            self._authorize(request, plan, approval, action="update")
            self._require_inactive(root, "update")
            self._command(context, ("extensions", "update", request.extension_name))
            health = self.verify(request)
            if health.status != "healthy":
                raise GeminiExtensionCommandError(
                    "Gemini extension update did not produce exact native discovery"
                )
        return self._result("update", "updated", request, health)

    def preview_uninstall(self, request: GeminiExtensionRequest) -> GeminiExtensionPlan:
        """Preview exact native removal."""
        return self._preview(request, action="uninstall")

    def uninstall(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
    ) -> GeminiExtensionResult:
        """Remove one extension through the documented native CLI."""
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            self._authorize(request, plan, approval, action="uninstall")
            self._require_inactive(root, "uninstall")
            self._command(
                context,
                ("extensions", "uninstall", request.extension_name),
            )
            if self._current(context, request.extension_name) is not None:
                raise GeminiExtensionCommandError(
                    "Gemini extension uninstall did not remove native discovery"
                )
        return GeminiExtensionResult(
            action="uninstall",
            status="uninstalled",
            extension_name=request.extension_name,
            package_id=request.package.id,
            version=None,
            scope=request.scope,
            enabled=False,
            restart_required=True,
        )

    def rollback(self, request: GeminiExtensionRequest) -> GeminiExtensionHandoff:
        """Expose truthful reviewed-source rollback when no atomic CLI exists."""
        if self.verify(request).status == "missing":
            raise InstallationConflictError(
                "Gemini extension rollback requires a native installation"
            )
        source_args: tuple[str, ...] = (request.source.location,)
        if request.source.ref is not None:
            source_args += ("--ref", request.source.ref)
        return GeminiExtensionHandoff(
            action="rollback",
            extension_name=request.extension_name,
            command=self.executable + ("extensions", "install") + source_args,
            interaction="restore the previously reviewed source, then reinstall it",
            consent_owner="gemini_cli",
            restart_required=True,
            reason="Gemini exposes no atomic version-selecting rollback command",
        )

    def gallery_handoff(
        self, request: GeminiExtensionRequest
    ) -> GeminiExtensionHandoff:
        """Return the visible gallery-to-reviewed-source transition."""
        self._admit(request)
        if request.source.kind is not GeminiExtensionSourceKind.GALLERY:
            raise ValueError("Gemini gallery handoff requires a gallery source")
        return self._gallery_handoff(request)

    def _gallery_handoff(
        self, request: GeminiExtensionRequest
    ) -> GeminiExtensionHandoff:
        return GeminiExtensionHandoff(
            action="select_source",
            extension_name=request.extension_name,
            command=(),
            interaction=(
                "open the Gemini extension gallery entry, select and review its "
                "repository, then create an immutable Git installation request"
            ),
            consent_owner="gemini_cli",
            restart_required=False,
            reason=(
                "the documented Gemini gallery is discovery-only and exposes no "
                "marketplace registration API"
            ),
        )

    def _set_enabled(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
        *,
        enabled: bool,
    ) -> GeminiExtensionResult:
        action = "enable" if enabled else "disable"
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            self._authorize(request, plan, approval, action=action)
            self._require_inactive(root, action)
            self._command(
                context,
                (
                    "extensions",
                    action,
                    request.extension_name,
                    "--scope",
                    context.native_scope,
                ),
            )
            health = self.verify(request)
            if health.status != "healthy" or health.enabled is not enabled:
                raise GeminiExtensionCommandError(
                    f"Gemini extension {action} did not produce exact native discovery"
                )
        return self._result(action, f"{action}d", request, health)

    def _preview(
        self, request: GeminiExtensionRequest, *, action: str
    ) -> GeminiExtensionPlan:
        root, context = self._admit(request)
        source_hash = self._validate_source(request, context)
        current = self._current(context, request.extension_name)
        current_version = (
            _required_string(current, "version", "Gemini extension version")
            if current is not None
            else None
        )
        current_enabled = (
            current.get("isActive") is True if current is not None else None
        )
        current_source_hash = (
            _source_metadata_hash(current) if current is not None else None
        )
        if action == "install" and current is not None:
            raise InstallationConflictError(
                "Gemini extension is already installed; use update or uninstall"
            )
        if action in {"enable", "disable", "update", "uninstall"} and current is None:
            raise InstallationConflictError(
                f"Gemini extension {action} requires a native installation"
            )
        if action == "enable" and current_enabled:
            raise InstallationConflictError("Gemini extension is already enabled")
        if action == "disable" and not current_enabled:
            raise InstallationConflictError("Gemini extension is already disabled")
        policy_status = self._policy_status(action, request)
        if policy_status == "allowed" and (
            request.source.kind is GeminiExtensionSourceKind.GALLERY
            or (
                action == "update"
                and request.source.kind is GeminiExtensionSourceKind.GIT
            )
        ):
            policy_status = "provider_handoff_required"
        command_ids = {
            "install": (
                ("gallery-handoff",)
                if request.source.kind is GeminiExtensionSourceKind.GALLERY
                else ("extension-validate", "extension-install", "extension-list")
            ),
            "enable": ("extension-enable", "extension-list"),
            "disable": ("extension-disable", "extension-list"),
            "update": (
                ("native-handoff",)
                if request.source.kind
                in {
                    GeminiExtensionSourceKind.GIT,
                    GeminiExtensionSourceKind.GALLERY,
                }
                else ("extension-update", "extension-list")
            ),
            "uninstall": ("extension-uninstall", "extension-list"),
        }[action]
        network_required = (
            request.source.kind is GeminiExtensionSourceKind.GIT
            and action
            in {
                "install",
                "update",
            }
        )
        source_trust_required = action == "install" and request.source.kind in {
            GeminiExtensionSourceKind.LOCAL,
            GeminiExtensionSourceKind.GIT,
        }
        semantic = {
            "action": action,
            "package_id": request.package.id,
            "package_version": request.package.version,
            "manifest_sha256": integration_package_semantic_hash(request.package),
            "extension_name": request.extension_name,
            "source_sha256": source_hash,
            "scope": request.scope.value,
            "root": str(root),
            "native_scope": context.native_scope,
            "expected_version": current_version,
            "expected_enabled": current_enabled,
            "expected_source_sha256": current_source_hash,
            "network_required": network_required,
            "native_consent_required": action in {"install", "update"},
            "source_trust_required": source_trust_required,
            "restart_required": action != "install"
            or request.source.kind is not GeminiExtensionSourceKind.GALLERY,
            "policy_status": policy_status,
            "command_ids": list(command_ids),
        }
        return GeminiExtensionPlan(
            action=action,
            plan_id=f"plan_{_json_hash(semantic)}",
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=str(semantic["manifest_sha256"]),
            extension_name=request.extension_name,
            source_sha256=source_hash,
            scope=request.scope,
            root=root,
            native_scope=context.native_scope,
            expected_version=current_version,
            expected_enabled=current_enabled,
            expected_source_sha256=current_source_hash,
            network_required=network_required,
            native_consent_required=bool(semantic["native_consent_required"]),
            source_trust_required=source_trust_required,
            restart_required=bool(semantic["restart_required"]),
            policy_status=policy_status,
            command_ids=command_ids,
        )

    def _authorize(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
        *,
        action: str,
    ) -> None:
        current = self._preview(request, action=action)
        if current != plan:
            raise InstallationConflictError(
                "Gemini extension source or native state changed after preview"
            )
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Gemini extension approval does not match the preview"
            )
        if plan.policy_status != "allowed":
            raise GeminiExtensionPolicyError(
                f"Gemini extension action denied: {plan.policy_status}"
            )
        if plan.native_consent_required and not approval.native_consent_acknowledged:
            raise GeminiExtensionPolicyError(
                "Gemini extension action requires explicit native consent acknowledgement"
            )
        if plan.source_trust_required and not approval.source_trust_acknowledged:
            raise GeminiExtensionPolicyError(
                "Gemini extension install requires explicit source trust acknowledgement"
            )
        if plan.network_required and not approval.allow_network:
            raise GeminiExtensionPolicyError(
                "Gemini Git extension action requires explicit network approval"
            )
        if (
            request.scope is InstallationScope.USER_HOME
            and not approval.allow_user_home
        ):
            raise InstallationScopeError(
                "Gemini user-home extension action requires explicit approval"
            )

    def _authorize_handoff(
        self,
        request: GeminiExtensionRequest,
        plan: GeminiExtensionPlan,
        approval: GeminiExtensionApproval,
        *,
        action: str,
    ) -> None:
        current = self._preview(request, action=action)
        if current != plan or approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Gemini extension handoff no longer matches the preview"
            )
        if plan.policy_status != "provider_handoff_required":
            raise GeminiExtensionPolicyError("Gemini extension handoff is not required")

    def _policy_status(self, action: str, request: GeminiExtensionRequest) -> str:
        assessment = assess_integration_package(request.package)
        if assessment.decision is IntegrationTrustDecision.BLOCKED:
            return "package_blocked"
        if not self.policy(action, request.package, request.scope):
            return "managed_policy_denied"
        return "allowed"

    def _validate_source(
        self,
        request: GeminiExtensionRequest,
        context: _GeminiExecutionContext,
    ) -> str:
        if request.source.kind is GeminiExtensionSourceKind.GALLERY:
            return _json_hash(
                {
                    "gallery": request.source.location,
                    "package_checksum": request.package.checksum,
                }
            )
        if request.source.kind is GeminiExtensionSourceKind.GIT:
            return _json_hash(
                {
                    "location": request.source.location,
                    "ref": request.source.ref,
                    "package_checksum": request.package.checksum,
                }
            )
        root = _absolute_path(Path(request.source.location))
        if root not in self.source_roots:
            raise InstallationScopeError(
                "Gemini local extension source is not explicitly admitted"
            )
        inspection = _inspect_local_source(root, request.extension_name)
        if inspection["version"] != request.package.version:
            raise InstallationConflictError(
                "Gemini extension manifest version does not match the package"
            )
        if inspection["checksum"] != request.package.checksum:
            raise InstallationConflictError(
                "Gemini extension source checksum does not match the package"
            )
        result = self._run(context, ("extensions", "validate", str(root)))
        if result.returncode != 0:
            raise GeminiExtensionCommandError(
                "Gemini native validation rejected the reviewed extension"
            )
        return str(inspection["source_sha256"])

    def _admit(
        self, request: GeminiExtensionRequest
    ) -> tuple[Path, _GeminiExecutionContext]:
        root = _absolute_path(request.root)
        return root, self._context(root, request.scope)

    def _context(self, root: Path, scope: InstallationScope) -> _GeminiExecutionContext:
        root = _absolute_path(root)
        if scope is InstallationScope.MANAGED_HOME:
            if root not in self.managed_roots:
                raise InstallationScopeError(
                    "Gemini managed extension root is not explicitly admitted"
                )
            context = _GeminiExecutionContext(root, root, "workspace")
        elif scope is InstallationScope.PROJECT:
            if root not in self.project_roots:
                raise InstallationScopeError(
                    "Gemini project extension root is not explicitly admitted"
                )
            identity = _json_hash({"project_root": str(root)})
            config_home = (
                self.data_dir / "native" / "gemini" / "extension-projects" / identity
            )
            context = _GeminiExecutionContext(config_home, root, "workspace")
        elif (
            not self.allow_user_home
            or self.user_home_root is None
            or root != self.user_home_root
        ):
            raise InstallationScopeError(
                "Gemini user-home extension root is disabled or mismatched"
            )
        else:
            context = _GeminiExecutionContext(root, root, "workspace")
        if not root.is_dir() or root.is_symlink():
            raise InstallationScopeError(
                "Gemini extension root must be an existing regular directory"
            )
        return context

    def _list(self, context: _GeminiExecutionContext) -> tuple[Mapping[str, Any], ...]:
        result = self._command(
            context,
            ("extensions", "list", "--output-format", "json"),
        )
        candidates: list[list[Mapping[str, Any]]] = []
        for channel in (result.stdout, result.stderr):
            if not channel.strip():
                continue
            try:
                value = json.loads(channel)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, list) and all(
                isinstance(item, dict) for item in value
            ):
                candidates.append(value)
        if len(candidates) != 1:
            raise GeminiExtensionCommandError(
                "Gemini extension list returned invalid or ambiguous JSON"
            )
        return tuple(candidates[0])

    def _current(
        self, context: _GeminiExecutionContext, extension_name: str
    ) -> Mapping[str, Any] | None:
        matches = [
            item for item in self._list(context) if item.get("name") == extension_name
        ]
        if len(matches) > 1:
            raise GeminiExtensionCommandError(
                "Gemini extension discovery returned duplicate names"
            )
        return matches[0] if matches else None

    def _command(
        self,
        context: _GeminiExecutionContext,
        args: tuple[str, ...],
        *,
        trust_workspace: bool = False,
    ) -> GeminiExtensionCommandResult:
        result = self._run(context, args, trust_workspace=trust_workspace)
        if result.returncode != 0:
            raise GeminiExtensionCommandError(
                "Gemini extension native command failed with redacted diagnostics"
            )
        return result

    def _run(
        self,
        context: _GeminiExecutionContext,
        args: tuple[str, ...],
        *,
        trust_workspace: bool = False,
    ) -> GeminiExtensionCommandResult:
        return self.command_runner(
            self.executable + args,
            _isolated_env(context.config_home, trust_workspace=trust_workspace),
            context.cwd,
            GEMINI_EXTENSION_COMMAND_TIMEOUT_SECONDS,
        )

    def _best_effort_uninstall(
        self, context: _GeminiExecutionContext, extension_name: str
    ) -> None:
        try:
            if self._current(context, extension_name) is not None:
                self._run(context, ("extensions", "uninstall", extension_name))
        except Exception:
            return

    def _lock_path(self, root: Path, scope: InstallationScope) -> Path:
        identity = _json_hash({"root": str(root), "scope": scope.value})
        return self.locks_root / f"{identity}.lock"

    def _require_inactive(self, root: Path, action: str) -> None:
        if self.target_active(root):
            raise InstallationConflictError(
                f"Gemini extension target is active; stop it before {action}"
            )

    def _result(
        self,
        action: str,
        status: str,
        request: GeminiExtensionRequest,
        health: GeminiExtensionHealth,
    ) -> GeminiExtensionResult:
        return GeminiExtensionResult(
            action=action,
            status=status,
            extension_name=request.extension_name,
            package_id=request.package.id,
            version=health.version,
            scope=request.scope,
            enabled=health.enabled,
            restart_required=True,
        )


def gemini_extension_target_plugin(
    factory: Callable[[], GeminiExtensionTargetDriver],
) -> ExtensionTargetPlugin:
    """Build the neutral registry entry for the Gemini extension target."""
    return ExtensionTargetPlugin(
        descriptor=GEMINI_EXTENSION_TARGET_DESCRIPTOR,
        factory=factory,
    )


def gemini_extension_source_checksum(root: str | Path, extension_name: str) -> str:
    """Return the canonical checksum for one strict local extension tree."""
    return str(
        _inspect_local_source(_absolute_path(Path(root)), extension_name)["checksum"]
    )


def _inspect_local_source(root: Path, extension_name: str) -> Mapping[str, str]:
    _assert_safe_tree_root(root, label="Gemini extension source")
    manifest = _read_json(
        root / "gemini-extension.json", label="Gemini extension manifest"
    )
    name = _required_string(manifest, "name", "Gemini extension name")
    _validate_extension_name(name, "Gemini extension name")
    if name != extension_name:
        raise ValueError("Gemini extension manifest name does not match the request")
    version = _required_string(manifest, "version", "Gemini extension version")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Gemini extension version is invalid")
    if "migratedTo" in manifest:
        raise ValueError("Gemini extension migratedTo requires a new reviewed source")
    for key in ("contextFileName",):
        value = manifest.get(key)
        if isinstance(value, str):
            _resolve_beneath(root, value, label=f"Gemini extension {key}")
        elif isinstance(value, list):
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(f"Gemini extension {key} is invalid")
                _resolve_beneath(root, item, label=f"Gemini extension {key}")
        elif value is not None:
            raise ValueError(f"Gemini extension {key} is invalid")
    tree_hash = _tree_checksum(root)
    return {
        "name": name,
        "version": version,
        "source_sha256": tree_hash,
        "checksum": f"sha256:{tree_hash}",
    }


def _tree_checksum(root: Path) -> str:
    _assert_safe_tree_root(root, label="Gemini extension source")
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(
        root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
    ):
        if path.is_symlink():
            raise ValueError("Gemini extension source contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Gemini extension source contains a non-regular file")
        count += 1
        if count > MAX_GEMINI_EXTENSION_FILES:
            raise ValueError("Gemini extension source contains too many files")
        size = path.stat().st_size
        if size > MAX_GEMINI_EXTENSION_FILE_BYTES:
            raise ValueError("Gemini extension source file is too large")
        total += size
        if total > MAX_GEMINI_EXTENSION_TOTAL_BYTES:
            raise ValueError("Gemini extension source is too large")
        relative = path.relative_to(root).as_posix()
        _normalize_relative_path(relative, label="Gemini extension source path")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if count == 0:
        raise ValueError("Gemini extension source is empty")
    return digest.hexdigest()


def _installation_from_item(
    item: Mapping[str, Any], *, scope: InstallationScope, root: Path
) -> GeminiExtensionInstallation:
    name = _required_string(item, "name", "Gemini extension name")
    version = _required_string(item, "version", "Gemini extension version")
    metadata = item.get("installMetadata")
    if not isinstance(metadata, Mapping):
        raise GeminiExtensionCommandError(
            "Gemini extension discovery omitted install metadata"
        )
    source_kind = _required_string(metadata, "type", "Gemini extension source type")
    return GeminiExtensionInstallation(
        name=name,
        version=version,
        source_kind=source_kind,
        source_sha256=_source_metadata_hash(item),
        scope=scope,
        root=root,
        enabled=item.get("isActive") is True,
    )


def _native_source_matches(
    item: Mapping[str, Any], source: GeminiExtensionSource
) -> bool:
    metadata = item.get("installMetadata")
    if not isinstance(metadata, Mapping):
        return False
    native_type = metadata.get("type")
    native_source = metadata.get("source")
    if not isinstance(native_source, str):
        return False
    if source.kind is GeminiExtensionSourceKind.LOCAL:
        return native_type == "local" and _absolute_path(
            Path(native_source)
        ) == _absolute_path(Path(source.location))
    if source.kind is GeminiExtensionSourceKind.GIT:
        if native_type not in {"git", "github-release"}:
            return False
        try:
            canonical = _canonical_git_source(native_source)
        except ValueError:
            return False
        native_ref = metadata.get("ref")
        return canonical == source.location and native_ref == source.ref
    return False


def _source_metadata_hash(item: Mapping[str, Any]) -> str:
    metadata = item.get("installMetadata")
    if not isinstance(metadata, Mapping):
        raise GeminiExtensionCommandError(
            "Gemini extension discovery omitted install metadata"
        )
    safe = {
        key: value
        for key, value in metadata.items()
        if key in {"source", "type", "ref", "autoUpdate", "preRelease"}
        and isinstance(value, (str, bool))
    }
    return _json_hash(safe)


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular file")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _resolve_beneath(root: Path, relative: str, *, label: str) -> Path:
    normalized = _normalize_relative_path(relative, label=label)
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} cannot traverse a symlink")
    resolved = _absolute_path(current)
    if not _is_relative_to(resolved, root):
        raise ValueError(f"{label} escapes the source root")
    if not resolved.is_file():
        raise ValueError(f"{label} does not reference a regular file")
    return resolved


def _assert_safe_tree_root(root: Path, *, label: str) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"{label} must be a regular directory")


def _normalize_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} is invalid")
    return path.as_posix()


def _canonical_git_source(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Gemini Git extension source must be a credential-free GitHub URL"
        )
    parts = tuple(part for part in parsed.path.split("/") if part)
    if len(parts) != 2:
        raise ValueError("Gemini Git extension source must identify one repository")
    repo = parts[1].removesuffix(".git")
    if not repo or any(not _IDENTITY_RE.fullmatch(part) for part in (parts[0], repo)):
        raise ValueError("Gemini Git extension repository identity is invalid")
    return urlunsplit(("https", "github.com", f"/{parts[0]}/{repo}.git", "", ""))


def _canonical_gallery_source(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"geminicli.com", "www.geminicli.com"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/extensions/")
    ):
        raise ValueError("Gemini gallery source must be a credential-free gallery URL")
    return urlunsplit(("https", "geminicli.com", parsed.path.rstrip("/"), "", ""))


def _supported_gemini_version(value: str | None) -> bool:
    if value is None:
        return False
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", value)
    return match is not None and tuple(int(item) for item in match.groups()) >= (
        0,
        46,
        0,
    )


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> GeminiExtensionCommandResult:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GeminiExtensionCommandError(
            "Gemini extension native command could not complete"
        ) from exc
    return GeminiExtensionCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[:MAX_GEMINI_EXTENSION_OUTPUT_CHARS],
        stderr=completed.stderr[:MAX_GEMINI_EXTENSION_OUTPUT_CHARS],
    )


def _isolated_env(
    config_home: Path, *, trust_workspace: bool = False
) -> dict[str, str]:
    env = {
        key: value
        for key in ("PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if (value := os.environ.get(key)) is not None
    }
    env.update(
        {
            "HOME": str(config_home),
            "GEMINI_CLI_HOME": str(config_home),
            "GEMINI_TELEMETRY_ENABLED": "false",
            "NO_COLOR": "1",
        }
    )
    if trust_workspace:
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    return env


def _bounded_output(result: GeminiExtensionCommandResult) -> str:
    return (result.stdout + "\n" + result.stderr)[:MAX_GEMINI_EXTENSION_OUTPUT_CHARS]


def _first_line(value: str) -> str | None:
    stripped = value.strip()
    return stripped.splitlines()[0] if stripped else None


def _required_string(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GeminiExtensionCommandError(f"{label} is missing or invalid")
    _validate_secret_free(value, label)
    return value


def _normalize_roots(values: Sequence[str | Path]) -> tuple[Path, ...]:
    return tuple(sorted({_absolute_path(Path(value)) for value in values}, key=str))


def _absolute_path(path: Path) -> Path:
    return path.expanduser().absolute()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_extension_name(value: str, label: str) -> None:
    if not isinstance(value, str) or not _EXTENSION_NAME_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_secret_free(value: str, label: str) -> None:
    redacted = redact_secrets(value)
    if not isinstance(redacted, str) or redacted != value:
        raise ValueError(f"{label} cannot contain secret material")


def _json_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "GEMINI_EXTENSION_TARGET_DESCRIPTOR",
    "GEMINI_EXTENSION_TARGET_ID",
    "GeminiExtensionApproval",
    "GeminiExtensionCommandError",
    "GeminiExtensionCommandResult",
    "GeminiExtensionHandoff",
    "GeminiExtensionHealth",
    "GeminiExtensionInstallation",
    "GeminiExtensionPlan",
    "GeminiExtensionPolicyError",
    "GeminiExtensionProbe",
    "GeminiExtensionRequest",
    "GeminiExtensionResult",
    "GeminiExtensionSource",
    "GeminiExtensionSourceKind",
    "GeminiExtensionTargetDriver",
    "GeminiExtensionTargetError",
    "gemini_extension_source_checksum",
    "gemini_extension_target_plugin",
]
