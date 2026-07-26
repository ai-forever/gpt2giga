"""Codex MCP target lifecycle over documented config and CLI surfaces."""

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

try:  # pragma: no cover - Python 3.10 compatibility
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

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


CODEX_MCP_TARGET_ID = "codex-mcp"
CODEX_MCP_TARGET_REVISION = "1"
CODEX_MCP_MARKER = "gigaloom-codex-mcp-v1"
CODEX_MCP_OWNER_ID = "codex-mcp-config"
CODEX_MCP_COMMAND_TIMEOUT_SECONDS = 10.0
CODEX_MCP_INVOCATION_TIMEOUT_SECONDS = 120.0
MAX_CODEX_MCP_OUTPUT_CHARS = 128_000
MAX_CODEX_MCP_UNINSTALL_DEPTH = 100
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_TOOL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}\Z")


class CodexMCPTransport(str, Enum):
    """Documented Codex MCP transport families."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class CodexMCPDefaultApproval(str, Enum):
    """Documented Codex default tool approval modes."""

    AUTO = "auto"
    PROMPT = "prompt"
    WRITES = "writes"
    APPROVE = "approve"


class CodexMCPTargetError(RuntimeError):
    """Base error for Codex MCP target operations."""


class CodexMCPCommandError(CodexMCPTargetError):
    """Raised when a bounded Codex CLI command cannot prove its contract."""


class CodexMCPActivationError(CodexMCPTargetError):
    """Raised when native activation is unavailable or unproven."""


@dataclass(frozen=True)
class CodexMCPServerSpec:
    """Secret-free Codex MCP configuration for one pinned server."""

    name: str
    transport: CodexMCPTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env_vars: tuple[str, ...] = ()
    url: str | None = None
    bearer_token_env_var: str | None = None
    env_http_headers: tuple[tuple[str, str], ...] = ()
    enabled: bool = True
    required: bool = False
    startup_timeout_sec: int = 10
    tool_timeout_sec: int = 60
    enabled_tools: tuple[str, ...] = ()
    disabled_tools: tuple[str, ...] = ()
    default_tools_approval_mode: CodexMCPDefaultApproval = (
        CodexMCPDefaultApproval.PROMPT
    )

    def __post_init__(self) -> None:
        _validate_identity(self.name, "Codex MCP server name")
        if not isinstance(self.transport, CodexMCPTransport):
            raise ValueError("Codex MCP transport is invalid")
        object.__setattr__(self, "args", _normalize_texts(self.args, "argument"))
        object.__setattr__(
            self,
            "env_vars",
            _normalize_names(self.env_vars, "environment variable"),
        )
        object.__setattr__(
            self,
            "enabled_tools",
            _normalize_tools(self.enabled_tools, "enabled tool"),
        )
        object.__setattr__(
            self,
            "disabled_tools",
            _normalize_tools(self.disabled_tools, "disabled tool"),
        )
        headers = tuple(sorted(tuple(item) for item in self.env_http_headers))
        if len(headers) != len(set(headers)) or len(
            {item[0] for item in headers}
        ) != len(headers):
            raise ValueError("Codex MCP environment headers contain duplicates")
        for header, env_name in headers:
            _validate_header_name(header)
            _validate_env_name(env_name)
        object.__setattr__(self, "env_http_headers", headers)
        if not isinstance(self.enabled, bool) or not isinstance(self.required, bool):
            raise ValueError("Codex MCP enablement flags must be booleans")
        for field_name in ("startup_timeout_sec", "tool_timeout_sec"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or not 1 <= value <= 3600:
                raise ValueError(f"Codex MCP {field_name} is invalid")
        if not isinstance(self.default_tools_approval_mode, CodexMCPDefaultApproval):
            raise ValueError("Codex MCP approval mode is invalid")
        self._validate_transport()

    def _validate_transport(self) -> None:
        if self.transport is CodexMCPTransport.STDIO:
            if not self.command or not self.command.strip():
                raise ValueError("Codex stdio MCP server requires a command")
            _validate_secret_free(self.command, "Codex MCP command")
            if self.url is not None or self.bearer_token_env_var is not None:
                raise ValueError("Codex stdio MCP server cannot use HTTP fields")
            if self.env_http_headers:
                raise ValueError("Codex stdio MCP server cannot use HTTP headers")
            for env_name in self.env_vars:
                _validate_env_name(env_name)
            if self.cwd is not None:
                _validate_secret_free(self.cwd, "Codex MCP cwd")
            return
        if (
            self.command is not None
            or self.args
            or self.cwd is not None
            or self.env_vars
        ):
            raise ValueError("Codex HTTP MCP server cannot use stdio fields")
        if self.url is None:
            raise ValueError("Codex HTTP MCP server requires a URL")
        object.__setattr__(self, "url", _canonical_https_url(self.url))
        if self.bearer_token_env_var is not None:
            _validate_env_name(self.bearer_token_env_var)


@dataclass(frozen=True)
class CodexMCPRequest:
    """One immutable package projected to one explicit Codex target root."""

    package: IntegrationPackage
    scope: InstallationScope
    root: Path
    server: CodexMCPServerSpec

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("Codex MCP request requires an IntegrationPackage")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("Codex MCP request scope is invalid")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.server, CodexMCPServerSpec):
            raise TypeError("Codex MCP request server is invalid")
        if not any(
            component.type is IntegrationComponentType.MCP
            for component in self.package.components
        ):
            raise ValueError("Codex MCP request package has no MCP component")
        if self.scope not in self.package.scopes:
            raise ValueError("Codex MCP request package does not support the scope")
        if not any(
            item.target_id == CODEX_MCP_TARGET_ID for item in self.package.compatibility
        ):
            raise ValueError("Codex MCP request package is not target-compatible")


@dataclass(frozen=True)
class CodexMCPPlan:
    """Content-free Codex lifecycle preview bound to one installer plan."""

    action: str
    plan_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    server_name: str
    server_spec_sha256: str
    enabled: bool
    installation: InstallationPlan


@dataclass(frozen=True)
class CodexMCPProbe:
    """Bounded current Codex CLI capability evidence."""

    status: str
    version: str | None
    command: str
    capabilities: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class CodexMCPInstallation:
    """Content-free current Codex MCP installation projection."""

    transaction_id: str
    package_id: str
    package_version: str
    scope: InstallationScope
    server_name: str
    enabled: bool
    current: bool


@dataclass(frozen=True)
class CodexMCPHealth:
    """Content-free exact-config and native CLI health evidence."""

    transaction_id: str
    package_id: str
    server_name: str
    enabled: bool
    exact_snapshot: bool
    native_cli_loaded: bool
    status: str


@dataclass(frozen=True)
class CodexMCPUninstallPlan:
    """Approval-bound request to unwind one package's owned transaction chain."""

    plan_id: str
    package_id: str
    transaction_id: str
    owner_revision: str
    scope: InstallationScope


