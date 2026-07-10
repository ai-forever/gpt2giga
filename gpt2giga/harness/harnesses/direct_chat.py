"""Direct Chat Completions harness through the local gpt2giga proxy."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from gpt2giga.harness import proxy
from gpt2giga.harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    attachment_warning_events,
    request_render_plan,
)
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessChatMessage,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HarnessEventType,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    emit_event,
)
from gpt2giga.protocols.normalized import NormalizedStreamEvent, NormalizedToolCall
from gpt2giga.protocols.openai.stream_accumulator import (
    OpenAIChatCompletionStreamAccumulator,
    openai_usage_to_normalized_usage,
    stream_tool_call_to_normalized_tool_call,
)


DEFAULT_MODEL = "GigaChat"
MESSAGE_DELTA_FLUSH_CHARS = 64
MESSAGE_DELTA_FLUSH_SECONDS = 0.08


class DirectChatHarness(BaseHarness):
    """Call /v1 or /v2 Chat Completions on the local proxy."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="direct-chat",
            title="Direct Chat Completions",
            kind="built-in",
            description=("Direct OpenAI-style Chat Completions through gpt2giga"),
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_streaming=True,
            supports_attachments=True,
            accepted_attachment_kinds=("image", "text", "workspace_file"),
            attachment_transport=("openai_content_parts", "inline_text"),
            tags=("chat", "proxy"),
        )

    def availability(self) -> Availability:
        return Availability.available("built-in harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        model = request.model or context.default_model or DEFAULT_MODEL
        url = proxy.build_chat_completions_url(context.proxy_url, request.api_mode)
        payload = {
            "model": model,
            "messages": _payload_messages(request),
            "stream": bool(request.stream),
        }
        api_key = context.api_key or proxy.cached_sidecar_api_key(context.proxy_url)
        cli_command = (
            "giga",
            "chat",
            "--api-mode",
            request.api_mode.value,
            "--model",
            model,
            request.prompt,
        )
        curl_command = _curl_command(url, payload, bool(api_key))
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={
                    "url": url,
                    "payload": payload,
                    "curl_command": curl_command,
                    **attachment_raw_metadata(request),
                },
                events=attachment_warning_events(request),
                command=cli_command,
            )
        events = attachment_warning_events(request)
        if context.auto_start_proxy:
            startup = proxy.ensure_proxy_available(context, request.api_mode)
            api_key = startup.api_key or api_key
            curl_command = _curl_command(url, payload, bool(api_key))
            if not startup.ok:
                return HarnessResult(
                    ok=False,
                    text="",
                    raw={
                        "url": url,
                        "payload": payload,
                        "curl_command": curl_command,
                        **attachment_raw_metadata(request),
                        "proxy_start": {
                            "started": startup.started,
                            "detail": startup.detail,
                            "error": startup.error,
                        },
                    },
                    command=cli_command,
                    error=startup.error or "proxy is not reachable",
                )
            if startup.started:
                events = (
                    *events,
                    HarnessEvent(
                        type="proxy_sidecar",
                        message="Started local gpt2giga proxy sidecar.",
                        payload={
                            "proxy_url": context.proxy_url,
                            "pid": startup.pid,
                        },
                    ),
                )
        try:
            if request.stream:
                return self._run_stream(
                    request=request,
                    context=context,
                    url=url,
                    payload=payload,
                    api_key=api_key,
                    cli_command=cli_command,
                    curl_command=curl_command,
                    events=events,
                )
            data = proxy.request_json(
                "POST",
                url,
                payload=payload,
                api_key=api_key,
                timeout=context.timeout_seconds,
            )
        except proxy.ProxyRequestError as exc:
            return HarnessResult(
                ok=False,
                text="",
                raw={
                    "url": url,
                    "payload": payload,
                    "curl_command": curl_command,
                    **attachment_raw_metadata(request),
                },
                command=cli_command,
                events=events,
                error=str(exc),
            )
        events = list(events)
        usage_event = _usage_event(data.get("usage"))
        if usage_event is not None:
            _emit_or_collect(request, events, usage_event)
        return HarnessResult(
            ok=True,
            text=proxy.extract_text(data),
            raw={
                **proxy.safe_raw(data),
                "url": url,
                "curl_command": curl_command,
                **attachment_raw_metadata(request),
            },
            events=tuple(events),
            command=cli_command,
        )

    def _run_stream(
        self,
        *,
        request: HarnessRequest,
        context: HarnessContext,
        url: str,
        payload: dict[str, Any],
        api_key: str | None,
        cli_command: tuple[str, ...],
        curl_command: tuple[str, ...],
        events: tuple[HarnessEvent, ...],
    ) -> HarnessResult:
        pending_events: list[HarnessEvent] = []
        for event in events:
            _emit_or_collect(request, pending_events, event)
        accumulator = OpenAIChatCompletionStreamAccumulator()
        message_deltas = _MessageDeltaCoalescer(request, pending_events)
        chunk_count = 0
        last_payload: Mapping[str, Any] = {}
        try:
            for stream_payload in proxy.stream_sse_json(
                "POST",
                url,
                payload=payload,
                api_key=api_key,
                timeout=context.timeout_seconds,
                cancel_event=request.cancel_event,
                idle_callback=message_deltas.flush_if_due,
            ):
                chunk_count += 1
                last_payload = stream_payload
                for normalized_event in accumulator.observe_payload(stream_payload):
                    if normalized_event.type == "content_delta":
                        message_deltas.push(normalized_event)
                        continue
                    message_deltas.flush()
                    event = _normalized_harness_event(normalized_event)
                    if event is not None:
                        _emit_or_collect(request, pending_events, event)
        except proxy.ProxyRequestError as exc:
            message_deltas.flush()
            return HarnessResult(
                ok=False,
                text="",
                raw={
                    "url": url,
                    "payload": payload,
                    "curl_command": curl_command,
                    "stream": True,
                    "chunk_count": chunk_count,
                    **attachment_raw_metadata(request),
                },
                command=cli_command,
                events=tuple(pending_events),
                error=str(exc),
            )

        message_deltas.flush()
        response = accumulator.to_normalized_response()
        for index, raw_tool_call in sorted(accumulator.tool_calls.items()):
            tool_call = stream_tool_call_to_normalized_tool_call(raw_tool_call)
            tool_call.raw_extensions["index"] = index
            _emit_or_collect(
                request,
                pending_events,
                HarnessEvent(
                    type=HarnessEventType.TOOL_CALL_FINISHED.value,
                    message=f"Tool call {tool_call.name or tool_call.id or index} assembled.",
                    payload={
                        **_tool_call_payload(tool_call),
                        "status": "requested",
                        "source": "direct-chat",
                    },
                ),
            )
        error = response.error.message if response.error is not None else None
        return HarnessResult(
            ok=error is None,
            text="".join(accumulator.content_parts),
            raw={
                "url": url,
                "curl_command": curl_command,
                "stream": True,
                "chunk_count": chunk_count,
                "last_payload": proxy.safe_raw(dict(last_payload)),
                "response": response.to_json_dict(),
                **attachment_raw_metadata(request),
            },
            events=tuple(pending_events),
            command=cli_command,
            error=error,
        )


