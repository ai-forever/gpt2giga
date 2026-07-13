"""Codex CLI harness for running Codex through local gpt2giga."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

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
    workspace_error,
)
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    attachment_warning_events,
    cli_args_from_attachments,
    prompt_with_attachments,
)
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

MODE_TO_SANDBOX = {
    "plan": "read-only",
    "read": "read-only",
    "edit": "workspace-write",
}


class CodexCliHarness(BaseHarness):
    """Run Codex CLI in non-interactive mode against gpt2giga."""

    def __init__(
        self,
        *,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        self.executable_resolver = executable_resolver or ExecutableResolver.path_only()

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Codex CLI",
            kind="agent-cli",
            description="Run Codex CLI against local gpt2giga proxy",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
            supports_workspace=True,
            supports_attachments=True,
            accepted_attachment_kinds=("image", "text", "workspace_file"),
            attachment_transport=("cli_image_flag", "prompt_path_reference"),
            supports_native_sessions=True,
            supports_external_history=True,
            default_invocation_mode=HarnessInvocationMode.NATIVE,
            tags=("codex", "agent"),
        )

    def availability(self) -> Availability:
        resolution = self.executable_resolution()
        if resolution.error is not None:
            return Availability.error(resolution.error)
        if resolution.executable is None:
            return Availability.missing(
                "codex executable not found",
                (
                    "Install OpenAI Codex CLI on PATH or configure "
                    "executables.codex-cli in ~/.gpt2giga/harness/config.toml."
                ),
            )
        return Availability.available(
            f"codex executable found via {resolution.source}: {resolution.executable}"
        )

    def executable_resolution(self) -> ExecutableResolution:
        """Return the configured or PATH-discovered Codex executable."""
        return self.executable_resolver.resolve(self.spec().id, "codex")

    def build_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> tuple[str, ...]:
        """Build the Codex command without executing it."""
        resolution = self.executable_resolution()
        executable = resolution.executable or resolution.configured or "codex"
        sandbox = MODE_TO_SANDBOX.get(request.mode, MODE_TO_SANDBOX["plan"])
        model = request.model or context.default_model or "GigaChat"
        prompt = prompt_with_attachments(request)
        attachment_args = cli_args_from_attachments(request)
        prompt_separator = ("--",) if attachment_args and prompt else ()
        stream_args = ("--json",) if request.stream else ()
        return (
            executable,
            "--ask-for-approval",
            "on-request",
            "exec",
            "--sandbox",
            sandbox,
            "--ephemeral",
            *stream_args,
            "-m",
            model,
            *attachment_args,
            *prompt_separator,
            prompt,
        )

    def build_env(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        codex_home: str | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment for the external CLI."""
        extra = {
            "GPT2GIGA_API_KEY": context.api_key or "0",
            "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
            "GPT2GIGA_HARNESS_API_MODE": request.api_mode.value,
        }
        if codex_home is not None:
            extra["CODEX_HOME"] = codex_home
        return build_safe_env(
            context,
            extra=extra,
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
                        self.build_env(request, context, codex_home="<temp>")
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
        with tempfile.TemporaryDirectory(prefix="gpt2giga-codex-") as temp_dir:
            codex_home = str(Path(temp_dir) / ".codex")
            Path(codex_home).mkdir(parents=True, exist_ok=True)
            _write_codex_config(Path(codex_home), request, prepared_context)
            env = self.build_env(request, prepared_context, codex_home=codex_home)
            if request.stream:
                result = run_streaming_command(
                    label="Codex CLI",
                    command=command,
                    env=env,
                    cwd=request.workspace or None,
                    timeout_seconds=context.timeout_seconds,
                    request=request,
                    parse_payload=_CodexStreamParser(),
                )
            else:
                result = run_command(
                    label="Codex CLI",
                    command=command,
                    env=env,
                    cwd=request.workspace or None,
                    timeout_seconds=context.timeout_seconds,
                )
            return with_events(
                result,
                (*attachment_warning_events(request), *proxy_events),
            )


def _write_codex_config(
    codex_home: Path,
    request: HarnessRequest,
    context: HarnessContext,
) -> None:
    model = request.model or context.default_model or "GigaChat"
    base_url = context.api_base_url(request.api_mode)
    config = (
        f'model = "{_toml_escape(model)}"\n'
        'model_provider = "gpt2giga_harness"\n'
        'model_reasoning_effort = "none"\n\n'
        "[model_providers.gpt2giga_harness]\n"
        'name = "gpt2giga_harness"\n'
        f'base_url = "{_toml_escape(base_url)}"\n'
        'env_key = "GPT2GIGA_API_KEY"\n'
        'wire_api = "responses"\n'
        "supports_websockets = false\n"
    )
    write_startup_config("codex-cli", codex_home, config)


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class _CodexStreamParser:
    """Normalize Codex CLI JSONL events without repeating final message text."""

    def __init__(self) -> None:
        self._item_text: dict[str, str] = {}
        self.terminal_outcome: StreamTerminalOutcome | None = None

    def __call__(self, payload: Mapping[str, Any]) -> tuple[HarnessEvent, ...]:
        events: list[HarnessEvent] = []
        event_type = str(payload.get("type") or "")
        item = _mapping(payload.get("item"))
        item_type = str(item.get("type") or "")
        item_id = str(item.get("id") or payload.get("item_id") or item_type or "item")

        if item_type == "agent_message":
            message_event = self._message_event(payload, item, item_id)
            if message_event is not None:
                events.append(message_event)
        elif _is_codex_tool_item(item_type):
            tool_event = _codex_tool_event(event_type, item, item_id)
            if tool_event is not None:
                events.append(tool_event)

        normalized_usage = usage_event(payload.get("usage"))
        if normalized_usage is not None:
            events.append(normalized_usage)

        if event_type in {"error", "turn.failed", "item.failed"}:
            error = (
                payload.get("message")
                or payload.get("error")
                or item.get("error")
                or item.get("message")
            )
            failure = stream_terminal_failure(
                error,
                fallback={
                    "error": "Codex CLI reported an error",
                    "turn.failed": "Codex CLI turn failed",
                    "item.failed": "Codex CLI item failed",
                }[event_type],
            )
            if self.terminal_outcome is None:
                self.terminal_outcome = failure
            events.append(
                HarnessEvent(
                    type="stderr_delta",
                    message="Codex CLI reported an error.",
                    payload={"delta": failure.error or "Codex CLI failed"},
                )
            )
        return tuple(events)

    def _message_event(
        self,
        payload: Mapping[str, Any],
        item: Mapping[str, Any],
        item_id: str,
    ) -> HarnessEvent | None:
        explicit_delta = payload.get("delta")
        if isinstance(explicit_delta, str) and explicit_delta:
            previous = self._item_text.get(item_id, "")
            self._item_text[item_id] = previous + explicit_delta
            return message_delta_event(explicit_delta)

        text = item.get("text") or item.get("content")
        if not isinstance(text, str) or not text:
            return None
        previous = self._item_text.get(item_id, "")
        if text == previous:
            return None
        if previous and text.startswith(previous):
            delta = text[len(previous) :]
        elif previous:
            return None
        else:
            delta = text
        self._item_text[item_id] = text
        return message_delta_event(delta)


def _is_codex_tool_item(item_type: str) -> bool:
    return item_type in {
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "todo_list",
        "web_search",
        "dynamic_tool_call",
    } or item_type.endswith("_tool_call")


def _codex_tool_event(
    event_type: str,
    item: Mapping[str, Any],
    item_id: str,
) -> HarnessEvent | None:
    item_type = str(item.get("type") or "tool")
    name = _codex_tool_name(item_type, item)
    arguments = _codex_tool_arguments(item_type, item)
    status = item.get("status")
    if event_type == "item.started":
        return tool_call_event(
            "tool_call_started",
            tool_call_id=item_id,
            name=name,
            arguments=arguments,
            status=status or "running",
        )
    if event_type == "item.updated":
        if item_type == "todo_list":
            return tool_call_event(
                "tool_call_delta",
                tool_call_id=item_id,
                name=name,
                arguments=arguments,
                status=status or "running",
                arguments_are_complete=True,
            )
        arguments_delta = _first_present(item, "arguments_delta", "input_delta")
        result_delta = _first_present(item, "output_delta", "delta")
        if arguments_delta is None and result_delta is None and status is None:
            return None
        return tool_call_event(
            "tool_call_delta",
            tool_call_id=item_id,
            name=name,
            arguments=arguments_delta,
            result=result_delta,
            status=status,
        )
    if event_type in {"item.completed", "item.failed"}:
        result = _codex_tool_result(item, failed=event_type == "item.failed")
        return tool_call_event(
            "tool_call_finished",
            tool_call_id=item_id,
            name=name,
            arguments=arguments,
            result=result,
            status=status or ("failed" if event_type == "item.failed" else "completed"),
        )
    return None


def _codex_tool_result(item: Mapping[str, Any], *, failed: bool) -> Any:
    result = _first_present(
        item,
        "aggregated_output",
        "output",
        "result",
        "error",
        "stderr",
        "message",
    )
    if result not in (None, "", (), [], {}):
        return result
    if not failed and str(item.get("status") or "").lower() not in {
        "failed",
        "error",
    }:
        return result
    exit_code = item.get("exit_code")
    if exit_code is not None:
        return f"Command exited with code {exit_code} and produced no output."
    return "Codex marked this tool call as failed without an error message."


def _codex_tool_name(item_type: str, item: Mapping[str, Any]) -> str:
    explicit = item.get("name") or item.get("tool") or item.get("tool_name")
    if explicit:
        return str(explicit)
    if item_type == "command_execution":
        return "shell"
    if item_type == "todo_list":
        return "update_plan"
    return item_type or "tool"


def _codex_tool_arguments(item_type: str, item: Mapping[str, Any]) -> Any:
    if item_type == "todo_list":
        todo_items = item.get("items")
        if not isinstance(todo_items, list):
            return {"plan": []}
        first_incomplete = next(
            (
                index
                for index, todo in enumerate(todo_items)
                if isinstance(todo, Mapping) and not bool(todo.get("completed"))
            ),
            None,
        )
        plan = []
        for index, todo in enumerate(todo_items):
            if not isinstance(todo, Mapping):
                continue
            text = todo.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            status = (
                "completed"
                if bool(todo.get("completed"))
                else "in_progress"
                if index == first_incomplete
                else "pending"
            )
            plan.append({"step": text.strip(), "status": status})
        return {"plan": plan}
    return _first_present(
        item,
        "arguments",
        "input",
        "command",
        "query",
        "changes",
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if value.get(key) is not None:
            return value[key]
    return None
