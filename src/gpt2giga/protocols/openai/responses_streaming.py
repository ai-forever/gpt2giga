"""Stateful projection of normalized events to OpenAI Responses SSE."""

from __future__ import annotations

import json
import time
from typing import Any

from gpt2giga.common.sources import merge_inline_data
from gpt2giga.protocol.response.processor import ResponseProcessor
from gpt2giga.protocols.normalized import (
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)


class ResponsesStreamProtocolError(ValueError):
    """Signal an invalid normalized lifecycle before projecting more events."""


class ResponsesStreamProjector:
    """Validate one normalized lifecycle and emit typed Responses SSE frames."""

    def __init__(
        self,
        *,
        request_payload: dict[str, Any],
        requested_model: str,
        response_id: str,
        created_at: int | None = None,
    ) -> None:
        self.request_payload = request_payload
        self.requested_model = requested_model
        self.response_id = response_id
        self.created_at = int(time.time()) if created_at is None else created_at
        self._sequence = 0
        self._last_provider_sequence: int | None = None
        self._started = False
        self._terminal = False
        self._output: list[dict[str, Any]] = []
        self._usage: NormalizedUsage | None = None
        self._text = ""
        self._text_item: dict[str, Any] | None = None
        self._text_output_index: int | None = None
        self._tool_item: dict[str, Any] | None = None
        self._tool_output_index: int | None = None
        self._hosted_message: dict[str, Any] = {
            "tool_executions": [],
            "files": [],
            "inline_data": {},
        }
        self._hosted_items_emitted = False

    @property
    def terminal(self) -> bool:
        """Return whether a terminal public lifecycle was emitted."""
        return self._terminal

    def project(self, event: NormalizedStreamEvent) -> list[str]:
        """Validate and project one normalized event into zero or more frames."""
        self._validate_sequence(event)
        self._collect_hosted_tool_metadata(event)
        if self._terminal:
            raise ResponsesStreamProtocolError("event received after terminal")
        if event.type == "message_start":
            return self._start(event)
        if not self._started:
            raise ResponsesStreamProtocolError("event received before message_start")

        if event.usage is not None:
            self._usage = event.usage
        if event.type == "heartbeat":
            return []
        if event.type == "usage":
            return []
        if event.type == "content_delta":
            return self._content_delta(event.content_delta or "")
        if event.type == "tool_call_start":
            frames = self._tool_delta(event.tool_call, start=True)
            if event.finish_reason is not None:
                frames.extend(self._complete(event.finish_reason))
            return frames
        if event.type == "tool_call_delta":
            frames = self._tool_delta(event.tool_call, start=False)
            if event.finish_reason is not None:
                frames.extend(self._complete(event.finish_reason))
            return frames
        if event.type == "message_end":
            frames = []
            if event.content_delta:
                frames.extend(self._content_delta(event.content_delta))
            frames.extend(self._complete(event.finish_reason or event.stop_reason))
            return frames
        if event.type == "cancelled":
            return self._incomplete("client_disconnected")
        if event.type == "error":
            return self._error(event)
        if event.type == "reasoning_delta":
            raise ResponsesStreamProtocolError(
                "reasoning_delta is outside the admitted Responses subset"
            )
        raise ResponsesStreamProtocolError(f"unsupported event type: {event.type}")

    def finish(self) -> None:
        """Reject an upstream iterator that ended without one terminal event."""
        if not self._terminal:
            raise ResponsesStreamProtocolError(
                "normalized stream ended without a terminal event"
            )

    def protocol_error_frame(self) -> str:
        """Build the stable terminal error frame for a pre-terminal violation."""
        if self._terminal:
            raise ResponsesStreamProtocolError("cannot emit error after terminal")
        self._terminal = True
        return self._frame(
            "error",
            {
                "code": "provider_protocol_error",
                "message": "The upstream stream violated its protocol contract.",
                "param": None,
            },
        )

    def _start(self, event: NormalizedStreamEvent) -> list[str]:
        if self._started:
            raise ResponsesStreamProtocolError("duplicate message_start")
        self._started = True
        return [
            self._frame(
                "response.created",
                {"response": self._response("in_progress", output=[])},
            )
        ]

    def _content_delta(self, delta: str) -> list[str]:
        frames = self._ensure_text_item()
        self._text += delta
        frames.append(
            self._frame(
                "response.output_text.delta",
                {
                    "item_id": self._text_item["id"],
                    "output_index": self._text_output_index,
                    "content_index": 0,
                    "delta": delta,
                    "logprobs": [],
                },
            )
        )
        return frames

    def _ensure_text_item(self) -> list[str]:
        if self._text_item is not None:
            return []
        if self._tool_item is not None:
            raise ResponsesStreamProtocolError(
                "mixed text and tool output is outside the admitted stream subset"
            )
        self._text_output_index = len(self._output)
        self._text_item = {
            "id": f"msg_{self.response_id}",
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        self._output.append(self._text_item)
        part = {
            "type": "output_text",
            "text": "",
            "annotations": [],
            "logprobs": [],
        }
        return [
            self._frame(
                "response.output_item.added",
                {
                    "output_index": self._text_output_index,
                    "item": dict(self._text_item),
                },
            ),
            self._frame(
                "response.content_part.added",
                {
                    "item_id": self._text_item["id"],
                    "output_index": self._text_output_index,
                    "content_index": 0,
                    "part": part,
                },
            ),
        ]

    def _tool_delta(
        self,
        tool_call: NormalizedToolCall | None,
        *,
        start: bool,
    ) -> list[str]:
        if tool_call is None:
            raise ResponsesStreamProtocolError("tool event is missing tool_call")
        if self._text_item is not None:
            raise ResponsesStreamProtocolError(
                "mixed text and tool output is outside the admitted stream subset"
            )

        frames: list[str] = []
        if self._tool_item is None:
            if not start:
                raise ResponsesStreamProtocolError("tool delta received before start")
            call_id = tool_call.id or "call_0"
            self._tool_output_index = len(self._output)
            self._tool_item = {
                "id": f"fc_{call_id}",
                "type": "function_call",
                "status": "in_progress",
                "call_id": call_id,
                "name": tool_call.name or "",
                "arguments": "",
            }
            self._output.append(self._tool_item)
            frames.append(
                self._frame(
                    "response.output_item.added",
                    {
                        "output_index": self._tool_output_index,
                        "item": dict(self._tool_item),
                    },
                )
            )
        elif start:
            raise ResponsesStreamProtocolError("duplicate tool_call_start")

        if tool_call.id and tool_call.id != self._tool_item["call_id"]:
            raise ResponsesStreamProtocolError("tool call id changed during stream")
        if tool_call.name:
            if self._tool_item["name"] and tool_call.name != self._tool_item["name"]:
                raise ResponsesStreamProtocolError("tool name changed during stream")
            self._tool_item["name"] = tool_call.name
        arguments = _arguments_delta(tool_call.arguments)
        if arguments:
            self._tool_item["arguments"] += arguments
            frames.append(
                self._frame(
                    "response.function_call_arguments.delta",
                    {
                        "item_id": self._tool_item["id"],
                        "output_index": self._tool_output_index,
                        "delta": arguments,
                    },
                )
            )
        return frames

    def _complete(self, reason: str | None) -> list[str]:
        if self._text_item is None and self._tool_item is None:
            frames = self._complete_hosted_tools()
            if not frames:
                frames = self._ensure_text_item()
        else:
            frames = []
        if self._text_item is not None:
            frames.extend(self._complete_text())
        if self._tool_item is not None:
            frames.extend(self._complete_tool())
        frames.extend(self._complete_hosted_tools())

        if reason in {"max_tokens", "length"}:
            frames.extend(self._incomplete("max_output_tokens"))
        elif reason == "content_filter":
            frames.extend(self._incomplete("content_filter"))
        else:
            self._terminal = True
            frames.append(
                self._frame(
                    "response.completed",
                    {"response": self._response("completed")},
                )
            )
        return frames

    def _complete_hosted_tools(self) -> list[str]:
        if self._hosted_items_emitted:
            return []
        self._hosted_items_emitted = True
        items = ResponseProcessor.create_hosted_tool_response_items(
            self._hosted_message,
            self.response_id,
            request_data=self.request_payload,
        )
        frames: list[str] = []
        for item in items:
            output_index = len(self._output)
            self._output.append(item)
            added_item = dict(item)
            added_item["status"] = "in_progress"
            frames.extend(
                [
                    self._frame(
                        "response.output_item.added",
                        {
                            "output_index": output_index,
                            "item": added_item,
                        },
                    ),
                    self._frame(
                        "response.output_item.done",
                        {
                            "output_index": output_index,
                            "item": dict(item),
                        },
                    ),
                ]
            )
        return frames

    def _collect_hosted_tool_metadata(self, event: NormalizedStreamEvent) -> None:
        raw_chunk = event.raw_extensions.get("openai_chunk")
        if not isinstance(raw_chunk, dict):
            return
        choices = raw_chunk.get("choices")
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("delta", choice.get("message"))
            if not isinstance(message, dict):
                continue
            for field in ("tool_executions", "files"):
                values = message.get(field)
                if isinstance(values, list):
                    self._hosted_message[field].extend(
                        value for value in values if isinstance(value, dict)
                    )
            merge_inline_data(
                self._hosted_message["inline_data"],
                message.get("inline_data"),
            )

    def _complete_text(self) -> list[str]:
        part = {
            "type": "output_text",
            "text": self._text,
            "annotations": [],
            "logprobs": [],
        }
        self._text_item["status"] = "completed"
        self._text_item["content"] = [part]
        return [
            self._frame(
                "response.output_text.done",
                {
                    "item_id": self._text_item["id"],
                    "output_index": self._text_output_index,
                    "content_index": 0,
                    "text": self._text,
                    "logprobs": [],
                },
            ),
            self._frame(
                "response.content_part.done",
                {
                    "item_id": self._text_item["id"],
                    "output_index": self._text_output_index,
                    "content_index": 0,
                    "part": part,
                },
            ),
            self._frame(
                "response.output_item.done",
                {
                    "output_index": self._text_output_index,
                    "item": dict(self._text_item),
                },
            ),
        ]

    def _complete_tool(self) -> list[str]:
        self._tool_item["status"] = "completed"
        return [
            self._frame(
                "response.function_call_arguments.done",
                {
                    "item_id": self._tool_item["id"],
                    "output_index": self._tool_output_index,
                    "arguments": self._tool_item["arguments"],
                },
            ),
            self._frame(
                "response.output_item.done",
                {
                    "output_index": self._tool_output_index,
                    "item": dict(self._tool_item),
                },
            ),
        ]

    def _incomplete(self, reason: str) -> list[str]:
        self._terminal = True
        return [
            self._frame(
                "response.incomplete",
                {
                    "response": self._response(
                        "incomplete",
                        incomplete_details={"reason": reason},
                    )
                },
            )
        ]

    def _error(self, event: NormalizedStreamEvent) -> list[str]:
        self._terminal = True
        error = event.error
        return [
            self._frame(
                "error",
                {
                    "code": error.code if error is not None else "provider_failure",
                    "message": (
                        error.message
                        if error is not None
                        else "Provider stream failed."
                    ),
                    "param": error.param if error is not None else None,
                },
            )
        ]

    def _response(
        self,
        status: str,
        *,
        output: list[dict[str, Any]] | None = None,
        incomplete_details: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        text = self.request_payload.get("text")
        if not isinstance(text, dict):
            text = {"format": {"type": "text"}}
        return {
            "id": f"resp_{self.response_id}",
            "object": "response",
            "created_at": self.created_at,
            "status": status,
            "error": None,
            "incomplete_details": incomplete_details,
            "instructions": self.request_payload.get("instructions"),
            "max_output_tokens": self.request_payload.get("max_output_tokens"),
            "model": self.requested_model,
            "output": list(self._output) if output is None else output,
            "parallel_tool_calls": True,
            "previous_response_id": None,
            "reasoning": {"effort": None, "summary": None},
            "store": True,
            "temperature": self.request_payload.get("temperature", 1),
            "text": text,
            "tool_choice": self.request_payload.get("tool_choice", "auto"),
            "tools": self.request_payload.get("tools", []),
            "top_p": self.request_payload.get("top_p", 1),
            "truncation": "disabled",
            "usage": _usage(self._usage),
            "user": None,
            "metadata": dict(self.request_payload.get("metadata") or {}),
        }

    def _frame(self, event_type: str, data: dict[str, Any]) -> str:
        data["type"] = event_type
        data["sequence_number"] = self._sequence
        self._sequence += 1
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    def _validate_sequence(self, event: NormalizedStreamEvent) -> None:
        if event.sequence is None:
            return
        if (
            self._last_provider_sequence is not None
            and event.sequence <= self._last_provider_sequence
        ):
            raise ResponsesStreamProtocolError(
                "normalized provider sequence is not strictly increasing"
            )
        self._last_provider_sequence = event.sequence


def _arguments_delta(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _usage(usage: NormalizedUsage | None) -> dict[str, int] | None:
    if usage is None:
        return None
    values = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }
    return {key: value for key, value in values.items() if value is not None}
