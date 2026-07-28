"""Gemini CLI harness for running Gemini through local gpt2giga."""

from __future__ import annotations

from collections import deque
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from importlib import metadata
import hashlib
import json
import tempfile
from pathlib import Path
import threading
import time
from typing import Any, Mapping

from gpt2giga_harness.cli_capabilities import (
    CliCapabilitySnapshot,
    cli_probe_availability,
    probe_cli_capabilities,
)
from gpt2giga_harness.harnesses.agent_cli import (
    StreamTerminalOutcome,
    build_safe_env,
    message_delta_event,
    prepare_proxy_for_agent,
    run_command,
    run_streaming_command,
    stream_terminal_failure,
    tool_call_event,
    usage_event,
    with_events,
    with_raw_metadata,
    workspace_error,
)
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_capability_error,
    attachment_raw_metadata,
    attachment_warning_events,
    cli_args_from_attachments,
    prompt_with_attachments,
)
from gpt2giga_harness.harnesses.adapter_parity import gemini_adapter_capabilities
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.harness_model import signed_harness_model_headers
from gpt2giga_harness.executables import ExecutableResolution, ExecutableResolver
from gpt2giga_harness.gemini_acp import (
    GEMINI_ACP_PROTOCOL,
    GEMINI_ACP_PROTOCOL_VERSION,
    AuthProvider,
    GeminiAcpDriver,
    GeminiAcpError,
    GeminiAcpStdioScope,
    McpProvider,
    create_gemini_acp_stdio_scope,
)
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.execution import (
    EMPTY_EXTENSION_SNAPSHOT_HASH,
    ExecutionClassification,
    ExecutionClassificationStatus,
    ExecutionSnapshot,
    ExecutionTransport,
    InteractionMode,
    ProviderRef,
    RouteRef,
    RuntimeOwnership,
    SnapshotEvidenceRef,
    create_execution_snapshot,
)
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyResolution,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.structured_sessions import (
    AdapterCapabilitySnapshot,
    StructuredSessionConfigSnapshot,
    StructuredSessionCoordinator,
    StructuredSessionLinkStore,
    StructuredTurnInput,
    structured_session_link_to_dict,
)
from gpt2giga_harness.managed_mcp import (
    materialize_headless_mcp_snapshot,
    write_startup_config,
)
from gpt2giga_harness.types import (
    AttachmentTransportSupport,
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HeadlessContinuationStrategy,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    redact_secrets,
)

MODE_TO_APPROVAL = {
    "plan": "--approval-mode=plan",
    "read": "--approval-mode=plan",
}


def gemini_cli_custom_headers(
    context: HarnessContext,
    model: str,
) -> str:
    """Pin all Gemini CLI requests to the Harness-selected model."""
    harness_headers = ",".join(
        f"{name}:{value}"
        for name, value in signed_harness_model_headers(
            protocol="gemini",
            model=model,
            key=context.harness_model_key,
        )
    )
    existing_headers = context.extra_env.get("GEMINI_CLI_CUSTOM_HEADERS")
    if existing_headers and harness_headers:
        return f"{existing_headers},{harness_headers}"
    return existing_headers or harness_headers


