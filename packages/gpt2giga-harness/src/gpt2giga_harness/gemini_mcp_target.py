"""Gemini MCP target lifecycle over documented config and CLI surfaces."""

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


GEMINI_MCP_TARGET_ID = "gemini-mcp"
GEMINI_MCP_TARGET_REVISION = "1"
GEMINI_MCP_OWNER_ID = "gemini-mcp-config"
GEMINI_MCP_CONFIG_PATH = ".gemini/settings.json"
GEMINI_MCP_COMMAND_TIMEOUT_SECONDS = 10.0
MAX_GEMINI_MCP_OUTPUT_CHARS = 128_000
MAX_GEMINI_MCP_UNINSTALL_DEPTH = 100
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_ENV_REFERENCE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]{0,127}\}\Z")


class GeminiMCPTransport(str, Enum):
    """Current documented Gemini MCP transport families admitted by the target."""

    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class GeminiMCPTargetError(RuntimeError):
    """Base error for Gemini MCP target operations."""


class GeminiMCPCommandError(GeminiMCPTargetError):
    """Raised when a bounded Gemini CLI command cannot prove its contract."""


@dataclass(frozen=True)
class GeminiMCPServerSpec:
    """Secret-free Gemini MCP configuration for one immutable server."""

    name: str
    transport: GeminiMCPTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    url: str | None = None
    env_http_headers: tuple[tuple[str, str], ...] = ()
    enabled: bool = True
    timeout_ms: int = 10_000
    description: str | None = None
    include_tools: tuple[str, ...] = ()
    exclude_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.name, "Gemini MCP server name")
        if not isinstance(self.transport, GeminiMCPTransport):
            raise ValueError("Gemini MCP transport is invalid")
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
            raise ValueError("Gemini MCP environment headers contain duplicates")
        for header, env_name in headers:
            _validate_header_name(header)
            _validate_env_name(env_name)
        object.__setattr__(self, "env_http_headers", headers)
        if not isinstance(self.enabled, bool):
            raise ValueError("Gemini MCP enablement flag must be a boolean")
        if (
            not isinstance(self.timeout_ms, int)
            or not 1 <= self.timeout_ms <= 3_600_000
        ):
            raise ValueError("Gemini MCP timeout is invalid")
        if self.description is not None:
            if not isinstance(self.description, str) or not self.description.strip():
                raise ValueError("Gemini MCP description is invalid")
            _validate_secret_free(self.description, "Gemini MCP description")
        object.__setattr__(
            self,
            "include_tools",
            _normalize_tools(self.include_tools, "included tool"),
        )
        object.__setattr__(
            self,
            "exclude_tools",
            _normalize_tools(self.exclude_tools, "excluded tool"),
        )
        if set(self.include_tools) & set(self.exclude_tools):
            raise ValueError("Gemini MCP tool filters overlap")
        self._validate_transport()

    def _validate_transport(self) -> None:
        if self.transport is GeminiMCPTransport.STDIO:
            if not self.command or not self.command.strip():
                raise ValueError("Gemini stdio MCP server requires a command")
            _validate_secret_free(self.command, "Gemini MCP command")
            if self.url is not None or self.env_http_headers:
                raise ValueError("Gemini stdio MCP server cannot use HTTP fields")
            return
        if self.command is not None or self.args or self.env_vars:
            raise ValueError("Gemini remote MCP server cannot use stdio fields")
        if self.url is None:
            raise ValueError("Gemini remote MCP server requires a URL")
        object.__setattr__(self, "url", _canonical_https_url(self.url))


@dataclass(frozen=True)
class GeminiMCPRequest:
    """One immutable package projected to an admitted Gemini config root."""

    package: IntegrationPackage
    scope: InstallationScope
    root: Path
    server: GeminiMCPServerSpec

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("Gemini MCP request requires an IntegrationPackage")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("Gemini MCP request scope is invalid")
        if self.scope not in {
            InstallationScope.MANAGED_HOME,
            InstallationScope.PROJECT,
            InstallationScope.USER_HOME,
        }:
            raise ValueError("Gemini MCP request scope is unsupported")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.server, GeminiMCPServerSpec):
            raise TypeError("Gemini MCP request server is invalid")
        if self.server.name != self.package.id:
            raise ValueError("Gemini MCP server name must equal the package id")
        if not any(
            component.type is IntegrationComponentType.MCP
            for component in self.package.components
        ):
            raise ValueError("Gemini MCP request package has no MCP component")
        if self.scope not in self.package.scopes:
            raise ValueError("Gemini MCP request package does not support the scope")
        if not any(
            item.target_id == GEMINI_MCP_TARGET_ID
            for item in self.package.compatibility
        ):
            raise ValueError("Gemini MCP request package is not target-compatible")


