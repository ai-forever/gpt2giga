"""OpenInference-style LLM observability attribute helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gpt2giga.core.redaction import redact_traffic_payload
from gpt2giga.models.config import ProxySettings
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedEmbeddingRequest,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedTool,
    NormalizedToolCall,
)

NORMALIZE_REQUEST_SPAN_NAME = "protocol.normalize.request"
NORMALIZE_RESPONSE_SPAN_NAME = "protocol.normalize.response"
CHAT_COMPLETION_SPAN_NAME = "ChatCompletion"
RESPONSES_SPAN_NAME = "Responses"
MESSAGES_SPAN_NAME = "Messages"
EMBEDDINGS_SPAN_NAME = "Embeddings"
STREAM_SPAN_NAME = "stream.emit"
OPENINFERENCE_SPAN_KIND = "LLM"
OPENINFERENCE_EMBEDDING_SPAN_KIND = "EMBEDDING"
GPT2GIGA_API_FORMAT_ATTRIBUTE = "gpt2giga.api_format"


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
    tool_payloads = _request_tool_payloads(request)
    tool_names = _tool_names(tool_payloads)
    attrs: dict[str, Any] = {
        "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
        "llm.model_name": request.model,
        "llm.provider": "gigachat",
        "llm.operation": request.operation,
        "llm.request.type": "chat",
        "llm.streaming": request.stream,
        "llm.input_messages.count": len(request.messages),
        "llm.tools.count": len(tool_payloads),
    }
    if tool_names:
        attrs["llm.tools.names"] = tool_names
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
    if policy.capture_tool_args and tool_payloads:
        attrs["llm.tools"] = _json_attribute(
            tool_payloads,
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
    tool_call_payloads = _response_tool_call_payloads(response, messages)
    tool_call_names = _tool_names(tool_call_payloads)
    finish_reasons = [
        choice.finish_reason
        for choice in response.choices
        if choice.finish_reason is not None
    ]
    status = "failed" if response.error is not None else "ok"
    attrs: dict[str, Any] = {
        "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
        "llm.model_name": response.model,
        "llm.provider": response.provider,
        "llm.output_messages.count": len(messages),
        "llm.tool_calls.count": len(tool_call_payloads),
        "llm.response.status": status,
        "status": status,
    }
    if tool_call_names:
        attrs["llm.tool_calls.names"] = tool_call_names
    if response.id is not None:
        attrs["llm.response.id"] = response.id
    if response.metadata:
        attrs["llm.response.metadata"] = _json_attribute(
            _metadata_payload(response.metadata, policy),
            policy,
        )
    if finish_reasons:
        attrs["llm.finish_reasons"] = finish_reasons
        attrs["llm.finish_reason"] = finish_reasons[0]
    if response.usage is not None:
        attrs.update(
            {
                "llm.token_count.prompt": response.usage.input_tokens,
                "llm.token_count.completion": response.usage.output_tokens,
                "llm.token_count.total": response.usage.total_tokens,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        )
    if response.error is not None:
        attrs.update(
            {
                "error_type": response.error.type,
                "error_message": response.error.message,
                "error.type": response.error.type,
                "error.message": response.error.message,
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
    if policy.capture_tool_args and tool_call_payloads:
        attrs["llm.tool_calls"] = _json_attribute(
            tool_call_payloads,
            policy,
        )
    return attrs


def build_llm_chat_completion_attributes(
    request: NormalizedChatRequest,
    response: NormalizedResponse,
    *,
    settings: ProxySettings | None = None,
) -> dict[str, Any]:
    """Map a complete non-streaming chat exchange to one LLM span."""
    attrs = build_llm_request_attributes(request, settings=settings)
    attrs.update(build_llm_response_attributes(response, settings=settings))
    attrs["llm.operation"] = request.operation
    attrs["llm.request.type"] = "chat"
    attrs[GPT2GIGA_API_FORMAT_ATTRIBUTE] = _chat_api_format(request)
    return attrs


def build_llm_embeddings_attributes(
    request: NormalizedEmbeddingRequest,
    response: Mapping[str, Any],
    *,
    settings: ProxySettings | None = None,
) -> dict[str, Any]:
    """Map an embeddings exchange to safe OpenInference-style attributes."""
    policy = LLMContentPolicy.from_settings(settings)
    data = response.get("data")
    usage = response.get("usage")
    metadata = response.get("metadata")
    model = _string_or_none(response.get("model")) or request.model
    attrs: dict[str, Any] = {
        "openinference.span.kind": OPENINFERENCE_EMBEDDING_SPAN_KIND,
        "embedding.model_name": model,
        "embedding.provider": "gigachat",
        "embedding.operation": request.operation,
        "embedding.input.count": _input_item_count(request.input),
        "embedding.output.count": len(data) if isinstance(data, list) else 0,
        "embedding.encoding_format": request.encoding_format,
        "embedding.dimensions": request.dimensions,
        GPT2GIGA_API_FORMAT_ATTRIBUTE: "embeddings",
        "llm.model_name": model,
        "llm.provider": "gigachat",
        "llm.operation": request.operation,
        "llm.request.type": "embeddings",
        "status": "ok",
    }
    if request.user is not None:
        attrs["user"] = request.user
    if isinstance(usage, Mapping):
        prompt_tokens = usage.get("prompt_tokens")
        total_tokens = usage.get("total_tokens")
        attrs.update(
            {
                "llm.token_count.prompt": prompt_tokens,
                "llm.token_count.total": total_tokens,
                "input_tokens": prompt_tokens,
                "total_tokens": total_tokens,
            }
        )
    if isinstance(metadata, Mapping) and metadata:
        attrs["llm.response.metadata"] = _json_attribute(
            _metadata_payload(metadata, policy),
            policy,
        )
    return {key: value for key, value in attrs.items() if value is not None}


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


def build_tool_call_span_events(
    response: NormalizedResponse,
    *,
    settings: ProxySettings | None = None,
) -> list[dict[str, Any]]:
    """Map observed tool calls to safe span events."""
    policy = LLMContentPolicy.from_settings(settings)
    messages = [
        choice.message for choice in response.choices if choice.message is not None
    ]
    events: list[dict[str, Any]] = []
    for index, payload in enumerate(_response_tool_call_payloads(response, messages)):
        attributes: dict[str, Any] = {
            "openinference.span.kind": OPENINFERENCE_SPAN_KIND,
            "llm.tool_call.index": index,
            "llm.tool_call.name": payload.get("name"),
            "llm.tool_call.id": payload.get("id"),
            "llm.tool_call.status": payload.get("status"),
            "llm.tool_call.source": payload.get("source"),
        }
        if policy.capture_tool_args:
            attributes["llm.tool_calls"] = _json_attribute([payload], policy)
        events.append(
            {
                "name": "llm.tool_call",
                "attributes": attributes,
            }
        )
    return events


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
                "input_tokens": event.usage.input_tokens,
                "output_tokens": event.usage.output_tokens,
                "total_tokens": event.usage.total_tokens,
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
        if event.tool_call.name is not None:
            attrs["llm.tool_calls.names"] = [event.tool_call.name]
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
        reasoning_content = message.raw_extensions.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            payload["reasoning_content"] = reasoning_content
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
        "source": "request.tools",
    }


def _tool_call_payload(
    tool_call: NormalizedToolCall,
    *,
    include_args: bool,
    source: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": tool_call.id,
        "type": tool_call.type,
        "name": tool_call.name,
    }
    if source is not None:
        payload["source"] = source
    if include_args:
        payload["arguments"] = tool_call.arguments
    return {key: value for key, value in payload.items() if value is not None}


def _request_tool_payloads(request: NormalizedChatRequest) -> list[dict[str, Any]]:
    payloads = [_tool_payload(tool) for tool in request.tools if tool.name]
    for message in request.messages:
        payloads.extend(
            _tool_payloads_from_raw_extensions(
                message.raw_extensions,
                source="message.raw_extensions",
            )
        )
    return _dedupe_payloads(payloads)


def _tool_payloads_from_raw_extensions(
    value: Any,
    *,
    source: str,
) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        payloads: list[dict[str, Any]] = []
        for key in ("mcp_tools", "tools", "available_tools"):
            raw_tools = value.get(key)
            if isinstance(raw_tools, list):
                payloads.extend(
                    _raw_tool_payload(item, source=f"{source}.{key}")
                    for item in raw_tools
                    if isinstance(item, Mapping)
                )
        for key in ("additional_kwargs", "metadata", "kwargs"):
            nested = value.get(key)
            if isinstance(nested, (Mapping, list)):
                payloads.extend(
                    _tool_payloads_from_raw_extensions(
                        nested,
                        source=f"{source}.{key}",
                    )
                )
        return [payload for payload in payloads if payload]
    if isinstance(value, list):
        payloads = []
        for index, item in enumerate(value):
            if isinstance(item, (Mapping, list)):
                payloads.extend(
                    _tool_payloads_from_raw_extensions(
                        item,
                        source=f"{source}[{index}]",
                    )
                )
        return payloads
    return []


def _raw_tool_payload(tool: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    function = tool.get("function")
    function_data = function if isinstance(function, Mapping) else tool
    name = function_data.get("name") or tool.get("name")
    if not isinstance(name, str) or not name:
        return {}
    parameters = (
        function_data.get("parameters")
        or function_data.get("input_schema")
        or function_data.get("schema")
    )
    payload: dict[str, Any] = {
        "type": str(tool.get("type") or "function"),
        "name": name,
        "description": _string_or_none(function_data.get("description")),
        "source": source,
    }
    if isinstance(parameters, Mapping):
        payload["parameters"] = dict(parameters)
    for field_name in ("namespace", "server", "server_name"):
        value = tool.get(field_name) or function_data.get(field_name)
        if isinstance(value, str) and value:
            payload[field_name] = value
    return {key: value for key, value in payload.items() if value is not None}


def _response_tool_call_payloads(
    response: NormalizedResponse,
    messages: list[NormalizedMessage],
) -> list[dict[str, Any]]:
    payloads = [
        _tool_call_payload(
            tool_call,
            include_args=True,
            source="response.message",
        )
        for message in messages
        for tool_call in message.tool_calls
    ]
    payloads.extend(_metadata_called_tool_payloads(response.metadata))
    return _dedupe_payloads(payloads)


def _metadata_called_tool_payloads(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_called_tools = metadata.get("gigachat_called_tools")
    decoded = _decode_called_tools(raw_called_tools)
    payloads: list[dict[str, Any]] = []
    for item in decoded:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        payload: dict[str, Any] = {
            "id": item.get("call_id") or item.get("tools_state_id") or item.get("id"),
            "type": "function",
            "name": name,
            "arguments": item.get("arguments"),
            "namespace": item.get("namespace"),
            "status": item.get("status"),
            "source": "metadata.gigachat_called_tools",
        }
        payloads.append(
            {key: value for key, value in payload.items() if value is not None}
        )
    return payloads


def _metadata_payload(
    metadata: Mapping[str, Any],
    policy: LLMContentPolicy,
) -> dict[str, Any]:
    payload = dict(metadata)
    called_tools = _decode_called_tools(payload.get("gigachat_called_tools"))
    if called_tools:
        payload["gigachat_called_tools"] = (
            called_tools
            if policy.capture_tool_args
            else [_strip_tool_arguments(item) for item in called_tools]
        )
    else:
        payload.pop("gigachat_called_tools", None)
    return payload


def _decode_called_tools(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
    elif isinstance(value, list):
        decoded = value
    else:
        return []
    if not isinstance(decoded, list):
        return []
    return [dict(item) for item in decoded if isinstance(item, Mapping)]


def _strip_tool_arguments(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "arguments"}


def _tool_names(payloads: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for payload in payloads:
        name = payload.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _dedupe_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        key = json.dumps(
            {
                "id": payload.get("id"),
                "name": payload.get("name"),
                "namespace": payload.get("namespace"),
                "arguments": payload.get("arguments"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(payload)
    return deduped


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _input_item_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0 if value is None else 1


def _chat_api_format(request: NormalizedChatRequest) -> str:
    if request.protocol == "anthropic":
        return "messages"
    if request.protocol == "gemini":
        return "generate_content"
    if request.operation == "responses":
        return "responses"
    return "chat_completions"


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