def _curl_command(
    url: str,
    payload: dict[str, object],
    include_auth: bool,
) -> tuple[str, ...]:
    command = ["curl", "-sS", url, "-H", "Content-Type: application/json"]
    if include_auth:
        command.extend(["-H", "Authorization: Bearer <redacted>"])
    command.extend(["-d", json.dumps(payload, ensure_ascii=False)])
    return tuple(command)


def _request_messages(request: HarnessRequest) -> tuple[HarnessChatMessage, ...]:
    if request.messages:
        return request.messages
    return (HarnessChatMessage(role="user", content=request.prompt),)


def _payload_messages(request: HarnessRequest) -> list[dict[str, Any]]:
    messages = [
        {"role": message.role, "content": message.content}
        for message in _request_messages(request)
    ]
    plan = request_render_plan(request)
    if not plan:
        return messages
    messages[-1]["content"] = _content_with_attachments(request, plan)
    return messages


def _content_with_attachments(
    request: HarnessRequest,
    plan: Mapping[str, Any],
) -> str | list[Mapping[str, Any]]:
    content_parts = [
        dict(part)
        for part in plan.get("content_parts", ())
        if isinstance(part, Mapping)
    ]
    prompt_prefix = str(plan.get("prompt_prefix") or "").strip()
    prompt_suffix = str(plan.get("prompt_suffix") or "").strip()
    if content_parts:
        merged_parts: list[Mapping[str, Any]] = []
        merged_text = False
        for part in content_parts:
            if part.get("type") == "text" and not merged_text:
                merged_parts.append(
                    {
                        **part,
                        "text": _join_text(
                            prompt_prefix,
                            str(part.get("text") or request.prompt),
                            prompt_suffix,
                        ),
                    }
                )
                merged_text = True
            else:
                merged_parts.append(part)
        if not merged_text and (prompt_prefix or prompt_suffix):
            merged_parts.insert(
                0,
                {
                    "type": "text",
                    "text": _join_text(prompt_prefix, request.prompt, prompt_suffix),
                },
            )
        return merged_parts
    return _join_text(prompt_prefix, request.prompt, prompt_suffix)


