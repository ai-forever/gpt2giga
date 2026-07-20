"""Claude MCP target lifecycle over documented config and CLI surfaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from gpt2giga_harness.integration_installer import (
    FileInstallMutation,
    InstallationApproval,
    InstallationConflictError,
    InstallationPlan,
    InstallationRequest,
    InstallationResult,
    InstallationStateError,
    InstallationTarget,
    TransactionalIntegrationInstaller,
)
from gpt2giga_harness.integration_packages import (
    ExtensionTargetDescriptor,
    ExtensionTargetPlugin,
    InstallationScope,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationTrustEvidence,
    IntegrationTrustKind,
    IntegrationTrustStatus,
    integration_package_semantic_hash,
)
from gpt2giga_harness.types import redact_secrets


CLAUDE_MCP_TARGET_ID = "claude-mcp"
CLAUDE_MCP_TARGET_REVISION = "1"
CLAUDE_MCP_OWNER_ID = "claude-mcp-config"
CLAUDE_MCP_CONFIG_PATH = ".mcp.json"
CLAUDE_MCP_COMMAND_TIMEOUT_SECONDS = 10.0
MAX_CLAUDE_MCP_OUTPUT_CHARS = 128_000
MAX_CLAUDE_MCP_UNINSTALL_DEPTH = 100
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_ENV_REFERENCE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]{0,127}\}\Z")


class ClaudeMCPTransport(str, Enum):
    """Current documented Claude MCP transport families admitted by the target."""

    STDIO = "stdio"
    HTTP = "http"


class ClaudeMCPTargetError(RuntimeError):
    """Base error for Claude MCP target operations."""


class ClaudeMCPCommandError(ClaudeMCPTargetError):
    """Raised when a bounded Claude CLI command cannot prove its contract."""


@dataclass(frozen=True)
class ClaudeMCPServerSpec:
    """Secret-free Claude MCP configuration for one immutable server."""

    name: str
    transport: ClaudeMCPTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    url: str | None = None
    env_http_headers: tuple[tuple[str, str], ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_identity(self.name, "Claude MCP server name")
        if not isinstance(self.transport, ClaudeMCPTransport):
            raise ValueError("Claude MCP transport is invalid")
        object.__setattr__(self, "args", _normalize_texts(self.args, "argument"))
        object.__setattr__(
            self,
            "env_vars",
            _normalize_names(self.env_vars, "environment variable"),
        )
        headers = tuple(sorted(tuple(item) for item in self.env_http_headers))
        if len(headers) != len(set(headers)) or len(
            {item[0].lower() for item in headers}
        ) != len(headers):
            raise ValueError("Claude MCP environment headers contain duplicates")
        for header, env_name in headers:
            _validate_header_name(header)
            _validate_env_name(env_name)
        object.__setattr__(self, "env_http_headers", headers)
        if not isinstance(self.enabled, bool):
            raise ValueError("Claude MCP enablement flag must be a boolean")
        self._validate_transport()

    def _validate_transport(self) -> None:
        if self.transport is ClaudeMCPTransport.STDIO:
            if not self.command or not self.command.strip():
                raise ValueError("Claude stdio MCP server requires a command")
            _validate_secret_free(self.command, "Claude MCP command")
            if self.url is not None or self.env_http_headers:
                raise ValueError("Claude stdio MCP server cannot use HTTP fields")
            return
        if self.command is not None or self.args or self.env_vars:
            raise ValueError("Claude HTTP MCP server cannot use stdio fields")
        if self.url is None:
            raise ValueError("Claude HTTP MCP server requires a URL")
        object.__setattr__(self, "url", _canonical_https_url(self.url))


@dataclass(frozen=True)
class ClaudeMCPRequest:
    """One immutable package projected to an admitted Claude config root."""

    package: IntegrationPackage
    scope: InstallationScope
    root: Path
    server: ClaudeMCPServerSpec

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("Claude MCP request requires an IntegrationPackage")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("Claude MCP request scope is invalid")
        if self.scope is InstallationScope.USER_HOME:
            raise ValueError(
                "Claude user scope requires native handoff because ~/.claude.json "
                "also owns auth and cache state"
            )
        if self.scope not in {
            InstallationScope.MANAGED_HOME,
            InstallationScope.PROJECT,
        }:
            raise ValueError("Claude MCP request scope is unsupported")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.server, ClaudeMCPServerSpec):
            raise TypeError("Claude MCP request server is invalid")
        if self.server.name != self.package.id:
            raise ValueError("Claude MCP server name must equal the package id")
        if not any(
            component.type is IntegrationComponentType.MCP
            for component in self.package.components
        ):
            raise ValueError("Claude MCP request package has no MCP component")
        if self.scope not in self.package.scopes:
            raise ValueError("Claude MCP request package does not support the scope")
        if not any(
            item.target_id == CLAUDE_MCP_TARGET_ID
            for item in self.package.compatibility
        ):
            raise ValueError("Claude MCP request package is not target-compatible")


@dataclass(frozen=True)
class ClaudeMCPPlan:
    """Content-free Claude lifecycle preview bound to one installer plan."""

    action: str
    plan_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    server_spec_sha256: str
    enabled: bool
    installation: InstallationPlan


@dataclass(frozen=True)
class ClaudeMCPProbe:
    """Bounded current Claude CLI capability evidence."""

    status: str
    version: str | None
    command: str
    capabilities: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class ClaudeMCPInstallation:
    """Content-free current Claude MCP installation projection."""

    transaction_id: str
    package_id: str
    package_version: str
    scope: InstallationScope
    server_name: str
    enabled: bool
    current: bool


@dataclass(frozen=True)
class ClaudeMCPHealth:
    """Exact config plus provider-owned Claude discovery evidence."""

    transaction_id: str
    package_id: str
    server_name: str
    enabled: bool
    exact_snapshot: bool
    native_cli_discovered: bool
    native_consent_required: bool
    auth_ownership: str
    consent_ownership: str
    status: str


@dataclass(frozen=True)
class ClaudeMCPUninstallPlan:
    """Approval-bound request to unwind one package's owned transaction chain."""

    plan_id: str
    package_id: str
    transaction_id: str
    owner_revision: str
    scope: InstallationScope