@dataclass(frozen=True)
class GeminiMCPPlan:
    """Content-free Gemini lifecycle preview bound to one installer plan."""

    action: str
    plan_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    server_spec_sha256: str
    enabled: bool
    installation: InstallationPlan


@dataclass(frozen=True)
class GeminiMCPProbe:
    """Bounded current Gemini CLI capability evidence."""

    status: str
    version: str | None
    command: str
    capabilities: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class GeminiMCPInstallation:
    """Content-free current Gemini MCP installation projection."""

    transaction_id: str
    package_id: str
    package_version: str
    scope: InstallationScope
    server_name: str
    enabled: bool
    current: bool


@dataclass(frozen=True)
class GeminiMCPHealth:
    """Exact config plus distinct native-terminal and ACP evidence."""

    transaction_id: str
    package_id: str
    server_name: str
    enabled: bool
    exact_snapshot: bool
    native_cli_discovered: bool
    native_workspace_trust_required: bool
    native_terminal_status: str
    acp_transport_supported: bool
    acp_activation: str
    auth_ownership: str
    workspace_trust_ownership: str
    status: str


@dataclass(frozen=True)
class GeminiMCPUninstallPlan:
    """Approval-bound request to unwind one package's owned transaction chain."""

    plan_id: str
    package_id: str
    transaction_id: str
    owner_revision: str
    scope: InstallationScope


@dataclass(frozen=True)
class GeminiMCPActivation:
    """Content-free activation preview without starting a Gemini process."""

    transaction_id: str
    server_name: str
    argv: tuple[str, ...]
    cwd: Path
    native_terminal_env: tuple[tuple[str, str], ...]
    native_workspace_trust_required: bool
    acp_transport_supported: bool
    acp_injection_required: bool
    auth_ownership: str
    workspace_trust_ownership: str
    executes_provider: bool = False


