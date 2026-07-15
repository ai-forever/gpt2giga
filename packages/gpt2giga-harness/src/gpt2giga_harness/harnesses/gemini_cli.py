"""Gemini CLI harness for running Gemini through local gpt2giga."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

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
from gpt2giga_harness.executables import ExecutableResolution, ExecutableResolver
from gpt2giga_harness.native import HarnessInvocationMode
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
HARNESS_MODEL_HEADER = "X-GPT2GIGA-Harness-Model"
PASS_MODEL_HEADER = "X-GPT2GIGA-Pass-Model"


def gemini_cli_custom_headers(
    context: HarnessContext,
    model: str,
) -> str:
    """Pin all Gemini CLI requests to the Harness-selected model."""
    harness_headers = (
        f"{HARNESS_MODEL_HEADER}:{quote(model, safe='')},{PASS_MODEL_HEADER}:false"
    )
    existing_headers = context.extra_env.get("GEMINI_CLI_CUSTOM_HEADERS")
    if existing_headers:
        return f"{existing_headers},{harness_headers}"
    return harness_headers


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
                result = run_streaming_command(
                    label="Gemini CLI",
                    command=command,
                    env=env,
                    cwd=request.workspace,
                    timeout_seconds=context.timeout_seconds,
                    request=request,
                    parse_payload=_GeminiStreamParser(),
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


def _managed_mcp_reference(request: HarnessRequest) -> Mapping[str, Any] | None:
    value = request.extra.get("managed_mcp_snapshot")
    return dict(value) if isinstance(value, Mapping) else None


class _GeminiStreamParser:
    """Normalize Gemini CLI stream-json events."""

    def __init__(self) -> None:
        self.terminal_outcome: StreamTerminalOutcome | None = None
        self.recognized_payloads = 0

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
            events.append(
                tool_call_event(
                    "tool_call_started",
                    tool_call_id=payload.get("tool_id"),
                    name=payload.get("tool_name"),
                    arguments=payload.get("parameters"),
                    status="running",
                )
            )
        elif event_type == "tool_result":
            error = _mapping(payload.get("error"))
            result = payload.get("output")
            if result is None and error:
                result = error.get("message")
            events.append(
                tool_call_event(
                    "tool_call_finished",
                    tool_call_id=payload.get("tool_id"),
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
