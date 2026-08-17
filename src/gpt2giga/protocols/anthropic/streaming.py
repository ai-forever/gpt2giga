"""Project normalized stream events to Anthropic Messages SSE."""

from __future__ import annotations

import json
from typing import Any

from gpt2giga.protocols.normalized import NormalizedStreamEvent, NormalizedToolCall


class AnthropicStreamProjector:
    """Statefully render normalized stream events in Anthropic SSE order."""

    def __init__(
        self,
        *,
        requested_model: str,
        response_id: str,
    ) -> None:
        self.requested_model = requested_model
        self.response_id = response_id
        self._block_index = 0
        self._block_type: str | None = None
        self._input_tokens = 0
        self._output_tokens = 0

    def project(self, event: NormalizedStreamEvent) -> list[str]:
        """Render zero or more Anthropic SSE frames for one normalized event."""
        if event.usage is not None and event.usage.input_tokens is not None:
            self._input_tokens = int(event.usage.input_tokens)
        if event.usage is not None and event.usage.output_tokens is not None:
            self._output_tokens = int(event.usage.output_tokens)
        if event.type == "message_start":
            return [
                _sse(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": _message_id(event.id or self.response_id),
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": self.requested_model,
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    },
                ),
                _sse("ping", {"type": "ping"}),
            ]
        if event.type == "content_delta":
            return self._text_delta(event.content_delta or "")
        if event.type == "reasoning_delta":
            return self._thinking_delta(event.reasoning_delta or "")
        if event.type == "tool_call_start":
            return self._tool_start(event.tool_call)
        if event.type == "tool_call_delta":
            return self._tool_delta(event.tool_call)
        if event.type == "message_end":
            return self._message_end(event)
        if event.type == "error":
            error = event.error
            return [
                _sse(
                    "error",
                    {
                        "type": "error",
                        "error": {
                            "type": error.type if error else "api_error",
                            "message": (
                                error.message if error else "Stream interrupted"
                            ),
                            **(
                                {"code": error.code}
                                if error is not None and error.code is not None
                                else {}
                            ),
                        },
                    },
                )
            ]
        if event.type == "cancelled":
            return [
                _sse(
                    "error",
                    {
                        "type": "error",
                        "error": {
                            "type": "request_cancelled",
                            "message": "Request cancelled",
                        },
                    },
                )
            ]
        return []

    def _text_delta(self, text: str) -> list[str]:
        frames = self._start_block("text", {"type": "text", "text": ""})
        if text:
            frames.append(
                _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self._block_index,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
            )
        return frames

    def _thinking_delta(self, text: str) -> list[str]:
        frames = self._start_block(
            "thinking",
            {"type": "thinking", "thinking": ""},
        )
        if text:
            frames.append(
                _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self._block_index,
                        "delta": {"type": "thinking_delta", "thinking": text},
                    },
                )
            )
        return frames

    def _tool_start(self, tool_call: NormalizedToolCall | None) -> list[str]:
        call = tool_call or NormalizedToolCall()
        frames = self._start_block(
            "tool_use",
            {
                "type": "tool_use",
                "id": call.id or f"toolu_{self.response_id}",
                "name": call.name or "",
                "input": {},
            },
        )
        frames.extend(self._tool_delta(call))
        return frames

    def _tool_delta(self, tool_call: NormalizedToolCall | None) -> list[str]:
        if tool_call is None or tool_call.arguments in (None, "", {}):
            return []
        arguments = tool_call.arguments
        partial = (
            arguments
            if isinstance(arguments, str)
            else json.dumps(arguments, ensure_ascii=False)
        )
        return [
            _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._block_index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": partial,
                    },
                },
            )
        ]

    def _message_end(self, event: NormalizedStreamEvent) -> list[str]:
        frames = self._stop_block()
        stop_reason = {
            "length": "max_tokens",
            "max_tokens": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "end_turn",
        }.get(event.stop_reason or event.finish_reason or "stop", "end_turn")
        frames.extend(
            [
                _sse(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {
                            "stop_reason": stop_reason,
                            "stop_sequence": None,
                        },
                        "usage": {
                            "input_tokens": self._input_tokens,
                            "output_tokens": self._output_tokens,
                        },
                    },
                ),
                _sse("message_stop", {"type": "message_stop"}),
            ]
        )
        return frames

    def _start_block(
        self,
        block_type: str,
        payload: dict[str, Any],
    ) -> list[str]:
        if self._block_type == block_type:
            return []
        frames = self._stop_block()
        self._block_type = block_type
        frames.append(
            _sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": self._block_index,
                    "content_block": payload,
                },
            )
        )
        return frames

    def _stop_block(self) -> list[str]:
        if self._block_type is None:
            return []
        frame = _sse(
            "content_block_stop",
            {"type": "content_block_stop", "index": self._block_index},
        )
        self._block_index += 1
        self._block_type = None
        return [frame]


def _message_id(value: str) -> str:
    return value if value.startswith("msg_") else f"msg_{value}"


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
