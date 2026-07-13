"""Claude Code harness for running Claude through local gpt2giga."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

from gpt2giga_harness.harnesses.agent_cli import (
    StreamTerminalOutcome,
    build_safe_env,
    executable_availability,
    message_delta_event,
    prepare_proxy_for_agent,
    run_command,
    run_streaming_command,
    stream_terminal_failure,
    tool_call_event,
    usage_event,
    with_events,
    workspace_error,
)
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    attachment_warning_events,
    cli_args_from_attachments,
    prompt_with_attachments,
)
from gpt2giga_harness.harnesses.adapter_parity import claude_adapter_capabilities
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.executables import ExecutableResolution, ExecutableResolver
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.managed_mcp import write_startup_config
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    redact_secrets,
)

MODE_TO_PERMISSION = {
    "plan": "plan",
    "read": "plan",
    "edit": "default",
}


class ClaudeCodeHarness(BaseHarness):
    """Run Claude Code in print mode against gpt2giga."""

    def __init__(
        self,
        *,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        self.executable_resolver = executable_resolver or ExecutableResolver.path_only()

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="claude-code",
            title="Claude Code",
            kind="agent-cli",
            description="Run Claude Code against local gpt2giga proxy",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
            supports_workspace=True,
            supports_attachments=True,
            accepted_attachment_kinds=(
                "image",
                "text",
                "workspace_file",
                "document",
            ),
            attachment_transport=("prompt_path_reference", "at_file_reference"),
            supports_native_sessions=True,
            supports_external_history=True,
            default_invocation_mode=HarnessInvocationMode.NATIVE,
            tags=("claude", "agent"),
            adapter_capabilities=claude_adapter_capabilities(),
        )

    def availability(self) -> Availability:
        resolution = self.executable_resolution()
        if resolution.error is not None:
            return Availability.error(resolution.error)
        return executable_availability(
            executable=resolution.executable,
            executable_name="claude",
            install_hint=(
                "Install Claude Code on PATH or configure executables.claude-code "
                "in ~/.gpt2giga/harness/config.toml."
            ),
            version_args=None,
            source=resolution.source,
        )

    def executable_resolution(self) -> ExecutableResolution:
        """Return the configured or PATH-discovered Claude executable."""
        return self.executable_resolver.resolve(self.spec().id, "claude")

    def build_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> tuple[str, ...]:
        """Build the Claude Code command without executing it."""
        resolution = self.executable_resolution()
        executable = resolution.executable or resolution.configured or "claude"
        model = request.model or context.default_model or "GigaChat"
        permission_mode = MODE_TO_PERMISSION.get(
            request.mode, MODE_TO_PERMISSION["plan"]
        )
        prompt = prompt_with_attachments(request)
        output_format = "stream-json" if request.stream else "json"
        stream_args = (
            ("--include-partial-messages", "--verbose") if request.stream else ()
        )
        return (
            executable,
            "--bare",
            "--safe-mode",
            "-p",
            "--model",
            model,
            "--output-format",
            output_format,
            *stream_args,
            "--no-session-persistence",
            "--permission-mode",
            permission_mode,
            *cli_args_from_attachments(request),
            prompt,
        )

    def build_env(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        home: str | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment for Claude Code."""
        return build_safe_env(
            context,
            home=home,
            extra={
                "ANTHROPIC_BASE_URL": context.api_base_url(request.api_mode),
                "ANTHROPIC_API_KEY": context.api_key or "0",
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
        prepared_context, proxy_events, proxy_error = prepare_proxy_for_agent(
            request,
            context,
            command=command,
        )
        if proxy_error is not None:
            return proxy_error
        with tempfile.TemporaryDirectory(prefix="gpt2giga-claude-") as temp_dir:
            _write_claude_settings(Path(temp_dir))
            prepared_env = self.build_env(request, prepared_context, home=temp_dir)
            if request.stream:
                result = run_streaming_command(
                    label="Claude Code",
                    command=command,
                    env=prepared_env,
                    cwd=request.workspace,
                    timeout_seconds=context.timeout_seconds,
                    request=request,
                    parse_payload=_ClaudeStreamParser(),
                )
            else:
                result = run_command(
                    label="Claude Code",
                    command=command,
                    env=prepared_env,
                    cwd=request.workspace,
                    timeout_seconds=context.timeout_seconds,
                )
            return with_events(
                result,
                (*attachment_warning_events(request), *proxy_events),
            )


def _write_claude_settings(home: Path) -> None:
    write_startup_config("claude-code", home, {})


class _ClaudeStreamParser:
    """Normalize Claude Code stream-json content, tool, and usage events."""

    def __init__(self) -> None:
        self._has_message_delta = False
        self._blocks: dict[int, dict[str, Any]] = {}
        self._started_tools: set[str] = set()
        self.terminal_outcome: StreamTerminalOutcome | None = None

    def __call__(self, payload: Mapping[str, Any]) -> tuple[HarnessEvent, ...]:
        event_type = str(payload.get("type") or "")
        events: list[HarnessEvent] = []
        if event_type == "stream_event":
            events.extend(self._stream_events(_mapping(payload.get("event"))))
        elif event_type == "assistant":
            events.extend(self._assistant_events(_mapping(payload.get("message"))))
        elif event_type == "user":
            events.extend(self._tool_result_events(_mapping(payload.get("message"))))
        elif event_type == "result":
            result_failed = _claude_result_failed(payload)
            final_text = payload.get("result")
            if not result_failed and not self._has_message_delta:
                message_event = message_delta_event(final_text)
                if message_event is not None:
                    self._has_message_delta = True
                    events.append(message_event)
            if result_failed:
                events.append(
                    self._terminal_failure_event(
                        payload.get("error")
                        or payload.get("errors")
                        or payload.get("result")
                        or payload.get("subtype"),
                        fallback="Claude Code reported a failed result",
                    )
                )
        elif event_type == "error":
            events.append(
                self._terminal_failure_event(
                    payload.get("error") or payload.get("message"),
                    fallback="Claude Code stream failed",
                )
            )

        usage = usage_event(payload.get("usage"))
        if usage is not None:
            events.append(usage)
        return tuple(events)

    def _stream_events(
        self,
        event: Mapping[str, Any],
    ) -> tuple[HarnessEvent, ...]:
        event_type = str(event.get("type") or "")
        events: list[HarnessEvent] = []
        if event_type == "message_start":
            usage = usage_event(_mapping(event.get("message")).get("usage"))
            if usage is not None:
                events.append(usage)
        elif event_type == "content_block_start":
            index = _integer(event.get("index"))
            block = dict(_mapping(event.get("content_block")))
            self._blocks[index] = block
            if block.get("type") == "text":
                message_event = message_delta_event(block.get("text"))
                if message_event is not None:
                    self._has_message_delta = True
                    events.append(message_event)
            elif block.get("type") == "tool_use":
                tool_id = str(block.get("id") or f"tool-{index}")
                self._started_tools.add(tool_id)
                initial_input = block.get("input")
                events.append(
                    tool_call_event(
                        "tool_call_started",
                        tool_call_id=tool_id,
                        name=block.get("name"),
                        arguments=None if initial_input == {} else initial_input,
                        status="running",
                    )
                )
        elif event_type == "content_block_delta":
            index = _integer(event.get("index"))
            delta = _mapping(event.get("delta"))
            if delta.get("type") == "text_delta":
                message_event = message_delta_event(delta.get("text"))
                if message_event is not None:
                    self._has_message_delta = True
                    events.append(message_event)
            elif delta.get("type") == "input_json_delta":
                block = self._blocks.get(index, {})
                tool_id = str(block.get("id") or f"tool-{index}")
                events.append(
                    tool_call_event(
                        "tool_call_delta",
                        tool_call_id=tool_id,
                        name=block.get("name"),
                        arguments=delta.get("partial_json"),
                        status="running",
                    )
                )
        elif event_type == "message_delta":
            usage = usage_event(event.get("usage"))
            if usage is not None:
                events.append(usage)
        elif event_type == "error":
            events.append(
                self._terminal_failure_event(
                    event.get("error") or event.get("message"),
                    fallback="Claude Code stream failed",
                )
            )
        return tuple(events)

    def _terminal_failure_event(
        self,
        value: Any,
        *,
        fallback: str,
    ) -> HarnessEvent:
        failure = stream_terminal_failure(value, fallback=fallback)
        if self.terminal_outcome is None:
            self.terminal_outcome = failure
        return HarnessEvent(
            type="stderr_delta",
            message="Claude Code reported an error.",
            payload={"delta": failure.error or fallback},
        )

    def _assistant_events(
        self,
        message: Mapping[str, Any],
    ) -> tuple[HarnessEvent, ...]:
        events: list[HarnessEvent] = []
        content = message.get("content")
        if isinstance(content, list):
            fallback_text: list[str] = []
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    fallback_text.append(part["text"])
                elif part.get("type") == "tool_use":
                    tool_id = str(part.get("id") or "tool-call")
                    if tool_id not in self._started_tools:
                        self._started_tools.add(tool_id)
                        events.append(
                            tool_call_event(
                                "tool_call_started",
                                tool_call_id=tool_id,
                                name=part.get("name"),
                                arguments=part.get("input"),
                                status="running",
                            )
                        )
            if fallback_text and not self._has_message_delta:
                message_event = message_delta_event("".join(fallback_text))
                if message_event is not None:
                    self._has_message_delta = True
                    events.append(message_event)
        usage = usage_event(message.get("usage"))
        if usage is not None:
            events.append(usage)
        return tuple(events)

    def _tool_result_events(
        self,
        message: Mapping[str, Any],
    ) -> tuple[HarnessEvent, ...]:
        content = message.get("content")
        if not isinstance(content, list):
            return ()
        events: list[HarnessEvent] = []
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "tool_result":
                continue
            events.append(
                tool_call_event(
                    "tool_call_finished",
                    tool_call_id=part.get("tool_use_id"),
                    result=part.get("content"),
                    status="error" if part.get("is_error") else "success",
                )
            )
        return tuple(events)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _claude_result_failed(payload: Mapping[str, Any]) -> bool:
    is_error = payload.get("is_error")
    flagged = is_error is True or (
        isinstance(is_error, str) and is_error.strip().lower() == "true"
    )
    return (
        flagged
        or _has_error_value(payload.get("errors"))
        or _has_error_value(payload.get("error"))
    )


def _has_error_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, list, tuple, set)):
        return bool(value)
    return value is not None and value is not False
