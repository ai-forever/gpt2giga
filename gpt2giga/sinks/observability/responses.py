"""OpenAI Responses observability helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.models.config import ProxySettings
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedError,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedResponseFormat,
    NormalizedStreamEvent,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.sinks.observability.factory import emit_observability_event
from gpt2giga.sinks.observability.llm import (
    RESPONSES_SPAN_NAME,
    build_llm_chat_completion_attributes,
    build_stream_span_events,
    build_tool_call_span_events,
)


async def emit_openai_response_observability(
    state: Any,
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
    *,
    context: RequestContext | None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    """Emit one OpenInference-style span for an OpenAI Responses exchange."""
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        return

    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    normalized_request = responses_request_to_normalized(
        request_payload,
        context=context,
    )
    normalized_response = responses_payload_to_normalized_response(response_payload)
    span_events = list(events or [])
    span_events.extend(
        build_tool_call_span_events(normalized_response, settings=settings)
    )
    await emit_observability_event(
        sink,
        RESPONSES_SPAN_NAME,
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


async def observe_openai_response_stream(
    state: Any,
    body_iterator: AsyncIterator[str],
    *,
    request_payload: Mapping[str, Any],
    context: RequestContext | None,
) -> AsyncIterator[str]:
    """Observe Responses SSE chunks and emit one final LLM span."""
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        async for chunk in body_iterator:
            yield chunk
        return

    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    observer = OpenAIResponseStreamObserver(settings=settings)
    async for chunk in body_iterator:
        observer.observe_chunk(chunk)
        yield chunk

    if not observer.has_observed_payload:
        return
    await emit_openai_response_observability(
        state,
        request_payload,
        observer.to_response_payload(request_payload),
        context=context,
        events=observer.events,
    )


def responses_request_to_normalized(
    payload: Mapping[str, Any],
    *,
    context: RequestContext | None = None,
) -> NormalizedChatRequest:
    """Convert an OpenAI Responses request to a normalized chat-like request."""
    raw_extensions = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "input",
            "instructions",
            "max_output_tokens",
            "metadata",
            "model",
            "stream",
            "temperature",
            "text",
            "tool_choice",
            "tools",
            "top_p",
            "user",
        }
        and value is not None
    }
    return NormalizedChatRequest(
        id=context.request_id if context is not None else None,
        protocol="openai",
        operation="responses",
        model=_string_or_none(payload.get("model")),
        stream=bool(payload.get("stream", False)),
        messages=_responses_input_to_messages(payload),
        tools=_responses_tools_to_normalized(payload.get("tools")),
        tool_choice=payload.get("tool_choice"),
        response_format=_responses_response_format(payload.get("text")),
        generation_config=NormalizedGenerationConfig(
            temperature=payload.get("temperature"),
            top_p=payload.get("top_p"),
            max_tokens=payload.get("max_output_tokens"),
        ),
        user=_string_or_none(payload.get("user")),
        metadata=dict(payload["metadata"])
        if isinstance(payload.get("metadata"), Mapping)
        else {},
        raw_extensions=raw_extensions,
    )


def responses_payload_to_normalized_response(
    payload: Mapping[str, Any],
) -> NormalizedResponse:
    """Convert an OpenAI Responses payload to a normalized response."""
    message = _responses_output_to_message(payload.get("output"))
    status = _string_or_none(payload.get("status"))
    error = _responses_error(payload.get("error"), status=status)
    return NormalizedResponse(
        id=_string_or_none(payload.get("id")),
        model=_string_or_none(payload.get("model")),
        provider="gigachat",
        choices=[
            NormalizedChoice(
                index=0,
                message=message,
                finish_reason=_responses_finish_reason(status, message),
            )
        ],
        usage=_responses_usage_to_normalized(payload.get("usage")),
        error=error,
        metadata=dict(payload["metadata"])
        if isinstance(payload.get("metadata"), Mapping)
        else {},
    )


class OpenAIResponseStreamObserver:
    """Collect enough Responses stream data for one final LLM span."""

    def __init__(self, *, settings: ProxySettings | None = None) -> None:
        self.has_observed_payload = False
        self.response_payload: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        self._settings = settings
        self._saw_first_token = False

    def observe_chunk(self, chunk: Any) -> None:
        """Observe one Responses SSE chunk."""
        for event_type, payload in _iter_responses_sse_payloads(chunk):
            self.observe_payload(event_type, payload)

    def observe_payload(self, event_type: str, payload: Mapping[str, Any]) -> None:
        """Observe one parsed Responses SSE payload."""
        self.has_observed_payload = True
        response = payload.get("response")
        if isinstance(response, Mapping):
            self.response_payload = dict(response)
        if event_type == "error" or payload.get("type") == "error":
            self.error = dict(payload)

        span_event = self._span_event(event_type, payload)
        if span_event is not None:
            self.events.append(span_event)

    def to_response_payload(self, request_payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return final response payload or synthesize a failed one."""
        if self.response_payload is not None and self.error is None:
            return self.response_payload
        error = self.error or {}
        response_payload = dict(self.response_payload or {})
        response_payload.update(
            {
                "status": "failed",
                "error": {
                    "type": _string_or_none(error.get("code")) or "stream_error",
                    "message": _string_or_none(error.get("message")) or "Stream failed",
                    "code": error.get("code"),
                    "param": _string_or_none(error.get("param")),
                },
            }
        )
        response_payload.setdefault(
            "id", f"resp_{_string_or_none(error.get('sequence_number')) or 'stream'}"
        )
        response_payload.setdefault("object", "response")
        response_payload.setdefault("model", request_payload.get("model"))
        response_payload.setdefault("output", [])
        response_payload.setdefault("usage", None)
        response_payload.setdefault("metadata", request_payload.get("metadata", {}))
        return response_payload

    def _span_event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if event_type == "response.created":
            return _stream_event("stream.start", event_type, payload)
        if event_type == "response.output_text.delta":
            first_token = not self._saw_first_token
            self._saw_first_token = True
            if first_token:
                event = NormalizedStreamEvent(
                    type="content_delta",
                    model=_response_model(payload),
                    sequence=_sequence_number(payload),
                    content_delta=_string_or_none(payload.get("delta")),
                )
                return build_stream_span_events(
                    event,
                    settings=self._settings,
                    first_content_delta=True,
                )[0]
        if event_type == "response.completed":
            return _stream_event("stream.completed", event_type, payload)
        if event_type in {"error", "response.failed", "response.incomplete"}:
            return _stream_event("stream.error", event_type, payload)
        return None


