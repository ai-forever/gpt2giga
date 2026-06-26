"""Gemini protocol adapter for normalized chat requests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from gpt2giga.common.json_schema import normalize_tool_parameters_schema
from gpt2giga.common.tools import normalize_gigachat_builtin_tool_type
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
_GEMINI_FUNCTION_DECLARATION_KEYS = {
    "functionDeclarations",
    "function_declarations",
}
_GEMINI_FUNCTION_PARAMETERS_KEYS = {
    "parameters",
    "parametersJsonSchema",
    "parameters_json_schema",
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
        builtin_tool_mapping_enabled: bool = True,
    ) -> NormalizedChatRequest:
        """Convert a Gemini generateContent request body to normalized form."""
        _validate_generate_payload(payload)
        generation_config = _mapping_value(
            payload, "generationConfig", "generation_config"
        )
        metadata, raw_extensions = _extensions(payload)
        raw_extensions.update(_gemini_protocol_extensions(payload))
        unsupported_tools = _unsupported_gemini_tools(
            payload.get("tools"),
            builtin_tool_mapping_enabled=builtin_tool_mapping_enabled,
        )
        if unsupported_tools:
            raw_extensions["unsupportedTools"] = unsupported_tools
        tools = _normalize_tools(
            payload.get("tools"),
            builtin_tool_mapping_enabled=builtin_tool_mapping_enabled,
        )
        function_calling_config = _function_calling_config(
            _mapping_value(payload, "toolConfig", "tool_config")
        )
        allowed_function_names = _allowed_function_names(function_calling_config)
        _validate_allowed_function_names(allowed_function_names, tools)
        tools = _filter_tools_by_allowed_names(tools, allowed_function_names)

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
            tools=tools,
            tool_choice=_normalize_tool_choice(
                function_calling_config,
                allowed_names=allowed_function_names,
                tools=tools,
            ),
            response_format=_normalize_response_format(generation_config),
            generation_config=_normalize_generation_config(generation_config),
            metadata=metadata,
            raw_extensions=raw_extensions,
        )


def gemini_invalid_request(message: str, *, param: str | None = None) -> HTTPException:
    """Build a Gemini-compatible validation error."""
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": param,
                "code": "invalid_request",
            }
        },
    )


def _validate_generate_payload(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise gemini_invalid_request(
            "Gemini generateContent request body must be an object."
        )
    contents = payload.get("contents")
    if contents is None:
        raise gemini_invalid_request(
            "Gemini generateContent request must include contents.",
            param="contents",
        )
    if not isinstance(contents, list):
        raise gemini_invalid_request(
            "Gemini contents must be a non-empty list.",
            param="contents",
        )
    if not contents:
        raise gemini_invalid_request(
            "Gemini contents must not be empty.",
            param="contents",
        )
    for content_index, content in enumerate(contents):
        _validate_content(content, param=f"contents[{content_index}]")
    _validate_generation_config(
        _value(payload, "generationConfig", "generation_config")
    )
    _validate_tools(payload.get("tools"))
    _validate_tool_config(_value(payload, "toolConfig", "tool_config"))


def _validate_content(value: Any, *, param: str) -> None:
    if not isinstance(value, Mapping):
        raise gemini_invalid_request(
            "Gemini content entries must be objects.",
            param=param,
        )
    parts = value.get("parts")
    if not isinstance(parts, list):
        raise gemini_invalid_request(
            "Gemini content parts must be a non-empty list.",
            param=f"{param}.parts",
        )
    if not parts:
        raise gemini_invalid_request(
            "Gemini content parts must not be empty.",
            param=f"{param}.parts",
        )
    for part_index, part in enumerate(parts):
        _validate_content_part(part, param=f"{param}.parts[{part_index}]")


def _validate_content_part(part: Any, *, param: str) -> None:
    if not isinstance(part, Mapping):
        raise gemini_invalid_request(
            "Gemini content parts must be objects.",
            param=param,
        )
    field_count = sum(
        bool(value)
        for value in (
            "text" in part,
            _part_value(part, "inlineData", "inline_data") is not None,
            _part_value(part, "fileData", "file_data") is not None,
            _part_value(part, "functionCall", "function_call") is not None,
            _part_value(part, "functionResponse", "function_response") is not None,
        )
    )
    if field_count == 0:
        raise gemini_invalid_request(
            "Gemini content part shape is not supported.",
            param=param,
        )
    if field_count > 1:
        raise gemini_invalid_request(
            "Gemini content parts must contain exactly one supported part field.",
            param=param,
        )
    if "text" in part and not isinstance(part.get("text"), str):
        raise gemini_invalid_request(
            "Gemini text parts must contain a string text value.",
            param=f"{param}.text",
        )
    inline_data = _part_value(part, "inlineData", "inline_data")
    if inline_data is not None and not isinstance(inline_data, Mapping):
        raise gemini_invalid_request(
            "Gemini inlineData parts must be objects.",
            param=f"{param}.inlineData",
        )
    file_data = _part_value(part, "fileData", "file_data")
    if file_data is not None and not isinstance(file_data, Mapping):
        raise gemini_invalid_request(
            "Gemini fileData parts must be objects.",
            param=f"{param}.fileData",
        )
    function_call = _part_value(part, "functionCall", "function_call")
    if function_call is not None:
        _validate_function_call(function_call, param=f"{param}.functionCall")
    function_response = _part_value(part, "functionResponse", "function_response")
    if function_response is not None:
        _validate_function_response(
            function_response,
            param=f"{param}.functionResponse",
        )


def _validate_function_call(value: Any, *, param: str) -> None:
    if not isinstance(value, Mapping):
        raise gemini_invalid_request(
            "Gemini functionCall parts must be objects.",
            param=param,
        )
    if not isinstance(value.get("name"), str) or not value.get("name"):
        raise gemini_invalid_request(
            "Gemini functionCall.name must be a non-empty string.",
            param=f"{param}.name",
        )
    args = value.get("args")
    if args is not None and not isinstance(args, Mapping):
        raise gemini_invalid_request(
            "Gemini functionCall.args must be an object when provided.",
            param=f"{param}.args",
        )


def _validate_function_response(value: Any, *, param: str) -> None:
    if not isinstance(value, Mapping):
        raise gemini_invalid_request(
            "Gemini functionResponse parts must be objects.",
            param=param,
        )
    if not isinstance(value.get("name"), str) or not value.get("name"):
        raise gemini_invalid_request(
            "Gemini functionResponse.name must be a non-empty string.",
            param=f"{param}.name",
        )
    response = value.get("response")
    if response is not None and not isinstance(response, Mapping):
        raise gemini_invalid_request(
            "Gemini functionResponse.response must be an object when provided.",
            param=f"{param}.response",
        )


def _validate_generation_config(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise gemini_invalid_request(
            "Gemini generationConfig must be an object.",
            param="generationConfig",
        )
    mime_type = _part_value(value, "responseMimeType", "response_mime_type")
    response_schema = _response_schema_value(value)
    response_json_schema = _response_json_schema_value(value)
    if response_schema is not None and response_json_schema is not None:
        raise gemini_invalid_request(
            "Gemini responseSchema and responseJsonSchema are mutually exclusive.",
            param="generationConfig.responseJsonSchema",
        )
    schema = (
        response_json_schema if response_json_schema is not None else response_schema
    )
    schema_param = (
        "generationConfig.responseJsonSchema"
        if response_json_schema is not None
        else "generationConfig.responseSchema"
    )
    if mime_type is not None and not isinstance(mime_type, str):
        raise gemini_invalid_request(
            "Gemini responseMimeType must be a string.",
            param="generationConfig.responseMimeType",
        )
    if schema is not None and not isinstance(schema, Mapping):
        raise gemini_invalid_request(
            "Gemini responseSchema must be an object.",
            param=schema_param,
        )
    if schema is not None and mime_type != "application/json":
        raise gemini_invalid_request(
            "Gemini responseSchema is supported only with application/json.",
            param=schema_param,
        )
    if mime_type == "application/json" and schema is None:
        raise gemini_invalid_request(
            "GigaChat does not support Gemini JSON mode without a response schema. "
            "Provide generationConfig.responseJsonSchema or responseSchema.",
            param="generationConfig.responseMimeType",
        )
    if mime_type not in {None, "application/json", "text/plain"}:
        raise gemini_invalid_request(
            f"Unsupported Gemini responseMimeType: {mime_type}.",
            param="generationConfig.responseMimeType",
        )


def _validate_tools(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise gemini_invalid_request("Gemini tools must be a list.", param="tools")
    for tool_index, tool in enumerate(value):
        if not isinstance(tool, Mapping):
            raise gemini_invalid_request(
                "Gemini tool entries must be objects.",
                param=f"tools[{tool_index}]",
            )
        declarations = _part_value(
            tool,
            "functionDeclarations",
            "function_declarations",
        )
        if declarations is None:
            continue
        if isinstance(declarations, Mapping):
            declarations = [declarations]
        if not isinstance(declarations, list):
            raise gemini_invalid_request(
                "Gemini functionDeclarations must be a list.",
                param=f"tools[{tool_index}].functionDeclarations",
            )
        for declaration_index, declaration in enumerate(declarations):
            _validate_function_declaration(
                declaration,
                param=(
                    f"tools[{tool_index}].functionDeclarations[{declaration_index}]"
                ),
            )


def _validate_function_declaration(value: Any, *, param: str) -> None:
    if not isinstance(value, Mapping):
        raise gemini_invalid_request(
            "Gemini function declarations must be objects.",
            param=param,
        )
    if not isinstance(value.get("name"), str) or not value.get("name"):
        raise gemini_invalid_request(
            "Gemini function declaration name must be a non-empty string.",
            param=f"{param}.name",
        )
    parameters = value.get("parameters")
    if parameters is not None and not isinstance(parameters, Mapping):
        raise gemini_invalid_request(
            "Gemini function declaration parameters must be an object.",
            param=f"{param}.parameters",
        )
    parameters_json_schema = _part_value(
        value,
        "parametersJsonSchema",
        "parameters_json_schema",
    )
    if parameters_json_schema is not None and not isinstance(
        parameters_json_schema,
        Mapping,
    ):
        raise gemini_invalid_request(
            "Gemini function declaration parametersJsonSchema must be an object.",
            param=f"{param}.parametersJsonSchema",
        )
    if parameters is not None and parameters_json_schema is not None:
        raise gemini_invalid_request(
            "Gemini function declaration parameters and parametersJsonSchema are "
            "mutually exclusive.",
            param=f"{param}.parametersJsonSchema",
        )


def _validate_tool_config(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise gemini_invalid_request(
            "Gemini toolConfig must be an object.",
            param="toolConfig",
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
            "responseJsonSchema",
            "response_json_schema",
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
        return _normalize_content(value)
    if isinstance(value, list):
        messages: list[NormalizedMessage] = []
        for item in value:
            if isinstance(item, Mapping) or isinstance(item, str):
                messages.extend(_normalize_content(item))
        return _drop_tool_calls_abandoned_by_followup(messages)
    return [NormalizedMessage(role="user", content=str(value))]


def _normalize_content(value: Mapping[str, Any] | str) -> list[NormalizedMessage]:
    if isinstance(value, str):
        return [NormalizedMessage(role="user", content=value)]

    role = _gemini_role_to_normalized(str(value.get("role") or "user"))
    parts = value.get("parts")
    if isinstance(parts, Mapping):
        parts = [parts]
    if not isinstance(parts, list):
        parts = []

    messages: list[NormalizedMessage] = []
    pending_parts: list[NormalizedContentPart] = []
    pending_tool_calls: list[NormalizedToolCall] = []
    raw_extensions = _content_raw_extensions(value)

    def flush_pending_message() -> None:
        if not pending_parts and not pending_tool_calls:
            return
        messages.append(
            NormalizedMessage(
                role=role,
                content=_collapse_text_parts(pending_parts),
                tool_calls=list(pending_tool_calls),
                raw_extensions=raw_extensions,
            )
        )
        pending_parts.clear()
        pending_tool_calls.clear()

    for part in parts:
        if not isinstance(part, Mapping):
            continue
        if "functionResponse" in part or "function_response" in part:
            flush_pending_message()
            messages.append(
                _function_response_to_normalized(
                    part,
                    gemini_role=value.get("role"),
                )
            )
            continue
        if "functionCall" in part or "function_call" in part:
            pending_tool_calls.append(_function_call_to_normalized(part))
            continue
        pending_parts.append(_part_to_normalized(part))

    flush_pending_message()
    if messages:
        return messages
    return [
        NormalizedMessage(
            role=role,
            content=None,
            raw_extensions=raw_extensions,
        )
    ]


def _content_raw_extensions(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"role", "parts"}}


def _gemini_role_to_normalized(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "model":
        return "assistant"
    if normalized == "function":
        return "tool"
    return normalized or "user"


def _normalize_tools(
    value: Any,
    *,
    builtin_tool_mapping_enabled: bool = True,
) -> list[NormalizedTool]:
    if not isinstance(value, list):
        return []

    tools: list[NormalizedTool] = []
    for tool in value:
        if not isinstance(tool, Mapping):
            continue
        if builtin_tool_mapping_enabled:
            tools.extend(_gemini_builtin_tools_to_normalized(tool))
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


def _gemini_builtin_tools_to_normalized(
    tool: Mapping[str, Any],
) -> list[NormalizedTool]:
    normalized_tools: list[NormalizedTool] = []
    seen_fields: set[str] = set()
    for key, value in tool.items():
        if key in _GEMINI_FUNCTION_DECLARATION_KEYS:
            continue
        field_name = normalize_gigachat_builtin_tool_type(key)
        if field_name is None or field_name in seen_fields:
            continue
        seen_fields.add(field_name)
        config = dict(value) if isinstance(value, Mapping) else {}
        normalized_tools.append(
            NormalizedTool(
                type=field_name,
                name=field_name,
                parameters={},
                raw_extensions={field_name: config},
            )
        )
    return normalized_tools


def _unsupported_gemini_tools(
    value: Any,
    *,
    builtin_tool_mapping_enabled: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    unsupported_tools = []
    for tool in value:
        if not isinstance(tool, Mapping):
            continue
        tool_extensions = {
            key: item
            for key, item in tool.items()
            if key not in _GEMINI_FUNCTION_DECLARATION_KEYS
            and (
                not builtin_tool_mapping_enabled
                or normalize_gigachat_builtin_tool_type(key) is None
            )
        }
        if tool_extensions:
            unsupported_tools.append(tool_extensions)
    return unsupported_tools


def _function_declaration_to_normalized(
    declaration: Mapping[str, Any],
    tool: Mapping[str, Any],
) -> NormalizedTool:
    parameters = _function_declaration_parameters(declaration)
    raw_extensions = {
        key: value
        for key, value in declaration.items()
        if key not in {"name", "description"} | _GEMINI_FUNCTION_PARAMETERS_KEYS
    }
    tool_extensions = {
        key: value
        for key, value in tool.items()
        if key not in _GEMINI_FUNCTION_DECLARATION_KEYS
        and normalize_gigachat_builtin_tool_type(key) is None
    }
    if tool_extensions:
        raw_extensions["tool"] = tool_extensions
    return NormalizedTool(
        name=str(declaration.get("name") or ""),
        description=_string_or_none(declaration.get("description")),
        parameters=normalize_tool_parameters_schema(parameters),
        raw_extensions=raw_extensions,
    )


def _function_declaration_parameters(
    declaration: Mapping[str, Any],
) -> Mapping[str, Any]:
    parameters = declaration.get("parameters")
    if isinstance(parameters, Mapping):
        return parameters
    parameters_json_schema = _part_value(
        declaration,
        "parametersJsonSchema",
        "parameters_json_schema",
    )
    if isinstance(parameters_json_schema, Mapping):
        return parameters_json_schema
    return {}


def _function_calling_config(
    tool_config: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    function_calling_config = _part_value(
        tool_config,
        "functionCallingConfig",
        "function_calling_config",
    )
    if function_calling_config is None:
        return None
    if not isinstance(function_calling_config, Mapping):
        raise gemini_invalid_request(
            "Gemini toolConfig.functionCallingConfig must be an object.",
            param="toolConfig.functionCallingConfig",
        )
    return function_calling_config


def _allowed_function_names(
    function_calling_config: Mapping[str, Any] | None,
) -> list[str] | None:
    if function_calling_config is None:
        return None
    allowed_names = _part_value(
        function_calling_config,
        "allowedFunctionNames",
        "allowed_function_names",
    )
    if allowed_names is None:
        return None
    if not isinstance(allowed_names, list):
        raise gemini_invalid_request(
            "Gemini allowedFunctionNames must be a list of function names.",
            param="toolConfig.functionCallingConfig.allowedFunctionNames",
        )
    normalized_names = []
    for name in allowed_names:
        if not isinstance(name, str) or not name:
            raise gemini_invalid_request(
                "Gemini allowedFunctionNames entries must be non-empty strings.",
                param="toolConfig.functionCallingConfig.allowedFunctionNames",
            )
        normalized_names.append(name)
    if not normalized_names:
        raise gemini_invalid_request(
            "Gemini allowedFunctionNames must not be empty when provided.",
            param="toolConfig.functionCallingConfig.allowedFunctionNames",
        )
    return normalized_names


def _validate_allowed_function_names(
    allowed_names: list[str] | None,
    tools: list[NormalizedTool],
) -> None:
    if allowed_names is None:
        return
    declared_names = {tool.name for tool in tools if tool.type == "function"}
    missing_names = [name for name in allowed_names if name not in declared_names]
    if missing_names:
        missing = ", ".join(missing_names)
        raise gemini_invalid_request(
            f"Gemini allowedFunctionNames reference undeclared functions: {missing}.",
            param="toolConfig.functionCallingConfig.allowedFunctionNames",
        )


def _filter_tools_by_allowed_names(
    tools: list[NormalizedTool],
    allowed_names: list[str] | None,
) -> list[NormalizedTool]:
    if allowed_names is None:
        return tools
    allowed = set(allowed_names)
    return [tool for tool in tools if tool.type != "function" or tool.name in allowed]


def _normalize_tool_choice(
    function_calling_config: Mapping[str, Any] | None,
    *,
    allowed_names: list[str] | None,
    tools: list[NormalizedTool],
) -> Any | None:
    if function_calling_config is None:
        return None
    mode = _function_calling_mode(function_calling_config.get("mode"))
    if mode == "none":
        return "none"
    if mode == "auto":
        return "auto"
    candidate_names = allowed_names or _unique_function_tool_names(tools)
    if len(candidate_names) == 1:
        return {"type": "function", "function": {"name": candidate_names[0]}}
    if not candidate_names:
        raise gemini_invalid_request(
            "Gemini functionCallingConfig mode ANY requires at least one declared "
            "function.",
            param="toolConfig.functionCallingConfig.mode",
        )
    raise gemini_invalid_request(
        "Gemini functionCallingConfig mode ANY with multiple candidate functions "
        "is not supported by this backend; provide exactly one allowedFunctionNames "
        "entry to force a function.",
        param="toolConfig.functionCallingConfig.allowedFunctionNames",
    )


def _function_calling_mode(value: Any) -> str:
    if value is None:
        return "auto"
    if not isinstance(value, str):
        raise gemini_invalid_request(
            "Gemini functionCallingConfig.mode must be a string.",
            param="toolConfig.functionCallingConfig.mode",
        )
    mode = value.strip().upper()
    if mode in {"AUTO", "MODE_UNSPECIFIED"}:
        return "auto"
    if mode == "NONE":
        return "none"
    if mode == "ANY":
        return "any"
    raise gemini_invalid_request(
        f"Unsupported Gemini functionCallingConfig.mode: {value}.",
        param="toolConfig.functionCallingConfig.mode",
    )


def _unique_function_tool_names(tools: list[NormalizedTool]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        if tool.type != "function":
            continue
        if tool.name and tool.name not in names:
            names.append(tool.name)
    return names


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
    schema = _response_json_schema_value(config)
    if schema is None:
        schema = _response_schema_value(config)
    if not isinstance(mime_type, str):
        return None
    if mime_type == "text/plain":
        return None
    if mime_type == "application/json":
        if not isinstance(schema, Mapping):
            return None
        return NormalizedResponseFormat(
            type="json_schema",
            json_schema={"schema": dict(schema)},
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
        id=_string_or_none(function_call.get("id")),
        type="function",
        name=_string_or_none(function_call.get("name")),
        arguments=function_call.get("args", {}),
        raw_extensions={
            key: value
            for key, value in function_call.items()
            if key not in {"id", "name", "args"}
        },
    )


def _function_response_payload(part: Mapping[str, Any]) -> dict[str, Any]:
    function_response = _part_value(part, "functionResponse", "function_response")
    if not isinstance(function_response, Mapping):
        raise gemini_invalid_request(
            "Gemini functionResponse parts must be objects.",
            param="contents.parts.functionResponse",
        )
    return dict(function_response)


def _function_response_to_normalized(
    part: Mapping[str, Any],
    *,
    gemini_role: Any,
) -> NormalizedMessage:
    function_response = _function_response_payload(part)
    tool_call_id = _string_or_none(function_response.get("id"))
    return NormalizedMessage(
        role="tool",
        content=json.dumps(function_response.get("response", {}), ensure_ascii=False),
        name=_string_or_none(function_response.get("name")),
        tool_call_id=tool_call_id or _string_or_none(function_response.get("name")),
        raw_extensions={
            "gemini_role": gemini_role,
            "functionResponse": function_response,
        },
    )


def _drop_tool_calls_abandoned_by_followup(
    messages: list[NormalizedMessage],
) -> list[NormalizedMessage]:
    """Drop Gemini function calls only after a later non-tool turn abandons them."""
    pending: list[tuple[int, int, NormalizedToolCall]] = []

    for message_index, message in enumerate(messages):
        if message.role == "tool":
            _resolve_pending_tool_response(message, pending)
            continue

        if pending:
            _remove_pending_tool_calls(messages, pending)
            pending.clear()

        if message.role == "assistant" and message.tool_calls:
            pending.extend(
                (message_index, call_index, tool_call)
                for call_index, tool_call in enumerate(message.tool_calls)
            )

    return [
        message
        for message in messages
        if not (
            message.role == "assistant"
            and not message.tool_calls
            and not _message_has_content(message)
        )
    ]


def _resolve_pending_tool_response(
    message: NormalizedMessage,
    pending: list[tuple[int, int, NormalizedToolCall]],
) -> None:
    if not pending:
        return
    response_keys = _tool_response_keys(message)
    for index, (_message_index, _call_index, tool_call) in enumerate(pending):
        if response_keys and response_keys.isdisjoint(_tool_call_keys(tool_call)):
            continue
        pending.pop(index)
        return


def _remove_pending_tool_calls(
    messages: list[NormalizedMessage],
    pending: list[tuple[int, int, NormalizedToolCall]],
) -> None:
    pending_indexes_by_message: dict[int, set[int]] = {}
    for message_index, call_index, _tool_call in pending:
        pending_indexes_by_message.setdefault(message_index, set()).add(call_index)

    for message_index, pending_indexes in pending_indexes_by_message.items():
        message = messages[message_index]
        message.tool_calls = [
            tool_call
            for call_index, tool_call in enumerate(message.tool_calls)
            if call_index not in pending_indexes
        ]


def _tool_response_keys(message: NormalizedMessage) -> set[str]:
    keys = set()
    if message.tool_call_id:
        keys.add(f"id:{message.tool_call_id}")
    if message.name:
        keys.add(f"name:{message.name}")
    return keys


def _tool_call_keys(tool_call: NormalizedToolCall) -> set[str]:
    keys = set()
    if tool_call.id:
        keys.add(f"id:{tool_call.id}")
    if tool_call.name:
        keys.add(f"name:{tool_call.name}")
    return keys


def _message_has_content(message: NormalizedMessage) -> bool:
    content = message.content
    if isinstance(content, str):
        return bool(content)
    return content is not None


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


def _response_schema_value(mapping: Mapping[str, Any]) -> Any:
    return _part_value(mapping, "responseSchema", "response_schema")


def _response_json_schema_value(mapping: Mapping[str, Any]) -> Any:
    return _part_value(mapping, "responseJsonSchema", "response_json_schema")


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