@dataclass(frozen=True)
class CodexMCPInvocationRequest:
    """Transient native activation request; prompt and outputs are never retained."""

    transaction_id: str
    workspace: Path
    server_name: str
    tool_name: str
    prompt: str
    allow_provider_traffic: bool = False

    def __post_init__(self) -> None:
        if not _TOOL_RE.fullmatch(self.tool_name):
            raise ValueError("Codex MCP tool name is invalid")
        _validate_identity(self.server_name, "Codex MCP server name")
        if not self.prompt.strip() or len(self.prompt) > 8000:
            raise ValueError("Codex MCP activation prompt is invalid")
        _validate_secret_free(self.prompt, "Codex MCP activation prompt")
        if not isinstance(self.allow_provider_traffic, bool):
            raise ValueError("Codex MCP provider-traffic opt-in is invalid")
        if not isinstance(self.workspace, Path):
            object.__setattr__(self, "workspace", Path(self.workspace))


@dataclass(frozen=True)
class CodexMCPInvocationEvidence:
    """Content-free proof that Codex completed one exact MCP tool call."""

    transaction_id: str
    server_name: str
    tool_name: str
    status: str
    event_count: int
    surface: str = "codex-exec-jsonl-v1"


@dataclass(frozen=True)
class CodexCommandResult:
    """Bounded subprocess result returned by an injected command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


CodexCommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], Path | None, float], CodexCommandResult
]


CODEX_MCP_TARGET_DESCRIPTOR = ExtensionTargetDescriptor(
    id=CODEX_MCP_TARGET_ID,
    revision=CODEX_MCP_TARGET_REVISION,
    component_types=(IntegrationComponentType.MCP,),
    scopes=(
        InstallationScope.MANAGED_HOME,
        InstallationScope.PROJECT,
        InstallationScope.USER_HOME,
    ),
    capabilities=(
        "disable",
        "enable",
        "health",
        "install",
        "native_tool_invocation",
        "rollback",
        "stdio",
        "streamable_http",
        "uninstall",
        "update",
        "verify",
    ),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="codex-mcp-documented-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="openai-codex-docs",
            revision="2026-07-19",
        ),
    ),
)


class CodexMCPTargetDriver:
    """Own one reversible Codex MCP package per explicit target root."""

    descriptor = CODEX_MCP_TARGET_DESCRIPTOR

    def __init__(
        self,
        data_dir: str | Path,
        *,
        project_roots: Sequence[str | Path] = (),
        user_home_root: str | Path | None = None,
        allow_user_home: bool = False,
        executable: Sequence[str] = ("codex",),
        command_runner: CodexCommandRunner | None = None,
        target_active: Callable[[Path], bool] | None = None,
        allow_native_invocation: bool = False,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.executable = tuple(str(item) for item in executable)
        if not self.executable or any(not item for item in self.executable):
            raise ValueError("Codex MCP executable is invalid")
        self.command_runner = command_runner or _run_command
        self.allow_native_invocation = allow_native_invocation
        self.installer = TransactionalIntegrationInstaller(
            self.data_dir,
            project_roots=project_roots,
            user_home_root=user_home_root,
            allow_user_home=allow_user_home,
            target_active=target_active,
        )

    def probe_target(self) -> CodexMCPProbe:
        """Probe only documented, side-effect-free Codex MCP command surfaces."""
        with tempfile.TemporaryDirectory(prefix="gigaloom-codex-mcp-probe-") as raw:
            home = Path(raw) / ".codex"
            env = _isolated_env(home)
            version = self.command_runner(
                self.executable + ("--version",),
                env,
                None,
                CODEX_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            help_result = self.command_runner(
                self.executable + ("mcp", "--help"),
                env,
                None,
                CODEX_MCP_COMMAND_TIMEOUT_SECONDS,
            )
            exec_help = self.command_runner(
                self.executable + ("exec", "--help"),
                env,
                None,
                CODEX_MCP_COMMAND_TIMEOUT_SECONDS,
            )
        version_text = _first_line(version.stdout or version.stderr)
        help_text = _bounded_output(help_result)
        exec_text = _bounded_output(exec_help)
        capabilities = tuple(
            name
            for name, proven in (
                ("mcp_add", "add" in help_text),
                ("mcp_get", "get" in help_text),
                ("mcp_list", "list" in help_text),
                ("mcp_remove", "remove" in help_text),
                ("exec_json", "--json" in exec_text),
                ("exec_ephemeral", "--ephemeral" in exec_text),
            )
            if proven
        )
        status = (
            "supported"
            if version.returncode == help_result.returncode == exec_help.returncode == 0
            and len(capabilities) == 6
            else "unsupported"
        )
        return CodexMCPProbe(
            status=status,
            version=version_text,
            command=str(redact_secrets(self.executable[0])),
            capabilities=capabilities,
            evidence="bounded --version, mcp --help, and exec --help probes",
        )

    def discover_installed(self) -> tuple[CodexMCPInstallation, ...]:
        """Discover exact installer ownership plus the matching Codex block."""
        discovered: list[CodexMCPInstallation] = []
        for installed in self.installer.discover():
            if installed.target_id != CODEX_MCP_TARGET_ID:
                continue
            plan = self.installer.transaction_plan(installed.transaction_id)
            block = _owned_block(
                _config_text(plan.root, installed.scope), installed.package_id
            )
            metadata = _block_metadata(block, installed.package_id) if block else None
            discovered.append(
                CodexMCPInstallation(
                    transaction_id=installed.transaction_id,
                    package_id=installed.package_id,
                    package_version=installed.package_version,
                    scope=installed.scope,
                    server_name=str(metadata["server_name"]) if metadata else "unknown",
                    enabled=bool(metadata["enabled"]) if metadata else False,
                    current=installed.current and metadata is not None,
                )
            )
        return tuple(discovered)

    def preview_install(self, request: CodexMCPRequest) -> CodexMCPPlan:
        """Preview first installation without reading any real home implicitly."""
        if self._installation_for_root(request.root) is not None:
            raise InstallationConflictError(
                "Codex MCP target already owns a package; use update or uninstall"
            )
        return self._preview(request, action="install")

    def install(
        self,
        request: CodexMCPRequest,
        plan: CodexMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Install and prove that the native Codex CLI loads the exact server."""
        self._validate_action(request, plan, "install")
        return self.installer.apply(
            self._installation_request(request),
            plan.installation,
            approval,
            verifier=lambda root, _plan: self._verify_target(root, request),
        )

    def verify(self, transaction_id: str) -> CodexMCPHealth:
        """Verify exact files, owned block, and native Codex config loading."""
        installed = self.installer.verify(transaction_id)
        plan = self.installer.transaction_plan(transaction_id)
        block = _owned_block(
            _config_text(plan.root, installed.scope), installed.package_id
        )
        metadata = _block_metadata(block, installed.package_id) if block else None
        server_name = str(metadata["server_name"]) if metadata else "unknown"
        native_loaded = False
        if metadata is not None:
            native_loaded = self._native_get(plan.root, installed.scope, server_name)
        exact = installed.current and metadata is not None
        return CodexMCPHealth(
            transaction_id=transaction_id,
            package_id=installed.package_id,
            server_name=server_name,
            enabled=bool(metadata["enabled"]) if metadata else False,
            exact_snapshot=exact,
            native_cli_loaded=native_loaded,
            status="healthy" if exact and native_loaded else "degraded",
        )

    def preview_enable(self, request: CodexMCPRequest) -> CodexMCPPlan:
        """Preview enabling the exact owned server."""
        return self._preview(
            replace(request, server=replace(request.server, enabled=True)),
            action="enable",
        )

    def enable(
        self,
        request: CodexMCPRequest,
        plan: CodexMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Enable one server through documented `enabled = true`."""
        enabled_request = replace(request, server=replace(request.server, enabled=True))
        return self._update(enabled_request, plan, approval, action="enable")

    def preview_disable(self, request: CodexMCPRequest) -> CodexMCPPlan:
        """Preview disabling the exact owned server without deleting it."""
        return self._preview(
            replace(request, server=replace(request.server, enabled=False)),
            action="disable",
        )

    def disable(
        self,
        request: CodexMCPRequest,
        plan: CodexMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Disable one server through documented `enabled = false`."""
        disabled_request = replace(
            request, server=replace(request.server, enabled=False)
        )
        return self._update(disabled_request, plan, approval, action="disable")

    def preview_update(self, request: CodexMCPRequest) -> CodexMCPPlan:
        """Preview a pinned package/spec replacement for the same package id."""
        return self._preview(request, action="update")

    def update(
        self,
        request: CodexMCPRequest,
        plan: CodexMCPPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Atomically update config and preserve the previous owner for rollback."""
        return self._update(request, plan, approval, action="update")

    def preview_uninstall(self, transaction_id: str) -> CodexMCPUninstallPlan:
        """Bind uninstall approval to the exact current owner revision."""
        installed = self.installer.verify(transaction_id)
        semantic = {
            "action": "uninstall",
            "package_id": installed.package_id,
            "transaction_id": installed.transaction_id,
            "owner_revision": installed.owner_revision,
            "scope": installed.scope.value,
        }
        return CodexMCPUninstallPlan(
            plan_id=f"plan_{_json_hash(semantic)}",
            package_id=installed.package_id,
            transaction_id=installed.transaction_id,
            owner_revision=installed.owner_revision,
            scope=installed.scope,
        )

    def uninstall(
        self,
        plan: CodexMCPUninstallPlan,
        approval: InstallationApproval,
    ) -> InstallationResult:
        """Unwind only the approved package's exact owned update chain."""
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "Codex MCP uninstall approval does not match the preview"
            )
        if plan.scope is InstallationScope.USER_HOME and not approval.allow_user_home:
            raise InstallationConflictError(
                "Codex MCP user-home uninstall requires explicit approval"
            )
        current = self.installer.verify(plan.transaction_id)
        if (
            current.package_id != plan.package_id
            or current.owner_revision != plan.owner_revision
        ):
            raise InstallationConflictError(
                "Codex MCP installation changed after uninstall preview"
            )
        result: InstallationResult | None = None
        root = self.installer.transaction_plan(plan.transaction_id).root
        for _ in range(MAX_CODEX_MCP_UNINSTALL_DEPTH):
            result = self.installer.rollback(current.transaction_id)
            remaining = self._installation_for_root(root)
            if remaining is None:
                return result
            if remaining.package_id != plan.package_id:
                raise InstallationStateError(
                    "Codex MCP uninstall encountered a foreign owner"
                )
            current = self.installer.verify(remaining.transaction_id)
        raise InstallationStateError("Codex MCP uninstall chain is too deep")

    def rollback(self, transaction_id: str) -> InstallationResult:
        """Roll back exactly one current lifecycle transition."""
        return self.installer.rollback(transaction_id)

    def health(self, transaction_id: str) -> CodexMCPHealth:
        """Alias the target health contract to exact verification."""
        return self.verify(transaction_id)

    def prove_native_tool_invocation(
        self,
        request: CodexMCPInvocationRequest,
    ) -> CodexMCPInvocationEvidence:
        """Run an explicitly opted-in Codex exec and retain only bounded proof."""
        if not self.allow_native_invocation or not request.allow_provider_traffic:
            raise CodexMCPActivationError(
                "native Codex MCP invocation requires explicit opt-in"
            )
        health = self.verify(request.transaction_id)
        if (
            health.status != "healthy"
            or not health.enabled
            or health.server_name != request.server_name
        ):
            raise CodexMCPActivationError("Codex MCP target is not healthy and enabled")
        installed = self.installer.verify(request.transaction_id)
        plan = self.installer.transaction_plan(request.transaction_id)
        result = self._run_target(
            plan.root,
            installed.scope,
            (
                "exec",
                "--json",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--cd",
                str(request.workspace.resolve()),
                request.prompt,
            ),
            timeout=CODEX_MCP_INVOCATION_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise CodexMCPActivationError("Codex native MCP invocation failed")
        events = _jsonl_events(result.stdout)
        matched = [
            event
            for event in events
            if _completed_mcp_call(
                event,
                server_name=request.server_name,
                tool_name=request.tool_name,
            )
        ]
        if not matched:
            raise CodexMCPActivationError(
                "Codex did not report the requested completed MCP tool call"
            )
        return CodexMCPInvocationEvidence(
            transaction_id=request.transaction_id,
            server_name=request.server_name,
            tool_name=request.tool_name,
            status="completed",
            event_count=len(events),
        )

    def _preview(self, request: CodexMCPRequest, *, action: str) -> CodexMCPPlan:
        existing = self._installation_for_root(request.root)
        if action != "install":
            if existing is None:
                raise InstallationConflictError(
                    "Codex MCP lifecycle change requires an existing owner"
                )
            if existing.package_id != request.package.id:
                raise InstallationConflictError(
                    "Codex MCP target cannot replace a different package"
                )
        install_request = self._installation_request(request)
        installation = self.installer.preview(install_request)
        spec_hash = _server_spec_hash(request.server)
        return CodexMCPPlan(
            action=action,
            plan_id=installation.plan_id,
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=integration_package_semantic_hash(request.package),
            server_name=request.server.name,
            server_spec_sha256=spec_hash,
            enabled=request.server.enabled,
            installation=installation,
        )

    def _update(
        self,
        request: CodexMCPRequest,
        plan: CodexMCPPlan,
        approval: InstallationApproval,
        *,
        action: str,
    ) -> InstallationResult:
        self._validate_action(request, plan, action)
        return self.installer.update(
            self._installation_request(request),
            plan.installation,
            approval,
            verifier=lambda root, _plan: self._verify_target(root, request),
        )

    def _validate_action(
        self, request: CodexMCPRequest, plan: CodexMCPPlan, action: str
    ) -> None:
        expected = (
            action,
            request.package.id,
            request.package.version,
            integration_package_semantic_hash(request.package),
            request.server.name,
            _server_spec_hash(request.server),
            request.server.enabled,
        )
        actual = (
            plan.action,
            plan.package_id,
            plan.package_version,
            plan.manifest_sha256,
            plan.server_name,
            plan.server_spec_sha256,
            plan.enabled,
        )
        if actual != expected or plan.plan_id != plan.installation.plan_id:
            raise InstallationConflictError(
                "Codex MCP lifecycle plan does not match the request"
            )

    def _installation_request(self, request: CodexMCPRequest) -> InstallationRequest:
        root = request.root.expanduser().resolve()
        relative_path = _config_relative_path(request.scope)
        current = _config_text(root, request.scope)
        desired = _render_config(current, request)
        return InstallationRequest(
            package=request.package,
            target=InstallationTarget(
                id=CODEX_MCP_TARGET_ID,
                scope=request.scope,
                root=root,
                owner_id=CODEX_MCP_OWNER_ID,
            ),
            mutations=(
                FileInstallMutation(
                    relative_path=relative_path,
                    content=desired.encode("utf-8"),
                    mode=0o600,
                ),
            ),
        )

    def _verify_target(self, root: Path, request: CodexMCPRequest) -> bool:
        current = _config_text(root, request.scope)
        block = _owned_block(current, request.package.id)
        if block is None:
            return False
        metadata = _block_metadata(block, request.package.id)
        if metadata != {
            "manifest_sha256": integration_package_semantic_hash(request.package),
            "package_version": request.package.version,
            "server_name": request.server.name,
            "server_spec_sha256": _server_spec_hash(request.server),
            "enabled": request.server.enabled,
        }:
            return False
        return self._native_get(root, request.scope, request.server.name)

    def _native_get(
        self, root: Path, scope: InstallationScope, server_name: str
    ) -> bool:
        result = self._run_target(root, scope, ("mcp", "get", server_name, "--json"))
        if result.returncode != 0:
            return False
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        return isinstance(payload, Mapping) and payload.get("name") == server_name

    def _run_target(
        self,
        root: Path,
        scope: InstallationScope,
        args: tuple[str, ...],
        *,
        timeout: float = CODEX_MCP_COMMAND_TIMEOUT_SECONDS,
    ) -> CodexCommandResult:
        if scope is InstallationScope.PROJECT:
            with tempfile.TemporaryDirectory(
                prefix="gigaloom-codex-project-home-"
            ) as raw:
                env = _isolated_env(Path(raw) / ".codex")
                return self.command_runner(
                    self.executable
                    + (
                        "-c",
                        f'projects.{_toml_key(str(root))}.trust_level="trusted"',
                    )
                    + args,
                    env,
                    root,
                    timeout,
                )
        return self.command_runner(
            self.executable + args,
            _isolated_env(root),
            None,
            timeout,
        )

    def _installation_for_root(self, root: Path):
        resolved = root.expanduser().resolve()
        matches = []
        for installed in self.installer.discover():
            if installed.target_id != CODEX_MCP_TARGET_ID:
                continue
            plan = self.installer.transaction_plan(installed.transaction_id)
            if plan.root == resolved:
                matches.append(installed)
        if len(matches) > 1:
            raise InstallationStateError("Codex MCP target has duplicate owners")
        return matches[0] if matches else None


def codex_mcp_target_plugin(
    factory: Callable[[], CodexMCPTargetDriver],
) -> ExtensionTargetPlugin:
    """Build a neutral runtime registration for a configured Codex target."""
    return ExtensionTargetPlugin(
        descriptor=CODEX_MCP_TARGET_DESCRIPTOR,
        factory=factory,
    )


def _render_config(current: str, request: CodexMCPRequest) -> str:
    _parse_toml(current)
    existing = _owned_block(current, request.package.id)
    base = _remove_owned_block(current, request.package.id)
    parsed = _parse_toml(base)
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, Mapping):
        raise ValueError("Codex mcp_servers config must be a table")
    if request.server.name in servers:
        raise InstallationConflictError(
            "Codex MCP server name is already owned outside this package"
        )
    if existing is None and _all_owned_package_ids(current):
        raise InstallationConflictError(
            "Codex MCP target currently supports one package per root"
        )
    block = _render_owned_block(request)
    return f"{base.rstrip()}\n\n{block}".lstrip("\n").rstrip() + "\n"


def _render_owned_block(request: CodexMCPRequest) -> str:
    manifest_hash = integration_package_semantic_hash(request.package)
    spec_hash = _server_spec_hash(request.server)
    package_id = request.package.id
    server = request.server
    lines = [
        f"# BEGIN {CODEX_MCP_MARKER} package={package_id}",
        f"# package_version={request.package.version}",
        f"# manifest_sha256={manifest_hash}",
        f"# server_name={server.name}",
        f"# server_spec_sha256={spec_hash}",
        f"[mcp_servers.{_toml_key(server.name)}]",
    ]
    if server.transport is CodexMCPTransport.STDIO:
        lines.append(f"command = {_toml_string(server.command or '')}")
        if server.args:
            lines.append(f"args = {_toml_array(server.args)}")
        if server.cwd:
            lines.append(f"cwd = {_toml_string(server.cwd)}")
        if server.env_vars:
            lines.append(f"env_vars = {_toml_array(server.env_vars)}")
    else:
        lines.append(f"url = {_toml_string(server.url or '')}")
        if server.bearer_token_env_var:
            lines.append(
                f"bearer_token_env_var = {_toml_string(server.bearer_token_env_var)}"
            )
        if server.env_http_headers:
            rendered = ", ".join(
                f"{_toml_key(key)} = {_toml_string(value)}"
                for key, value in server.env_http_headers
            )
            lines.append(f"env_http_headers = {{ {rendered} }}")
    lines.extend(
        (
            f"enabled = {'true' if server.enabled else 'false'}",
            f"required = {'true' if server.required else 'false'}",
            f"startup_timeout_sec = {server.startup_timeout_sec}",
            f"tool_timeout_sec = {server.tool_timeout_sec}",
            "default_tools_approval_mode = "
            f"{_toml_string(server.default_tools_approval_mode.value)}",
        )
    )
    if server.enabled_tools:
        lines.append(f"enabled_tools = {_toml_array(server.enabled_tools)}")
    if server.disabled_tools:
        lines.append(f"disabled_tools = {_toml_array(server.disabled_tools)}")
    lines.append(f"# END {CODEX_MCP_MARKER} package={package_id}")
    return "\n".join(lines)


def _owned_block(current: str, package_id: str) -> str | None:
    matches = list(_block_pattern(package_id).finditer(current))
    if len(matches) > 1:
        raise InstallationStateError("Codex MCP config has duplicate owned blocks")
    return matches[0].group(0) if matches else None


def _remove_owned_block(current: str, package_id: str) -> str:
    return _block_pattern(package_id).sub("", current).strip()


def _block_pattern(package_id: str) -> re.Pattern[str]:
    escaped_marker = re.escape(CODEX_MCP_MARKER)
    escaped_package = re.escape(package_id)
    return re.compile(
        rf"(?ms)^# BEGIN {escaped_marker} package={escaped_package}\n.*?"
        rf"^# END {escaped_marker} package={escaped_package}\n?"
    )


def _all_owned_package_ids(current: str) -> tuple[str, ...]:
    pattern = re.compile(
        rf"(?m)^# BEGIN {re.escape(CODEX_MCP_MARKER)} package=([^\s]+)$"
    )
    return tuple(match.group(1) for match in pattern.finditer(current))


def _block_metadata(block: str, package_id: str) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line in block.splitlines()[1:5]:
        if not line.startswith("# ") or "=" not in line:
            raise InstallationStateError("Codex MCP owned block metadata is invalid")
        key, value = line[2:].split("=", 1)
        values[key] = value
    expected_keys = {
        "package_version",
        "manifest_sha256",
        "server_name",
        "server_spec_sha256",
    }
    if set(values) != expected_keys:
        raise InstallationStateError("Codex MCP owned block metadata is invalid")
    parsed = _parse_toml(block)
    servers = parsed.get("mcp_servers")
    if not isinstance(servers, Mapping) or len(servers) != 1:
        raise InstallationStateError("Codex MCP owned server table is invalid")
    server_name = values["server_name"]
    server = servers.get(server_name)
    if not isinstance(server, Mapping):
        raise InstallationStateError("Codex MCP owned server binding is invalid")
    if package_id not in _all_owned_package_ids(block):
        raise InstallationStateError("Codex MCP owned package binding is invalid")
    return {
        **values,
        "enabled": server.get("enabled") is not False,
    }


def _config_relative_path(scope: InstallationScope) -> str:
    return ".codex/config.toml" if scope is InstallationScope.PROJECT else "config.toml"


def _config_text(root: Path, scope: InstallationScope) -> str:
    path = root / _config_relative_path(scope)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _parse_toml(value: str) -> Mapping[str, Any]:
    try:
        parsed = tomllib.loads(value) if value.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Codex config.toml is invalid") from exc
    if not isinstance(parsed, Mapping):  # pragma: no cover - tomllib contract
        raise ValueError("Codex config.toml must be a table")
    return parsed


def _server_spec_hash(server: CodexMCPServerSpec) -> str:
    payload = {
        "name": server.name,
        "transport": server.transport.value,
        "command": server.command,
        "args": list(server.args),
        "cwd": server.cwd,
        "env_vars": list(server.env_vars),
        "url": server.url,
        "bearer_token_env_var": server.bearer_token_env_var,
        "env_http_headers": [list(item) for item in server.env_http_headers],
        "enabled": server.enabled,
        "required": server.required,
        "startup_timeout_sec": server.startup_timeout_sec,
        "tool_timeout_sec": server.tool_timeout_sec,
        "enabled_tools": list(server.enabled_tools),
        "disabled_tools": list(server.disabled_tools),
        "default_tools_approval_mode": server.default_tools_approval_mode.value,
    }
    return _json_hash(payload)


def _completed_mcp_call(
    event: Mapping[str, Any], *, server_name: str, tool_name: str
) -> bool:
    if event.get("type") != "item.completed":
        return False
    item = event.get("item")
    if not isinstance(item, Mapping) or item.get("type") != "mcp_tool_call":
        return False
    observed_server = item.get("server") or item.get("server_name")
    observed_tool = item.get("tool") or item.get("name") or item.get("tool_name")
    status = str(item.get("status") or "completed").lower()
    return (
        observed_server == server_name
        and observed_tool == tool_name
        and status in {"completed", "success", "succeeded"}
    )


def _jsonl_events(value: str) -> tuple[Mapping[str, Any], ...]:
    events: list[Mapping[str, Any]] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexMCPActivationError("Codex JSONL output is invalid") from exc
        if not isinstance(item, Mapping):
            raise CodexMCPActivationError("Codex JSONL event is invalid")
        events.append(item)
        if len(events) > 10_000:
            raise CodexMCPActivationError("Codex JSONL output is too large")
    return tuple(events)


def _run_command(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path | None,
    timeout: float,
) -> CodexCommandResult:
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
        raise CodexMCPCommandError(
            f"Codex command failed with {type(exc).__name__}"
        ) from exc
    return CodexCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[-MAX_CODEX_MCP_OUTPUT_CHARS:],
        stderr=completed.stderr[-MAX_CODEX_MCP_OUTPUT_CHARS:],
    )