@dataclass(frozen=True)
class GeminiCommandResult:
    """Bounded subprocess result returned by an injected command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


GeminiCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float], GeminiCommandResult
]


GEMINI_MCP_TARGET_DESCRIPTOR = ExtensionTargetDescriptor(
    id=GEMINI_MCP_TARGET_ID,
    revision=GEMINI_MCP_TARGET_REVISION,
    component_types=(IntegrationComponentType.MCP,),
    scopes=(
        InstallationScope.MANAGED_HOME,
        InstallationScope.PROJECT,
        InstallationScope.USER_HOME,
    ),
    capabilities=(
        "acp_http",
        "acp_sse",
        "disable",
        "enable",
        "health",
        "http",
        "install",
        "native_terminal",
        "rollback",
        "sse",
        "stdio",
        "uninstall",
        "update",
        "verify",
        "workspace_trust",
    ),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="gemini-mcp-documented-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="google-gemini-cli-docs",
            revision="2026-07-19",
        ),
    ),
)


class GeminiMCPTargetDriver:
    """Own one reversible Gemini MCP package per explicit target root."""

    descriptor = GEMINI_MCP_TARGET_DESCRIPTOR

    def __init__(
        self,
        data_dir: str | Path,
        *,
        project_roots: Sequence[str | Path] = (),
        user_home_root: str | Path | None = None,
        allow_user_home: bool = False,
        executable: Sequence[str] = ("gemini",),
        command_runner: GeminiCommandRunner | None = None,
        target_active: Callable[[Path], bool] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.executable = tuple(str(item) for item in executable)
        if not self.executable or any(not item for item in self.executable):
            raise ValueError("Gemini MCP executable is invalid")
        self.command_runner = command_runner or _run_command
        self.installer = TransactionalIntegrationInstaller(
            self.data_dir,
            project_roots=project_roots,
            user_home_root=user_home_root,
            allow_user_home=allow_user_home,
            target_active=target_active,
        )

    def probe_target(self) -> GeminiMCPProbe:
        """Probe documented, side-effect-free Gemini MCP and ACP surfaces."""
        with tempfile.TemporaryDirectory(prefix="gigaloom-gemini-mcp-probe-") as raw:
            env = _isolated_env(Path(raw))
            version = self.command_runner(
                self.executable + ("--version",),
                env,
                None,
                GEMINI_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            root_help = self.command_runner(
                self.executable + ("--help",),
                env,
                None,
                GEMINI_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            mcp_help = self.command_runner(
                self.executable + ("mcp", "--help"),
                env,
                None,
                GEMINI_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            add_help = self.command_runner(
                self.executable + ("mcp", "add", "--help"),
                env,
                None,
                GEMINI_MCP_COMMAND_TIMEOUT_SECONDS,
            )
        root_text = _bounded_output(root_help)
        mcp_text = _bounded_output(mcp_help)
        add_text = _bounded_output(add_help)
        capabilities = tuple(
            name
            for name, proven in (
                ("mcp_add", "add" in mcp_text),
                ("mcp_list", "list" in mcp_text),
                ("mcp_remove", "remove" in mcp_text),
                ("mcp_enable", "enable" in mcp_text),
                ("mcp_disable", "disable" in mcp_text),
                ("mcp_project_scope", "project" in add_text),
                ("mcp_user_scope", "user" in add_text),
                ("stdio", "stdio" in add_text),
                ("sse", "sse" in add_text),
                ("http", "http" in add_text),
                ("acp", "--acp" in root_text),
            )
            if proven
        )
        results = (version, root_help, mcp_help, add_help)
        status = (
            "supported"
            if all(item.returncode == 0 for item in results) and len(capabilities) == 11
            else "unsupported"
        )
        return GeminiMCPProbe(
            status=status,
            version=_first_line(version.stdout or version.stderr),
            command=str(redact_secrets(self.executable[0])),
            capabilities=capabilities,
            evidence="bounded --version, --help, mcp --help, and mcp add --help probes",
        )

    def discover_installed(self) -> tuple[GeminiMCPInstallation, ...]:
        """Discover installer ownership plus the exact package-named server."""
        discovered: list[GeminiMCPInstallation] = []
        for installed in self.installer.discover():
            if installed.target_id != GEMINI_MCP_TARGET_ID:
                continue
            plan = self.installer.transaction_plan(installed.transaction_id)
            config = _config(plan.root)
            server = _server(config, installed.package_id)
            discovered.append(
                GeminiMCPInstallation(
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

    def preview_install(self, request: GeminiMCPRequest) -> GeminiMCPPlan:
        """Preview a first install without addressing a real Gemini home."""
        if self._installation_for_root(request.root) is not None:
            raise InstallationConflictError(
                "Gemini MCP target already owns a package; use update or uninstall"
            )
        return self._preview(request, action="install")

    def install(
        self,
        request: GeminiMCPRequest,
        plan: GeminiMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Install and prove isolated native-terminal discovery."""
        self._validate_action(request, plan, "install")
        return self.installer.apply(
            self._installation_request(request, owned=False),
            plan.installation,
            approval,
            verifier=lambda root, _plan: self._verify_target(root, request),
        )

    def verify(self, transaction_id: str) -> GeminiMCPHealth:
        """Verify exact files and keep terminal/ACP activation distinct."""
        installed = self.installer.verify(transaction_id)
        plan = self.installer.transaction_plan(transaction_id)
        config = _config(plan.root)
        server = _server(config, installed.package_id)
        enabled = server is not None
        discovered, trust_required = self._native_list(
            plan.root,
            installed.package_id,
            expect_present=enabled,
        )
        exact = installed.current
        acp_supported = enabled and _acp_transport_supported(server)
        if not enabled:
            status = "disabled" if discovered else "degraded"
        elif discovered and trust_required:
            status = "awaiting_workspace_trust"
        elif discovered and acp_supported:
            status = "ready_for_native_or_acp"
        elif discovered:
            status = "ready_for_native_terminal"
        else:
            status = "degraded"
        return GeminiMCPHealth(
            transaction_id=transaction_id,
            package_id=installed.package_id,
            server_name=installed.package_id,
            enabled=enabled,
            exact_snapshot=exact,
            native_cli_discovered=discovered if enabled else False,
            native_workspace_trust_required=trust_required,
            native_terminal_status=(
                "disabled_untrusted" if trust_required else "configured"
            ),
            acp_transport_supported=acp_supported,
            acp_activation=(
                "session_injected"
                if acp_supported
                else "unsupported_stdio"
                if enabled
                else "disabled"
            ),
            auth_ownership="gemini_cli",
            workspace_trust_ownership="gemini_cli",
            status=status,
        )

    def preview_enable(self, request: GeminiMCPRequest) -> GeminiMCPPlan:
        """Preview restoring the exact package-named server."""
        return self._preview(
            replace(request, server=replace(request.server, enabled=True)),
            action="enable",
        )

    def enable(
        self,
        request: GeminiMCPRequest,
        plan: GeminiMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Enable by atomically restoring the documented server entry."""
        enabled = replace(request, server=replace(request.server, enabled=True))
        return self._update(enabled, plan, approval, action="enable")

    def preview_disable(self, request: GeminiMCPRequest) -> GeminiMCPPlan:
        """Preview removing the server entry while retaining rollback ownership."""
        return self._preview(
            replace(request, server=replace(request.server, enabled=False)),
            action="disable",
        )

    def disable(
        self,
        request: GeminiMCPRequest,
        plan: GeminiMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Disable without altering provider-owned global enablement or trust."""
        disabled = replace(request, server=replace(request.server, enabled=False))
        return self._update(disabled, plan, approval, action="disable")

    def preview_update(self, request: GeminiMCPRequest) -> GeminiMCPPlan:
        """Preview a pinned package/spec replacement."""
        return self._preview(request, action="update")

    def update(
        self,
        request: GeminiMCPRequest,
        plan: GeminiMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Atomically update config while preserving native ownership."""
        return self._update(request, plan, approval, action="update")

    def preview_uninstall(self, transaction_id: str) -> GeminiMCPUninstallPlan:
        """Bind uninstall approval to the exact current owner revision."""
        installed = self.installer.verify(transaction_id)
        semantic = {
            "action": "uninstall",
            "package_id": installed.package_id,
            "transaction_id": installed.transaction_id,
            "owner_revision": installed.owner_revision,
            "scope": installed.scope.value,
        }
        return GeminiMCPUninstallPlan(
            plan_id=f"plan_{_json_hash(semantic)}",
            package_id=installed.package_id,
            transaction_id=installed.transaction_id,
            owner_revision=installed.owner_revision,
            scope=installed.scope,
        )

    def uninstall(
        self,
        plan: GeminiMCPUninstallPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Unwind only the approved package's exact update chain."""
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Gemini MCP uninstall approval does not match the preview"
            )
        if plan.scope is InstallationScope.USER_HOME and not approval.allow_user_home:
            raise InstallationConflictError(
                "Gemini MCP user-home uninstall requires explicit approval"
            )
        current = self.installer.verify(plan.transaction_id)
        if (
            current.package_id != plan.package_id
            or current.owner_revision != plan.owner_revision
        ):
            raise InstallationConflictError(
                "Gemini MCP installation changed after uninstall preview"
            )
        result: InstallationResult | None = None
        root = self.installer.transaction_plan(plan.transaction_id).root
        for _ in range(MAX_GEMINI_MCP_UNINSTALL_DEPTH):
            result = self.installer.rollback(current.transaction_id)
            remaining = self._installation_for_root(root)
            if remaining is None:
                return result
            if remaining.package_id != plan.package_id:
                raise InstallationStateError(
                    "Gemini MCP uninstall encountered a foreign owner"
                )
            current = self.installer.verify(remaining.transaction_id)
        raise InstallationStateError("Gemini MCP uninstall chain is too deep")

    def rollback(self, transaction_id: str) -> InstallationResult:
        """Roll back exactly one current lifecycle transition."""
        return self.installer.rollback(transaction_id)

    def health(self, transaction_id: str) -> GeminiMCPHealth:
        """Alias target health to exact transport-aware verification."""
        return self.verify(transaction_id)

    def preview_activation(
        self,
        transaction_id: str,
        *,
        workspace: str | Path | None = None,
    ) -> GeminiMCPActivation:
        """Describe native-terminal and ACP activation without execution."""
        health = self.verify(transaction_id)
        if (
            not health.enabled
            or not health.exact_snapshot
            or not health.native_cli_discovered
        ):
            raise GeminiMCPTargetError("Gemini MCP target is not exactly discoverable")
        installed = self.installer.verify(transaction_id)
        root = self.installer.transaction_plan(transaction_id).root
        if installed.scope in {
            InstallationScope.MANAGED_HOME,
            InstallationScope.USER_HOME,
        }:
            argv = self.executable
            cwd = Path(workspace).expanduser().resolve() if workspace else root
            native_env = (("GEMINI_CLI_HOME", str(root)),)
        else:
            if workspace is not None and Path(workspace).expanduser().resolve() != root:
                raise ValueError(
                    "Gemini project activation workspace must equal its root"
                )
            argv = self.executable
            cwd = root
            native_env = ()
        return GeminiMCPActivation(
            transaction_id=transaction_id,
            server_name=health.server_name,
            argv=argv,
            cwd=cwd,
            native_terminal_env=native_env,
            native_workspace_trust_required=True,
            acp_transport_supported=health.acp_transport_supported,
            acp_injection_required=health.acp_transport_supported,
            auth_ownership="gemini_cli",
            workspace_trust_ownership="gemini_cli",
        )

    def acp_server(self, transaction_id: str) -> Mapping[str, Any]:
        """Return the exact reviewed HTTP/SSE server for ACP session injection."""
        health = self.verify(transaction_id)
        if not health.acp_transport_supported:
            raise GeminiMCPTargetError(
                "Gemini ACP does not advertise the installed MCP transport"
            )
        installed = self.installer.verify(transaction_id)
        plan = self.installer.transaction_plan(transaction_id)
        server = _server(_config(plan.root), installed.package_id)
        if server is None:
            raise GeminiMCPTargetError("Gemini MCP target is disabled")
        return _acp_server_payload(installed.package_id, server)

    def _preview(self, request: GeminiMCPRequest, *, action: str) -> GeminiMCPPlan:
        existing = self._installation_for_root(request.root)
        if action != "install":
            if existing is None:
                raise InstallationConflictError(
                    "Gemini MCP lifecycle change requires an existing owner"
                )
            if existing.package_id != request.package.id:
                raise InstallationConflictError(
                    "Gemini MCP target cannot replace a different package"
                )
        installation = self.installer.preview(
            self._installation_request(request, owned=existing is not None)
        )
        return GeminiMCPPlan(
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
        request: GeminiMCPRequest,
        plan: GeminiMCPPlan,
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
        self, request: GeminiMCPRequest, plan: GeminiMCPPlan, action: str
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
                "Gemini MCP lifecycle plan does not match the request"
            )

    def _installation_request(
        self, request: GeminiMCPRequest, *, owned: bool
    ) -> InstallationRequest:
        root = request.root.expanduser().resolve()
        current = _config_text(root)
        desired = _render_config(current, request, owned=owned)
        return InstallationRequest(
            package=request.package,
            target=InstallationTarget(
                id=GEMINI_MCP_TARGET_ID,
                scope=request.scope,
                root=root,
                owner_id=GEMINI_MCP_OWNER_ID,
            ),
            mutations=(
                FileInstallMutation(
                    relative_path=GEMINI_MCP_CONFIG_PATH,
                    content=desired.encode("utf-8"),
                    mode=(
                        0o644 if request.scope is InstallationScope.PROJECT else 0o600
                    ),
                ),
            ),
        )

    def _verify_target(self, root: Path, request: GeminiMCPRequest) -> bool:
        config = _config(root)
        server = _server(config, request.package.id)
        if request.server.enabled:
            if server != _server_payload(request.server):
                return False
        elif server is not None:
            return False
        discovered, _trust_required = self._native_list(
            root,
            request.package.id,
            expect_present=request.server.enabled,
        )
        return discovered

    def _native_list(
        self,
        root: Path,
        server_name: str,
        *,
        expect_present: bool,
    ) -> tuple[bool, bool]:
        with tempfile.TemporaryDirectory(prefix="gigaloom-gemini-mcp-get-") as raw:
            raw_path = Path(raw)
            project = raw_path / "project"
            project.mkdir(mode=0o700)
            config_path = project / GEMINI_MCP_CONFIG_PATH
            config_path.parent.mkdir(mode=0o700)
            config_path.write_text(_config_text(root), encoding="utf-8")
            result = self.command_runner(
                self.executable + ("mcp", "list"),
                _isolated_env(raw_path / "home"),
                project,
                GEMINI_MCP_COMMAND_TIMEOUT_SECONDS,
            )
        output = _strip_ansi(_bounded_output(result))
        if not expect_present:
            absent = result.returncode == 0 and not re.search(
                rf"(?m)^.\s+{re.escape(server_name)}:", output
            )
            return absent, False
        discovered = result.returncode == 0 and bool(
            re.search(rf"(?m)^.\s+{re.escape(server_name)}:", output)
        )
        trust_required = discovered and "untrusted" in output.lower()
        return discovered, trust_required

    def _installation_for_root(self, root: Path):
        resolved = root.expanduser().resolve()
        matches = []
        for installed in self.installer.discover():
            if installed.target_id != GEMINI_MCP_TARGET_ID:
                continue
            plan = self.installer.transaction_plan(installed.transaction_id)
            if plan.root == resolved:
                matches.append(installed)
        if len(matches) > 1:
            raise InstallationStateError("Gemini MCP target has duplicate owners")
        return matches[0] if matches else None


def gemini_mcp_target_plugin(
    factory: Callable[[], GeminiMCPTargetDriver],
) -> ExtensionTargetPlugin:
    """Build a neutral runtime registration for a configured Gemini target."""
    return ExtensionTargetPlugin(
        descriptor=GEMINI_MCP_TARGET_DESCRIPTOR,
        factory=factory,
    )


def _render_config(current: str, request: GeminiMCPRequest, *, owned: bool) -> str:
    config = dict(_parse_config(current))
    _validate_secret_free_config(config)
    raw_servers = config.get("mcpServers", {})
    if not isinstance(raw_servers, Mapping):
        raise ValueError("Gemini mcpServers config must be an object")
    servers = dict(raw_servers)
    if not owned and request.package.id in servers:
        raise InstallationConflictError(
            "Gemini MCP server name is already owned outside this package"
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
        return (root / GEMINI_MCP_CONFIG_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _parse_config(value: str) -> Mapping[str, Any]:
    if not value.strip():
        return {}

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Gemini settings.json contains duplicate keys")
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini settings.json is invalid") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("Gemini settings.json must be an object")
    servers = parsed.get("mcpServers", {})
    if not isinstance(servers, Mapping):
        raise ValueError("Gemini mcpServers config must be an object")
    return parsed


def _server(config: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    servers = config.get("mcpServers", {})
    if not isinstance(servers, Mapping):
        raise ValueError("Gemini mcpServers config must be an object")
    server = servers.get(name)
    if server is None:
        return None
    if not isinstance(server, Mapping):
        raise ValueError("Gemini MCP server config must be an object")
    return server


def _server_payload(server: GeminiMCPServerSpec) -> dict[str, Any]:
    if server.transport is GeminiMCPTransport.STDIO:
        payload: dict[str, Any] = {
            "command": server.command,
            "args": list(server.args),
        }
        if server.env_vars:
            payload["env"] = {name: f"${{{name}}}" for name in server.env_vars}
    else:
        payload = {"type": server.transport.value, "url": server.url}
        if server.env_http_headers:
            payload["headers"] = {
                header: f"${{{env_name}}}"
                for header, env_name in server.env_http_headers
            }
    payload["timeout"] = server.timeout_ms
    payload["trust"] = False
    if server.description is not None:
        payload["description"] = server.description
    if server.include_tools:
        payload["includeTools"] = list(server.include_tools)
    if server.exclude_tools:
        payload["excludeTools"] = list(server.exclude_tools)
    return payload


def _acp_transport_supported(server: Mapping[str, Any] | None) -> bool:
    return server is not None and server.get("type") in {"http", "sse"}


def _acp_server_payload(
    server_name: str, server: Mapping[str, Any]
) -> Mapping[str, Any]:
    if not _acp_transport_supported(server):
        raise GeminiMCPTargetError(
            "Gemini ACP supports only the reviewed HTTP and SSE MCP transports"
        )
    payload: dict[str, Any] = {
        "name": server_name,
        "type": server["type"],
        "url": server["url"],
    }
    headers = server.get("headers")
    if headers is not None:
        if not isinstance(headers, Mapping):
            raise ValueError("Gemini MCP headers must be an object")
        payload["headers"] = dict(headers)
    return payload


def _server_spec_hash(server: GeminiMCPServerSpec) -> str:
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
                raise ValueError("Gemini settings.json contains secret material")
            _validate_secret_free_config(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_secret_free_config(item)
        return
    if isinstance(value, str) and str(redact_secrets(value)) != value:
        raise ValueError("Gemini settings.json contains secret material")


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> GeminiCommandResult:
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
        raise GeminiMCPCommandError(
            f"Gemini command failed with {type(exc).__name__}"
        ) from exc
    return GeminiCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[-MAX_GEMINI_MCP_OUTPUT_CHARS:],
        stderr=completed.stderr[-MAX_GEMINI_MCP_OUTPUT_CHARS:],
    )


def _isolated_env(config_home: Path) -> dict[str, str]:
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
    return env


def _bounded_output(result: GeminiCommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"[-MAX_GEMINI_MCP_OUTPUT_CHARS:]


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)


def _first_line(value: str) -> str | None:
    lines = value.strip().splitlines()
    return lines[0][:200] if lines else None


def _canonical_https_url(value: str) -> str:
    _validate_secret_free(value, "Gemini MCP URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Gemini remote MCP URL must be credential-free HTTPS")
    if parsed.fragment:
        raise ValueError("Gemini remote MCP URL cannot contain a fragment")
    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )


def _normalize_texts(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(str(item) for item in values)
    if len(normalized) > 256:
        raise ValueError(f"Gemini MCP {label} count is invalid")
    for item in normalized:
        if not item or len(item) > 4096:
            raise ValueError(f"Gemini MCP {label} is invalid")
        _validate_secret_free(item, f"Gemini MCP {label}")
    return normalized


def _normalize_names(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(str(item) for item in values)))
    if len(normalized) != len(tuple(values)):
        raise ValueError(f"Gemini MCP {label} contains duplicates")
    for item in normalized:
        _validate_env_name(item)
    return normalized


def _normalize_tools(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(str(item) for item in values)))
    if len(normalized) != len(tuple(values)) or len(normalized) > 256:
        raise ValueError(f"Gemini MCP {label} values are duplicated or excessive")
    for item in normalized:
        if not item or len(item) > 256 or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", item):
            raise ValueError(f"Gemini MCP {label} is invalid")
    return normalized


def _validate_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_env_name(value: str) -> None:
    if not isinstance(value, str) or not _ENV_RE.fullmatch(value):
        raise ValueError("Gemini MCP environment variable name is invalid")


def _validate_header_name(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value):
        raise ValueError("Gemini MCP HTTP header name is invalid")


def _validate_secret_free(value: str, label: str) -> None:
    if str(redact_secrets(value)) != value:
        raise ValueError(f"{label} contains secret material")


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "GEMINI_MCP_TARGET_DESCRIPTOR",
    "GEMINI_MCP_TARGET_ID",
    "GeminiCommandResult",
    "GeminiMCPCommandError",
    "GeminiMCPActivation",
    "GeminiMCPHealth",
    "GeminiMCPInstallation",
    "GeminiMCPPlan",
    "GeminiMCPProbe",
    "GeminiMCPRequest",
    "GeminiMCPServerSpec",
    "GeminiMCPTargetDriver",
    "GeminiMCPTargetError",
    "GeminiMCPTransport",
    "GeminiMCPUninstallPlan",
    "gemini_mcp_target_plugin",
]