def _responses_input_to_messages(
    payload: Mapping[str, Any],
) -> list[NormalizedMessage]:
    messages: list[NormalizedMessage] = []
    instructions = payload.get("instructions")
    if instructions is not None:
        messages.append(
            NormalizedMessage(role="system", content=_content_to_text(instructions))
        )

    input_value = payload.get("input")
    if isinstance(input_value, list):
        for item in input_value:
            message = _responses_input_item_to_message(item)
            if message is not None:
                messages.append(message)
    elif input_value is not None:
        messages.append(
            NormalizedMessage(role="user", content=_content_to_text(input_value))
        )
    return messages


def _responses_input_item_to_message(value: Any) -> NormalizedMessage | None:
    if not isinstance(value, Mapping):
        return NormalizedMessage(role="user", content=_content_to_text(value))

    item_type = value.get("type")
    if item_type == "function_call":
        return NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id=_string_or_none(value.get("call_id") or value.get("id")),
                    name=_string_or_none(value.get("name")),
                    arguments=value.get("arguments"),
                )
            ],
            raw_extensions=_raw_extensions(
                value, {"type", "call_id", "id", "name", "arguments"}
            ),
        )
    if item_type == "function_call_output":
        return NormalizedMessage(
            role="tool",
            content=_content_to_text(value.get("output")),
            tool_call_id=_string_or_none(value.get("call_id") or value.get("id")),
            raw_extensions=_raw_extensions(value, {"type", "output", "call_id", "id"}),
        )

    role = _string_or_none(value.get("role")) or "user"
    return NormalizedMessage(
        role=role,
        content=_content_to_text(value.get("content", value.get("text", value))),
        raw_extensions=_raw_extensions(value, {"role", "content", "text"}),
    )


def _responses_tools_to_normalized(value: Any) -> list[NormalizedTool]:
    if not isinstance(value, list):
        return []
    tools: list[NormalizedTool] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        data = function if isinstance(function, Mapping) else item
        name = data.get("name") or item.get("name") or item.get("type")
        if not isinstance(name, str) or not name:
            continue
        parameters = (
            data.get("parameters") or data.get("input_schema") or data.get("schema")
        )
        tools.append(
            NormalizedTool(
                type=_string_or_none(item.get("type")) or "function",
                name=name,
                description=_string_or_none(data.get("description")),
                parameters=dict(parameters) if isinstance(parameters, Mapping) else {},
                raw_extensions=_raw_extensions(
                    item,
                    {
                        "type",
                        "function",
                        "name",
                        "description",
                        "parameters",
                        "input_schema",
                        "schema",
                    },
                ),
            )
        )
    return tools


def _responses_response_format(value: Any) -> NormalizedResponseFormat | None:
    if not isinstance(value, Mapping):
        return None
    format_value = value.get("format")
    if not isinstance(format_value, Mapping):
        return None
    response_type = format_value.get("type")
    if not isinstance(response_type, str):
        return None
    json_schema = format_value.get("json_schema") or format_value.get("schema")
    return NormalizedResponseFormat(
        type=response_type,
        json_schema=dict(json_schema) if isinstance(json_schema, Mapping) else None,
        raw_extensions=_raw_extensions(format_value, {"type", "json_schema", "schema"}),
    )


