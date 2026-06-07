"""OpenInference-style LLM observability attribute helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from gpt2giga.core.redaction import redact_traffic_payload
from gpt2giga.models.config import ProxySettings
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedTool,
    NormalizedToolCall,
)

NORMALIZE_REQUEST_SPAN_NAME = "protocol.normalize.request"
NORMALIZE_RESPONSE_SPAN_NAME = "protocol.normalize.response"
STREAM_SPAN_NAME = "stream.emit"
OPENINFERENCE_SPAN_KIND = "LLM"


@dataclass(frozen=True)
class LLMContentPolicy:
    """Represent observability content capture decisions."""

    capture_content: bool = False
    capture_messages: bool = False
    capture_tool_args: bool = False
    capture_responses: bool = False
    max_content_length: int = 8_000
    redaction_enabled: bool = True

    @classmethod
    def from_settings(cls, settings: ProxySettings | None) -> "LLMContentPolicy":
        """Build a content policy from proxy settings."""
        if settings is None:
            return cls()
        capture_content = bool(settings.observability_capture_content)
        return cls(
            capture_content=capture_content,
            capture_messages=capture_content
            and bool(settings.observability_capture_messages),
            capture_tool_args=capture_content
            and bool(settings.observability_capture_tool_args),
            capture_responses=capture_content
            and bool(settings.observability_capture_responses),
            max_content_length=settings.observability_max_content_length,
            redaction_enabled=settings.observability_redaction_enabled,
        )


def build_llm_request_attributes(
    request: NormalizedChatRequest,
    *,
    settings: ProxySettings | None = None,
) -> dict[str, Any]:
    """Map a normalized chat request to safe OpenInference-style attributes."""
    policy = LLMContentPolicy.from_settings(settings)
    attrs: dict[str, Any] = {
        "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
        "llm.model_name": request.model,
        "llm.provider": "gigachat",
        "llm.operation": request.operation,
        "llm.request.type": "chat",
        "llm.streaming": request.stream,
        "llm.input_messages.count": len(request.messages),
        "llm.tools.count": len(request.tools),
    }
    if request.tools:
        attrs["llm.tools.names"] = [tool.name for tool in request.tools]
    if request.tool_choice is not None:
        attrs["llm.tool_choice"] = _json_attribute(request.tool_choice, policy)
    invocation = request.generation_config.to_json_dict(exclude_none=True)
    if invocation:
        attrs["llm.invocation_parameters"] = _json_attribute(invocation, policy)
    if request.response_format is not None:
        attrs["llm.response_format"] = request.response_format.type

    if policy.capture_messages:
        attrs["llm.input_messages"] = _json_attribute(
            [
                _message_payload(
                    message,
                    include_content=True,
                    include_tool_args=policy.capture_tool_args,
                )
                for message in request.messages
            ],
            policy,
        )
        attrs["input.value"] = attrs["llm.input_messages"]
    if policy.capture_tool_args and request.tools:
        attrs["llm.tools"] = _json_attribute(
            [_tool_payload(tool) for tool in request.tools],
            policy,
        )
    return attrs


def build_llm_response_attributes(
    response: NormalizedResponse,
    *,
    settings: ProxySettings | None = None,
) -> dict[str, Any]:
    """Map a normalized chat response to safe OpenInference-style attributes."""
    policy = LLMContentPolicy.from_settings(settings)
    messages = [
        choice.message for choice in response.choices if choice.message is not None
    ]
    tool_calls = [tool_call for message in messages for tool_call in message.tool_calls]
    finish_reasons = [
        choice.finish_reason
        for choice in response.choices
        if choice.finish_reason is not None
    ]
    attrs: dict[str, Any] = {
        "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
        "llm.model_name": response.model,
        "llm.provider": response.provider,
        "llm.output_messages.count": len(messages),
        "llm.tool_calls.count": len(tool_calls),
    }
    if finish_reasons:
        attrs["llm.finish_reasons"] = finish_reasons
        attrs["llm.finish_reason"] = finish_reasons[0]
    if response.usage is not None:
        attrs.update(
            {
                "llm.token_count.prompt": response.usage.input_tokens,
                "llm.token_count.completion": response.usage.output_tokens,
                "llm.token_count.total": response.usage.total_tokens,
            }
        )
    if response.error is not None:
        attrs.update(
            {
                "error_type": response.error.type,
                "error_message": response.error.message,
            }
        )

    if policy.capture_responses:
        attrs["llm.output_messages"] = _json_attribute(
            [
                _message_payload(
                    message,
                    include_content=True,
                    include_tool_args=policy.capture_tool_args,
                )
                for message in messages
            ],
            policy,
        )
        attrs["output.value"] = attrs["llm.output_messages"]
    if policy.capture_tool_args and tool_calls:
        attrs["llm.tool_calls"] = _json_attribute(
            [
                _tool_call_payload(tool_call, include_args=True)
                for tool_call in tool_calls
            ],
            policy,
        )
    return attrs


def build_stream_span_events(
    event: NormalizedStreamEvent,
    *,
    settings: ProxySettings | None = None,
    first_content_delta: bool = False,
) -> list[dict[str, Any]]:
    """Map one normalized stream event to OpenTelemetry span events."""
    event_name = _stream_span_event_name(
        event,
        first_content_delta=first_content_delta,
    )
    if event_name is None:
        return []
    return [
        {
            "name": event_name,
            "attributes": build_stream_event_attributes(event, settings=settings),
        }
    ]


def build_stream_event_attributes(
    event: NormalizedStreamEvent,
    *,
    settings: ProxySettings | None = None,
) -> dict[str, Any]:
    """Build safe attributes for one normalized stream span event."""
    policy = LLMContentPolicy.from_settings(settings)
    attrs: dict[str, Any] = {
        "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
        "stream.event.type": event.type,
        "stream.sequence": event.sequence,
        "llm.model_name": event.model,
        "llm.provider": "gigachat",
        "llm.choice_index": event.choice_index,
        "llm.finish_reason": event.finish_reason,
    }
    if event.usage is not None:
        attrs.update(
            {
                "llm.token_count.prompt": event.usage.input_tokens,
                "llm.token_count.completion": event.usage.output_tokens,
                "llm.token_count.total": event.usage.total_tokens,
            }
        )
    if event.error is not None:
        attrs.update(
            {
                "error_type": event.error.type,
                "error_message": event.error.message,
                "error_code": event.error.code,
            }
        )
    if event.tool_call is not None:
        attrs["llm.tool_call.name"] = event.tool_call.name
        attrs["llm.tool_call.id"] = event.tool_call.id
        if policy.capture_tool_args:
            attrs["llm.tool_calls"] = _json_attribute(
                [_tool_call_payload(event.tool_call, include_args=True)],
                policy,
            )
    if policy.capture_responses and event.content_delta is not None:
        attrs["llm.output_messages"] = _json_attribute(
            [{"role": "assistant", "content": event.content_delta}],
            policy,
        )
        attrs["output.value"] = attrs["llm.output_messages"]
    if policy.capture_responses and event.reasoning_delta is not None:
        attrs["llm.reasoning_delta"] = _json_attribute(
            event.reasoning_delta,
            policy,
        )
    return attrs


def _message_payload(
    message: NormalizedMessage,
    *,
    include_content: bool,
    include_tool_args: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role}
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if include_content:
        payload["content"] = message.content
    if message.tool_calls:
        payload["tool_calls"] = [
            _tool_call_payload(tool_call, include_args=include_tool_args)
            for tool_call in message.tool_calls
        ]
    return payload


def _tool_payload(tool: NormalizedTool) -> dict[str, Any]:
    return {
        "type": tool.type,
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


def _tool_call_payload(
    tool_call: NormalizedToolCall,
    *,
    include_args: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": tool_call.id,
        "type": tool_call.type,
        "name": tool_call.name,
    }
    if include_args:
        payload["arguments"] = tool_call.arguments
    return {key: value for key, value in payload.items() if value is not None}


def _stream_span_event_name(
    event: NormalizedStreamEvent,
    *,
    first_content_delta: bool,
) -> str | None:
    if event.type == "message_start":
        return "stream.start"
    if event.type == "content_delta" and first_content_delta:
        return "stream.first_token"
    if event.type in {"tool_call_start", "tool_call_delta"}:
        return "stream.tool_call_delta"
    if event.type == "message_end":
        return "stream.completed"
    if event.type == "error":
        return "stream.error"
    return None


def _json_attribute(value: Any, policy: LLMContentPolicy) -> str:
    if policy.redaction_enabled:
        value = redact_traffic_payload(value)
    text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    if len(text) <= policy.max_content_length:
        return text
    marker = "...[truncated]"
    keep = max(policy.max_content_length - len(marker), 0)
    return text[:keep] + marker