def _join_text(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _emit_or_collect(
    request: HarnessRequest,
    events: list[HarnessEvent],
    event: HarnessEvent,
) -> None:
    if not emit_event(request, event):
        events.append(event)


class _MessageDeltaCoalescer:
    """Batch tiny token deltas before hitting the persistent session event store."""

    def __init__(
        self,
        request: HarnessRequest,
        events: list[HarnessEvent],
    ) -> None:
        self._request = request
        self._events = events
        self._parts: list[str] = []
        self._character_count = 0
        self._started_at: float | None = None
        self._last_sequence: int | None = None

    def push(self, event: NormalizedStreamEvent) -> None:
        """Add one content delta and flush when the size/time budget is reached."""
        delta = event.content_delta
        if not delta:
            return
        now = time.monotonic()
        if (
            self._parts
            and self._started_at is not None
            and now - self._started_at >= MESSAGE_DELTA_FLUSH_SECONDS
        ):
            self.flush()
        if not self._parts:
            self._started_at = now
        self._parts.append(delta)
        self._character_count += len(delta)
        self._last_sequence = event.sequence
        if self._character_count >= MESSAGE_DELTA_FLUSH_CHARS:
            self.flush()

    def flush(self) -> None:
        """Publish the buffered text as one normalized message event."""
        if not self._parts:
            return
        payload: dict[str, Any] = {
            "delta": "".join(self._parts),
            "source": "direct-chat",
        }
        if self._last_sequence is not None:
            payload["sequence"] = self._last_sequence
        _emit_or_collect(
            self._request,
            self._events,
            HarnessEvent(
                type=HarnessEventType.MESSAGE_DELTA.value,
                message="Assistant message delta.",
                payload=payload,
            ),
        )
        self._parts.clear()
        self._character_count = 0
        self._started_at = None
        self._last_sequence = None

    def flush_if_due(self) -> None:
        """Publish pending text once its latency budget has elapsed."""
        if (
            self._parts
            and self._started_at is not None
            and time.monotonic() - self._started_at >= MESSAGE_DELTA_FLUSH_SECONDS
        ):
            self.flush()


def _normalized_harness_event(event: NormalizedStreamEvent) -> HarnessEvent | None:
    if event.type == "content_delta" and event.content_delta:
        return HarnessEvent(
            type=HarnessEventType.MESSAGE_DELTA.value,
            message="Assistant message delta.",
            payload={
                "delta": event.content_delta,
                "sequence": event.sequence,
                "source": "direct-chat",
            },
        )
    if event.type in {"tool_call_start", "tool_call_delta"}:
        tool_call = event.tool_call
        if tool_call is None:
            return None
        payload = {
            **_tool_call_payload(tool_call),
            "source": "direct-chat",
        }
        arguments_delta = tool_call.raw_extensions.get("arguments_delta")
        if arguments_delta is not None:
            payload["arguments_delta"] = arguments_delta
        return HarnessEvent(
            type=(
                HarnessEventType.TOOL_CALL_STARTED.value
                if event.type == "tool_call_start"
                else HarnessEventType.TOOL_CALL_DELTA.value
            ),
            message=(
                f"Tool call {tool_call.name or tool_call.id or 'tool'} started."
                if event.type == "tool_call_start"
                else f"Tool call {tool_call.name or tool_call.id or 'tool'} updated."
            ),
            payload=payload,
        )
    if event.type == "usage" and event.usage is not None:
        return HarnessEvent(
            type=HarnessEventType.USAGE.value,
            message="Token usage updated.",
            payload=_usage_payload(event.usage),
        )
    if event.type == "error" and event.error is not None:
        return HarnessEvent(
            type=HarnessEventType.ERROR.value,
            message=event.error.message or "Direct chat stream failed.",
            payload={
                "type": event.error.type,
                "code": event.error.code,
                "source": "direct-chat",
            },
        )
    return None


def _usage_event(value: Any) -> HarnessEvent | None:
    usage = openai_usage_to_normalized_usage(value)
    if usage is None:
        return None
    return HarnessEvent(
        type=HarnessEventType.USAGE.value,
        message="Token usage updated.",
        payload=_usage_payload(usage),
    )


def _usage_payload(usage: Any) -> dict[str, Any]:
    payload = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "source": "direct-chat",
    }
    raw = dict(usage.raw_extensions)
    prompt_details = raw.get("prompt_tokens_details")
    completion_details = raw.get("completion_tokens_details")
    if isinstance(prompt_details, Mapping):
        payload["cached_input_tokens"] = prompt_details.get("cached_tokens")
    if isinstance(completion_details, Mapping):
        payload["reasoning_output_tokens"] = completion_details.get("reasoning_tokens")
    for key in ("cached_input_tokens", "reasoning_output_tokens"):
        if raw.get(key) is not None:
            payload[key] = raw[key]
    return {key: item for key, item in payload.items() if item is not None}


def _tool_call_payload(tool_call: NormalizedToolCall) -> dict[str, Any]:
    index = tool_call.raw_extensions.get("index")
    tool_call_id = tool_call.id or (f"tool_{index}" if index is not None else None)
    return {
        key: value
        for key, value in {
            "tool_call_id": tool_call_id,
            "name": tool_call.name,
            "type": tool_call.type,
            "arguments": tool_call.arguments,
        }.items()
        if value is not None
    }