def _responses_output_to_message(value: Any) -> NormalizedMessage:
    if not isinstance(value, list):
        return NormalizedMessage(role="assistant", content=None)

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type == "message":
            text_parts.extend(_responses_message_text_parts(item))
        elif item_type == "reasoning":
            reasoning_parts.extend(_responses_reasoning_parts(item))
        elif item_type == "function_call":
            tool_calls.append(_responses_function_call(item))
        elif _is_builtin_tool_output(item_type):
            tool_calls.append(_responses_builtin_tool_call(item))

    message = NormalizedMessage(
        role="assistant",
        content="\n".join(part for part in text_parts if part) or None,
        tool_calls=tool_calls,
    )
    if reasoning_parts:
        message.raw_extensions["reasoning_content"] = "\n".join(
            part for part in reasoning_parts if part
        )
    return message


def _responses_message_text_parts(item: Mapping[str, Any]) -> list[str]:
    content = item.get("content")
    if not isinstance(content, list):
        return [_content_to_text(content)] if content is not None else []
    parts: list[str] = []
    for part in content:
        if not isinstance(part, Mapping):
            parts.append(_content_to_text(part))
            continue
        text = part.get("text") or part.get("output_text")
        if text is not None:
            parts.append(_content_to_text(text))
    return parts


def _responses_reasoning_parts(item: Mapping[str, Any]) -> list[str]:
    summary = item.get("summary")
    if not isinstance(summary, list):
        return []
    parts = []
    for part in summary:
        if isinstance(part, Mapping) and part.get("text") is not None:
            parts.append(_content_to_text(part["text"]))
    return parts


def _responses_function_call(item: Mapping[str, Any]) -> NormalizedToolCall:
    return NormalizedToolCall(
        id=_string_or_none(item.get("call_id") or item.get("id")),
        type="function",
        name=_string_or_none(item.get("name")),
        arguments=item.get("arguments"),
        raw_extensions=_raw_extensions(
            item, {"type", "call_id", "id", "name", "arguments"}
        ),
    )


def _responses_builtin_tool_call(item: Mapping[str, Any]) -> NormalizedToolCall:
    item_type = _string_or_none(item.get("type")) or "tool"
    return NormalizedToolCall(
        id=_string_or_none(item.get("id")),
        type=item_type,
        name=_builtin_tool_name(item_type),
        arguments=_builtin_tool_arguments(item),
        raw_extensions=_raw_extensions(item, {"type", "id"}),
    )


def _builtin_tool_arguments(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"id", "type", "status"} and value is not None
    }


def _responses_usage_to_normalized(value: Any) -> NormalizedUsage | None:
    if not isinstance(value, Mapping):
        return None
    return NormalizedUsage(
        input_tokens=value.get("input_tokens", value.get("prompt_tokens")),
        output_tokens=value.get("output_tokens", value.get("completion_tokens")),
        total_tokens=value.get("total_tokens"),
        raw_extensions=_raw_extensions(
            value,
            {
                "input_tokens",
                "prompt_tokens",
                "output_tokens",
                "completion_tokens",
                "total_tokens",
            },
        ),
    )


def _responses_error(value: Any, *, status: str | None) -> NormalizedError | None:
    if isinstance(value, Mapping):
        return NormalizedError(
            type=_string_or_none(value.get("type") or value.get("code")) or "api_error",
            message=_string_or_none(value.get("message")) or "",
            code=value.get("code"),
            param=_string_or_none(value.get("param")),
        )
    if status in {"failed", "incomplete", "cancelled"}:
        return NormalizedError(type=status, message=f"Response {status}")
    return None


def _responses_finish_reason(
    status: str | None,
    message: NormalizedMessage,
) -> str | None:
    if message.tool_calls:
        return "tool_calls"
    if status == "completed":
        return "stop"
    return status


def _iter_responses_sse_payloads(chunk: Any) -> list[tuple[str, Mapping[str, Any]]]:
    text = (
        chunk.decode("utf-8", errors="replace")
        if isinstance(chunk, bytes)
        else str(chunk)
    )
    payloads: list[tuple[str, Mapping[str, Any]]] = []
    for block in text.split("\n\n"):
        event_type = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        if not data:
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            payloads.append(
                (event_type or _string_or_none(payload.get("type")) or "event", payload)
            )
    return payloads


def _stream_event(
    name: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "name": name,
        "attributes": {
            "stream.event.type": event_type,
            "stream.sequence": _sequence_number(payload),
            "llm.model_name": _response_model(payload),
        },
    }


def _response_model(payload: Mapping[str, Any]) -> str | None:
    response = payload.get("response")
    if isinstance(response, Mapping):
        return _string_or_none(response.get("model"))
    return None


def _sequence_number(payload: Mapping[str, Any]) -> int | None:
    value = payload.get("sequence_number")
    return value if isinstance(value, int) else None


def _content_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _raw_extensions(value: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in excluded}


def _is_builtin_tool_output(item_type: Any) -> bool:
    return item_type in {
        "code_interpreter_call",
        "computer_call",
        "file_search_call",
        "image_generation_call",
        "local_shell_call",
        "mcp_call",
        "web_search_call",
    }


def _builtin_tool_name(item_type: str) -> str:
    suffix = "_call"
    return item_type.removesuffix(suffix) if item_type.endswith(suffix) else item_type


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
