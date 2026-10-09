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
        self._tool_indexes: dict[str, int] = {}
        self._emitted_tool_fields: dict[str, set[str]] = {}
        self._emitted_roles: set[int] = set()
        self._pending_tool_chunks: list[dict[str, Any]] = []
        self._tool_state_id: str | None = None

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

    def chunk_to_events(self, chunk: Any) -> list[NormalizedStreamEvent]:
        """Preserve every complete parallel tool call from one SDK chunk."""
        processed = self.response_processor.process_stream_chunk(
            chunk,
            self.requested_model,
            self.response_id,
            request_data=self.request_data,
        )
        state_id = _tool_state_from_chunk(processed)
        if state_id:
            self._tool_state_id = state_id
        delta = _first_choice(processed).get("delta") or {}
        if self._pending_tool_chunks or (
            delta.get("tool_calls") and not self._tool_state_id
        ):
            self._pending_tool_chunks.append(processed)
            return self.flush_tool_events() if self._tool_state_id else []
        return self._processed_chunk_to_events(processed)

    def flush_tool_events(self) -> list[NormalizedStreamEvent]:
        """Release tool chunks after state arrives or the provider stream ends."""
        pending, self._pending_tool_chunks = self._pending_tool_chunks, []
        return [
            event
            for chunk in pending
            for event in self._processed_chunk_to_events(chunk)
        ]

    def _processed_chunk_to_events(
        self, processed: Mapping[str, Any]
    ) -> list[NormalizedStreamEvent]:
        choice = _first_choice(processed)
        delta = choice.get("delta") or {}
        calls = delta.get("tool_calls") or []
        if calls and self._tool_state_id:
            calls = [{"tools_state_id": self._tool_state_id, **call} for call in calls]
            delta = {**delta, "tool_calls": calls}
            choice = {**choice, "delta": delta}
            processed = {**processed, "choices": [choice]}
        if len(calls) <= 1:
            return [self._processed_chunk_to_event(processed)]
        events = []
        for index, call in enumerate(calls):
            split_delta = {**delta, "tool_calls": [call]}
            if index:
                split_delta.pop("content", None)
                split_delta.pop("reasoning_content", None)
            split_choice = {**choice, "delta": split_delta}
            if index < len(calls) - 1:
                split_choice["finish_reason"] = None
            split_chunk = {**processed, "choices": [split_choice]}
            events.append(self._processed_chunk_to_event(split_chunk))
        return events

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
            "system_fingerprint": None,
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
        tool_key = None
        if tool_call is not None:
            tool_key = (
                tool_call.id
                or tool_call.name
                or str(tool_call.raw_extensions.get("index", 0))
            )
            tool_call.raw_extensions["index"] = self._tool_indexes.setdefault(
                tool_key, len(self._tool_indexes)
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
            raw_extensions={
                "openai_chunk": (
                    dict(processed)
                    if event_type == "heartbeat"
                    else self._openai_chunk(processed, tool_key)
                )
            },
            metadata=_metadata(processed),
        )

    def _openai_chunk(
        self, processed: Mapping[str, Any], tool_key: str | None
    ) -> dict[str, Any]:
        """Emit opaque tool identifiers once for SDK string accumulation."""
        choice = _first_choice(processed)
        if not choice:
            return dict(processed)
        delta = dict(choice.get("delta") or {})
        choice_index = choice.get("index", 0)
        if choice_index in self._emitted_roles:
            delta.pop("role", None)
        elif delta.get("role"):
            self._emitted_roles.add(choice_index)
        if tool_key is not None:
            calls = list(delta["tool_calls"])
            call = dict(calls[0])
            call["index"] = self._tool_indexes[tool_key]
            function = dict(call.get("function") or {})
            emitted = self._emitted_tool_fields.setdefault(tool_key, set())
            for field, container, key in (
                ("id", call, "id"),
                ("tools_state_id", call, "tools_state_id"),
                ("name", function, "name"),
            ):
                if field in emitted:
                    container.pop(key, None)
                elif container.get(key):
                    emitted.add(field)
            call["function"] = function
            calls[0] = call
            delta["tool_calls"] = calls
        choices = list(processed.get("choices") or [])
        choices[0] = {**choice, "delta": delta}
        return {**processed, "choices": choices}

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


def _tool_state_from_chunk(data: Mapping[str, Any]) -> str | None:
    delta = _first_choice(data).get("delta") or {}
    for call in delta.get("tool_calls") or []:
        state_id = call.get("tools_state_id")
        if isinstance(state_id, str) and state_id:
            return state_id
    state_id = _metadata(data).get("gigachat_tool_state_id")
    return state_id if isinstance(state_id, str) and state_id else None
