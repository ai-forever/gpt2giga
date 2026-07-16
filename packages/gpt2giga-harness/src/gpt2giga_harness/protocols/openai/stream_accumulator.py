"""Accumulate OpenAI Chat Completions SSE payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from gpt2giga.protocols.normalized.models import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)


class OpenAIChatCompletionStreamAccumulator:
    """Collect an OpenAI-compatible SSE stream and expose normalized events."""

    def __init__(self) -> None:
        self.has_observed_payload = False
        self.response_id: str | None = None
        self.model: str | None = None
        self.finish_reason: str | None = None
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.usage: NormalizedUsage | None = None
        self.error: NormalizedError | None = None
        self.tool_calls: dict[int, dict[str, Any]] = {}
        self._sequence = 0

    def observe_chunk(self, chunk: Any) -> tuple[NormalizedStreamEvent, ...]:
        """Observe one raw SSE chunk and return normalized incremental events."""
        events: list[NormalizedStreamEvent] = []
        for payload in iter_sse_json_payloads(chunk):
            events.extend(self.observe_payload(payload))
        return tuple(events)

    def observe_payload(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[NormalizedStreamEvent, ...]:
        """Observe one decoded JSON payload and return normalized events."""
        self.has_observed_payload = True
        self.response_id = string_or_none(payload.get("id")) or self.response_id
        self.model = string_or_none(payload.get("model")) or self.model
        events: list[NormalizedStreamEvent] = []

        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            self.metadata.update(dict(metadata))

        error = payload.get("error")
        if isinstance(error, Mapping):
            self.error = NormalizedError(
                type=string_or_none(error.get("type")) or "stream_error",
                message=string_or_none(error.get("message")) or "",
                code=error.get("code"),
                param=string_or_none(error.get("param")),
            )
            events.append(self._event("error", error=self.error))

        for choice_position, choice in enumerate(payload.get("choices") or []):
            if isinstance(choice, Mapping):
                events.extend(self._observe_choice(choice_position, choice))

        if not payload.get("choices"):
            events.extend(self._observe_gigachat_messages(payload))

        usage = openai_usage_to_normalized_usage(payload.get("usage"))
        if usage is not None:
            self.usage = usage
            events.append(self._event("usage", usage=usage))
        return tuple(events)

    def _observe_gigachat_messages(
        self,
        payload: Mapping[str, Any],
    ) -> list[NormalizedStreamEvent]:
        """Observe GigaChat v2 Responses-shaped message deltas."""
        events: list[NormalizedStreamEvent] = []
        for message in payload.get("messages") or ():
            if not isinstance(message, Mapping):
                continue
            role = string_or_none(message.get("role"))
            for part in message.get("content") or ():
                if not isinstance(part, Mapping):
                    continue
                text = part.get("text")
                if not isinstance(text, str) or not text:
                    continue
                if role == "reasoning":
                    self.reasoning_parts.append(text)
                    events.append(self._event("reasoning_delta", reasoning_delta=text))
                elif role == "assistant":
                    self.content_parts.append(text)
                    events.append(self._event("content_delta", content_delta=text))
        finish_reason = string_or_none(payload.get("finish_reason"))
        if finish_reason is not None:
            self.finish_reason = finish_reason
            events.append(self._event("message_end", finish_reason=finish_reason))
        return events

    def to_normalized_response(self) -> NormalizedResponse:
        """Return the accumulated response in the shared normalized shape."""
        message = NormalizedMessage(
            role="assistant",
            content="".join(self.content_parts),
            tool_calls=[
                stream_tool_call_to_normalized_tool_call(tool_call)
                for _, tool_call in sorted(self.tool_calls.items())
            ],
        )
        if self.reasoning_parts:
            message.raw_extensions["reasoning_content"] = "".join(self.reasoning_parts)
        return NormalizedResponse(
            id=self.response_id,
            model=self.model,
            provider="gigachat",
            choices=[
                NormalizedChoice(
                    index=0,
                    message=message,
                    finish_reason=self.finish_reason,
                )
            ],
            usage=self.usage,
            error=self.error,
            metadata=self.metadata,
        )

    def _observe_choice(
        self,
        choice_position: int,
        choice: Mapping[str, Any],
    ) -> list[NormalizedStreamEvent]:
        events: list[NormalizedStreamEvent] = []
        choice_index = choice.get("index", choice_position)
        if not isinstance(choice_index, int):
            choice_index = choice_position
        delta = choice.get("delta")
        if isinstance(delta, Mapping):
            content = delta.get("content")
            if isinstance(content, str) and content:
                self.content_parts.append(content)
                events.append(
                    self._event(
                        "content_delta",
                        choice_index=choice_index,
                        content_delta=content,
                    )
                )

            reasoning_content = delta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                self.reasoning_parts.append(reasoning_content)
                events.append(
                    self._event(
                        "reasoning_delta",
                        choice_index=choice_index,
                        reasoning_delta=reasoning_content,
                    )
                )

            for raw_tool_call in delta.get("tool_calls") or []:
                if not isinstance(raw_tool_call, Mapping):
                    continue
                tool_index, started = self._observe_tool_call(raw_tool_call)
                tool_call = stream_tool_call_to_normalized_tool_call(
                    self.tool_calls[tool_index]
                )
                tool_call.raw_extensions["index"] = tool_index
                function = raw_tool_call.get("function")
                if (
                    isinstance(function, Mapping)
                    and function.get("arguments") is not None
                ):
                    tool_call.raw_extensions["arguments_delta"] = function.get(
                        "arguments"
                    )
                events.append(
                    self._event(
                        "tool_call_delta" if started else "tool_call_start",
                        choice_index=choice_index,
                        tool_call=tool_call,
                    )
                )

        finish_reason = string_or_none(choice.get("finish_reason"))
        if finish_reason is not None:
            self.finish_reason = finish_reason
            events.append(
                self._event(
                    "message_end",
                    choice_index=choice_index,
                    finish_reason=finish_reason,
                )
            )
        return events

    def _observe_tool_call(self, raw_tool_call: Mapping[str, Any]) -> tuple[int, bool]:
        index = raw_tool_call.get("index", len(self.tool_calls))
        if not isinstance(index, int):
            index = len(self.tool_calls)
        raw_id = string_or_none(raw_tool_call.get("id"))
        existing = self.tool_calls.get(index)
        existing_id = (
            string_or_none(existing.get("id")) if existing is not None else None
        )
        if raw_id is not None and existing_id is not None and raw_id != existing_id:
            index = max(self.tool_calls, default=-1) + 1
        started = index in self.tool_calls
        tool_call = self.tool_calls.setdefault(
            index,
            {"function": {"arguments": ""}},
        )
        if raw_tool_call.get("id") is not None:
            tool_call["id"] = raw_tool_call.get("id")
        if raw_tool_call.get("type") is not None:
            tool_call["type"] = raw_tool_call.get("type")
        function = raw_tool_call.get("function")
        if isinstance(function, Mapping):
            target_function = tool_call.setdefault("function", {"arguments": ""})
            if function.get("name") is not None:
                target_function["name"] = function.get("name")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                target_function["arguments"] = (
                    target_function.get("arguments", "") + arguments
                )
        return index, started

    def _event(self, event_type: str, **kwargs: Any) -> NormalizedStreamEvent:
        event = NormalizedStreamEvent(
            type=event_type,
            id=self.response_id,
            model=self.model,
            sequence=self._sequence,
            metadata=dict(self.metadata),
            **kwargs,
        )
        self._sequence += 1
        return event


def iter_sse_json_payloads(chunk: Any) -> list[Mapping[str, Any]]:
    """Decode JSON payloads from one or more OpenAI-compatible SSE frames."""
    if isinstance(chunk, bytes):
        text = chunk.decode("utf-8", errors="replace")
    else:
        text = str(chunk)
    payloads: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            payloads.append(payload)
    return payloads


def stream_tool_call_to_normalized_tool_call(
    value: Mapping[str, Any],
) -> NormalizedToolCall:
    """Convert one accumulated OpenAI tool call to the normalized shape."""
    function = value.get("function")
    function = function if isinstance(function, Mapping) else {}
    return NormalizedToolCall(
        id=string_or_none(value.get("id")),
        type=string_or_none(value.get("type")) or "function",
        name=string_or_none(function.get("name")),
        arguments=function.get("arguments"),
    )


def openai_usage_to_normalized_usage(value: Any) -> NormalizedUsage | None:
    """Normalize OpenAI or GigaChat token usage field names."""
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


def string_or_none(value: Any) -> str | None:
    """Return a string value or ``None``."""
    if value is None:
        return None
    return str(value)
