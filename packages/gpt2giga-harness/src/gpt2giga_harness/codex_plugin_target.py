"""Codex plugin lifecycle over documented marketplace and plugin CLI surfaces."""

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
    InstallationStateError,
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


CODEX_PLUGIN_TARGET_ID = "codex-plugin"
CODEX_PLUGIN_TARGET_REVISION = "1"
CODEX_PLUGIN_COMMAND_TIMEOUT_SECONDS = 30.0
MAX_CODEX_PLUGIN_OUTPUT_CHARS = 128_000
MAX_CODEX_PLUGIN_FILES = 512
MAX_CODEX_PLUGIN_FILE_BYTES = 16 * 1024 * 1024
MAX_CODEX_PLUGIN_TOTAL_BYTES = 64 * 1024 * 1024
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9._-]+)?\Z")
_PLAN_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_GITHUB_SHORTHAND_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class CodexPluginSourceKind(str, Enum):
    """Documented Codex marketplace source families admitted by the driver."""

    LOCAL = "local"
    GIT = "git"


class CodexPluginTargetError(RuntimeError):
    """Base error for Codex plugin target operations."""


class CodexPluginCommandError(CodexPluginTargetError):
    """Raised when a bounded native Codex command cannot prove its result."""


class CodexPluginPolicyError(CodexPluginTargetError):
    """Raised when managed policy or explicit native consent denies an action."""


@dataclass(frozen=True)
class CodexPluginSource:
    """One explicit local or immutable Git marketplace source."""

    marketplace_name: str
    kind: CodexPluginSourceKind
    location: str
    ref: str | None = None
    sparse: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.marketplace_name, "Codex marketplace name")
        if not isinstance(self.kind, CodexPluginSourceKind):
            raise ValueError("Codex plugin source kind is invalid")
        if not isinstance(self.location, str) or not self.location.strip():
            raise ValueError("Codex plugin source location is invalid")
        _validate_secret_free(self.location, "Codex plugin source location")
        sparse = tuple(sorted(set(self.sparse)))
        if len(sparse) != len(self.sparse) or len(sparse) > 32:
            raise ValueError("Codex plugin sparse paths are invalid")
        for item in sparse:
            _normalize_relative_path(item, label="Codex plugin sparse path")
        object.__setattr__(self, "sparse", sparse)
        if self.kind is CodexPluginSourceKind.LOCAL:
            if self.ref is not None or sparse:
                raise ValueError("local Codex marketplaces cannot use Git selectors")
            return
        if self.ref is None:
            raise ValueError("Git Codex marketplaces require an immutable ref")
        _validate_identity(self.ref, "Codex plugin source ref")
        object.__setattr__(self, "location", _canonical_git_source(self.location))


@dataclass(frozen=True)
class CodexPluginRequest:
    """One immutable integration projected to an explicit Codex plugin home."""

    package: IntegrationPackage
    scope: InstallationScope
    root: Path
    source: CodexPluginSource
    plugin_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("Codex plugin request requires an IntegrationPackage")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("Codex plugin request scope is invalid")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.source, CodexPluginSource):
            raise TypeError("Codex plugin request source is invalid")
        _validate_identity(self.plugin_name, "Codex plugin name")
        if not any(
            item.type is IntegrationComponentType.PLUGIN
            for item in self.package.components
        ):
            raise ValueError("Codex plugin request package has no plugin component")
        if self.scope not in self.package.scopes:
            raise ValueError("Codex plugin request package does not support the scope")
        if not any(
            item.target_id == CODEX_PLUGIN_TARGET_ID
            for item in self.package.compatibility
        ):
            raise ValueError("Codex plugin request package is not target-compatible")
        if self.source.kind is CodexPluginSourceKind.LOCAL:
            if self.package.source_type is not IntegrationSourceType.LOCAL:
                raise ValueError("local Codex source requires a local package source")
            if _absolute_path(Path(self.package.source)) != _absolute_path(
                Path(self.source.location)
            ):
                raise ValueError(
                    "Codex plugin source does not match the package source"
                )
        elif self.package.source_type not in {
            IntegrationSourceType.GIT,
            IntegrationSourceType.PROVIDER_MARKETPLACE,
        }:
            raise ValueError("Git Codex source requires a Git or marketplace package")
        elif _canonical_git_source(self.package.source) != self.source.location:
            raise ValueError("Codex plugin source does not match the package source")
        if (
            self.source.kind is CodexPluginSourceKind.GIT
            and self.package.immutable_ref != self.source.ref
        ):
            raise ValueError(
                "Codex plugin Git ref does not match the immutable package"
            )