@dataclass(frozen=True)
class ClaudeMCPHandoff:
    """Content-free provider-owned launch instructions for the pinned server."""

    transaction_id: str
    server_name: str
    argv: tuple[str, ...]
    cwd: Path
    auth_prerequisite: str
    auth_ownership: str
    consent_ownership: str
    provider_ui_handoff: bool
    embedded_execution: bool = False


@dataclass(frozen=True)
class ClaudeCommandResult:
    """Bounded subprocess result returned by an injected command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


ClaudeCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float], ClaudeCommandResult
]


CLAUDE_MCP_TARGET_DESCRIPTOR = ExtensionTargetDescriptor(
    id=CLAUDE_MCP_TARGET_ID,
    revision=CLAUDE_MCP_TARGET_REVISION,
    component_types=(IntegrationComponentType.MCP,),
    scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
    capabilities=(
        "disable",
        "enable",
        "health",
        "http",
        "install",
        "native_consent",
        "provider_handoff",
        "rollback",
        "stdio",
        "uninstall",
        "update",
        "verify",
    ),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="claude-mcp-documented-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="anthropic-claude-code-docs",
            revision="2026-07-19",
        ),
    ),
)


class ClaudeMCPTargetDriver:
    """Own one reversible Claude MCP package per explicit target root."""

    descriptor = CLAUDE_MCP_TARGET_DESCRIPTOR

    def __init__(
        self,
        data_dir: str | Path,
        *,
        project_roots: Sequence[str | Path] = (),
        executable: Sequence[str] = ("claude",),
        command_runner: ClaudeCommandRunner | None = None,
        target_active: Callable[[Path], bool] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.executable = tuple(str(item) for item in executable)
        if not self.executable or any(not item for item in self.executable):
            raise ValueError("Claude MCP executable is invalid")
        self.command_runner = command_runner or _run_command
        self.installer = TransactionalIntegrationInstaller(
            self.data_dir,
            project_roots=project_roots,
            target_active=target_active,
        )

    def probe_target(self) -> ClaudeMCPProbe:
        """Probe documented, side-effect-free Claude MCP and handoff surfaces."""
        with tempfile.TemporaryDirectory(prefix="gigaloom-claude-mcp-probe-") as raw:
            env = _isolated_env(Path(raw) / ".claude")
            version = self.command_runner(
                self.executable + ("--version",),
                env,
                None,
                CLAUDE_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            root_help = self.command_runner(
                self.executable + ("--help",),
                env,
                None,
                CLAUDE_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            mcp_help = self.command_runner(
                self.executable + ("mcp", "--help"),
                env,
                None,
                CLAUDE_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            add_help = self.command_runner(
                self.executable + ("mcp", "add", "--help"),
                env,
                None,
                CLAUDE_MCP_COMMAND_TIMEOUT_SECONDS,
            )
        root_text = _bounded_output(root_help)
        mcp_text = _bounded_output(mcp_help)
        add_text = _bounded_output(add_help)
        capabilities = tuple(
            name
            for name, proven in (
                ("mcp_add", "add" in mcp_text),
                ("mcp_get", "get" in mcp_text),
                ("mcp_list", "list" in mcp_text),
                ("mcp_remove", "remove" in mcp_text),
                ("mcp_project_scope", "project" in add_text),
                ("mcp_user_scope", "user" in add_text),
                ("mcp_config", "--mcp-config" in root_text),
                ("strict_mcp_config", "--strict-mcp-config" in root_text),
            )
            if proven
        )
        results = (version, root_help, mcp_help, add_help)
        status = (
            "supported"
            if all(item.returncode == 0 for item in results) and len(capabilities) == 8
            else "unsupported"
        )
        return ClaudeMCPProbe(
            status=status,
            version=_first_line(version.stdout or version.stderr),
            command=str(redact_secrets(self.executable[0])),
            capabilities=capabilities,
            evidence="bounded --version, --help, mcp --help, and mcp add --help probes",
        )

    def discover_installed(self) -> tuple[ClaudeMCPInstallation, ...]:
        """Discover installer ownership plus the exact package-named server."""
        discovered: list[ClaudeMCPInstallation] = []
        for installed in self.installer.discover():
            if installed.target_id != CLAUDE_MCP_TARGET_ID:
                continue
            plan = self.installer.transaction_plan(installed.transaction_id)
            config = _config(plan.root)
            server = _server(config, installed.package_id)
            discovered.append(
                ClaudeMCPInstallation(
                    transaction_id=installed.transaction_id,
                    package_id=installed.package_id,
                    package_version=installed.package_version,
                    scope=installed.scope,
                    server_name=installed.package_id,
                    enabled=server is not None,
                    current=installed.current,
                )
            )
        return tuple(discovered)

    def preview_install(self, request: ClaudeMCPRequest) -> ClaudeMCPPlan:
        """Preview a first install without addressing a real Claude home."""
        if self._installation_for_root(request.root) is not None:
            raise InstallationConflictError(
                "Claude MCP target already owns a package; use update or uninstall"
            )
        return self._preview(request, action="install")

    def install(
        self,
        request: ClaudeMCPRequest,
        plan: ClaudeMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Install and prove provider-owned discovery without granting consent."""
        self._validate_action(request, plan, "install")
        return self.installer.apply(
            self._installation_request(request, owned=False),
            plan.installation,
            approval,
            verifier=lambda root, _plan: self._verify_target(root, request),
        )

    def verify(self, transaction_id: str) -> ClaudeMCPHealth:
        """Verify exact files and native discovery in isolated consent state."""
        installed = self.installer.verify(transaction_id)
        plan = self.installer.transaction_plan(transaction_id)
        config = _config(plan.root)
        server = _server(config, installed.package_id)
        enabled = server is not None
        discovered, pending = self._native_get(
            plan.root,
            installed.package_id,
            expect_present=enabled,
        )
        exact = installed.current
        if not enabled:
            status = "disabled" if discovered else "degraded"
        elif discovered and pending:
            status = "awaiting_native_consent"
        elif discovered:
            status = "provider_owned"
        else:
            status = "degraded"
        return ClaudeMCPHealth(
            transaction_id=transaction_id,
            package_id=installed.package_id,
            server_name=installed.package_id,
            enabled=enabled,
            exact_snapshot=exact,
            native_cli_discovered=discovered if enabled else False,
            native_consent_required=pending,
            auth_ownership="claude_code",
            consent_ownership="claude_code",
            status=status,
        )

    def preview_enable(self, request: ClaudeMCPRequest) -> ClaudeMCPPlan:
        """Preview restoring the exact package-named server."""
        return self._preview(
            replace(request, server=replace(request.server, enabled=True)),
            action="enable",
        )

    def enable(
        self,
        request: ClaudeMCPRequest,
        plan: ClaudeMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Enable by atomically restoring the documented server entry."""
        enabled = replace(request, server=replace(request.server, enabled=True))
        return self._update(enabled, plan, approval, action="enable")

    def preview_disable(self, request: ClaudeMCPRequest) -> ClaudeMCPPlan:
        """Preview removing the server entry while retaining rollback ownership."""
        return self._preview(
            replace(request, server=replace(request.server, enabled=False)),
            action="disable",
        )

    def disable(
        self,
        request: ClaudeMCPRequest,
        plan: ClaudeMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Disable without altering Claude's provider-owned consent state."""
        disabled = replace(request, server=replace(request.server, enabled=False))
        return self._update(disabled, plan, approval, action="disable")

    def preview_update(self, request: ClaudeMCPRequest) -> ClaudeMCPPlan:
        """Preview a pinned package/spec replacement."""
        return self._preview(request, action="update")

    def update(
        self,
        request: ClaudeMCPRequest,
        plan: ClaudeMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Atomically update config while preserving native ownership."""
        return self._update(request, plan, approval, action="update")

    def preview_uninstall(self, transaction_id: str) -> ClaudeMCPUninstallPlan:
        """Bind uninstall approval to the exact current owner revision."""
        installed = self.installer.verify(transaction_id)
        semantic = {
            "action": "uninstall",
            "package_id": installed.package_id,
            "transaction_id": installed.transaction_id,
            "owner_revision": installed.owner_revision,
            "scope": installed.scope.value,
        }
        return ClaudeMCPUninstallPlan(
            plan_id=f"plan_{_json_hash(semantic)}",
            package_id=installed.package_id,
            transaction_id=installed.transaction_id,
            owner_revision=installed.owner_revision,
            scope=installed.scope,
        )

    def uninstall(
        self,
        plan: ClaudeMCPUninstallPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Unwind only the approved package's exact update chain."""
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Claude MCP uninstall approval does not match the preview"
            )
        current = self.installer.verify(plan.transaction_id)
        if (
            current.package_id != plan.package_id
            or current.owner_revision != plan.owner_revision
        ):
            raise InstallationConflictError(
                "Claude MCP installation changed after uninstall preview"
            )
        result: InstallationResult | None = None
        root = self.installer.transaction_plan(plan.transaction_id).root
        for _ in range(MAX_CLAUDE_MCP_UNINSTALL_DEPTH):
            result = self.installer.rollback(current.transaction_id)
            remaining = self._installation_for_root(root)
            if remaining is None:
                return result
            if remaining.package_id != plan.package_id:
                raise InstallationStateError(
                    "Claude MCP uninstall encountered a foreign owner"
                )
            current = self.installer.verify(remaining.transaction_id)
        raise InstallationStateError("Claude MCP uninstall chain is too deep")

    def rollback(self, transaction_id: str) -> InstallationResult:
        """Roll back exactly one current lifecycle transition."""
        return self.installer.rollback(transaction_id)

    def health(self, transaction_id: str) -> ClaudeMCPHealth:
        """Alias target health to exact, consent-preserving verification."""
        return self.verify(transaction_id)

    def preview_handoff(
        self,
        transaction_id: str,
        *,
        workspace: str | Path | None = None,
    ) -> ClaudeMCPHandoff:
        """Return provider-owned launch instructions without executing Claude."""
        health = self.verify(transaction_id)
        if (
            not health.enabled
            or not health.exact_snapshot
            or not health.native_cli_discovered
        ):
            raise ClaudeMCPTargetError("Claude MCP target is not exactly discoverable")
        installed = self.installer.verify(transaction_id)
        root = self.installer.transaction_plan(transaction_id).root
        if installed.scope is InstallationScope.MANAGED_HOME:
            argv = self.executable + (
                "--mcp-config",
                str(root / CLAUDE_MCP_CONFIG_PATH),
                "--strict-mcp-config",
            )
            cwd = Path(workspace).expanduser().resolve() if workspace else root
        else:
            if workspace is not None and Path(workspace).expanduser().resolve() != root:
                raise ValueError("Claude project handoff workspace must equal its root")
            argv = self.executable
            cwd = root
        return ClaudeMCPHandoff(
            transaction_id=transaction_id,
            server_name=health.server_name,
            argv=argv,
            cwd=cwd,
            auth_prerequisite="claude_native_auth",
            auth_ownership="claude_code",
            consent_ownership="claude_code",
            provider_ui_handoff=True,
        )

    def _preview(self, request: ClaudeMCPRequest, *, action: str) -> ClaudeMCPPlan:
        existing = self._installation_for_root(request.root)
        if action != "install":
            if existing is None:
                raise InstallationConflictError(
                    "Claude MCP lifecycle change requires an existing owner"
                )
            if existing.package_id != request.package.id:
                raise InstallationConflictError(
                    "Claude MCP target cannot replace a different package"
                )
        installation = self.installer.preview(
            self._installation_request(request, owned=existing is not None)
        )
        return ClaudeMCPPlan(
            action=action,
            plan_id=installation.plan_id,
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=integration_package_semantic_hash(request.package),
            server_spec_sha256=_server_spec_hash(request.server),
            enabled=request.server.enabled,
            installation=installation,
        )

    def _update(
        self,
        request: ClaudeMCPRequest,
        plan: ClaudeMCPPlan,
        approval: InstallationApproval,
        *,
        action: str,
    ) -> InstallationResult:
        self._validate_action(request, plan, action)
        return self.installer.update(
            self._installation_request(request, owned=True),
            plan.installation,
            approval,
            verifier=lambda root, _plan: self._verify_target(root, request),
        )

    def _validate_action(
        self, request: ClaudeMCPRequest, plan: ClaudeMCPPlan, action: str
    ) -> None:
        expected = (
            action,
            request.package.id,
            request.package.version,
            integration_package_semantic_hash(request.package),
            _server_spec_hash(request.server),
            request.server.enabled,
        )
        actual = (
            plan.action,
            plan.package_id,
            plan.package_version,
            plan.manifest_sha256,
            plan.server_spec_sha256,
            plan.enabled,
        )
        if actual != expected or plan.plan_id != plan.installation.plan_id:
            raise InstallationConflictError(
                "Claude MCP lifecycle plan does not match the request"
            )

    def _installation_request(
        self, request: ClaudeMCPRequest, *, owned: bool
    ) -> InstallationRequest:
        root = request.root.expanduser().resolve()
        current = _config_text(root)
        desired = _render_config(current, request, owned=owned)
        return InstallationRequest(
            package=request.package,
            target=InstallationTarget(
                id=CLAUDE_MCP_TARGET_ID,
                scope=request.scope,
                root=root,
                owner_id=CLAUDE_MCP_OWNER_ID,
            ),
            mutations=(
                FileInstallMutation(
                    relative_path=CLAUDE_MCP_CONFIG_PATH,
                    content=desired.encode("utf-8"),
                    mode=(
                        0o644 if request.scope is InstallationScope.PROJECT else 0o600
                    ),
                ),
            ),
        )

    def _verify_target(self, root: Path, request: ClaudeMCPRequest) -> bool:
        config = _config(root)
        server = _server(config, request.package.id)
        if request.server.enabled:
            if server != _server_payload(request.server):
                return False
        elif server is not None:
            return False
        discovered, _pending = self._native_get(
            root,
            request.package.id,
            expect_present=request.server.enabled,
        )
        return discovered

    def _native_get(
        self,
        root: Path,
        server_name: str,
        *,
        expect_present: bool,
    ) -> tuple[bool, bool]:
        with tempfile.TemporaryDirectory(prefix="gigaloom-claude-mcp-get-") as raw:
            raw_path = Path(raw)
            project = raw_path / "project"
            project.mkdir(mode=0o700)
            (project / CLAUDE_MCP_CONFIG_PATH).write_text(
                _config_text(root), encoding="utf-8"
            )
            result = self.command_runner(
                self.executable + ("mcp", "get", server_name),
                _isolated_env(raw_path / ".claude"),
                project,
                CLAUDE_MCP_COMMAND_TIMEOUT_SECONDS,
            )
        output = _bounded_output(result)
        if not expect_present:
            absent = result.returncode != 0 and "No MCP server named" in output
            return absent, False
        discovered = result.returncode == 0 and f"{server_name}:" in output
        pending = discovered and "Pending approval" in output
        return discovered, pending

    def _installation_for_root(self, root: Path):
        resolved = root.expanduser().resolve()
        matches = []
        for installed in self.installer.discover():
            if installed.target_id != CLAUDE_MCP_TARGET_ID:
                continue
            plan = self.installer.transaction_plan(installed.transaction_id)
            if plan.root == resolved:
                matches.append(installed)
        if len(matches) > 1:
            raise InstallationStateError("Claude MCP target has duplicate owners")
        return matches[0] if matches else None


def claude_mcp_target_plugin(
    factory: Callable[[], ClaudeMCPTargetDriver],
) -> ExtensionTargetPlugin:
    """Build a neutral runtime registration for a configured Claude target."""
    return ExtensionTargetPlugin(
        descriptor=CLAUDE_MCP_TARGET_DESCRIPTOR,
        factory=factory,
    )


def _render_config(current: str, request: ClaudeMCPRequest, *, owned: bool) -> str:
    config = dict(_parse_config(current))
    _validate_secret_free_config(config)
    raw_servers = config.get("mcpServers", {})
    if not isinstance(raw_servers, Mapping):
        raise ValueError("Claude mcpServers config must be an object")
    servers = dict(raw_servers)
    if not owned and request.package.id in servers:
        raise InstallationConflictError(
            "Claude MCP server name is already owned outside this package"
        )
    if request.server.enabled:
        servers[request.package.id] = _server_payload(request.server)
    else:
        servers.pop(request.package.id, None)
    config["mcpServers"] = servers
    return json.dumps(config, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _config(root: Path) -> Mapping[str, Any]:
    return _parse_config(_config_text(root))


def _config_text(root: Path) -> str:
    try:
        return (root / CLAUDE_MCP_CONFIG_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _parse_config(value: str) -> Mapping[str, Any]:
    if not value.strip():
        return {}

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Claude .mcp.json contains duplicate keys")
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise ValueError("Claude .mcp.json is invalid") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("Claude .mcp.json must be an object")
    servers = parsed.get("mcpServers", {})
    if not isinstance(servers, Mapping):
        raise ValueError("Claude mcpServers config must be an object")
    return parsed


def _server(config: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    servers = config.get("mcpServers", {})
    if not isinstance(servers, Mapping):
        raise ValueError("Claude mcpServers config must be an object")
    server = servers.get(name)
    if server is None:
        return None
    if not isinstance(server, Mapping):
        raise ValueError("Claude MCP server config must be an object")
    return server


def _server_payload(server: ClaudeMCPServerSpec) -> dict[str, Any]:
    if server.transport is ClaudeMCPTransport.STDIO:
        payload: dict[str, Any] = {
            "type": "stdio",
            "command": server.command,
            "args": list(server.args),
        }
        if server.env_vars:
            payload["env"] = {name: f"${{{name}}}" for name in server.env_vars}
        return payload
    payload = {"type": "http", "url": server.url}
    if server.env_http_headers:
        payload["headers"] = {
            header: f"${{{env_name}}}" for header, env_name in server.env_http_headers
        }
    return payload


def _server_spec_hash(server: ClaudeMCPServerSpec) -> str:
    return _json_hash(
        {
            "name": server.name,
            "enabled": server.enabled,
            "server": _server_payload(server),
        }
    )


def _validate_secret_free_config(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                _validate_secret_free_config(item)
                continue
            if isinstance(item, str) and _ENV_REFERENCE_RE.fullmatch(item):
                continue
            if redact_secrets({str(key): item}) != {str(key): item}:
                raise ValueError("Claude .mcp.json contains secret material")
            _validate_secret_free_config(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_secret_free_config(item)
        return
    if isinstance(value, str) and str(redact_secrets(value)) != value:
        raise ValueError("Claude .mcp.json contains secret material")


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> ClaudeCommandResult:
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
        raise ClaudeMCPCommandError(
            f"Claude command failed with {type(exc).__name__}"
        ) from exc
    return ClaudeCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[-MAX_CLAUDE_MCP_OUTPUT_CHARS:],
        stderr=completed.stderr[-MAX_CLAUDE_MCP_OUTPUT_CHARS:],
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


def _bounded_output(result: ClaudeCommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"[-MAX_CLAUDE_MCP_OUTPUT_CHARS:]


def _first_line(value: str) -> str | None:
    lines = value.strip().splitlines()
    return lines[0][:200] if lines else None


def _canonical_https_url(value: str) -> str:
    _validate_secret_free(value, "Claude MCP URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Claude HTTP MCP URL must be credential-free HTTPS")
    if parsed.fragment:
        raise ValueError("Claude HTTP MCP URL cannot contain a fragment")
    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )


def _normalize_texts(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(str(item) for item in values)
    if len(normalized) > 256:
        raise ValueError(f"Claude MCP {label} count is invalid")
    for item in normalized:
        if not item or len(item) > 4096:
            raise ValueError(f"Claude MCP {label} is invalid")
        _validate_secret_free(item, f"Claude MCP {label}")
    return normalized


def _normalize_names(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(str(item) for item in values)))
    if len(normalized) != len(tuple(values)):
        raise ValueError(f"Claude MCP {label} contains duplicates")
    for item in normalized:
        _validate_env_name(item)
    return normalized


def _validate_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_env_name(value: str) -> None:
    if not isinstance(value, str) or not _ENV_RE.fullmatch(value):
        raise ValueError("Claude MCP environment variable name is invalid")


def _validate_header_name(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value):
        raise ValueError("Claude MCP HTTP header name is invalid")


def _validate_secret_free(value: str, label: str) -> None:
    if str(redact_secrets(value)) != value:
        raise ValueError(f"{label} contains secret material")


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CLAUDE_MCP_TARGET_DESCRIPTOR",
    "CLAUDE_MCP_TARGET_ID",
    "ClaudeCommandResult",
    "ClaudeMCPCommandError",
    "ClaudeMCPHandoff",
    "ClaudeMCPHealth",
    "ClaudeMCPInstallation",
    "ClaudeMCPPlan",
    "ClaudeMCPProbe",
    "ClaudeMCPRequest",
    "ClaudeMCPServerSpec",
    "ClaudeMCPTargetDriver",
    "ClaudeMCPTargetError",
    "ClaudeMCPTransport",
    "ClaudeMCPUninstallPlan",
    "claude_mcp_target_plugin",
]
