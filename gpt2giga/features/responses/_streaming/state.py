"""Mutable state helpers for Responses v2 streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Optional

from gigachat import GigaChat

from gpt2giga.features.responses._streaming.events import (
    ResponsesStreamEventSequencer,
)


def _empty_output_text_part() -> dict[str, Any]:
    return {
        "type": "output_text",
        "text": "",
        "annotations": [],
    }


@dataclass(slots=True)
class OutputMeta:
    """Track stable output ordering for final event emission."""

    kind: str
    key: str


@dataclass(slots=True)
class TextItemState:
    """Mutable state for a streamed assistant text item."""

    item: dict[str, Any]
    item_id: str
    output_index: int
    text: str = ""
    item_added: bool = False
    part_added: bool = False


@dataclass(slots=True)
class FunctionCallState:
    """Mutable state for a streamed function-call item."""

    item: dict[str, Any]
    item_id: str
    output_index: int
    call_id: str
    name: str
    arguments: str = ""
    added: bool = False


@dataclass(slots=True)
class ToolItemState:
    """Mutable state for a streamed builtin-tool item."""

    item: dict[str, Any]
    item_id: str
    output_index: int
    raw_status: str | None
    added: bool = False
    last_emitted_status: str | None = None


@dataclass(slots=True)
class ResponsesV2StreamState:
    """Aggregate mutable state for the Responses v2 streaming flow."""

    response_id: str
    request_data: Optional[dict[str, Any]]
    response_store: dict[Any, Any]
    created_at: int = field(default_factory=lambda: int(time()))
    completed_at: int | None = None
    model: str = "unknown"
    thread_id: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    output_items: list[dict[str, Any]] = field(default_factory=list)
    output_meta: list[OutputMeta] = field(default_factory=list)
    text_states: dict[str, TextItemState] = field(default_factory=dict)
    function_states: dict[str, FunctionCallState] = field(default_factory=dict)
    tool_states: dict[str, ToolItemState] = field(default_factory=dict)
    hydrated_image_results: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.request_data:
            self.model = self.request_data.get("model", "unknown")

    def build_current_response(self, processor: Any, status: str) -> dict[str, Any]:
        """Build the current public Responses payload for the given status."""
        return processor.build_response_api_result_v2(
            request_data=self.request_data,
            gpt_model=self.model,
            response_id=self.response_id,
            output=self.output_items,
            usage=self.usage,
            created_at=self.created_at,
            completed_at=self.completed_at,
            status=status,
            incomplete_details=self.incomplete_details(processor, status),
            thread_id=self.thread_id,
        )

    def incomplete_details(
        self, processor: Any, status: str
    ) -> Optional[dict[str, Any]]:
        """Return incomplete details for an unfinished response status."""
        _, details = processor._build_response_status(self.finish_reason)
        return details if status == "incomplete" else None

    def add_output_item(
        self, kind: str, key: str, item: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        """Append an output item while preserving finalization order."""
        output_index = len(self.output_items)
        self.output_items.append(item)
        self.output_meta.append(OutputMeta(kind=kind, key=key))
        return output_index, item

    def ensure_text_state(self, message_key: str, item_id: str) -> TextItemState:
        """Return the text state for a streamed assistant message."""
        state = self.text_states.get(message_key)
        if state is not None:
            return state

        item = {
            "id": item_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        output_index, item = self.add_output_item("message", message_key, item)
        state = TextItemState(
            item=item,
            item_id=item_id,
            output_index=output_index,
        )
        self.text_states[message_key] = state
        return state

    def ensure_function_state(
        self,
        call_key: str,
        *,
        item_id: str,
        call_id: str,
        name: str | None,
    ) -> FunctionCallState | None:
        """Return the function-call state, creating it when the name is known."""
        state = self.function_states.get(call_key)
        if state is not None:
            if name:
                state.name = name
                state.item["name"] = name
            return state
        if not name:
            return None

        item = {
            "id": item_id,
            "type": "function_call",
            "status": "in_progress",
            "call_id": call_id,
            "name": name,
            "arguments": "",
        }
        output_index, item = self.add_output_item("function_call", call_key, item)
        state = FunctionCallState(
            item=item,
            item_id=item_id,
            output_index=output_index,
            call_id=call_id,
            name=name,
        )
        self.function_states[call_key] = state
        return state

    def ensure_tool_state(
        self,
        tool_key: str,
        *,
        item_id: str,
        output_item: dict[str, Any],
        raw_status: str | None,
    ) -> ToolItemState:
        """Return the builtin-tool state for the given tool key."""
        state = self.tool_states.get(tool_key)
        if state is not None:
            state.item.update(output_item)
            if raw_status is not None:
                state.raw_status = raw_status
            return state

        item = dict(output_item)
        output_index, item = self.add_output_item("tool", tool_key, item)
        state = ToolItemState(
            item=item,
            item_id=item_id,
            output_index=output_index,
            raw_status=raw_status,
        )
        self.tool_states[tool_key] = state
        return state

    def handle_text_update(
        self,
        update: Any,
        *,
        emitter: ResponsesStreamEventSequencer,
    ) -> list[str]:
        """Apply a text delta and return the emitted SSE events."""
        state = self.ensure_text_state(update.message_key, update.item_id)
        events: list[str] = []
        if not state.item_added:
            events.append(
                emitter.emit(
                    "response.output_item.added",
                    {
                        "output_index": state.output_index,
                        "item": state.item,
                    },
                )
            )
            state.item_added = True
        if not state.part_added:
            state.item["content"] = [_empty_output_text_part()]
            events.append(
                emitter.emit(
                    "response.content_part.added",
                    {
                        "item_id": state.item_id,
                        "output_index": state.output_index,
                        "content_index": 0,
                        "part": state.item["content"][0],
                    },
                )
            )
            state.part_added = True

        state.text += update.text
        state.item["content"][0]["text"] = state.text
        events.append(
            emitter.emit(
                "response.output_text.delta",
                {
                    "item_id": state.item_id,
                    "output_index": state.output_index,
                    "content_index": 0,
                    "delta": update.text,
                    "logprobs": [],
                },
            )
        )
        return events

    def handle_function_call_update(
        self,
        update: Any,
        *,
        emitter: ResponsesStreamEventSequencer,
    ) -> list[str]:
        """Apply a function-call delta and return the emitted SSE events."""
        state = self.ensure_function_state(
            update.call_key,
            item_id=update.item_id,
            call_id=update.call_id,
            name=update.name,
        )
        if state is None:
            return []

        events: list[str] = []
        if not state.added:
            events.append(
                emitter.emit(
                    "response.output_item.added",
                    {
                        "output_index": state.output_index,
                        "item": state.item,
                    },
                )
            )
            state.added = True
        if update.arguments:
            state.arguments += update.arguments
            state.item["arguments"] = state.arguments
            events.append(
                emitter.emit(
                    "response.function_call_arguments.delta",
                    {
                        "item_id": state.item_id,
                        "output_index": state.output_index,
                        "delta": update.arguments,
                    },
                )
            )
        return events

    async def handle_tool_update(
        self,
        update: Any,
        *,
        emitter: ResponsesStreamEventSequencer,
        giga_client: GigaChat | Any,
    ) -> list[str]:
        """Apply a builtin-tool update and return the emitted SSE events."""
        update.output_item = await self.hydrate_image_generation_result(
            update.output_item,
            giga_client=giga_client,
        )
        state = self.ensure_tool_state(
            update.tool_key,
            item_id=update.item_id,
            output_item=update.output_item,
            raw_status=update.raw_status,
        )
        events: list[str] = []
        if not state.added:
            events.append(
                emitter.emit(
                    "response.output_item.added",
                    {
                        "output_index": state.output_index,
                        "item": state.item,
                    },
                )
            )
            state.added = True
        events.extend(self.emit_tool_progress(state, emitter=emitter))
        return events

    def finalize(
        self, processor: Any, *, emitter: ResponsesStreamEventSequencer
    ) -> list[str]:
        """Finalize output items and return terminal SSE events."""
        self.completed_at = int(time())
        response_status, _ = processor._build_response_status(self.finish_reason)
        final_item_status = processor._build_output_item_status(response_status)
        events: list[str] = []

        for meta in self.output_meta:
            if meta.kind == "message":
                state = self.text_states[meta.key]
                state.item["status"] = final_item_status
                if not state.item_added:
                    events.append(
                        emitter.emit(
                            "response.output_item.added",
                            {
                                "output_index": state.output_index,
                                "item": state.item,
                            },
                        )
                    )
                    state.item_added = True
                if not state.part_added:
                    state.item["content"] = [_empty_output_text_part()]
                    events.append(
                        emitter.emit(
                            "response.content_part.added",
                            {
                                "item_id": state.item_id,
                                "output_index": state.output_index,
                                "content_index": 0,
                                "part": state.item["content"][0],
                            },
                        )
                    )
                    state.part_added = True

                part = {
                    "type": "output_text",
                    "text": state.text,
                    "annotations": [],
                }
                state.item["content"] = [part]
                events.append(
                    emitter.emit(
                        "response.output_text.done",
                        {
                            "item_id": state.item_id,
                            "output_index": state.output_index,
                            "content_index": 0,
                            "text": state.text,
                            "logprobs": [],
                        },
                    )
                )
                events.append(
                    emitter.emit(
                        "response.content_part.done",
                        {
                            "item_id": state.item_id,
                            "output_index": state.output_index,
                            "content_index": 0,
                            "part": part,
                        },
                    )
                )
                events.append(
                    emitter.emit(
                        "response.output_item.done",
                        {
                            "output_index": state.output_index,
                            "item": state.item,
                        },
                    )
                )
                continue

            if meta.kind == "function_call":
                function_state = self.function_states[meta.key]
                function_state.item["status"] = final_item_status
                events.append(
                    emitter.emit(
                        "response.function_call_arguments.done",
                        {
                            "item_id": function_state.item_id,
                            "output_index": function_state.output_index,
                            "name": function_state.name,
                            "arguments": function_state.arguments,
                        },
                    )
                )
                events.append(
                    emitter.emit(
                        "response.output_item.done",
                        {
                            "output_index": function_state.output_index,
                            "item": function_state.item,
                        },
                    )
                )
                continue

            tool_state = self.tool_states[meta.key]
            item = tool_state.item
            if item.get("status") not in {"completed", "failed"}:
                item["status"] = (
                    "completed" if response_status == "completed" else final_item_status
                )
            events.extend(self.emit_tool_progress(tool_state, emitter=emitter))
            events.append(
                emitter.emit(
                    "response.output_item.done",
                    {
                        "output_index": tool_state.output_index,
                        "item": item,
                    },
                )
            )

        return events

    def tool_event_type(self, tool_item: dict[str, Any], status: str) -> str | None:
        """Map a builtin tool item/status pair to the public SSE event type."""
        item_type = tool_item.get("type")
        if item_type == "web_search_call":
            if status in {"in_progress", "searching", "completed"}:
                return f"response.web_search_call.{status}"
        if item_type == "code_interpreter_call":
            if status in {"in_progress", "interpreting", "completed"}:
                return f"response.code_interpreter_call.{status}"
        if item_type == "image_generation_call":
            if status in {"in_progress", "generating", "completed"}:
                return f"response.image_generation_call.{status}"
        if item_type == "url_content_extraction_call":
            if status in {"in_progress", "completed"}:
                return f"response.url_content_extraction_call.{status}"
        if item_type == "model_3d_generate_call":
            if status in {"in_progress", "generating", "completed"}:
                return f"response.model_3d_generate_call.{status}"
        return None

    def emit_tool_progress(
        self,
        state: ToolItemState,
        *,
        emitter: ResponsesStreamEventSequencer,
    ) -> list[str]:
        """Emit at most one progress event for the current builtin-tool status."""
        status = state.item.get("status")
        if not isinstance(status, str):
            return []
        if state.last_emitted_status == status:
            return []
        event_type = self.tool_event_type(state.item, status)
        if event_type is None:
            return []
        state.last_emitted_status = status
        return [
            emitter.emit(
                event_type,
                {
                    "item_id": state.item_id,
                    "output_index": state.output_index,
                },
            )
        ]

    async def hydrate_image_generation_result(
        self,
        item: dict[str, Any],
        *,
        giga_client: GigaChat | Any,
    ) -> dict[str, Any]:
        """Hydrate image-generation file IDs into base64 payloads when available."""
        if item.get("type") != "image_generation_call":
            return item

        file_id = item.get("result")
        if not isinstance(file_id, str) or not file_id:
            return item

        cached_result = self.hydrated_image_results.get(file_id)
        if cached_result is not None:
            item["result"] = cached_result
            return item

        get_file_content = getattr(giga_client, "aget_file_content", None)
        if not callable(get_file_content):
            return item

        try:
            file_response = await get_file_content(file_id=file_id)
        except Exception:
            return item

        file_content = getattr(file_response, "content", None)
        if isinstance(file_content, str) and file_content:
            self.hydrated_image_results[file_id] = file_content
            item["result"] = file_content
        return item