@dataclass(frozen=True)
class CodexPluginApproval:
    """Explicit authority for one exact provider-native mutation preview."""

    plan_id: str
    authority: str
    native_consent_acknowledged: bool = False
    allow_network: bool = False
    allow_user_home: bool = False

    def __post_init__(self) -> None:
        if not _PLAN_RE.fullmatch(self.plan_id):
            raise ValueError("Codex plugin approval plan_id is invalid")
        _validate_identity(self.authority, "Codex plugin approval authority")
        for field_name in (
            "native_consent_acknowledged",
            "allow_network",
            "allow_user_home",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(
                    f"Codex plugin approval {field_name} must be a boolean"
                )


@dataclass(frozen=True)
class CodexPluginPlan:
    """Content-free preview bound to source, native state, policy, and restart."""

    action: str
    plan_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    plugin_id: str
    source_sha256: str
    scope: InstallationScope
    root: Path
    expected_version: str | None
    network_required: bool
    native_consent_required: bool
    restart_required: bool
    policy_status: str
    command_ids: tuple[str, ...]


@dataclass(frozen=True)
class CodexPluginProbe:
    """Bounded installed-Codex capability evidence."""

    status: str
    version: str | None
    command: str
    capabilities: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class CodexPluginInstallation:
    """Content-free native Codex plugin discovery projection."""

    plugin_id: str
    name: str
    marketplace_name: str
    version: str
    scope: InstallationScope
    root: Path
    enabled: bool
    source_kind: str


@dataclass(frozen=True)
class CodexPluginHealth:
    """Exact package identity and native discovery evidence."""

    plugin_id: str
    package_id: str
    version: str
    enabled: bool
    exact_version: bool
    exact_source: bool
    status: str


@dataclass(frozen=True)
class CodexPluginResult:
    """Content-free terminal evidence for one documented native CLI action."""

    action: str
    status: str
    plugin_id: str
    package_id: str
    version: str | None
    scope: InstallationScope
    enabled: bool
    restart_required: bool
    native_consent_owner: str = "codex"


@dataclass(frozen=True)
class CodexPluginHandoff:
    """Truthful provider-owned transition without undocumented config writes."""

    action: str
    plugin_id: str
    command: tuple[str, ...]
    interaction: str
    consent_owner: str
    restart_required: bool
    reason: str


@dataclass(frozen=True)
class CodexPluginCommandResult:
    """Bounded subprocess result returned by an injected command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


CodexPluginCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float],
    CodexPluginCommandResult,
]
CodexPluginPolicy = Callable[[str, IntegrationPackage, InstallationScope], bool]


CODEX_PLUGIN_TARGET_DESCRIPTOR = ExtensionTargetDescriptor(
    id=CODEX_PLUGIN_TARGET_ID,
    revision=CODEX_PLUGIN_TARGET_REVISION,
    component_types=(IntegrationComponentType.PLUGIN,),
    scopes=(InstallationScope.MANAGED_HOME, InstallationScope.USER_HOME),
    capabilities=(
        "documented_cli_install",
        "documented_cli_uninstall",
        "git_marketplace",
        "local_marketplace",
        "native_discovery",
        "native_enablement_handoff",
        "policy_deny",
        "restart_required",
        "rollback_handoff",
        "update",
    ),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="codex-plugin-documented-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="openai-codex-docs",
            revision="2026-07-19",
        ),
    ),
)


class CodexPluginTargetDriver:
    """Operate Codex plugins only through documented native CLI commands."""

    descriptor = CODEX_PLUGIN_TARGET_DESCRIPTOR

    def __init__(
        self,
        data_dir: str | Path,
        *,
        managed_roots: Sequence[str | Path] = (),
        source_roots: Sequence[str | Path] = (),
        user_home_root: str | Path | None = None,
        allow_user_home: bool = False,
        executable: Sequence[str] = ("codex",),
        command_runner: CodexPluginCommandRunner | None = None,
        policy: CodexPluginPolicy | None = None,
        target_active: Callable[[Path], bool] | None = None,
    ) -> None:
        self.data_dir = _absolute_path(Path(data_dir))
        self.locks_root = self.data_dir / "integrations" / "codex-plugin" / "locks"
        native_root = self.data_dir / "native"
        self.managed_roots = tuple(
            sorted({_absolute_path(Path(item)) for item in managed_roots}, key=str)
        )
        for root in self.managed_roots:
            if not _is_relative_to(root, native_root):
                raise ValueError("managed Codex plugin roots must be Harness-native")
        self.source_roots = tuple(
            sorted({_absolute_path(Path(item)) for item in source_roots}, key=str)
        )
        self.user_home_root = (
            _absolute_path(Path(user_home_root)) if user_home_root is not None else None
        )
        self.allow_user_home = allow_user_home
        self.executable = tuple(str(item) for item in executable)
        if not self.executable or any(not item for item in self.executable):
            raise ValueError("Codex plugin executable is invalid")
        self.command_runner = command_runner or _run_command
        self.policy = policy or (lambda _action, _package, _scope: True)
        if not callable(self.policy):
            raise TypeError("Codex plugin policy must be callable")
        self.target_active = target_active or (lambda _root: False)

    def probe_target(self) -> CodexPluginProbe:
        """Probe documented JSON plugin surfaces in an isolated temporary home."""
        with tempfile.TemporaryDirectory(prefix="gigaloom-codex-plugin-probe-") as raw:
            root = Path(raw) / ".codex"
            commands = (
                ("--version",),
                ("plugin", "--help"),
                ("plugin", "add", "--help"),
                ("plugin", "list", "--help"),
                ("plugin", "remove", "--help"),
                ("plugin", "marketplace", "add", "--help"),
                ("plugin", "marketplace", "list", "--help"),
                ("plugin", "marketplace", "upgrade", "--help"),
                ("plugin", "marketplace", "remove", "--help"),
            )
            results = tuple(self._run(root, args) for args in commands)
        version = _first_line(results[0].stdout or results[0].stderr)
        texts = tuple(_bounded_output(item) for item in results[1:])
        capabilities = tuple(
            name
            for name, proven in (
                ("plugin_add_json", "--json" in texts[1]),
                ("plugin_list_json", "--json" in texts[2]),
                ("plugin_remove_json", "--json" in texts[3]),
                ("marketplace_add_json", "--json" in texts[4]),
                ("marketplace_list_json", "--json" in texts[5]),
                ("marketplace_upgrade_json", "--json" in texts[6]),
                ("marketplace_remove_json", "--json" in texts[7]),
            )
            if proven
        )
        supported = (
            all(item.returncode == 0 for item in results)
            and len(capabilities) == 7
            and _supported_codex_version(version)
        )
        return CodexPluginProbe(
            status="supported" if supported else "unsupported",
            version=version,
            command=str(redact_secrets(self.executable[0])),
            capabilities=capabilities,
            evidence="bounded --version and documented plugin JSON help probes",
        )

    def discover_installed(self) -> tuple[CodexPluginInstallation, ...]:
        """Discover plugins through native JSON output for configured roots only."""
        roots = [(item, InstallationScope.MANAGED_HOME) for item in self.managed_roots]
        if self.allow_user_home and self.user_home_root is not None:
            roots.append((self.user_home_root, InstallationScope.USER_HOME))
        discovered: list[CodexPluginInstallation] = []
        for root, scope in roots:
            payload = self._plugin_list(root)
            for item in _plugin_items(payload, "installed"):
                discovered.append(_installation_from_item(item, root, scope))
        return tuple(
            sorted(discovered, key=lambda item: (str(item.root), item.plugin_id))
        )

    def preview_install(self, request: CodexPluginRequest) -> CodexPluginPlan:
        """Preview exact source registration and native installation commands."""
        return self._preview(request, action="install")

    def install(
        self,
        request: CodexPluginRequest,
        plan: CodexPluginPlan,
        approval: CodexPluginApproval,
    ) -> CodexPluginResult:
        """Register a source and install through the documented native CLI."""
        root = self._admit_root(request)
        with exclusive_file_lock(self._lock_path(root)):
            self._authorize(request, plan, approval, action="install")
            if self.target_active(root):
                raise InstallationConflictError(
                    "Codex plugin target is active; start a new session after installation"
                )
            added_marketplace = self._ensure_marketplace(root, request.source)
            try:
                result = self._json_command(
                    root,
                    ("plugin", "add", self._selector(request), "--json"),
                )
                self._validate_add_result(result, request)
                health = self.verify(request)
                if health.status != "healthy":
                    raise CodexPluginCommandError(
                        "Codex plugin install did not produce exact native discovery"
                    )
            except Exception:
                if added_marketplace:
                    self._best_effort_cleanup(root, request)
                raise
        return self._result("install", "installed", request, health)

    def verify(self, request: CodexPluginRequest) -> CodexPluginHealth:
        """Verify exact identity through native JSON without reading plugin caches."""
        root = self._admit_root(request)
        current = self._current_plugin(root, self._selector(request))
        if current is None:
            return CodexPluginHealth(
                plugin_id=self._selector(request),
                package_id=request.package.id,
                version="unknown",
                enabled=False,
                exact_version=False,
                exact_source=False,
                status="missing",
            )
        version = _required_string(current, "version", "Codex plugin version")
        source_matches = _item_source_matches(current, request.source)
        exact_version = version == request.package.version
        enabled = current.get("enabled") is True
        return CodexPluginHealth(
            plugin_id=self._selector(request),
            package_id=request.package.id,
            version=version,
            enabled=enabled,
            exact_version=exact_version,
            exact_source=source_matches,
            status=(
                "healthy"
                if exact_version and source_matches and enabled
                else "degraded"
            ),
        )

    def health(self, request: CodexPluginRequest) -> CodexPluginHealth:
        """Alias native exact-discovery verification."""
        return self.verify(request)

    def enable(self, request: CodexPluginRequest) -> CodexPluginHandoff:
        """Return the documented plugin-browser enablement handoff."""
        return self._enablement_handoff(request, action="enable")

    def disable(self, request: CodexPluginRequest) -> CodexPluginHandoff:
        """Return the documented plugin-browser disablement handoff."""
        return self._enablement_handoff(request, action="disable")

    def preview_update(self, request: CodexPluginRequest) -> CodexPluginPlan:
        """Preview a reviewed marketplace refresh and exact native re-install."""
        return self._preview(request, action="update")

    def update(
        self,
        request: CodexPluginRequest,
        plan: CodexPluginPlan,
        approval: CodexPluginApproval,
    ) -> CodexPluginResult | CodexPluginHandoff:
        """Update local sources; hand immutable Git ref replacement to Codex."""
        root = self._admit_root(request)
        with exclusive_file_lock(self._lock_path(root)):
            if plan.policy_status == "provider_handoff_required":
                current = self._preview(request, action="update")
                if current != plan:
                    raise InstallationConflictError(
                        "Codex plugin source or native state changed after preview"
                    )
                if approval.plan_id != plan.plan_id:
                    raise InstallationConflictError(
                        "Codex plugin approval does not match the preview"
                    )
                return CodexPluginHandoff(
                    action="update",
                    plugin_id=self._selector(request),
                    command=self.executable,
                    interaction=(
                        "review the new immutable Git ref in /plugins, then reinstall "
                        "from the provider-owned marketplace source"
                    ),
                    consent_owner="codex",
                    restart_required=True,
                    reason=(
                        "Codex has no atomic command to replace a shared marketplace "
                        "source ref"
                    ),
                )
            self._authorize(request, plan, approval, action="update")
            if self.target_active(root):
                raise InstallationConflictError(
                    "Codex plugin target is active; stop it before update"
                )
            self._ensure_marketplace(root, request.source)
            result = self._json_command(
                root,
                ("plugin", "add", self._selector(request), "--json"),
            )
            self._validate_add_result(result, request)
            health = self.verify(request)
            if health.status != "healthy":
                raise CodexPluginCommandError(
                    "Codex plugin update did not produce exact native discovery"
                )
        return self._result("update", "updated", request, health)

    def preview_uninstall(self, request: CodexPluginRequest) -> CodexPluginPlan:
        """Preview native removal while retaining shared marketplace registration."""
        return self._preview(request, action="uninstall")

    def uninstall(
        self,
        request: CodexPluginRequest,
        plan: CodexPluginPlan,
        approval: CodexPluginApproval,
    ) -> CodexPluginResult:
        """Remove one plugin through the documented CLI without editing its cache."""
        root = self._admit_root(request)
        with exclusive_file_lock(self._lock_path(root)):
            self._authorize(request, plan, approval, action="uninstall")
            if self.target_active(root):
                raise InstallationConflictError(
                    "Codex plugin target is active; stop it before uninstall"
                )
            result = self._json_command(
                root,
                ("plugin", "remove", self._selector(request), "--json"),
            )
            _validate_plugin_id(result, self._selector(request))
            if self._current_plugin(root, self._selector(request)) is not None:
                raise CodexPluginCommandError(
                    "Codex plugin uninstall did not remove native discovery"
                )
        return CodexPluginResult(
            action="uninstall",
            status="uninstalled",
            plugin_id=self._selector(request),
            package_id=request.package.id,
            version=None,
            scope=request.scope,
            enabled=False,
            restart_required=True,
        )

    def rollback(self, request: CodexPluginRequest) -> CodexPluginHandoff:
        """Expose truthful reviewed-source rollback when no atomic CLI exists."""
        self._admit_root(request)
        return CodexPluginHandoff(
            action="rollback",
            plugin_id=self._selector(request),
            command=self.executable + ("plugin", "add", self._selector(request)),
            interaction="restore the previously reviewed marketplace ref, then reinstall",
            consent_owner="codex",
            restart_required=True,
            reason="Codex exposes install/update but no atomic plugin rollback command",
        )

    def _preview(self, request: CodexPluginRequest, *, action: str) -> CodexPluginPlan:
        root = self._admit_root(request)
        source_hash = self._validate_source(request)
        current = self._current_plugin(root, self._selector(request))
        current_version = (
            _required_string(current, "version", "Codex plugin version")
            if current is not None
            else None
        )
        if action == "install" and current is not None:
            raise InstallationConflictError(
                "Codex plugin is already installed; use update or uninstall"
            )
        if action in {"update", "uninstall"} and current is None:
            raise InstallationConflictError(
                f"Codex plugin {action} requires a native installation"
            )
        policy_status = self._policy_status(action, request)
        if (
            policy_status == "allowed"
            and action == "update"
            and request.source.kind is CodexPluginSourceKind.GIT
        ):
            policy_status = "provider_handoff_required"
        command_ids = {
            "install": ("marketplace-add", "plugin-add", "plugin-list"),
            "update": (
                ("native-handoff",)
                if request.source.kind is CodexPluginSourceKind.GIT
                else ("marketplace-list", "plugin-add", "plugin-list")
            ),
            "uninstall": ("plugin-remove", "plugin-list"),
        }[action]
        network_required = (
            request.source.kind is CodexPluginSourceKind.GIT
            and action in {"install", "update"}
        )
        semantic = {
            "action": action,
            "package_id": request.package.id,
            "package_version": request.package.version,
            "manifest_sha256": integration_package_semantic_hash(request.package),
            "plugin_id": self._selector(request),
            "source_sha256": source_hash,
            "scope": request.scope.value,
            "root": str(root),
            "expected_version": current_version,
            "network_required": network_required,
            "native_consent_required": True,
            "restart_required": True,
            "policy_status": policy_status,
            "command_ids": list(command_ids),
        }
        return CodexPluginPlan(
            action=action,
            plan_id=f"plan_{_json_hash(semantic)}",
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=semantic["manifest_sha256"],
            plugin_id=self._selector(request),
            source_sha256=source_hash,
            scope=request.scope,
            root=root,
            expected_version=current_version,
            network_required=semantic["network_required"],
            native_consent_required=True,
            restart_required=True,
            policy_status=policy_status,
            command_ids=command_ids,
        )

    def _authorize(
        self,
        request: CodexPluginRequest,
        plan: CodexPluginPlan,
        approval: CodexPluginApproval,
        *,
        action: str,
    ) -> None:
        current = self._preview(request, action=action)
        if current != plan:
            raise InstallationConflictError(
                "Codex plugin source or native state changed after preview"
            )
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Codex plugin approval does not match the preview"
            )
        if plan.policy_status != "allowed":
            raise CodexPluginPolicyError(
                f"Codex plugin action denied: {plan.policy_status}"
            )
        if not approval.native_consent_acknowledged:
            raise CodexPluginPolicyError(
                "Codex plugin action requires explicit native consent acknowledgement"
            )
        if plan.network_required and not approval.allow_network:
            raise CodexPluginPolicyError(
                "Codex Git marketplace action requires explicit network approval"
            )
        if (
            request.scope is InstallationScope.USER_HOME
            and not approval.allow_user_home
        ):
            raise InstallationScopeError(
                "Codex user-home plugin action requires explicit approval"
            )

    def _policy_status(self, action: str, request: CodexPluginRequest) -> str:
        assessment = assess_integration_package(request.package)
        if assessment.decision is IntegrationTrustDecision.BLOCKED:
            return "package_blocked"
        if not self.policy(action, request.package, request.scope):
            return "managed_policy_denied"
        return "allowed"

    def _validate_source(self, request: CodexPluginRequest) -> str:
        if request.source.kind is CodexPluginSourceKind.GIT:
            return _json_hash(
                {
                    "marketplace_name": request.source.marketplace_name,
                    "location": request.source.location,
                    "ref": request.source.ref,
                    "sparse": list(request.source.sparse),
                    "package_checksum": request.package.checksum,
                }
            )
        root = _absolute_path(Path(request.source.location))
        if root not in self.source_roots:
            raise InstallationScopeError(
                "Codex local marketplace source is not explicitly admitted"
            )
        inspection = _inspect_local_source(root, request.source, request.plugin_name)
        if inspection["version"] != request.package.version:
            raise InstallationConflictError(
                "Codex plugin manifest version does not match the package"
            )
        if inspection["checksum"] != request.package.checksum:
            raise InstallationConflictError(
                "Codex plugin source checksum does not match the package"
            )
        return str(inspection["source_sha256"])

    def _admit_root(self, request: CodexPluginRequest) -> Path:
        root = _absolute_path(request.root)
        if request.scope is InstallationScope.PROJECT:
            raise InstallationScopeError(
                "Codex plugin caches are home-scoped; project roots are unsupported"
            )
        if request.scope is InstallationScope.MANAGED_HOME:
            if root not in self.managed_roots:
                raise InstallationScopeError(
                    "Codex managed plugin root is not explicitly admitted"
                )
        elif (
            not self.allow_user_home
            or self.user_home_root is None
            or root != self.user_home_root
        ):
            raise InstallationScopeError(
                "Codex user-home plugin root is disabled or mismatched"
            )
        if not root.is_dir() or root.is_symlink():
            raise InstallationScopeError(
                "Codex plugin root must be an existing regular directory"
            )
        return root

    def _ensure_marketplace(self, root: Path, source: CodexPluginSource) -> bool:
        payload = self._json_command(root, ("plugin", "marketplace", "list", "--json"))
        marketplaces = payload.get("marketplaces", [])
        if not isinstance(marketplaces, list):
            raise CodexPluginCommandError("Codex marketplace list JSON is invalid")
        matches = [
            item
            for item in marketplaces
            if isinstance(item, Mapping) and item.get("name") == source.marketplace_name
        ]
        if len(matches) > 1:
            raise InstallationStateError("Codex marketplace list has duplicate names")
        if matches:
            if not _marketplace_source_matches(matches[0], source):
                raise InstallationConflictError(
                    "Codex marketplace name is registered to another source"
                )
            return False
        result = self._json_command(root, self._marketplace_add_args(source))
        _validate_marketplace_name(result, source.marketplace_name)
        matches = [
            item
            for item in self._marketplace_items(root)
            if item.get("name") == source.marketplace_name
        ]
        if len(matches) != 1 or not _marketplace_source_matches(matches[0], source):
            raise CodexPluginCommandError(
                "Codex marketplace registration did not preserve the reviewed source"
            )
        return True

    def _marketplace_add_args(self, source: CodexPluginSource) -> tuple[str, ...]:
        args: list[str] = ["plugin", "marketplace", "add", source.location]
        if source.ref is not None:
            args.extend(("--ref", source.ref))
        for item in source.sparse:
            args.extend(("--sparse", item))
        args.append("--json")
        return tuple(args)

    def _plugin_list(self, root: Path) -> Mapping[str, Any]:
        return self._json_command(root, ("plugin", "list", "--available", "--json"))

    def _current_plugin(self, root: Path, selector: str) -> Mapping[str, Any] | None:
        payload = self._plugin_list(root)
        matches = [
            item
            for item in _plugin_items(payload, "installed")
            if item.get("pluginId") == selector
        ]
        if len(matches) > 1:
            raise InstallationStateError("Codex plugin list has duplicate identities")
        return matches[0] if matches else None

    def _json_command(self, root: Path, args: tuple[str, ...]) -> Mapping[str, Any]:
        result = self._run(root, args)
        if result.returncode != 0:
            raise CodexPluginCommandError(
                f"Codex command {args[0]} failed with status {result.returncode}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CodexPluginCommandError(
                "Codex command returned invalid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise CodexPluginCommandError("Codex command JSON must be an object")
        return payload

    def _run(self, root: Path, args: tuple[str, ...]) -> CodexPluginCommandResult:
        return self.command_runner(
            self.executable + args,
            _isolated_env(root),
            None,
            CODEX_PLUGIN_COMMAND_TIMEOUT_SECONDS,
        )

    def _validate_add_result(
        self, result: Mapping[str, Any], request: CodexPluginRequest
    ) -> None:
        _validate_plugin_id(result, self._selector(request))
        if result.get("version") != request.package.version:
            raise CodexPluginCommandError(
                "Codex installed plugin version does not match the reviewed package"
            )

    def _best_effort_cleanup(self, root: Path, request: CodexPluginRequest) -> None:
        try:
            current = self._current_plugin(root, self._selector(request))
            if (
                current is not None
                and current.get("version") == request.package.version
                and _item_source_matches(current, request.source)
            ):
                self._run(
                    root,
                    ("plugin", "remove", self._selector(request), "--json"),
                )
            remaining = _plugin_items(self._plugin_list(root), "installed")
            if not any(
                item.get("marketplaceName") == request.source.marketplace_name
                for item in remaining
            ):
                self._run(
                    root,
                    (
                        "plugin",
                        "marketplace",
                        "remove",
                        request.source.marketplace_name,
                        "--json",
                    ),
                )
        except Exception:
            # Best-effort rollback must not mask the original installation failure.
            pass

    def _marketplace_items(self, root: Path) -> tuple[Mapping[str, Any], ...]:
        payload = self._json_command(root, ("plugin", "marketplace", "list", "--json"))
        marketplaces = payload.get("marketplaces", [])
        if not isinstance(marketplaces, list) or any(
            not isinstance(item, Mapping) for item in marketplaces
        ):
            raise CodexPluginCommandError("Codex marketplace list JSON is invalid")
        return tuple(marketplaces)

    def _lock_path(self, root: Path) -> Path:
        if self.locks_root.is_symlink():
            raise InstallationStateError("Codex plugin lock root cannot be a symlink")
        self.locks_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.locks_root.is_symlink():
            raise InstallationStateError("Codex plugin lock root cannot be a symlink")
        os.chmod(self.locks_root, 0o700)
        return self.locks_root / _json_hash({"root": str(root)})

    def _enablement_handoff(
        self, request: CodexPluginRequest, *, action: str
    ) -> CodexPluginHandoff:
        health = self.verify(request)
        if health.status == "missing":
            raise InstallationConflictError(
                f"Codex plugin {action} requires a native installation"
            )
        return CodexPluginHandoff(
            action=action,
            plugin_id=self._selector(request),
            command=self.executable,
            interaction="open /plugins and press Space on the reviewed plugin",
            consent_owner="codex",
            restart_required=True,
            reason="Codex exposes enablement through its native plugin browser",
        )

    @staticmethod
    def _selector(request: CodexPluginRequest) -> str:
        return f"{request.plugin_name}@{request.source.marketplace_name}"

    @staticmethod
    def _result(
        action: str,
        status: str,
        request: CodexPluginRequest,
        health: CodexPluginHealth,
    ) -> CodexPluginResult:
        return CodexPluginResult(
            action=action,
            status=status,
            plugin_id=health.plugin_id,
            package_id=request.package.id,
            version=health.version,
            scope=request.scope,
            enabled=health.enabled,
            restart_required=True,
        )


def codex_plugin_target_plugin(
    factory: Callable[[], CodexPluginTargetDriver],
) -> ExtensionTargetPlugin:
    """Build a neutral runtime registration for a configured Codex target."""
    return ExtensionTargetPlugin(
        descriptor=CODEX_PLUGIN_TARGET_DESCRIPTOR,
        factory=factory,
    )


def codex_plugin_source_checksum(
    marketplace_root: str | Path,
    marketplace_name: str,
    plugin_name: str,
) -> str:
    """Return the deterministic package checksum for one local marketplace entry."""
    source = CodexPluginSource(
        marketplace_name=marketplace_name,
        kind=CodexPluginSourceKind.LOCAL,
        location=str(_absolute_path(Path(marketplace_root))),
    )
    inspection = _inspect_local_source(
        _absolute_path(Path(marketplace_root)), source, plugin_name
    )
    return str(inspection["checksum"])


def _inspect_local_source(
    root: Path,
    source: CodexPluginSource,
    plugin_name: str,
) -> Mapping[str, Any]:
    _assert_safe_tree_root(root, label="Codex marketplace root")
    marketplace_path = root / ".agents" / "plugins" / "marketplace.json"
    marketplace = _read_json(marketplace_path, label="Codex marketplace manifest")
    if marketplace.get("name") != source.marketplace_name:
        raise ValueError("Codex marketplace manifest name does not match the source")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("Codex marketplace plugins must be a list")
    matches = [
        item
        for item in plugins
        if isinstance(item, Mapping) and item.get("name") == plugin_name
    ]
    if len(matches) != 1:
        raise ValueError("Codex marketplace must contain one exact plugin entry")
    entry = matches[0]
    _validate_marketplace_policy(entry)
    relative_source = _local_plugin_path(entry)
    plugin_root = _resolve_beneath(root, relative_source, label="Codex plugin source")
    _assert_safe_tree_root(plugin_root, label="Codex plugin source")
    manifest = _read_json(
        plugin_root / ".codex-plugin" / "plugin.json",
        label="Codex plugin manifest",
    )
    if manifest.get("name") != plugin_name:
        raise ValueError("Codex plugin manifest name does not match the marketplace")
    version = _required_string(manifest, "version", "Codex plugin manifest version")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Codex plugin manifest version is invalid")
    _required_string(manifest, "description", "Codex plugin description")
    _validate_manifest_paths(plugin_root, manifest)
    checksum = _tree_checksum(plugin_root)
    return {
        "version": version,
        "checksum": checksum,
        "source_sha256": _json_hash(
            {
                "marketplace_name": source.marketplace_name,
                "plugin_name": plugin_name,
                "entry": entry,
                "checksum": checksum,
            }
        ),
    }


def _validate_marketplace_policy(entry: Mapping[str, Any]) -> None:
    policy = entry.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("Codex marketplace policy is required")
    if policy.get("installation") != "AVAILABLE":
        raise CodexPluginPolicyError(
            "Codex marketplace installation policy denies install"
        )
    if policy.get("authentication") not in {"ON_INSTALL", "ON_FIRST_USE"}:
        raise ValueError("Codex marketplace authentication policy is invalid")
    _required_string(entry, "category", "Codex marketplace category")


def _local_plugin_path(entry: Mapping[str, Any]) -> str:
    source = entry.get("source")
    if isinstance(source, str):
        value = source
    elif isinstance(source, Mapping) and source.get("source") == "local":
        value = source.get("path")
    else:
        raise ValueError("Codex local marketplace entry source is invalid")
    if not isinstance(value, str) or not value.startswith("./"):
        raise ValueError("Codex local plugin path must start with ./")
    return _normalize_relative_path(value[2:], label="Codex local plugin path")


def _validate_manifest_paths(root: Path, manifest: Mapping[str, Any]) -> None:
    for field_name in ("skills", "mcpServers", "apps", "hooks"):
        value = manifest.get(field_name)
        if value is not None:
            _validate_manifest_path(root, value, field_name)
    interface = manifest.get("interface")
    if interface is None:
        return
    if not isinstance(interface, Mapping):
        raise ValueError("Codex plugin interface must be an object")
    for field_name in ("composerIcon", "logo"):
        value = interface.get(field_name)
        if value is not None:
            _validate_manifest_path(root, value, f"interface.{field_name}")
    screenshots = interface.get("screenshots", [])
    if not isinstance(screenshots, list):
        raise ValueError("Codex plugin interface screenshots must be a list")
    for value in screenshots:
        _validate_manifest_path(root, value, "interface.screenshots")


def _validate_manifest_path(root: Path, value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.startswith("./"):
        raise ValueError(f"Codex plugin {field_name} must be a ./ path")
    path = _resolve_beneath(
        root,
        _normalize_relative_path(value[2:], label=f"Codex plugin {field_name}"),
        label=f"Codex plugin {field_name}",
    )
    if not path.exists() or path.is_symlink():
        raise ValueError(f"Codex plugin {field_name} path is missing or unsafe")


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Codex plugin source cannot contain symlinks")
        if path.is_file():
            files.append(path)
    if not files or len(files) > MAX_CODEX_PLUGIN_FILES:
        raise ValueError("Codex plugin source file count is invalid")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        stat = path.stat()
        if stat.st_size > MAX_CODEX_PLUGIN_FILE_BYTES:
            raise ValueError("Codex plugin source file is too large")
        total += stat.st_size
        if total > MAX_CODEX_PLUGIN_TOTAL_BYTES:
            raise ValueError("Codex plugin source is too large")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _plugin_items(
    payload: Mapping[str, Any], field_name: str
) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(field_name, [])
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise CodexPluginCommandError(f"Codex plugin {field_name} JSON is invalid")
    return tuple(value)


def _installation_from_item(
    item: Mapping[str, Any], root: Path, scope: InstallationScope
) -> CodexPluginInstallation:
    plugin_id = _required_string(item, "pluginId", "Codex plugin id")
    name = _required_string(item, "name", "Codex plugin name")
    marketplace = _required_string(
        item, "marketplaceName", "Codex plugin marketplace name"
    )
    version = _required_string(item, "version", "Codex plugin version")
    marketplace_source = item.get("marketplaceSource")
    source_kind = (
        str(marketplace_source.get("sourceType", "unknown"))
        if isinstance(marketplace_source, Mapping)
        else "unknown"
    )
    return CodexPluginInstallation(
        plugin_id=plugin_id,
        name=name,
        marketplace_name=marketplace,
        version=version,
        scope=scope,
        root=root,
        enabled=item.get("enabled") is True,
        source_kind=source_kind,
    )


def _item_source_matches(item: Mapping[str, Any], source: CodexPluginSource) -> bool:
    marketplace_source = item.get("marketplaceSource")
    if not isinstance(marketplace_source, Mapping):
        return False
    source_type = marketplace_source.get("sourceType")
    observed = marketplace_source.get("source")
    if source.kind is CodexPluginSourceKind.LOCAL:
        return source_type == "local" and observed == str(
            _absolute_path(Path(source.location))
        )
    return source_type in {"git", "github"} and observed == source.location


def _marketplace_source_matches(
    item: Mapping[str, Any], source: CodexPluginSource
) -> bool:
    marketplace_source = item.get("marketplaceSource")
    if not isinstance(marketplace_source, Mapping):
        return False
    observed = marketplace_source.get("source")
    source_type = marketplace_source.get("sourceType")
    if source.kind is CodexPluginSourceKind.LOCAL:
        return source_type == "local" and observed == str(
            _absolute_path(Path(source.location))
        )
    if source_type not in {"git", "github"} or observed != source.location:
        return False
    observed_ref = marketplace_source.get("ref")
    return observed_ref is None or observed_ref == source.ref


def _validate_marketplace_name(payload: Mapping[str, Any], expected: str) -> None:
    if payload.get("marketplaceName") != expected:
        raise CodexPluginCommandError("Codex marketplace result identity is invalid")


def _validate_plugin_id(payload: Mapping[str, Any], expected: str) -> None:
    if payload.get("pluginId") != expected:
        raise CodexPluginCommandError("Codex plugin result identity is invalid")


def _required_string(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"{label} is invalid")
    return value


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or unsafe")
    if path.stat().st_size > MAX_CODEX_PLUGIN_FILE_BYTES:
        raise ValueError(f"{label} is too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return payload


def _resolve_beneath(root: Path, relative: str, *, label: str) -> Path:
    path = root / relative
    resolved = _absolute_path(path)
    if not _is_relative_to(resolved, root):
        raise ValueError(f"{label} escapes its root")
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink")
    return resolved


def _assert_safe_tree_root(root: Path, *, label: str) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"{label} must be a regular directory")


def _normalize_relative_path(value: str, *, label: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if (
        not value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{label} is invalid")
    normalized = path.as_posix()
    if len(normalized) > 1024:
        raise ValueError(f"{label} is too long")
    return normalized


def _canonical_git_source(value: str) -> str:
    if _GITHUB_SHORTHAND_RE.fullmatch(value):
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Codex Git marketplace must use credential-free HTTPS")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, "", ""))


def _supported_codex_version(value: str | None) -> bool:
    if value is None:
        return False
    match = re.search(r"(?:codex-cli\s+)?(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return False
    version = tuple(int(item) for item in match.groups())
    return (0, 144, 0) <= version < (1, 0, 0)


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> CodexPluginCommandResult:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            env=dict(env),
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexPluginCommandError(
            f"Codex plugin command failed with {type(exc).__name__}"
        ) from exc
    return CodexPluginCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[-MAX_CODEX_PLUGIN_OUTPUT_CHARS:],
        stderr=completed.stderr[-MAX_CODEX_PLUGIN_OUTPUT_CHARS:],
    )


def _isolated_env(root: Path) -> dict[str, str]:
    env = {
        key: value
        for key in ("PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if (value := os.environ.get(key)) is not None
    }
    env["HOME"] = str(root.parent)
    env["CODEX_HOME"] = str(root)
    return env


def _bounded_output(result: CodexPluginCommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"[-MAX_CODEX_PLUGIN_OUTPUT_CHARS:]


def _first_line(value: str) -> str | None:
    lines = value.strip().splitlines()
    return lines[0][:200] if lines else None


def _absolute_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_secret_free(value: str, label: str) -> None:
    if str(redact_secrets(value)) != value:
        raise ValueError(f"{label} contains secret material")


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CODEX_PLUGIN_TARGET_DESCRIPTOR",
    "CODEX_PLUGIN_TARGET_ID",
    "CodexPluginApproval",
    "CodexPluginCommandError",
    "CodexPluginCommandResult",
    "CodexPluginHandoff",
    "CodexPluginHealth",
    "CodexPluginInstallation",
    "CodexPluginPlan",
    "CodexPluginPolicyError",
    "CodexPluginProbe",
    "CodexPluginRequest",
    "CodexPluginResult",
    "CodexPluginSource",
    "CodexPluginSourceKind",
    "CodexPluginTargetDriver",
    "codex_plugin_source_checksum",
    "codex_plugin_target_plugin",
]
