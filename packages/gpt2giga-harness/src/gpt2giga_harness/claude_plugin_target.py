"""Claude plugin lifecycle over documented marketplace and plugin CLI surfaces."""

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


CLAUDE_PLUGIN_TARGET_ID = "claude-plugin"
CLAUDE_PLUGIN_TARGET_REVISION = "1"
CLAUDE_PLUGIN_COMMAND_TIMEOUT_SECONDS = 30.0
MAX_CLAUDE_PLUGIN_OUTPUT_CHARS = 128_000
MAX_CLAUDE_PLUGIN_FILES = 512
MAX_CLAUDE_PLUGIN_FILE_BYTES = 16 * 1024 * 1024
MAX_CLAUDE_PLUGIN_TOTAL_BYTES = 64 * 1024 * 1024
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_PLUGIN_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9._-]+)?\Z")
_PLAN_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_GITHUB_SHORTHAND_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class ClaudePluginSourceKind(str, Enum):
    """Documented Claude marketplace source families admitted by the driver."""

    LOCAL = "local"
    GIT = "git"


class ClaudePluginTargetError(RuntimeError):
    """Base error for Claude plugin target operations."""


class ClaudePluginCommandError(ClaudePluginTargetError):
    """Raised when a bounded native Claude command cannot prove its result."""


class ClaudePluginPolicyError(ClaudePluginTargetError):
    """Raised when policy or explicit native consent denies an action."""


@dataclass(frozen=True)
class ClaudePluginSource:
    """One explicit local or immutable Git Claude marketplace source."""

    marketplace_name: str
    kind: ClaudePluginSourceKind
    location: str
    ref: str | None = None
    sparse: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_plugin_name(self.marketplace_name, "Claude marketplace name")
        if not isinstance(self.kind, ClaudePluginSourceKind):
            raise ValueError("Claude plugin source kind is invalid")
        if not isinstance(self.location, str) or not self.location.strip():
            raise ValueError("Claude plugin source location is invalid")
        _validate_secret_free(self.location, "Claude plugin source location")
        sparse = tuple(sorted(set(self.sparse)))
        if len(sparse) != len(self.sparse) or len(sparse) > 32:
            raise ValueError("Claude plugin sparse paths are invalid")
        for item in sparse:
            _normalize_relative_path(item, label="Claude plugin sparse path")
        object.__setattr__(self, "sparse", sparse)
        if self.kind is ClaudePluginSourceKind.LOCAL:
            if self.ref is not None or sparse:
                raise ValueError("local Claude marketplaces cannot use Git selectors")
            return
        if self.ref is None:
            raise ValueError("Git Claude marketplaces require an immutable ref")
        _validate_identity(self.ref, "Claude plugin source ref")
        object.__setattr__(self, "location", _canonical_git_source(self.location))


@dataclass(frozen=True)
class ClaudePluginRequest:
    """One immutable integration projected to an explicit Claude plugin scope."""

    package: IntegrationPackage
    scope: InstallationScope
    root: Path
    source: ClaudePluginSource
    plugin_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("Claude plugin request requires an IntegrationPackage")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("Claude plugin request scope is invalid")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.source, ClaudePluginSource):
            raise TypeError("Claude plugin request source is invalid")
        _validate_plugin_name(self.plugin_name, "Claude plugin name")
        if not any(
            item.type is IntegrationComponentType.PLUGIN
            for item in self.package.components
        ):
            raise ValueError("Claude plugin request package has no plugin component")
        if self.scope not in self.package.scopes:
            raise ValueError("Claude plugin request package does not support the scope")
        if not any(
            item.target_id == CLAUDE_PLUGIN_TARGET_ID
            for item in self.package.compatibility
        ):
            raise ValueError("Claude plugin request package is not target-compatible")
        if self.source.kind is ClaudePluginSourceKind.LOCAL:
            if self.package.source_type is not IntegrationSourceType.LOCAL:
                raise ValueError("local Claude source requires a local package source")
            if _absolute_path(Path(self.package.source)) != _absolute_path(
                Path(self.source.location)
            ):
                raise ValueError(
                    "Claude plugin source does not match the package source"
                )
        elif self.package.source_type not in {
            IntegrationSourceType.GIT,
            IntegrationSourceType.PROVIDER_MARKETPLACE,
        }:
            raise ValueError("Git Claude source requires a Git or marketplace package")
        elif _canonical_git_source(self.package.source) != self.source.location:
            raise ValueError("Claude plugin source does not match the package source")
        if (
            self.source.kind is ClaudePluginSourceKind.GIT
            and self.package.immutable_ref != self.source.ref
        ):
            raise ValueError(
                "Claude plugin Git ref does not match the immutable package"
            )


