"""Gemini protocol adapter for normalized chat requests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from gpt2giga.common.json_schema import normalize_tool_parameters_schema
from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.gemini.response_adapter import (
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTool,
    NormalizedToolCall,
)

_GENERATE_FIELDS = {
    "cachedContent",
    "cached_content",
    "contents",
    "generationConfig",
    "generation_config",
    "safetySettings",
    "safety_settings",
    "serviceTier",
    "service_tier",
    "store",
    "systemInstruction",
    "system_instruction",
    "toolConfig",
    "tool_config",
    "tools",
}


class GeminiProtocolAdapter:
    """Convert Gemini-compatible payloads to normalized models."""

    name = "gemini"

    async def to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedChatRequest:
        """Convert a Gemini generateContent payload to normalized form."""
        model = _model_from_context(context)
        return self.generate_content_to_normalized(
            payload,
            model=model,
            context=context,
        )

    async def from_normalized(
        self,
        payload: Any,
        *,
        context: RequestContext | None = None,
    ) -> Any:
        """Convert a normalized response to Gemini GenerateContent shape."""
        return normalized_chat_response_to_gemini(
            payload,
            requested_model=_model_from_context(context)
            or getattr(payload, "model", ""),
            context=context,
        )

    def generate_content_to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        model: str | None,
        context: RequestContext | None = None,
        stream: bool | None = None,
    ) -> NormalizedChatRequest:
        """Convert a Gemini generateContent request body to normalized form."""
        generation_config = _mapping_value(
            payload, "generationConfig", "generation_config"
        )
        metadata, raw_extensions = _extensions(payload)
        raw_extensions.update(_gemini_protocol_extensions(payload))

        return NormalizedChatRequest(
            id=context.request_id if context is not None else None,
            protocol="gemini",
            operation="chat",
            model=model,
            stream=bool(stream) if stream is not None else False,
            messages=[
                *_system_messages(
                    _value(payload, "systemInstruction", "system_instruction")
                ),
                *_normalize_contents(payload.get("contents")),
            ],
            tools=_normalize_tools(payload.get("tools")),
            tool_choice=_normalize_tool_choice(
                _mapping_value(payload, "toolConfig", "tool_config")
            ),
            response_format=_normalize_response_format(generation_config),
            generation_config=_normalize_generation_config(generation_config),
            metadata=metadata,
            raw_extensions=raw_extensions,
        )


def _model_from_context(context: RequestContext | None) -> str | None:
    if context is None:
        return None
    return context.model_requested


def _value(payload: Mapping[str, Any], camel: str, snake: str) -> Any:
    if camel in payload:
        return payload[camel]
    return payload.get(snake)


def _mapping_value(
    payload: Mapping[str, Any], camel: str, snake: str
) -> Mapping[str, Any]:
    value = _value(payload, camel, snake)
    return value if isinstance(value, Mapping) else {}


def _extensions(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = {}
    raw_extensions = {}
    for key, value in payload.items():
        if key in _GENERATE_FIELDS or value is None:
            continue
        if key == "metadata" and isinstance(value, Mapping):
            metadata = dict(value)
            continue
        raw_extensions[key] = value
    return metadata, raw_extensions


def _gemini_protocol_extensions(payload: Mapping[str, Any]) -> dict[str, Any]:
    extensions: dict[str, Any] = {}
    for source, target in (
        ("safetySettings", "safetySettings"),
        ("safety_settings", "safetySettings"),
        ("toolConfig", "toolConfig"),
        ("tool_config", "toolConfig"),
        ("cachedContent", "cachedContent"),
        ("cached_content", "cachedContent"),
        ("serviceTier", "serviceTier"),
        ("service_tier", "serviceTier"),
        ("store", "store"),
    ):
        if (
            source in payload
            and payload[source] is not None
            and target not in extensions
        ):
            extensions[target] = payload[source]
    generation_config = _mapping_value(payload, "generationConfig", "generation_config")
    ignored_generation_fields = {
        key: value
        for key, value in generation_config.items()
        if key
        not in {
            "candidateCount",
            "candidate_count",
            "frequencyPenalty",
            "frequency_penalty",
            "maxOutputTokens",
            "max_output_tokens",
            "presencePenalty",
            "presence_penalty",
            "responseMimeType",
            "response_mime_type",
            "responseModalities",
            "response_modalities",
            "responseSchema",
            "response_schema",
            "seed",
            "stopSequences",
            "stop_sequences",
            "temperature",
            "topK",
            "top_k",
            "topP",
            "top_p",
        }
    }
    if ignored_generation_fields:
        extensions["generationConfig"] = ignored_generation_fields
    return extensions


def _system_messages(value: Any) -> list[NormalizedMessage]:
    text = _content_text(value)
    if not text:
        return []
    return [NormalizedMessage(role="system", content=text)]


def _normalize_contents(value: Any) -> list[NormalizedMessage]:
    if value is None:
        return []
    if isinstance(value, str):
        return [NormalizedMessage(role="user", content=value)]
    if isinstance(value, Mapping):
        return [_normalize_content(value)]
    if isinstance(value, list):
        return [
            _normalize_content(item)
            for item in value
            if isinstance(item, Mapping) or isinstance(item, str)
        ]
    return [NormalizedMessage(role="user", content=str(value))]


def _normalize_content(value: Mapping[str, Any] | str) -> NormalizedMessage:
    if isinstance(value, str):
        return NormalizedMessage(role="user", content=value)

    role = _gemini_role_to_normalized(str(value.get("role") or "user"))
    parts = value.get("parts")
    if isinstance(parts, Mapping):
        parts = [parts]
    if not isinstance(parts, list):
        parts = []

    tool_calls = [
        _function_call_to_normalized(part)
        for part in parts
        if isinstance(part, Mapping)
        and _part_value(part, "functionCall", "function_call")
    ]
    function_responses = [
        _function_response_payload(part)
        for part in parts
        if isinstance(part, Mapping)
        and _part_value(part, "functionResponse", "function_response")
    ]
    if function_responses:
        first = function_responses[0]
        return NormalizedMessage(
            role="tool",
            content=json.dumps(first.get("response", {}), ensure_ascii=False),
            name=_string_or_none(first.get("name")),
            tool_call_id=_string_or_none(first.get("name")),
            raw_extensions={
                "gemini_role": value.get("role"),
                "functionResponse": first,
            },
        )

    normalized_parts = [
        _part_to_normalized(part) for part in parts if isinstance(part, Mapping)
    ]
    content = _collapse_text_parts(normalized_parts)
    return NormalizedMessage(
        role=role,
        content=content,
        tool_calls=tool_calls,
        raw_extensions={
            key: item for key, item in value.items() if key not in {"role", "parts"}
        },
    )


def _gemini_role_to_normalized(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "model":
        return "assistant"
    if normalized == "function":
        return "tool"
    return normalized or "user"


def _normalize_tools(value: Any) -> list[NormalizedTool]:
    if not isinstance(value, list):
        return []

    tools: list[NormalizedTool] = []
    for tool in value:
        if not isinstance(tool, Mapping):
            continue
        declarations = _part_value(
            tool,
            "functionDeclarations",
            "function_declarations",
        )
        if isinstance(declarations, Mapping):
            declarations = [declarations]
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if isinstance(declaration, Mapping):
                tools.append(_function_declaration_to_normalized(declaration, tool))
    return tools


def _function_declaration_to_normalized(
    declaration: Mapping[str, Any],
    tool: Mapping[str, Any],
) -> NormalizedTool:
    parameters = declaration.get("parameters")
    if not isinstance(parameters, Mapping):
        parameters = {}
    raw_extensions = {
        key: value
        for key, value in declaration.items()
        if key not in {"name", "description", "parameters"}
    }
    tool_extensions = {
        key: value
        for key, value in tool.items()
        if key not in {"functionDeclarations", "function_declarations"}
    }
    if tool_extensions:
        raw_extensions["tool"] = tool_extensions
    return NormalizedTool(
        name=str(declaration.get("name") or ""),
        description=_string_or_none(declaration.get("description")),
        parameters=normalize_tool_parameters_schema(parameters),
        raw_extensions=raw_extensions,
    )


def _normalize_tool_choice(tool_config: Mapping[str, Any]) -> Any | None:
    function_calling_config = _part_value(
        tool_config,
        "functionCallingConfig",
        "function_calling_config",
    )
    if not isinstance(function_calling_config, Mapping):
        return None
    allowed_names = _part_value(
        function_calling_config,
        "allowedFunctionNames",
        "allowed_function_names",
    )
    if isinstance(allowed_names, list) and len(allowed_names) == 1:
        return {"type": "function", "function": {"name": str(allowed_names[0])}}
    mode = function_calling_config.get("mode")
    if isinstance(mode, str):
        normalized_mode = mode.lower()
        if normalized_mode == "none":
            return "none"
        if normalized_mode == "any":
            return "required"
    return dict(function_calling_config)


def _normalize_generation_config(
    config: Mapping[str, Any],
) -> NormalizedGenerationConfig:
    return NormalizedGenerationConfig(
        temperature=_number_or_none(config.get("temperature")),
        top_p=_number_or_none(_part_value(config, "topP", "top_p")),
        max_tokens=_int_or_none(
            _part_value(config, "maxOutputTokens", "max_output_tokens")
        ),
        presence_penalty=_number_or_none(
            _part_value(config, "presencePenalty", "presence_penalty")
        ),
        frequency_penalty=_number_or_none(
            _part_value(config, "frequencyPenalty", "frequency_penalty")
        ),
        stop=_part_value(config, "stopSequences", "stop_sequences"),
        seed=_int_or_none(config.get("seed")),
        raw_extensions={
            key: value
            for key, value in {
                "candidateCount": _part_value(
                    config, "candidateCount", "candidate_count"
                ),
                "topK": _part_value(config, "topK", "top_k"),
                "responseModalities": _part_value(
                    config,
                    "responseModalities",
                    "response_modalities",
                ),
            }.items()
            if value is not None
        },
    )


def _normalize_response_format(
    config: Mapping[str, Any],
) -> NormalizedResponseFormat | None:
    mime_type = _part_value(config, "responseMimeType", "response_mime_type")
    schema = _part_value(config, "responseSchema", "response_schema")
    if not isinstance(mime_type, str):
        return None
    if mime_type == "application/json":
        return NormalizedResponseFormat(
            type="json_schema" if isinstance(schema, Mapping) else "json_object",
            json_schema={"schema": dict(schema)}
            if isinstance(schema, Mapping)
            else None,
            raw_extensions={"responseMimeType": mime_type},
        )
    return NormalizedResponseFormat(
        type=mime_type,
        raw_extensions={"responseMimeType": mime_type},
    )


def _part_to_normalized(part: Mapping[str, Any]) -> NormalizedContentPart:
    text = part.get("text")
    if isinstance(text, str):
        return NormalizedContentPart(type="text", text=text)

    inline_data = _part_value(part, "inlineData", "inline_data")
    if isinstance(inline_data, Mapping):
        mime_type = _mime_type(inline_data)
        data = inline_data.get("data")
        if isinstance(mime_type, str) and mime_type.startswith("image/") and data:
            return NormalizedContentPart(
                type="image_url",
                data={"url": f"data:{mime_type};base64,{data}"},
                mime_type=mime_type,
            )
        return NormalizedContentPart(
            type="file",
            data=dict(inline_data),
            mime_type=mime_type,
        )

    file_data = _part_value(part, "fileData", "file_data")
    if isinstance(file_data, Mapping):
        return NormalizedContentPart(
            type="file",
            data={
                "file_id": _part_value(file_data, "fileUri", "file_uri"),
                "mime_type": _mime_type(file_data),
            },
            mime_type=_mime_type(file_data),
            raw_extensions={"gemini_file_data": dict(file_data)},
        )

    return NormalizedContentPart(
        type="unknown",
        data=dict(part),
        raw_extensions=dict(part),
    )


def _function_call_to_normalized(part: Mapping[str, Any]) -> NormalizedToolCall:
    function_call = _part_value(part, "functionCall", "function_call")
    function_call = function_call if isinstance(function_call, Mapping) else {}
    return NormalizedToolCall(
        type="function",
        name=_string_or_none(function_call.get("name")),
        arguments=function_call.get("args", {}),
        raw_extensions={
            key: value
            for key, value in function_call.items()
            if key not in {"name", "args"}
        },
    )


def _function_response_payload(part: Mapping[str, Any]) -> dict[str, Any]:
    function_response = _part_value(part, "functionResponse", "function_response")
    return dict(function_response) if isinstance(function_response, Mapping) else {}


def _collapse_text_parts(
    parts: list[NormalizedContentPart],
) -> str | list[NormalizedContentPart] | None:
    if not parts:
        return None
    if all(part.type == "text" for part in parts):
        return "".join(part.text or "" for part in parts)
    return parts


def _content_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts = value.get("parts")
        if isinstance(parts, Mapping):
            parts = [parts]
        if isinstance(parts, list):
            text = "".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, Mapping) and isinstance(part.get("text"), str)
            )
            return text or None
    return str(value)


def _part_value(mapping: Mapping[str, Any], camel: str, snake: str) -> Any:
    if camel in mapping:
        return mapping[camel]
    return mapping.get(snake)


def _mime_type(mapping: Mapping[str, Any]) -> str | None:
    return _string_or_none(_part_value(mapping, "mimeType", "mime_type"))


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
