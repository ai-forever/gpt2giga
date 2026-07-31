"""GigaChat stream adapters for normalized streaming."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from gpt2giga.protocols.normalized import (
    NormalizedError,
    NormalizedMessage,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)


class GigaChatNormalizedStreamMapper:
    """Convert processed GigaChat stream chunks to normalized stream events."""

    def __init__(
        self,
        *,
        response_processor: Any,
        requested_model: str,
        response_id: str,
        request_data: dict[str, Any] | None = None,
    ) -> None:
        self.response_processor = response_processor
        self.requested_model = requested_model
        self.response_id = response_id
        self.request_data = request_data
        self._sequence = 0
        self._started_tool_calls: set[str] = set()

    def message_start(self) -> NormalizedStreamEvent:
        """Build the canonical stream start event."""
        return self._event(
            "message_start",
            delta=NormalizedMessage(role="assistant", content=""),
        )

    def chunk_to_event(self, chunk: Any) -> NormalizedStreamEvent:
        """Build one normalized event from one GigaChat-compatible chunk."""
        processed = self.response_processor.process_stream_chunk(
            chunk,
            self.requested_model,
            self.response_id,
            request_data=self.request_data,
        )
        return self._processed_chunk_to_event(processed)

    def flush_reasoning_events(self) -> list[NormalizedStreamEvent]:
        """Flush buffered reasoning parser state into normalized events."""
        flush_stream_reasoning = getattr(
            self.response_processor,
            "flush_stream_reasoning",
            None,
        )
        if flush_stream_reasoning is None:
            return []
        flushed = flush_stream_reasoning(self.response_id, family="chat")
        if not flushed.content and not flushed.reasoning_content:
            return []

        delta: dict[str, Any] = {"content": flushed.content}
        if flushed.reasoning_content:
            delta["reasoning_content"] = flushed.reasoning_content
        processed = {
            "id": f"chatcmpl-{self.response_id}",
            "object": "chat.completion.chunk",
            "created": int(datetime.now(timezone.utc).timestamp()),
            "model": self.requested_model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": None,
                    "logprobs": None,
                }
            ],
            "usage": None,
            "system_fingerprint": f"fp_{self.response_id}",
        }
        return [self._processed_chunk_to_event(processed)]

    def error_event(
        self,
        *,
        message: str,
        error_type: str,
        code: str,
        raw_message: str | None = None,
    ) -> NormalizedStreamEvent:
        """Build a canonical stream error event."""
        return self._event(
            "error",
            error=NormalizedError(
                type=error_type,
                message=raw_message or message,
                code=code,
            ),
        )

    def _processed_chunk_to_event(
        self,
        processed: Mapping[str, Any],
    ) -> NormalizedStreamEvent:
        choice = _first_choice(processed)
        delta = choice.get("delta") if isinstance(choice, Mapping) else {}
        delta = delta if isinstance(delta, Mapping) else {}
        finish_reason = (
            choice.get("finish_reason") if isinstance(choice, Mapping) else None
        )
        usage = _usage_to_normalized(processed.get("usage"))
        tool_call = _first_tool_call(delta)
        content_delta = (
            delta.get("content") if isinstance(delta.get("content"), str) else None
        )
        reasoning_delta = (
            delta.get("reasoning_content")
            if isinstance(delta.get("reasoning_content"), str)
            else None
        )

        event_type = "heartbeat"
        if tool_call is not None:
            tool_key = (
                tool_call.id
                or tool_call.name
                or str(tool_call.raw_extensions.get("index", 0))
            )
            event_type = (
                "tool_call_delta"
                if tool_key in self._started_tool_calls
                else "tool_call_start"
            )
            self._started_tool_calls.add(tool_key)
        elif finish_reason is not None:
            event_type = "message_end"
        elif content_delta:
            event_type = "content_delta"
        elif reasoning_delta:
            event_type = "reasoning_delta"
        elif usage is not None:
            event_type = "usage"

        return self._event(
            event_type,
            content_delta=content_delta,
            reasoning_delta=reasoning_delta,
            tool_call=tool_call,
            usage=usage,
            finish_reason=finish_reason,
            raw_extensions={"openai_chunk": dict(processed)},
            metadata=_metadata(processed),
        )

    def _event(self, event_type: str, **kwargs: Any) -> NormalizedStreamEvent:
        event = NormalizedStreamEvent(
            type=event_type,
            id=self.response_id,
            model=self.requested_model,
            sequence=self._sequence,
            **kwargs,
        )
        self._sequence += 1
        return event


def _first_choice(data: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0]
    return choice if isinstance(choice, Mapping) else {}


def _first_tool_call(delta: Mapping[str, Any]) -> NormalizedToolCall | None:
    tool_calls = delta.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    tool_call = tool_calls[0]
    if not isinstance(tool_call, Mapping):
        return None
    function = tool_call.get("function")
    function = function if isinstance(function, Mapping) else {}
    return NormalizedToolCall(
        id=tool_call.get("id") if isinstance(tool_call.get("id"), str) else None,
        type=str(tool_call.get("type") or "function"),
        name=function.get("name") if isinstance(function.get("name"), str) else None,
        arguments=function.get("arguments"),
        raw_extensions={
            key: value
            for key, value in tool_call.items()
            if key not in {"id", "type", "function"}
        },
    )


def _usage_to_normalized(value: Any) -> NormalizedUsage | None:
    if not isinstance(value, Mapping):
        return None
    return NormalizedUsage(
        input_tokens=value.get("prompt_tokens", value.get("input_tokens")),
        output_tokens=value.get("completion_tokens", value.get("output_tokens")),
        total_tokens=value.get("total_tokens"),
        raw_extensions={
            key: item
            for key, item in value.items()
            if key
            not in {
                "prompt_tokens",
                "completion_tokens",
                "input_tokens",
                "output_tokens",
                "total_tokens",
            }
        },
    )


def _metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}