class GeminiCliHarness(BaseHarness):
    """Run Gemini CLI in headless mode against gpt2giga."""

    def __init__(
        self,
        *,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        self.executable_resolver = executable_resolver or ExecutableResolver.path_only()

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="gemini-cli",
            title="Gemini CLI",
            kind="agent-cli",
            description="Run Gemini CLI against local gpt2giga proxy",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
            supports_workspace=True,
            supports_attachments=True,
            accepted_attachment_kinds=("text", "workspace_file", "document", "image"),
            attachment_transport=("at_file_reference", "prompt_path_reference"),
            attachment_capabilities={
                kind: AttachmentTransportSupport(
                    headless=("prompt_path_reference", "at_file_reference"),
                    native=("prompt_path_reference", "at_file_reference"),
                    detail=(
                        "Gemini CLI receives a contained path reference; rich image "
                        "or document transport is not claimed without CLI evidence."
                    ),
                )
                for kind in ("image", "text", "workspace_file", "document")
            },
            supports_native_sessions=True,
            supports_external_history=True,
            default_invocation_mode=HarnessInvocationMode.NATIVE,
            headless_continuation=HeadlessContinuationStrategy.UNSUPPORTED,
            tags=("gemini", "agent"),
            adapter_capabilities=gemini_adapter_capabilities(),
        )

    def availability(self) -> Availability:
        return cli_probe_availability(
            self.capability_probe(),
            install_hint=(
                "Install Gemini CLI on PATH or configure executables.gemini-cli "
                "in ~/.gpt2giga/harness/config.toml."
            ),
        )

    def capability_probe(self) -> CliCapabilitySnapshot:
        """Return cached, version-aware Gemini adapter evidence."""
        return probe_cli_capabilities(self.executable_resolution(), self.spec().id)

    def executable_resolution(self) -> ExecutableResolution:
        """Return the configured or PATH-discovered Gemini executable."""
        return self.executable_resolver.resolve(self.spec().id, "gemini")

    def durable_structured_capabilities(self) -> AdapterCapabilitySnapshot:
        """Return conservative reviewed ACP admission evidence."""
        probe = self.capability_probe()
        if (
            not probe.compatible
            or not probe.capabilities.get("--acp")
            or probe.parsed_version is None
        ):
            raise ValueError("installed Gemini CLI ACP capability is unavailable")
        return AdapterCapabilitySnapshot(
            adapter_id="gemini-cli",
            adapter_version=_adapter_version(),
            protocol=GEMINI_ACP_PROTOCOL,
            protocol_version=str(GEMINI_ACP_PROTOCOL_VERSION),
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=False,
            interrupt=True,
            steer=False,
            resume=True,
            fork=False,
            session_list=False,
            session_close=False,
            native_auth=True,
            provider_ui_handoff=False,
            dynamic_model=False,
            dynamic_mcp=True,
            recovery_after_process_loss=True,
            attachment_kinds=("audio", "embedded-context", "image"),
            attachment_transports=("acp-inline", "acp-resource"),
        )

    def run_durable_structured(
        self, request: HarnessRequest, context: HarnessContext
    ) -> HarnessResult:
        """Run one durable turn through the product Gemini ACP driver."""
        if (
            context.data_dir is None
            or request.session_id is None
            or request.run_id is None
        ):
            return HarnessResult(
                ok=False, text="", error="Gemini ACP durable identity is incomplete."
            )
        if _managed_mcp_reference(request) is not None:
            return HarnessResult(
                ok=False,
                text="",
                error="Gemini ACP durable managed MCP projection is not yet proven.",
            )
        resolution = self.executable_resolution()
        command = (
            (*resolution.command, "--acp")
            if resolution.command
            else ("gemini", "--acp")
        )
        prepared_context, proxy_events, proxy_error = prepare_proxy_for_agent(
            request,
            context,
            harness_id="gemini-cli",
            command=command,
        )
        if proxy_error is not None:
            return proxy_error
        scope_id = (
            "durable-"
            + hashlib.sha256(request.session_id.encode("utf-8")).hexdigest()[:24]
        )
        driver, scope = self.create_acp_driver(
            request,
            prepared_context,
            scope_id=scope_id,
            auth_provider=lambda: (
                "gateway",
                {
                    "gateway": {
                        "baseUrl": prepared_context.api_base_url(request.api_mode)
                    }
                },
            ),
        )
        coordinator = StructuredSessionCoordinator(
            driver,
            StructuredSessionLinkStore(context.data_dir),
            owner_id=_structured_owner(request),
        )
        link_id = (
            "gemini-link-"
            + hashlib.sha256(request.session_id.encode("utf-8")).hexdigest()[:24]
        )
        existing = coordinator.store.load(link_id)
        collected: list[HarnessEvent] = list(proxy_events)
        text_parts: list[str] = []

        def event_sink(event: Mapping[str, Any]) -> None:
            payload = event.get("payload")
            safe_payload = dict(payload) if isinstance(payload, Mapping) else {}
            normalized = HarnessEvent(
                type=str(event.get("type") or "session_state"),
                message="Gemini ACP emitted a structured event.",
                payload=safe_payload,
            )
            collected.append(normalized)
            if request.event_sink is not None:
                request.event_sink(normalized)
            content = safe_payload.get("content")
            if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                text_parts.append(str(content["text"]))

        try:
            link = coordinator.open_or_resume(
                link_id=link_id,
                harness_session_id=request.session_id,
                harness_run_id=request.run_id,
                execution_snapshot=_gemini_execution_snapshot(request),
                config_snapshot=StructuredSessionConfigSnapshot(
                    adapter_id="gemini-cli",
                    adapter_version=_adapter_version(),
                    protocol=GEMINI_ACP_PROTOCOL,
                    protocol_version=str(GEMINI_ACP_PROTOCOL_VERSION),
                    cli_sdk_version=str(self.capability_probe().parsed_version),
                    managed_home_id=scope.managed_home_id,
                ),
                existing_link=existing,
            )
            turn_finished = threading.Event()

            def monitor_cancel() -> None:
                while not turn_finished.wait(0.05):
                    if (
                        request.cancel_event is None
                        or not request.cancel_event.is_set()
                    ):
                        continue
                    turn_id = driver.active_turn_id
                    if turn_id is not None:
                        with suppress(Exception):
                            coordinator.interrupt(link, turn_id)
                    return

            cancel_monitor = threading.Thread(
                target=monitor_cancel,
                name=f"gemini-acp-cancel-{request.run_id}",
                daemon=True,
            )
            cancel_monitor.start()
            try:
                link, turn = coordinator.start_turn(
                    link,
                    StructuredTurnInput(request.run_id, request.prompt),
                    event_sink,
                    _durable_approval_bridge(request, context),
                )
            finally:
                turn_finished.set()
                cancel_monitor.join(timeout=0.2)
            ok = turn.status == "completed"
            return HarnessResult(
                ok=ok,
                text="".join(text_parts),
                raw={
                    "structured_session_link": structured_session_link_to_dict(link),
                    "structured_session_driver": "gemini-acp",
                },
                events=tuple(collected),
                command=command,
                error=None if ok else f"Gemini ACP turn ended as {turn.status}.",
            )
        finally:
            driver.close()

    def create_acp_driver(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        scope_id: str,
        auth_provider: AuthProvider,
        mcp_provider: McpProvider | None = None,
    ) -> tuple[GeminiAcpDriver, GeminiAcpStdioScope]:
        """Create the product ACP driver without admitting it to durable runtime."""
        capability = self.capability_probe()
        if not capability.compatible or not capability.capabilities.get("--acp"):
            raise GeminiAcpError("installed Gemini CLI ACP capability is unavailable")
        if capability.parsed_version is None:
            raise GeminiAcpError("installed Gemini CLI version is unavailable")
        resolution = self.executable_resolution()
        if not resolution.command:
            raise GeminiAcpError("installed Gemini CLI command is unavailable")
        if request.workspace is None:
            raise GeminiAcpError("Gemini ACP requires an explicit workspace")
        if context.data_dir is None:
            raise GeminiAcpError("Gemini ACP requires a Harness data directory")
        scope = create_gemini_acp_stdio_scope(
            command=resolution.command,
            env=self.build_env(request, context),
            workspace=request.workspace,
            data_dir=context.data_dir,
            scope_id=scope_id,
        )
        driver = GeminiAcpDriver(
            scope.transport_factory,
            cli_help="--acp",
            cli_version=capability.parsed_version,
            adapter_version=_adapter_version(),
            cwd=request.workspace,
            auth_provider=auth_provider,
            mcp_provider=mcp_provider,
            request_timeout_seconds=min(context.timeout_seconds, 30.0),
            prompt_timeout_seconds=context.timeout_seconds,
        )
        return driver, scope

    def build_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> tuple[str, ...]:
        """Build the Gemini CLI command without executing it."""
        resolution = self.executable_resolution()
        executable_argv = resolution.command or ("gemini",)
        model = request.model or context.default_model or "GigaChat"
        prompt = prompt_with_attachments(request)
        output_format = "stream-json" if request.stream else "json"
        command = [
            *executable_argv,
            "-m",
            model,
            *cli_args_from_attachments(request),
            "-p",
            prompt,
            "--output-format",
            output_format,
            "--skip-trust",
        ]
        approval = MODE_TO_APPROVAL.get(request.mode)
        if approval is not None:
            command.append(approval)
        return tuple(command)

    def build_env(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        home: str | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment for Gemini CLI."""
        model = request.model or context.default_model or "GigaChat"
        return build_safe_env(
            context,
            home=home,
            extra={
                "GOOGLE_GEMINI_BASE_URL": context.api_base_url(request.api_mode),
                "GEMINI_API_KEY": context.api_key or "0",
                "GEMINI_MODEL": model,
                "GEMINI_CLI_CUSTOM_HEADERS": gemini_cli_custom_headers(
                    context,
                    model,
                ),
                "GEMINI_CLI_TRUST_WORKSPACE": "true",
                "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
                "GPT2GIGA_HARNESS_API_MODE": request.api_mode.value,
            },
        )

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        command = self.build_command(request, context)
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={
                    "env": redact_secrets(
                        self.build_env(request, context, home="<temp>")
                    ),
                    "workspace": request.workspace,
                    **attachment_raw_metadata(request),
                },
                events=attachment_warning_events(request),
                command=command,
            )
        workspace_validation_error = workspace_error(request.workspace)
        if workspace_validation_error is not None:
            return HarnessResult(
                ok=False,
                text="",
                raw={},
                command=command,
                error=workspace_validation_error,
            )
        availability = self.availability()
        if availability.status.value != "available":
            return HarnessResult(
                ok=False,
                text="",
                raw={},
                command=command,
                error=availability.reason,
            )
        attachment_error = attachment_capability_error(
            request,
            self.capability_probe().capabilities,
            surface="headless_one_shot",
        )
        if attachment_error is not None:
            return HarnessResult(
                ok=False,
                text="",
                raw=attachment_raw_metadata(request),
                command=command,
                error=attachment_error,
            )
        prepared_context, proxy_events, proxy_error = prepare_proxy_for_agent(
            request,
            context,
            harness_id="gemini-cli",
            command=command,
        )
        if proxy_error is not None:
            return proxy_error
        with tempfile.TemporaryDirectory(prefix="gpt2giga-gemini-") as temp_dir:
            _write_gemini_settings(Path(temp_dir))
            managed_mcp = materialize_headless_mcp_snapshot(
                "gemini-cli",
                temp_dir,
                _managed_mcp_reference(request),
                data_dir=context.data_dir,
            )
            env = self.build_env(request, prepared_context, home=temp_dir)
            if request.stream:
                parser = _GeminiStreamParser(home=Path(temp_dir))
                result = run_streaming_command(
                    label="Gemini CLI",
                    command=command,
                    env=env,
                    cwd=request.workspace,
                    timeout_seconds=context.timeout_seconds,
                    request=request,
                    parse_payload=parser,
                )
            else:
                result = run_command(
                    label="Gemini CLI",
                    command=command,
                    env=env,
                    cwd=request.workspace,
                    timeout_seconds=context.timeout_seconds,
                )
            return with_raw_metadata(
                with_events(
                    result,
                    (*attachment_warning_events(request), *proxy_events),
                ),
                {"managed_mcp_snapshot": managed_mcp} if managed_mcp else None,
            )


def _write_gemini_settings(home: Path) -> None:
    write_startup_config(
        "gemini-cli",
        home,
        {"security": {"auth": {"selectedType": "gemini-api-key"}}},
    )


def _structured_owner(request: HarnessRequest) -> str:
    runtime = request.extra.get("runtime")
    worker_id = runtime.get("worker_id") if isinstance(runtime, Mapping) else None
    return str(worker_id or "durable-worker")


def _gemini_execution_snapshot(request: HarnessRequest) -> ExecutionSnapshot:
    api_mode = request.api_mode.value
    model = request.model or "unknown"
    route_revision = hashlib.sha256(f"{api_mode}\0{model}".encode("utf-8")).hexdigest()
    provider = ProviderRef("gpt2giga-harness", f"api-{api_mode}")
    workspace_execution = request.extra.get("workspace_execution")
    workspace_execution = (
        workspace_execution if isinstance(workspace_execution, Mapping) else {}
    )
    workspace = str(
        workspace_execution.get("source_workspace") or request.workspace or "unknown"
    )
    effective_workspace = str(request.workspace or workspace)
    workspace_id = (
        "workspace-" + hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:24]
    )
    return create_execution_snapshot(
        provider=provider,
        route=RouteRef(f"route-{route_revision[:24]}", route_revision, provider),
        harness_id="gemini-cli",
        harness_version=_adapter_version(),
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        interaction_mode=InteractionMode.INTERACTIVE,
        runtime_ownership=RuntimeOwnership.DURABLE,
        workspace_id=workspace_id,
        worktree_id=(
            "worktree-"
            + hashlib.sha256(effective_workspace.encode("utf-8")).hexdigest()[:24]
            if effective_workspace != workspace
            else None
        ),
        permission_profile=str(request.mode or "plan"),
        extension_snapshot_hash=EMPTY_EXTENSION_SNAPSHOT_HASH,
        capability_evidence=(
            SnapshotEvidenceRef(
                "gemini-acp",
                "reviewed-v1",
                "supported",
                "gemini-cli-probe",
            ),
        ),
        classification=ExecutionClassification(
            status=ExecutionClassificationStatus.EXPLICIT,
            source="gemini_acp_driver",
        ),
    )


def _durable_approval_bridge(request: HarnessRequest, context: HarnessContext):
    if context.data_dir is None:
        raise GeminiAcpError("durable approval requires a Harness data directory")
    store = RuntimeCoordinationStore(context.data_dir)

    def approve(contract: Mapping[str, Any]) -> str:
        binding = str(contract.get("binding_hash") or "")
        if len(binding) != 64:
            raise GeminiAcpError("Gemini ACP approval binding is invalid")
        approval = store.find_approval_request_by_binding(binding)
        if approval is None:
            runtime = request.extra.get("runtime")
            runtime = runtime if isinstance(runtime, Mapping) else {}
            timeout = max(float(context.timeout_seconds), 0.1)
            approval = store.create_approval_request(
                PolicyResolution(
                    action=PermissionAction.MCP_TOOL_CALL,
                    decision=PolicyDecision.ASK,
                    enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
                    policy_source="gemini_acp:request_permission",
                ),
                PolicyContext(
                    session_id=request.session_id,
                    run_id=request.run_id,
                    job_id=str(runtime.get("job_id") or "") or None,
                    reason="Gemini ACP requested permission for a tool call.",
                    preview={
                        "provider": "gemini-acp",
                        "tool_call_id": contract.get("tool_call_id"),
                        "option_kinds": [
                            item.get("kind")
                            for item in contract.get("options", ())
                            if isinstance(item, Mapping)
                        ],
                    },
                    approval_binding=binding,
                    enforcement_owner="gemini_acp.request_permission",
                ),
                expires_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=timeout)
                ).isoformat(),
            )
        if request.event_sink is not None:
            request.event_sink(
                HarnessEvent(
                    type="approval_requested",
                    message="Gemini ACP is waiting for Approval Center.",
                    payload={"approval_id": approval.id},
                )
            )
        deadline = time.monotonic() + max(float(context.timeout_seconds), 0.1)
        while time.monotonic() < deadline:
            current = store.get_approval_request(approval.id)
            if current.status is ApprovalStatus.APPROVED:
                return "allow"
            if current.status in {
                ApprovalStatus.DENIED,
                ApprovalStatus.EXPIRED,
                ApprovalStatus.CANCELED,
            }:
                return "deny"
            if request.cancel_event is not None and request.cancel_event.is_set():
                return "cancel"
            time.sleep(0.05)
        return "deny"

    return approve


def _managed_mcp_reference(request: HarnessRequest) -> Mapping[str, Any] | None:
    value = request.extra.get("managed_mcp_snapshot")
    return dict(value) if isinstance(value, Mapping) else None


def _adapter_version() -> str:
    try:
        value = metadata.version("gpt2giga-harness")
    except metadata.PackageNotFoundError:
        value = "unknown"
    normalized = str(value).strip()
    return normalized if normalized else "unknown"


class GeminiStreamParser:
    """Normalize Gemini CLI stream-json events."""

    def __init__(self, *, home: Path | None = None) -> None:
        self.terminal_outcome: StreamTerminalOutcome | None = None
        self.recognized_payloads = 0
        self._tool_context: dict[str, dict[str, Any]] = {}
        self._subagent_trace = _GeminiSubagentTrace(home) if home is not None else None

    def __call__(self, payload: Mapping[str, Any]) -> tuple[HarnessEvent, ...]:
        event_type = str(payload.get("type") or "")
        if event_type in {
            "init",
            "message",
            "tool_use",
            "tool_result",
            "result",
            "error",
        }:
            self.recognized_payloads += 1
        events: list[HarnessEvent] = []
        if event_type == "message" and payload.get("role") in {"assistant", "agent"}:
            message = message_delta_event(payload.get("content"))
            if message is not None:
                events.append(message)
        elif event_type == "tool_use":
            tool_call_id = str(payload.get("tool_id") or "tool-call")
            tool_name = str(payload.get("tool_name") or "tool")
            tool_arguments = payload.get("parameters")
            self._tool_context[tool_call_id] = {
                "name": tool_name,
                "arguments": tool_arguments,
            }
            if self._subagent_trace is not None:
                self._subagent_trace.register_started(tool_call_id, tool_name)
            events.append(
                tool_call_event(
                    "tool_call_started",
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    arguments=tool_arguments,
                    status="running",
                )
            )
        elif event_type == "tool_result":
            tool_call_id = str(payload.get("tool_id") or "tool-call")
            tool_context = self._tool_context.get(tool_call_id, {})
            if self._subagent_trace is not None:
                self._subagent_trace.register_finished(tool_call_id)
            error = _mapping(payload.get("error"))
            result = payload.get("output")
            if result is None and error:
                result = error.get("message")
            events.append(
                tool_call_event(
                    "tool_call_finished",
                    tool_call_id=tool_call_id,
                    name=tool_context.get("name"),
                    arguments=tool_context.get("arguments"),
                    result=result,
                    status=payload.get("status"),
                )
            )
        elif event_type == "error" or (
            event_type == "result" and _gemini_result_failed(payload)
        ):
            failure = stream_terminal_failure(
                payload.get("error") or payload.get("message") or payload.get("status"),
                fallback="Gemini CLI reported a failed result",
            )
            if self.terminal_outcome is None:
                self.terminal_outcome = failure
            events.append(
                HarnessEvent(
                    type="stderr_delta",
                    message="Gemini CLI reported an error.",
                    payload={"delta": failure.error or "Gemini CLI failed"},
                )
            )

        usage = usage_event(payload.get("stats") or payload.get("usage"))
        if usage is not None:
            events.append(usage)
        return tuple(events)

    def poll_events(self) -> tuple[HarnessEvent, ...]:
        """Read newly persisted tool activity from isolated subagent checkpoints."""
        if self._subagent_trace is None:
            return ()
        return self._subagent_trace.poll_events()


# Retain the historical private name for callers already importing it.
_GeminiStreamParser = GeminiStreamParser


class _GeminiSubagentTrace:
    """Tail Gemini's temporary subagent checkpoints into nested tool events."""

    def __init__(self, home: Path) -> None:
        self._home = home
        self._pending_parents: deque[str] = deque()
        self._active_parents: list[str] = []
        self._last_parent: str | None = None
        self._file_parents: dict[Path, str] = {}
        self._offsets: dict[Path, int] = {}
        self._started: set[str] = set()
        self._finished: set[str] = set()

    def register_started(self, tool_call_id: str, name: str) -> None:
        if name != "invoke_agent" or tool_call_id in self._active_parents:
            return
        self._pending_parents.append(tool_call_id)
        self._active_parents.append(tool_call_id)
        self._last_parent = tool_call_id

    def register_finished(self, tool_call_id: str) -> None:
        if tool_call_id in self._active_parents:
            self._active_parents.remove(tool_call_id)
        with suppress(ValueError):
            self._pending_parents.remove(tool_call_id)

    def poll_events(self) -> tuple[HarnessEvent, ...]:
        events: list[HarnessEvent] = []
        for path in self._checkpoint_paths():
            parent_id = self._parent_for(path)
            if parent_id is None:
                continue
            for payload in self._read_appended_payloads(path):
                tool_calls = payload.get("toolCalls")
                if not isinstance(tool_calls, list):
                    continue
                for tool_call in tool_calls:
                    if isinstance(tool_call, Mapping):
                        events.extend(self._tool_events(tool_call, parent_id=parent_id))
        return tuple(events)

    def _checkpoint_paths(self) -> tuple[Path, ...]:
        roots = self._home.glob(".gemini/tmp/*/chats")
        paths = (
            path for root in roots for path in root.glob("*/*.jsonl") if path.is_file()
        )
        return tuple(sorted(paths, key=_checkpoint_sort_key))

    def _parent_for(self, path: Path) -> str | None:
        parent_id = self._file_parents.get(path)
        if parent_id is not None:
            return parent_id
        if self._pending_parents:
            parent_id = self._pending_parents.popleft()
        elif self._active_parents:
            parent_id = self._active_parents[-1]
        elif self._last_parent is not None:
            parent_id = self._last_parent
        else:
            return None
        self._file_parents[path] = parent_id
        return parent_id

    def _read_appended_payloads(self, path: Path) -> tuple[Mapping[str, Any], ...]:
        offset = self._offsets.get(path, 0)
        try:
            size = path.stat().st_size
            if size < offset:
                offset = 0
            with path.open("rb") as checkpoint:
                checkpoint.seek(offset)
                data = checkpoint.read()
        except OSError:
            return ()
        last_newline = data.rfind(b"\n")
        if last_newline < 0:
            return ()
        complete = data[: last_newline + 1]
        self._offsets[path] = offset + len(complete)
        payloads: list[Mapping[str, Any]] = []
        for line in complete.splitlines():
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(payload, Mapping):
                payloads.append(payload)
        return tuple(payloads)

    def _tool_events(
        self,
        tool_call: Mapping[str, Any],
        *,
        parent_id: str,
    ) -> tuple[HarnessEvent, ...]:
        identifier = str(tool_call.get("id") or "").strip()
        name = str(tool_call.get("name") or "").strip()
        if not identifier or not name:
            return ()
        events: list[HarnessEvent] = []
        if identifier not in self._started:
            events.append(
                tool_call_event(
                    "tool_call_started",
                    tool_call_id=identifier,
                    name=name,
                    arguments=tool_call.get("args"),
                    status="running",
                    parent_tool_call_id=parent_id,
                    source="gemini-subagent-checkpoint",
                )
            )
            self._started.add(identifier)
            if name == "invoke_agent":
                self.register_started(identifier, name)

        status = _gemini_checkpoint_status(tool_call.get("status"))
        if status is None or identifier in self._finished:
            return tuple(events)
        events.append(
            tool_call_event(
                "tool_call_finished",
                tool_call_id=identifier,
                name=name,
                arguments=tool_call.get("args"),
                result=_gemini_checkpoint_result(tool_call),
                status=status,
                parent_tool_call_id=parent_id,
                source="gemini-subagent-checkpoint",
            )
        )
        self._finished.add(identifier)
        if name == "invoke_agent":
            self.register_finished(identifier)
        return tuple(events)


def _checkpoint_sort_key(path: Path) -> tuple[int, str]:
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return modified_ns, str(path)


def _gemini_checkpoint_status(value: Any) -> str | None:
    status = str(value or "").strip().lower()
    if status in {"success", "completed"}:
        return "success"
    if status in {"error", "failed", "cancelled", "canceled"}:
        return status
    return None


def _gemini_checkpoint_result(tool_call: Mapping[str, Any]) -> Any:
    result = tool_call.get("result")
    outputs: list[str] = []
    if isinstance(result, list):
        for item in result:
            if not isinstance(item, Mapping):
                continue
            function_response = item.get("functionResponse")
            if not isinstance(function_response, Mapping):
                continue
            response = function_response.get("response")
            if not isinstance(response, Mapping):
                continue
            output = response.get("output")
            if isinstance(output, str):
                outputs.append(output)
    if outputs:
        return "\n".join(outputs)
    if result is not None:
        return result
    error = tool_call.get("error")
    return error if error is not None else tool_call.get("description")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _gemini_result_failed(payload: Mapping[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    return status in {"error", "failed", "failure"} or _has_error_value(
        payload.get("error")
    )


def _has_error_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, list, tuple, set)):
        return bool(value)
    return value is not None and value is not False