def _isolated_env(codex_home: Path) -> dict[str, str]:
    env = {
        key: value
        for key in ("PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if (value := os.environ.get(key)) is not None
    }
    env["HOME"] = str(codex_home.parent)
    env["CODEX_HOME"] = str(codex_home)
    return env


def _bounded_output(result: CodexCommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"[-MAX_CODEX_MCP_OUTPUT_CHARS:]


def _first_line(value: str) -> str | None:
    lines = value.strip().splitlines()
    return lines[0][:200] if lines else None


def _toml_key(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _canonical_https_url(value: str) -> str:
    _validate_secret_free(value, "Codex MCP URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Codex HTTP MCP URL must be credential-free HTTPS")
    if parsed.fragment:
        raise ValueError("Codex HTTP MCP URL cannot contain a fragment")
    return urlunsplit(
        ("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )


def _normalize_texts(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(str(item) for item in values)
    if len(normalized) > 256:
        raise ValueError(f"Codex MCP {label} count is invalid")
    for item in normalized:
        if not item or len(item) > 4096:
            raise ValueError(f"Codex MCP {label} is invalid")
        _validate_secret_free(item, f"Codex MCP {label}")
    return normalized


def _normalize_names(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(str(item) for item in values)))
    if len(normalized) != len(tuple(values)):
        raise ValueError(f"Codex MCP {label} contains duplicates")
    for item in normalized:
        _validate_env_name(item)
    return normalized


def _normalize_tools(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(str(item) for item in values)))
    if len(normalized) != len(tuple(values)):
        raise ValueError(f"Codex MCP {label} contains duplicates")
    for item in normalized:
        if not _TOOL_RE.fullmatch(item):
            raise ValueError(f"Codex MCP {label} is invalid")
    return normalized


def _validate_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_env_name(value: str) -> None:
    if not isinstance(value, str) or not _ENV_RE.fullmatch(value):
        raise ValueError("Codex MCP environment variable name is invalid")


def _validate_header_name(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value):
        raise ValueError("Codex MCP HTTP header name is invalid")


def _validate_secret_free(value: str, label: str) -> None:
    if str(redact_secrets(value)) != value:
        raise ValueError(f"{label} contains secret material")


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CODEX_MCP_TARGET_DESCRIPTOR",
    "CODEX_MCP_TARGET_ID",
    "CodexCommandResult",
    "CodexMCPActivationError",
    "CodexMCPDefaultApproval",
    "CodexMCPHealth",
    "CodexMCPInstallation",
    "CodexMCPInvocationEvidence",
    "CodexMCPInvocationRequest",
    "CodexMCPPlan",
    "CodexMCPProbe",
    "CodexMCPRequest",
    "CodexMCPServerSpec",
    "CodexMCPTargetDriver",
    "CodexMCPTransport",
    "CodexMCPUninstallPlan",
    "codex_mcp_target_plugin",
]