@dataclass(frozen=True)
class ClaudePluginApproval:
    """Explicit authority for one exact provider-native mutation preview."""

    plan_id: str
    authority: str
    native_consent_acknowledged: bool = False
    allow_network: bool = False
    allow_user_home: bool = False

    def __post_init__(self) -> None:
        if not _PLAN_RE.fullmatch(self.plan_id):
            raise ValueError("Claude plugin approval plan_id is invalid")
        _validate_identity(self.authority, "Claude plugin approval authority")
        for field_name in (
            "native_consent_acknowledged",
            "allow_network",
            "allow_user_home",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(
                    f"Claude plugin approval {field_name} must be a boolean"
                )


@dataclass(frozen=True)
class ClaudePluginPlan:
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
    native_scope: str
    expected_version: str | None
    expected_enabled: bool | None
    network_required: bool
    native_consent_required: bool
    restart_required: bool
    policy_status: str
    command_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClaudePluginProbe:
    """Bounded installed-Claude capability evidence."""

    status: str
    version: str | None
    command: str
    capabilities: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class ClaudePluginInstallation:
    """Content-free native Claude plugin discovery projection."""

    plugin_id: str
    name: str
    marketplace_name: str
    version: str
    scope: InstallationScope
    root: Path
    enabled: bool


@dataclass(frozen=True)
class ClaudePluginHealth:
    """Exact package identity and native marketplace evidence."""

    plugin_id: str
    package_id: str
    version: str
    enabled: bool
    exact_version: bool
    exact_source: bool
    status: str


@dataclass(frozen=True)
class ClaudePluginResult:
    """Content-free terminal evidence for one documented native CLI action."""

    action: str
    status: str
    plugin_id: str
    package_id: str
    version: str | None
    scope: InstallationScope
    enabled: bool
    restart_required: bool
    native_consent_owner: str = "claude"


@dataclass(frozen=True)
class ClaudePluginHandoff:
    """Truthful provider-owned transition without undocumented config writes."""

    action: str
    plugin_id: str
    command: tuple[str, ...]
    interaction: str
    consent_owner: str
    restart_required: bool
    reason: str


@dataclass(frozen=True)
class ClaudePluginCommandResult:
    """Bounded subprocess result returned by an injected command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


ClaudePluginCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float],
    ClaudePluginCommandResult,
]
ClaudePluginPolicy = Callable[[str, IntegrationPackage, InstallationScope], bool]


CLAUDE_PLUGIN_TARGET_DESCRIPTOR = ExtensionTargetDescriptor(
    id=CLAUDE_PLUGIN_TARGET_ID,
    revision=CLAUDE_PLUGIN_TARGET_REVISION,
    component_types=(IntegrationComponentType.PLUGIN,),
    scopes=(
        InstallationScope.MANAGED_HOME,
        InstallationScope.PROJECT,
        InstallationScope.USER_HOME,
    ),
    capabilities=(
        "documented_cli_install",
        "documented_cli_uninstall",
        "git_marketplace",
        "local_marketplace",
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
            id="claude-plugin-documented-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="anthropic-claude-code-docs",
            revision="2026-07-19",
        ),
    ),
)


@dataclass(frozen=True)
class _ClaudeExecutionContext:
    config_dir: Path
    cwd: Path | None
    native_scope: str


class ClaudePluginTargetDriver:
    """Operate Claude plugins only through documented native CLI commands."""

    descriptor = CLAUDE_PLUGIN_TARGET_DESCRIPTOR

    def __init__(
        self,
        data_dir: str | Path,
        *,
        managed_roots: Sequence[str | Path] = (),
        project_roots: Sequence[str | Path] = (),
        source_roots: Sequence[str | Path] = (),
        user_home_root: str | Path | None = None,
        allow_user_home: bool = False,
        executable: Sequence[str] = ("claude",),
        command_runner: ClaudePluginCommandRunner | None = None,
        policy: ClaudePluginPolicy | None = None,
        target_active: Callable[[Path], bool] | None = None,
    ) -> None:
        self.data_dir = _absolute_path(Path(data_dir))
        self.locks_root = self.data_dir / "integrations" / "claude-plugin" / "locks"
        native_root = self.data_dir / "native"
        self.managed_roots = _normalize_roots(managed_roots)
        for root in self.managed_roots:
            if not _is_relative_to(root, native_root):
                raise ValueError("managed Claude plugin roots must be Harness-native")
        self.project_roots = _normalize_roots(project_roots)
        self.source_roots = _normalize_roots(source_roots)
        self.user_home_root = (
            _absolute_path(Path(user_home_root)) if user_home_root is not None else None
        )
        self.allow_user_home = allow_user_home
        self.executable = tuple(str(item) for item in executable)
        if not self.executable or any(not item for item in self.executable):
            raise ValueError("Claude plugin executable is invalid")
        self.command_runner = command_runner or _run_command
        self.policy = policy or (lambda _action, _package, _scope: True)
        if not callable(self.policy):
            raise TypeError("Claude plugin policy must be callable")
        self.target_active = target_active or (lambda _root: False)

    def probe_target(self) -> ClaudePluginProbe:
        """Probe documented plugin surfaces in an isolated temporary home."""
        with tempfile.TemporaryDirectory(prefix="gigaloom-claude-plugin-probe-") as raw:
            context = _ClaudeExecutionContext(Path(raw) / ".claude", None, "user")
            commands = (
                ("--version",),
                ("plugin", "--help"),
                ("plugin", "validate", "--help"),
                ("plugin", "install", "--help"),
                ("plugin", "list", "--help"),
                ("plugin", "update", "--help"),
                ("plugin", "uninstall", "--help"),
                ("plugin", "enable", "--help"),
                ("plugin", "disable", "--help"),
                ("plugin", "marketplace", "add", "--help"),
                ("plugin", "marketplace", "list", "--help"),
                ("plugin", "marketplace", "update", "--help"),
                ("plugin", "marketplace", "remove", "--help"),
            )
            results = tuple(self._run(context, args) for args in commands)
        version = _first_line(results[0].stdout or results[0].stderr)
        texts = tuple(_bounded_output(item) for item in results[1:])
        expectations = (
            ("plugin_validate_strict", "--strict", texts[1]),
            ("plugin_install_scope", "--scope", texts[2]),
            ("plugin_list_json", "--json", texts[3]),
            ("plugin_update_scope", "--scope", texts[4]),
            ("plugin_uninstall_scope", "--scope", texts[5]),
            ("plugin_enable_scope", "--scope", texts[6]),
            ("plugin_disable_scope", "--scope", texts[7]),
            ("marketplace_add_scope", "--scope", texts[8]),
            ("marketplace_list_json", "--json", texts[9]),
            ("marketplace_update", "update", texts[10]),
            ("marketplace_remove_scope", "--scope", texts[11]),
        )
        capabilities = tuple(
            name for name, needle, text in expectations if needle in text
        )
        supported = (
            all(item.returncode == 0 for item in results)
            and len(capabilities) == len(expectations)
            and _supported_claude_version(version)
        )
        return ClaudePluginProbe(
            status="supported" if supported else "unsupported",
            version=version,
            command=str(redact_secrets(self.executable[0])),
            capabilities=capabilities,
            evidence="bounded --version and documented plugin help probes",
        )

    def discover_installed(self) -> tuple[ClaudePluginInstallation, ...]:
        """Discover plugins through native JSON for configured roots only."""
        roots = [(root, InstallationScope.MANAGED_HOME) for root in self.managed_roots]
        roots.extend((root, InstallationScope.PROJECT) for root in self.project_roots)
        if self.allow_user_home and self.user_home_root is not None:
            roots.append((self.user_home_root, InstallationScope.USER_HOME))
        discovered: list[ClaudePluginInstallation] = []
        for root, scope in roots:
            context = self._context(root, scope)
            for item in self._plugin_list(context):
                if item.get("scope") != context.native_scope:
                    continue
                discovered.append(_installation_from_item(item, root, scope))
        return tuple(
            sorted(discovered, key=lambda item: (str(item.root), item.plugin_id))
        )

    def preview_install(self, request: ClaudePluginRequest) -> ClaudePluginPlan:
        """Preview exact source registration and native installation commands."""
        return self._preview(request, action="install")

    def install(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
    ) -> ClaudePluginResult:
        """Register a source and install through the documented native CLI."""
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            self._authorize(request, plan, approval, action="install")
            self._require_inactive(root, "install")
            added_marketplace = self._ensure_marketplace(context, request.source)
            try:
                self._command(
                    context,
                    (
                        "plugin",
                        "install",
                        self._selector(request),
                        "--scope",
                        context.native_scope,
                    ),
                )
                health = self.verify(request)
                if health.status != "healthy":
                    raise ClaudePluginCommandError(
                        "Claude plugin install did not produce exact native discovery"
                    )
            except Exception:
                if added_marketplace:
                    self._best_effort_cleanup(context, request)
                raise
        return self._result("install", "installed", request, health)

    def verify(self, request: ClaudePluginRequest) -> ClaudePluginHealth:
        """Verify exact identity through native JSON without reading plugin caches."""
        _root, context = self._admit(request)
        current = self._current_plugin(context, self._selector(request))
        if current is None:
            return ClaudePluginHealth(
                plugin_id=self._selector(request),
                package_id=request.package.id,
                version="unknown",
                enabled=False,
                exact_version=False,
                exact_source=False,
                status="missing",
            )
        version = _required_string(current, "version", "Claude plugin version")
        exact_source = self._registered_source_matches(context, request.source)
        exact_version = version == request.package.version
        enabled = current.get("enabled") is True
        return ClaudePluginHealth(
            plugin_id=self._selector(request),
            package_id=request.package.id,
            version=version,
            enabled=enabled,
            exact_version=exact_version,
            exact_source=exact_source,
            status="healthy" if exact_version and exact_source else "degraded",
        )

    def health(self, request: ClaudePluginRequest) -> ClaudePluginHealth:
        """Alias native exact-discovery verification."""
        return self.verify(request)

    def preview_enable(self, request: ClaudePluginRequest) -> ClaudePluginPlan:
        """Preview native plugin enablement."""
        return self._preview(request, action="enable")

    def enable(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
    ) -> ClaudePluginResult:
        """Enable through the documented native CLI after exact approval."""
        return self._set_enabled(request, plan, approval, enabled=True)

    def preview_disable(self, request: ClaudePluginRequest) -> ClaudePluginPlan:
        """Preview native plugin disablement."""
        return self._preview(request, action="disable")

    def disable(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
    ) -> ClaudePluginResult:
        """Disable through the documented native CLI after exact approval."""
        return self._set_enabled(request, plan, approval, enabled=False)

    def preview_update(self, request: ClaudePluginRequest) -> ClaudePluginPlan:
        """Preview a reviewed marketplace refresh and native update."""
        return self._preview(request, action="update")

    def update(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
    ) -> ClaudePluginResult | ClaudePluginHandoff:
        """Update local sources; hand immutable Git ref replacement to Claude."""
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            if plan.policy_status == "provider_handoff_required":
                current = self._preview(request, action="update")
                if current != plan or approval.plan_id != plan.plan_id:
                    raise InstallationConflictError(
                        "Claude plugin source or native state changed after preview"
                    )
                return ClaudePluginHandoff(
                    action="update",
                    plugin_id=self._selector(request),
                    command=self.executable
                    + (
                        "plugin",
                        "marketplace",
                        "add",
                        _marketplace_source_arg(request.source),
                        "--scope",
                        context.native_scope,
                    ),
                    interaction=(
                        "replace the reviewed immutable marketplace ref, then run "
                        "the native plugin update command"
                    ),
                    consent_owner="claude",
                    restart_required=True,
                    reason=(
                        "Claude exposes marketplace replacement and plugin update as "
                        "separate non-atomic commands"
                    ),
                )
            self._authorize(request, plan, approval, action="update")
            self._require_inactive(root, "update")
            self._command(
                context,
                (
                    "plugin",
                    "marketplace",
                    "update",
                    request.source.marketplace_name,
                ),
            )
            self._command(
                context,
                (
                    "plugin",
                    "update",
                    self._selector(request),
                    "--scope",
                    context.native_scope,
                ),
            )
            health = self.verify(request)
            if health.status != "healthy":
                raise ClaudePluginCommandError(
                    "Claude plugin update did not produce exact native discovery"
                )
        return self._result("update", "updated", request, health)

    def preview_uninstall(self, request: ClaudePluginRequest) -> ClaudePluginPlan:
        """Preview exact native removal without provider-home cache writes."""
        return self._preview(request, action="uninstall")

    def uninstall(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
    ) -> ClaudePluginResult:
        """Remove one plugin through the documented native CLI."""
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            self._authorize(request, plan, approval, action="uninstall")
            self._require_inactive(root, "uninstall")
            self._command(
                context,
                (
                    "plugin",
                    "uninstall",
                    self._selector(request),
                    "--scope",
                    context.native_scope,
                    "--yes",
                ),
            )
            if self._current_plugin(context, self._selector(request)) is not None:
                raise ClaudePluginCommandError(
                    "Claude plugin uninstall did not remove native discovery"
                )
        return ClaudePluginResult(
            action="uninstall",
            status="uninstalled",
            plugin_id=self._selector(request),
            package_id=request.package.id,
            version=None,
            scope=request.scope,
            enabled=False,
            restart_required=True,
        )

    def rollback(self, request: ClaudePluginRequest) -> ClaudePluginHandoff:
        """Expose truthful reviewed-source rollback when no atomic CLI exists."""
        _root, context = self._admit(request)
        if self.verify(request).status == "missing":
            raise InstallationConflictError(
                "Claude plugin rollback requires a native installation"
            )
        return ClaudePluginHandoff(
            action="rollback",
            plugin_id=self._selector(request),
            command=self.executable
            + (
                "plugin",
                "update",
                self._selector(request),
                "--scope",
                context.native_scope,
            ),
            interaction="restore the previously reviewed marketplace version, then update",
            consent_owner="claude",
            restart_required=True,
            reason="Claude exposes update but no atomic version-selecting rollback command",
        )

    def _set_enabled(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
        *,
        enabled: bool,
    ) -> ClaudePluginResult:
        action = "enable" if enabled else "disable"
        root, context = self._admit(request)
        with exclusive_file_lock(self._lock_path(root, request.scope)):
            self._authorize(request, plan, approval, action=action)
            self._require_inactive(root, action)
            self._command(
                context,
                (
                    "plugin",
                    action,
                    self._selector(request),
                    "--scope",
                    context.native_scope,
                ),
            )
            health = self.verify(request)
            if health.status != "healthy" or health.enabled is not enabled:
                raise ClaudePluginCommandError(
                    f"Claude plugin {action} did not produce exact native discovery"
                )
        return self._result(action, f"{action}d", request, health)

    def _preview(
        self, request: ClaudePluginRequest, *, action: str
    ) -> ClaudePluginPlan:
        root, context = self._admit(request)
        source_hash = self._validate_source(request, context)
        current = self._current_plugin(context, self._selector(request))
        current_version = (
            _required_string(current, "version", "Claude plugin version")
            if current is not None
            else None
        )
        current_enabled = (
            current.get("enabled") is True if current is not None else None
        )
        if action == "install" and current is not None:
            raise InstallationConflictError(
                "Claude plugin is already installed; use update or uninstall"
            )
        if action in {"enable", "disable", "update", "uninstall"} and current is None:
            raise InstallationConflictError(
                f"Claude plugin {action} requires a native installation"
            )
        if action == "enable" and current_enabled:
            raise InstallationConflictError("Claude plugin is already enabled")
        if action == "disable" and not current_enabled:
            raise InstallationConflictError("Claude plugin is already disabled")
        policy_status = self._policy_status(action, request)
        if (
            policy_status == "allowed"
            and action == "update"
            and request.source.kind is ClaudePluginSourceKind.GIT
        ):
            policy_status = "provider_handoff_required"
        command_ids = {
            "install": (
                "plugin-validate",
                "marketplace-add",
                "plugin-install",
                "plugin-list",
            ),
            "enable": ("plugin-enable", "plugin-list"),
            "disable": ("plugin-disable", "plugin-list"),
            "update": (
                ("native-handoff",)
                if request.source.kind is ClaudePluginSourceKind.GIT
                else ("marketplace-update", "plugin-update", "plugin-list")
            ),
            "uninstall": ("plugin-uninstall", "plugin-list"),
        }[action]
        network_required = (
            request.source.kind is ClaudePluginSourceKind.GIT
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
            "native_scope": context.native_scope,
            "expected_version": current_version,
            "expected_enabled": current_enabled,
            "network_required": network_required,
            "native_consent_required": True,
            "restart_required": True,
            "policy_status": policy_status,
            "command_ids": list(command_ids),
        }
        return ClaudePluginPlan(
            action=action,
            plan_id=f"plan_{_json_hash(semantic)}",
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=semantic["manifest_sha256"],
            plugin_id=self._selector(request),
            source_sha256=source_hash,
            scope=request.scope,
            root=root,
            native_scope=context.native_scope,
            expected_version=current_version,
            expected_enabled=current_enabled,
            network_required=network_required,
            native_consent_required=True,
            restart_required=True,
            policy_status=policy_status,
            command_ids=command_ids,
        )

    def _authorize(
        self,
        request: ClaudePluginRequest,
        plan: ClaudePluginPlan,
        approval: ClaudePluginApproval,
        *,
        action: str,
    ) -> None:
        current = self._preview(request, action=action)
        if current != plan:
            raise InstallationConflictError(
                "Claude plugin source or native state changed after preview"
            )
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Claude plugin approval does not match the preview"
            )
        if plan.policy_status != "allowed":
            raise ClaudePluginPolicyError(
                f"Claude plugin action denied: {plan.policy_status}"
            )
        if not approval.native_consent_acknowledged:
            raise ClaudePluginPolicyError(
                "Claude plugin action requires explicit native consent acknowledgement"
            )
        if plan.network_required and not approval.allow_network:
            raise ClaudePluginPolicyError(
                "Claude Git marketplace action requires explicit network approval"
            )
        if (
            request.scope is InstallationScope.USER_HOME
            and not approval.allow_user_home
        ):
            raise InstallationScopeError(
                "Claude user-home plugin action requires explicit approval"
            )

    def _policy_status(self, action: str, request: ClaudePluginRequest) -> str:
        assessment = assess_integration_package(request.package)
        if assessment.decision is IntegrationTrustDecision.BLOCKED:
            return "package_blocked"
        if not self.policy(action, request.package, request.scope):
            return "managed_policy_denied"
        return "allowed"

    def _validate_source(
        self,
        request: ClaudePluginRequest,
        context: _ClaudeExecutionContext,
    ) -> str:
        if request.source.kind is ClaudePluginSourceKind.GIT:
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
                "Claude local marketplace source is not explicitly admitted"
            )
        inspection = _inspect_local_source(root, request.source, request.plugin_name)
        if inspection["version"] != request.package.version:
            raise InstallationConflictError(
                "Claude plugin manifest version does not match the package"
            )
        if inspection["checksum"] != request.package.checksum:
            raise InstallationConflictError(
                "Claude plugin source checksum does not match the package"
            )
        result = self._run(context, ("plugin", "validate", "--strict", str(root)))
        if result.returncode != 0:
            raise ClaudePluginCommandError(
                "Claude strict plugin validation rejected the reviewed source"
            )
        return str(inspection["source_sha256"])

    def _admit(
        self, request: ClaudePluginRequest
    ) -> tuple[Path, _ClaudeExecutionContext]:
        root = _absolute_path(request.root)
        context = self._context(root, request.scope)
        return root, context

    def _context(self, root: Path, scope: InstallationScope) -> _ClaudeExecutionContext:
        root = _absolute_path(root)
        if scope is InstallationScope.MANAGED_HOME:
            if root not in self.managed_roots:
                raise InstallationScopeError(
                    "Claude managed plugin root is not explicitly admitted"
                )
            context = _ClaudeExecutionContext(root, None, "user")
        elif scope is InstallationScope.PROJECT:
            if root not in self.project_roots:
                raise InstallationScopeError(
                    "Claude project plugin root is not explicitly admitted"
                )
            identity = _json_hash({"project_root": str(root)})
            config_dir = (
                self.data_dir / "native" / "claude" / "plugin-projects" / identity
            )
            context = _ClaudeExecutionContext(config_dir, root, "project")
        elif (
            not self.allow_user_home
            or self.user_home_root is None
            or root != self.user_home_root
        ):
            raise InstallationScopeError(
                "Claude user-home plugin root is disabled or mismatched"
            )
        else:
            context = _ClaudeExecutionContext(root, None, "user")
        if not root.is_dir() or root.is_symlink():
            raise InstallationScopeError(
                "Claude plugin root must be an existing regular directory"
            )
        return context

    def _ensure_marketplace(
        self,
        context: _ClaudeExecutionContext,
        source: ClaudePluginSource,
    ) -> bool:
        matches = self._matching_marketplaces(context, source.marketplace_name)
        if matches:
            if not _marketplace_source_matches(matches[0], source):
                raise InstallationConflictError(
                    "Claude marketplace name is registered to another source"
                )
            return False
        self._command(context, self._marketplace_add_args(source, context.native_scope))
        matches = self._matching_marketplaces(context, source.marketplace_name)
        if len(matches) != 1 or not _marketplace_source_matches(matches[0], source):
            raise ClaudePluginCommandError(
                "Claude marketplace registration did not preserve the reviewed source"
            )
        return True

    @staticmethod
    def _marketplace_add_args(
        source: ClaudePluginSource, native_scope: str
    ) -> tuple[str, ...]:
        args: list[str] = [
            "plugin",
            "marketplace",
            "add",
            _marketplace_source_arg(source),
            "--scope",
            native_scope,
        ]
        if source.sparse:
            args.append("--sparse")
            args.extend(source.sparse)
        return tuple(args)

    def _registered_source_matches(
        self,
        context: _ClaudeExecutionContext,
        source: ClaudePluginSource,
    ) -> bool:
        matches = self._matching_marketplaces(context, source.marketplace_name)
        return len(matches) == 1 and _marketplace_source_matches(matches[0], source)

    def _matching_marketplaces(
        self, context: _ClaudeExecutionContext, name: str
    ) -> tuple[Mapping[str, Any], ...]:
        matches = tuple(
            item for item in self._marketplace_list(context) if item.get("name") == name
        )
        if len(matches) > 1:
            raise InstallationStateError("Claude marketplace list has duplicate names")
        return matches

    def _marketplace_list(
        self, context: _ClaudeExecutionContext
    ) -> tuple[Mapping[str, Any], ...]:
        payload = self._json_array_command(
            context, ("plugin", "marketplace", "list", "--json")
        )
        return tuple(payload)

    def _plugin_list(
        self, context: _ClaudeExecutionContext
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._json_array_command(context, ("plugin", "list", "--json")))

    def _current_plugin(
        self, context: _ClaudeExecutionContext, selector: str
    ) -> Mapping[str, Any] | None:
        matches = [
            item
            for item in self._plugin_list(context)
            if item.get("id") == selector and item.get("scope") == context.native_scope
        ]
        if len(matches) > 1:
            raise InstallationStateError("Claude plugin list has duplicate identities")
        return matches[0] if matches else None

    def _json_array_command(
        self, context: _ClaudeExecutionContext, args: tuple[str, ...]
    ) -> list[Mapping[str, Any]]:
        result = self._command(context, args)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudePluginCommandError(
                "Claude command returned invalid JSON"
            ) from exc
        if not isinstance(payload, list) or any(
            not isinstance(item, Mapping) for item in payload
        ):
            raise ClaudePluginCommandError("Claude command JSON must be an object list")
        return payload

    def _command(
        self, context: _ClaudeExecutionContext, args: tuple[str, ...]
    ) -> ClaudePluginCommandResult:
        result = self._run(context, args)
        if result.returncode != 0:
            raise ClaudePluginCommandError(
                f"Claude command {args[0]} failed with status {result.returncode}"
            )
        return result

    def _run(
        self, context: _ClaudeExecutionContext, args: tuple[str, ...]
    ) -> ClaudePluginCommandResult:
        return self.command_runner(
            self.executable + args,
            _isolated_env(context.config_dir),
            context.cwd,
            CLAUDE_PLUGIN_COMMAND_TIMEOUT_SECONDS,
        )

    def _best_effort_cleanup(
        self,
        context: _ClaudeExecutionContext,
        request: ClaudePluginRequest,
    ) -> None:
        try:
            if self._current_plugin(context, self._selector(request)) is not None:
                self._run(
                    context,
                    (
                        "plugin",
                        "uninstall",
                        self._selector(request),
                        "--scope",
                        context.native_scope,
                        "--yes",
                    ),
                )
            self._run(
                context,
                (
                    "plugin",
                    "marketplace",
                    "remove",
                    request.source.marketplace_name,
                    "--scope",
                    context.native_scope,
                ),
            )
        except Exception:
            pass

    def _lock_path(self, root: Path, scope: InstallationScope) -> Path:
        if self.locks_root.is_symlink():
            raise InstallationStateError("Claude plugin lock root cannot be a symlink")
        self.locks_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.locks_root.is_symlink():
            raise InstallationStateError("Claude plugin lock root cannot be a symlink")
        os.chmod(self.locks_root, 0o700)
        return self.locks_root / _json_hash({"root": str(root), "scope": scope.value})

    def _require_inactive(self, root: Path, action: str) -> None:
        if self.target_active(root):
            raise InstallationConflictError(
                f"Claude plugin target is active; stop it before {action}"
            )

    @staticmethod
    def _selector(request: ClaudePluginRequest) -> str:
        return f"{request.plugin_name}@{request.source.marketplace_name}"

    @staticmethod
    def _result(
        action: str,
        status: str,
        request: ClaudePluginRequest,
        health: ClaudePluginHealth,
    ) -> ClaudePluginResult:
        return ClaudePluginResult(
            action=action,
            status=status,
            plugin_id=health.plugin_id,
            package_id=request.package.id,
            version=health.version,
            scope=request.scope,
            enabled=health.enabled,
            restart_required=True,
        )


def claude_plugin_target_plugin(
    factory: Callable[[], ClaudePluginTargetDriver],
) -> ExtensionTargetPlugin:
    """Build a neutral runtime registration for a configured Claude target."""
    return ExtensionTargetPlugin(
        descriptor=CLAUDE_PLUGIN_TARGET_DESCRIPTOR,
        factory=factory,
    )


def claude_plugin_source_checksum(
    marketplace_root: str | Path,
    marketplace_name: str,
    plugin_name: str,
) -> str:
    """Return the deterministic package checksum for one local marketplace entry."""
    source = ClaudePluginSource(
        marketplace_name=marketplace_name,
        kind=ClaudePluginSourceKind.LOCAL,
        location=str(_absolute_path(Path(marketplace_root))),
    )
    inspection = _inspect_local_source(
        _absolute_path(Path(marketplace_root)), source, plugin_name
    )
    return str(inspection["checksum"])


def _inspect_local_source(
    root: Path,
    source: ClaudePluginSource,
    plugin_name: str,
) -> Mapping[str, Any]:
    _assert_safe_tree_root(root, label="Claude marketplace root")
    marketplace = _read_json(
        root / ".claude-plugin" / "marketplace.json",
        label="Claude marketplace manifest",
    )
    if marketplace.get("name") != source.marketplace_name:
        raise ValueError("Claude marketplace manifest name does not match the source")
    _required_string(marketplace, "description", "Claude marketplace description")
    owner = marketplace.get("owner")
    if not isinstance(owner, Mapping):
        raise ValueError("Claude marketplace owner is required")
    _required_string(owner, "name", "Claude marketplace owner name")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("Claude marketplace plugins must be a list")
    matches = [
        item
        for item in plugins
        if isinstance(item, Mapping) and item.get("name") == plugin_name
    ]
    if len(matches) != 1:
        raise ValueError("Claude marketplace must contain one exact plugin entry")
    entry = matches[0]
    relative_source = _local_plugin_path(entry)
    plugin_root = _resolve_beneath(root, relative_source, label="Claude plugin source")
    _assert_safe_tree_root(plugin_root, label="Claude plugin source")
    manifest = _read_json(
        plugin_root / ".claude-plugin" / "plugin.json",
        label="Claude plugin manifest",
    )
    if manifest.get("name") != plugin_name:
        raise ValueError("Claude plugin manifest name does not match the marketplace")
    version = _required_string(manifest, "version", "Claude plugin manifest version")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Claude plugin manifest version is invalid")
    _required_string(manifest, "description", "Claude plugin description")
    author = manifest.get("author")
    if not isinstance(author, Mapping):
        raise ValueError("Claude plugin author is required")
    _required_string(author, "name", "Claude plugin author name")
    _validate_manifest_paths(plugin_root, manifest)
    checksum = _tree_checksum(plugin_root)
    return {
        "version": version,
        "checksum": checksum,
        "source_sha256": _json_hash(
            {
                "marketplace_name": source.marketplace_name,
                "plugin_name": plugin_name,
                "marketplace": marketplace,
                "entry": entry,
                "checksum": checksum,
            }
        ),
    }


def _local_plugin_path(entry: Mapping[str, Any]) -> str:
    source = entry.get("source")
    if not isinstance(source, str) or not source.startswith("./"):
        raise ValueError("Claude local marketplace plugin source must start with ./")
    return _normalize_relative_path(source, label="Claude marketplace plugin source")


def _validate_manifest_paths(root: Path, manifest: Mapping[str, Any]) -> None:
    for field_name in (
        "skills",
        "commands",
        "agents",
        "hooks",
        "mcpServers",
        "lspServers",
    ):
        value = manifest.get(field_name)
        if value is None or isinstance(value, Mapping):
            continue
        values = value if isinstance(value, list) else [value]
        if any(not isinstance(item, str) for item in values):
            raise ValueError(f"Claude plugin {field_name} paths are invalid")
        for item in values:
            if item.startswith("./"):
                _resolve_beneath(root, item, label=f"Claude plugin {field_name}")
            elif "/" in item or item.startswith("."):
                raise ValueError(f"Claude plugin {field_name} path is invalid")


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Claude plugin source cannot contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Claude plugin source contains a non-regular file")
        files.append(path)
    if not files or len(files) > MAX_CLAUDE_PLUGIN_FILES:
        raise ValueError("Claude plugin source file count is invalid")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        data = path.read_bytes()
        total += len(data)
        if (
            len(data) > MAX_CLAUDE_PLUGIN_FILE_BYTES
            or total > MAX_CLAUDE_PLUGIN_TOTAL_BYTES
        ):
            raise ValueError("Claude plugin source size is invalid")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def _installation_from_item(
    item: Mapping[str, Any],
    root: Path,
    scope: InstallationScope,
) -> ClaudePluginInstallation:
    plugin_id = _required_string(item, "id", "Claude plugin id")
    name, marketplace_name = _split_selector(plugin_id)
    version = _required_string(item, "version", "Claude plugin version")
    enabled = item.get("enabled")
    if not isinstance(enabled, bool):
        raise ClaudePluginCommandError("Claude plugin enabled state is invalid")
    return ClaudePluginInstallation(
        plugin_id=plugin_id,
        name=name,
        marketplace_name=marketplace_name,
        version=version,
        scope=scope,
        root=root,
        enabled=enabled,
    )


def _marketplace_source_matches(
    item: Mapping[str, Any], source: ClaudePluginSource
) -> bool:
    if source.kind is ClaudePluginSourceKind.LOCAL:
        if item.get("source") != "directory":
            return False
        expected = _absolute_path(Path(source.location))
        paths = [item.get("path"), item.get("installLocation")]
        return all(
            isinstance(value, str) and _absolute_path(Path(value)) == expected
            for value in paths
        )
    expected_arg = _marketplace_source_arg(source)
    candidates = {
        value
        for key in ("sourceLocation", "url", "repo", "path", "installLocation")
        if isinstance((value := item.get(key)), str)
    }
    if expected_arg not in candidates and not (
        source.location in candidates and item.get("ref") == source.ref
    ):
        return False
    sparse = item.get("sparse")
    if source.sparse:
        return isinstance(sparse, (list, tuple)) and tuple(sparse) == source.sparse
    return sparse in (None, [], ())


def _marketplace_source_arg(source: ClaudePluginSource) -> str:
    if source.kind is ClaudePluginSourceKind.LOCAL:
        return str(_absolute_path(Path(source.location)))
    separator = "@" if _GITHUB_SHORTHAND_RE.fullmatch(source.location) else "#"
    return f"{source.location}{separator}{source.ref}"


def _split_selector(value: str) -> tuple[str, str]:
    if value.count("@") != 1:
        raise ClaudePluginCommandError("Claude plugin id is invalid")
    name, marketplace = value.split("@", 1)
    _validate_plugin_name(name, "Claude plugin name")
    _validate_plugin_name(marketplace, "Claude marketplace name")
    return name, marketplace


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is missing or unsafe")
    if path.stat().st_size > MAX_CLAUDE_PLUGIN_FILE_BYTES:
        raise ValueError(f"{label} is too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return payload


def _resolve_beneath(root: Path, relative: str, *, label: str) -> Path:
    normalized = _normalize_relative_path(relative, label=label)
    resolved = _absolute_path(root / normalized)
    if not _is_relative_to(resolved, root):
        raise ValueError(f"{label} escapes the marketplace root")
    cursor = root
    for part in PurePosixPath(normalized).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"{label} cannot traverse a symlink")
    return resolved


def _assert_safe_tree_root(root: Path, *, label: str) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"{label} must be an existing regular directory")


def _normalize_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} is invalid")
    candidate = value.removeprefix("./")
    path = PurePosixPath(candidate)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{label} is invalid")
    return path.as_posix()


def _canonical_git_source(value: str) -> str:
    _validate_secret_free(value, "Claude plugin Git source")
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
        or not parsed.path.endswith(".git")
    ):
        raise ValueError(
            "Claude plugin Git source must be GitHub shorthand or HTTPS .git"
        )
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, "", ""))


def _supported_claude_version(value: str | None) -> bool:
    if value is None:
        return False
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", value)
    if match is None:
        return False
    return tuple(int(item) for item in match.groups()) >= (2, 1, 143)


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> ClaudePluginCommandResult:
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
        raise ClaudePluginCommandError(
            f"Claude command failed with {type(exc).__name__}"
        ) from exc
    return ClaudePluginCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[-MAX_CLAUDE_PLUGIN_OUTPUT_CHARS:],
        stderr=completed.stderr[-MAX_CLAUDE_PLUGIN_OUTPUT_CHARS:],
    )


def _isolated_env(config_dir: Path) -> dict[str, str]:
    env = {
        key: value
        for key in ("PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if (value := os.environ.get(key)) is not None
    }
    env.update(
        {
            "HOME": str(config_dir.parent),
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            "NO_COLOR": "1",
        }
    )
    return env


def _bounded_output(result: ClaudePluginCommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"[-MAX_CLAUDE_PLUGIN_OUTPUT_CHARS:]


def _first_line(value: str) -> str | None:
    lines = value.strip().splitlines()
    return lines[0][:200] if lines else None


def _required_string(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"{label} is invalid")
    _validate_secret_free(value, label)
    return value


def _normalize_roots(values: Sequence[str | Path]) -> tuple[Path, ...]:
    return tuple(sorted({_absolute_path(Path(item)) for item in values}, key=str))


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_plugin_name(value: str, label: str) -> None:
    if not isinstance(value, str) or not _PLUGIN_NAME_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_secret_free(value: str, label: str) -> None:
    if str(redact_secrets(value)) != value:
        raise ValueError(f"{label} contains secret material")


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CLAUDE_PLUGIN_TARGET_DESCRIPTOR",
    "CLAUDE_PLUGIN_TARGET_ID",
    "ClaudePluginApproval",
    "ClaudePluginCommandError",
    "ClaudePluginCommandResult",
    "ClaudePluginHandoff",
    "ClaudePluginHealth",
    "ClaudePluginInstallation",
    "ClaudePluginPlan",
    "ClaudePluginPolicyError",
    "ClaudePluginProbe",
    "ClaudePluginRequest",
    "ClaudePluginResult",
    "ClaudePluginSource",
    "ClaudePluginSourceKind",
    "ClaudePluginTargetDriver",
    "ClaudePluginTargetError",
    "claude_plugin_source_checksum",
    "claude_plugin_target_plugin",
]
