"""Anthropic Messages observability helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.sinks.observability.factory import emit_observability_event
from gpt2giga.sinks.observability.llm import (
    CHAT_COMPLETION_SPAN_NAME,
    OPENINFERENCE_SPAN_KIND,
    build_llm_chat_completion_attributes,
    build_tool_call_span_events,
)


async def emit_anthropic_message_observability(
    state: Any,
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
    *,
    context: Any,
    events: list[dict[str, Any]] | None = None,
) -> None:
    """Emit one OpenInference-style span for an Anthropic Messages exchange."""
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        return
    try:
        protocol_adapter = getattr(state, "openai_protocol_adapter", None)
        if protocol_adapter is None:
            return
        normalized_request = await protocol_adapter.to_normalized(
            request_payload,
            context=context,
        )
        normalized_request.protocol = "anthropic"
        normalized_response = anthropic_message_to_normalized_response(response_payload)
    except Exception as exc:
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.warning(
                "Anthropic message observability normalization failed: {}", exc
            )
        return

    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    span_events = list(events or [])
    span_events.extend(
        build_tool_call_span_events(normalized_response, settings=settings)
    )
    await emit_observability_event(
        sink,
        CHAT_COMPLETION_SPAN_NAME,
        build_llm_chat_completion_attributes(
            normalized_request,
            normalized_response,
            settings=settings,
        ),
        context=context,
        events=span_events or None,
        logger=getattr(state, "logger", None),
    )
    if context is not None:
        context.llm_observability_emitted = True


async def observe_anthropic_message_stream(
    state: Any,
    body_iterator: AsyncIterator[str],
    *,
    request_payload: Mapping[str, Any],
    context: Any,
) -> AsyncIterator[str]:
    """Observe Anthropic SSE chunks and emit one final LLM span."""
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        async for chunk in body_iterator:
            yield chunk
        return

    observer = AnthropicMessageStreamObserver()
    async for chunk in body_iterator:
        observer.observe_chunk(chunk)
        yield chunk

    if not observer.has_observed_payload:
        return
    await emit_anthropic_message_observability(
        state,
        request_payload,
        observer.to_anthropic_message(),
        context=context,
        events=observer.events,
    )


def anthropic_message_to_normalized_response(
    payload: Mapping[str, Any],
) -> NormalizedResponse:
    """Convert an Anthropic Messages response to a normalized response."""
    usage = payload.get("usage")
    return NormalizedResponse(
        id=_string_or_none(payload.get("id")),
        model=_string_or_none(payload.get("model")),
        provider="gigachat",
        choices=[
            NormalizedChoice(
                index=0,
                message=_anthropic_content_to_normalized_message(
                    payload.get("content")
                ),
                finish_reason=_anthropic_stop_reason_to_finish_reason(
                    _string_or_none(payload.get("stop_reason"))
                ),
            )
        ],
        usage=_anthropic_usage_to_normalized_usage(usage),
        error=_anthropic_error_to_normalized_error(payload.get("error")),
    )


def _anthropic_content_to_normalized_message(content: Any) -> NormalizedMessage:
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    for block in content or []:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text", "")))
        elif block_type == "thinking":
            reasoning_parts.append(str(block.get("thinking", "")))
        elif block_type == "tool_use":
            tool_calls.append(
                NormalizedToolCall(
                    id=_string_or_none(block.get("id")),
                    name=_string_or_none(block.get("name")),
                    arguments=block.get("input"),
                )
            )
    message = NormalizedMessage(
        role="assistant",
        content="\n".join(part for part in text_parts if part),
        tool_calls=tool_calls,
    )
    if reasoning_parts:
        message.raw_extensions["reasoning_content"] = "\n".join(
            part for part in reasoning_parts if part
        )
    return message


def _anthropic_usage_to_normalized_usage(value: Any) -> NormalizedUsage | None:
    if not isinstance(value, Mapping):
        return None
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    total_tokens = None
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _anthropic_error_to_normalized_error(value: Any) -> NormalizedError | None:
    if not isinstance(value, Mapping):
        return None
    return NormalizedError(
        type=_string_or_none(value.get("type")) or "api_error",
        message=_string_or_none(value.get("message")) or "",
        code=value.get("code"),
    )


def _anthropic_stop_reason_to_finish_reason(stop_reason: str | None) -> str | None:
    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "stop_sequence": "stop",
    }
    if stop_reason is None:
        return None
    return mapping.get(stop_reason, stop_reason)


def _iter_anthropic_sse_payloads(chunk: Any) -> list[Mapping[str, Any]]:
    if isinstance(chunk, bytes):
        text = chunk.decode("utf-8", errors="replace")
    else:
        text = str(chunk)
    payloads: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data:
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            payloads.append(payload)
    return payloads


class AnthropicMessageStreamObserver:
    """Collect enough Anthropic stream data for one final LLM span."""

    def __init__(self) -> None:
        self.has_observed_payload = False
        self.response_id: str | None = None
        self.model: str | None = None
        self.stop_reason: str | None = None
        self.output_tokens: int | None = None
        self.content_blocks: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self._saw_first_token = False

    def observe_chunk(self, chunk: Any) -> None:
        """Observe one Anthropic SSE chunk."""
        for payload in _iter_anthropic_sse_payloads(chunk):
            self.observe_payload(payload)

    def observe_payload(self, payload: Mapping[str, Any]) -> None:
        """Observe one parsed Anthropic SSE payload."""
        self.has_observed_payload = True
        event_type = _string_or_none(payload.get("type"))
        if event_type == "message_start":
            message = payload.get("message")
            if isinstance(message, Mapping):
                self.response_id = _string_or_none(message.get("id"))
                self.model = _string_or_none(message.get("model"))
            self.events.append(
                _stream_event("stream.start", "message_start", self.model)
            )
        elif event_type == "content_block_start":
            self._observe_content_block_start(payload)
        elif event_type == "content_block_delta":
            self._observe_content_block_delta(payload)
        elif event_type == "message_delta":
            self._observe_message_delta(payload)
        elif event_type == "message_stop":
            self.events.append(
                _stream_event("stream.completed", "message_stop", self.model)
            )
        elif event_type == "error":
            self._observe_error(payload)

    def to_anthropic_message(self) -> dict[str, Any]:
        """Return an Anthropic Messages response reconstructed from stream events."""
        return {
            "id": self.response_id,
            "type": "message",
            "role": "assistant",
            "content": [block for _, block in sorted(self.content_blocks.items())],
            "model": self.model,
            "stop_reason": self.stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": self.output_tokens or 0,
            },
        }

    def _observe_content_block_start(self, payload: Mapping[str, Any]) -> None:
        index = _int_or_zero(payload.get("index"))
        block = payload.get("content_block")
        if not isinstance(block, Mapping):
            return
        block_type = block.get("type")
        if block_type == "text":
            self.content_blocks[index] = {"type": "text", "text": ""}
        elif block_type == "thinking":
            self.content_blocks[index] = {"type": "thinking", "thinking": ""}
        elif block_type == "tool_use":
            self.content_blocks[index] = {
                "type": "tool_use",
                "id": block.get("id"),
                "name": block.get("name"),
                "input": {},
            }

    def _observe_content_block_delta(self, payload: Mapping[str, Any]) -> None:
        index = _int_or_zero(payload.get("index"))
        delta = payload.get("delta")
        if not isinstance(delta, Mapping):
            return
        block = self.content_blocks.setdefault(index, {"type": "text", "text": ""})
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            block["text"] = str(block.get("text", "")) + str(delta.get("text", ""))
            self._add_first_token_event("content_delta")
        elif delta_type == "thinking_delta":
            block["thinking"] = str(block.get("thinking", "")) + str(
                delta.get("thinking", "")
            )
            self._add_first_token_event("reasoning_delta")
        elif delta_type == "input_json_delta":
            block["_partial_json"] = str(block.get("_partial_json", "")) + str(
                delta.get("partial_json", "")
            )
            block["input"] = _json_object_or_empty(block.get("_partial_json"))

    def _observe_message_delta(self, payload: Mapping[str, Any]) -> None:
        delta = payload.get("delta")
        if isinstance(delta, Mapping):
            self.stop_reason = _string_or_none(delta.get("stop_reason"))
        usage = payload.get("usage")
        if isinstance(usage, Mapping) and isinstance(usage.get("output_tokens"), int):
            self.output_tokens = usage["output_tokens"]

    def _observe_error(self, payload: Mapping[str, Any]) -> None:
        error = payload.get("error")
        attrs = {
            "error_type": None,
            "error_message": None,
        }
        if isinstance(error, Mapping):
            attrs["error_type"] = error.get("type")
            attrs["error_message"] = error.get("message")
        self.events.append(_stream_event("stream.error", "error", self.model, attrs))

    def _add_first_token_event(self, stream_event_type: str) -> None:
        if self._saw_first_token:
            return
        self._saw_first_token = True
        self.events.append(
            _stream_event("stream.first_token", stream_event_type, self.model)
        )


def _stream_event(
    name: str,
    event_type: str,
    model: str | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    attributes = {
        "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
        "stream.event.type": event_type,
        "llm.model_name": model,
        "llm.provider": "gigachat",
    }
    if extra:
        attributes.update(extra)
    return {"name": name, "attributes": attributes}


def _json_object_or_empty(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
