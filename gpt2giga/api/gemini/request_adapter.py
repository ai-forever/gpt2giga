"""Gemini transport adapter over canonical internal contracts."""

from __future__ import annotations

import json
from typing import Any

from gpt2giga.api.gemini.request import (
    GeminiAPIError,
    _extract_text_from_parts,
    _extract_text_from_system_instruction,
    _get_function_parameters_schema,
    _lowercase_schema_types,
    _normalize_contents,
    _raise_if_unsupported_part,
    _thinking_to_reasoning_effort,
    extract_embed_texts,
    normalize_model_name,
)
from gpt2giga.core.contracts import (
    NormalizedChatRequest,
    NormalizedEmbeddingsRequest,
    NormalizedMessage,
    NormalizedTool,
)
from gpt2giga.providers.gigachat.tool_mapping import convert_tool_to_giga_functions


def _build_normalized_messages(
    contents: Any,
    *,
    system_instruction: Any = None,
) -> list[NormalizedMessage]:
    normalized_messages: list[NormalizedMessage] = []
    system_text = _extract_text_from_system_instruction(system_instruction)
    if system_text:
        normalized_messages.append(
            NormalizedMessage(role="system", content=system_text)
        )

    for content in _normalize_contents(contents):
        if not isinstance(content, dict):
            continue

        role = str(content.get("role") or "user")
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each Gemini content item must contain a `parts` array.",
            )

        for part in parts:
            _raise_if_unsupported_part(part)

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_messages: list[NormalizedMessage] = []

        for index, part in enumerate(parts):
            if isinstance(part, str):
                text_parts.append(part)
                continue
            if not isinstance(part, dict):
                raise GeminiAPIError(
                    status_code=400,
                    status="INVALID_ARGUMENT",
                    message="Each Gemini part must be an object or string.",
                )

            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
                continue

            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                tool_calls.append(
                    {
                        "id": function_call.get("id")
                        or f"call_{len(normalized_messages)}_{index}",
                        "type": "function",
                        "function": {
                            "name": function_call.get("name", ""),
                            "arguments": json.dumps(
                                function_call.get("args", {}),
                                ensure_ascii=False,
                            ),
                        },
                    }
                )
                continue

            function_response = part.get("functionResponse")
            if isinstance(function_response, dict):
                tool_messages.append(
                    NormalizedMessage(
                        role="tool",
                        name=function_response.get("name", ""),
                        content=json.dumps(
                            function_response.get("response", {}),
                            ensure_ascii=False,
                        ),
                    )
                )

        if role == "model":
            normalized_messages.append(
                NormalizedMessage(
                    role="assistant",
                    content="\n".join(text_parts) if text_parts else "",
                    tool_calls=tool_calls,
                )
            )
            continue

        if text_parts:
            normalized_messages.append(
                NormalizedMessage(role="user", content="\n".join(text_parts))
            )
        normalized_messages.extend(tool_messages)

    return normalized_messages


def _build_normalized_tools(payload: dict[str, Any]) -> list[NormalizedTool]:
    tools_payload = payload.get("tools")
    if not tools_payload:
        return []
    if not isinstance(tools_payload, list):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`tools` must be an array when provided.",
        )

    normalized_tools: list[NormalizedTool] = []
    for tool in tools_payload:
        if not isinstance(tool, dict):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each Gemini tool must be an object.",
            )
        declarations = tool.get("functionDeclarations")
        if declarations is None:
            unsupported = next(
                (key for key in tool if key != "functionDeclarations"),
                None,
            )
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message=(
                    f"Gemini built-in tool `{unsupported or 'unknown'}` is not supported "
                    "by this proxy yet."
                ),
            )
        if not isinstance(declarations, list):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="`functionDeclarations` must be an array.",
            )

        for declaration in declarations:
            if not isinstance(declaration, dict):
                raise GeminiAPIError(
                    status_code=400,
                    status="INVALID_ARGUMENT",
                    message="Each function declaration must be an object.",
                )
            parameters = _get_function_parameters_schema(declaration)
            normalized_tools.append(
                NormalizedTool(
                    name=str(declaration.get("name", "")),
                    description=declaration.get("description"),
                    parameters=parameters,
                    raw={
                        "type": "function",
                        "function": {
                            "name": declaration.get("name", ""),
                            "description": declaration.get("description", ""),
                            "parameters": parameters,
                        },
                    },
                )
            )

    return normalized_tools


def build_normalized_chat_request(
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> NormalizedChatRequest:
    """Build a canonical internal request from a Gemini generateContent payload."""
    contents = payload.get("contents")
    if contents is None:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`contents` is required.",
        )

    generation_config = payload.get("generationConfig") or {}
    if not isinstance(generation_config, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`generationConfig` must be an object when provided.",
        )

    candidate_count = generation_config.get("candidateCount")
    if candidate_count not in (None, 1):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="Only `candidateCount=1` is supported by this proxy.",
        )

    tools = _build_normalized_tools(payload)
    tool_config = payload.get("toolConfig") or {}
    if tool_config and not isinstance(tool_config, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`toolConfig` must be an object when provided.",
        )
    function_calling_config = tool_config.get("functionCallingConfig") or {}
    if function_calling_config and not isinstance(function_calling_config, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`toolConfig.functionCallingConfig` must be an object.",
        )

    mode = str(function_calling_config.get("mode", "")).upper()
    allowed_names = function_calling_config.get("allowedFunctionNames") or []
    if mode == "NONE":
        tools = []

    options: dict[str, Any] = {}
    if generation_config.get("temperature") is not None:
        options["temperature"] = generation_config["temperature"]
    if generation_config.get("topP") is not None:
        options["top_p"] = generation_config["topP"]
    if generation_config.get("maxOutputTokens") is not None:
        options["max_tokens"] = generation_config["maxOutputTokens"]
    if generation_config.get("stopSequences") is not None:
        options["stop"] = generation_config["stopSequences"]

    response_mime_type = generation_config.get("responseMimeType")
    response_schema = generation_config.get("responseJsonSchema")
    if response_schema is None:
        response_schema = generation_config.get("responseSchema")
    if response_schema is not None:
        options["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "gemini_structured_output",
                "schema": _lowercase_schema_types(response_schema),
            },
        }
    elif response_mime_type == "application/json":
        options["response_format"] = {"type": "json_object"}

    reasoning_effort = _thinking_to_reasoning_effort(
        generation_config.get("thinkingConfig")
    )
    if reasoning_effort:
        options["reasoning_effort"] = reasoning_effort

    if tools:
        tool_payload = {"tools": [tool.to_openai_tool() for tool in tools]}
        options["functions"] = convert_tool_to_giga_functions(tool_payload)
        if logger is not None:
            logger.debug(f"Functions count: {len(options['functions'])}")

    if mode in {"ANY", "VALIDATED"} and len(allowed_names) == 1:
        options["function_call"] = {"name": allowed_names[0]}

    return NormalizedChatRequest(
        model=normalize_model_name(payload.get("model", "unknown")),
        messages=_build_normalized_messages(
            contents,
            system_instruction=payload.get("systemInstruction"),
        ),
        stream=False,
        tools=tools,
        options=options,
    )


def build_count_tokens_texts(payload: dict[str, Any]) -> list[str]:
    """Extract token-count texts from a Gemini generateContent payload."""
    request = build_normalized_chat_request(payload)
    texts: list[str] = []

    for message in request.messages:
        content = message.content
        if isinstance(content, str):
            if content:
                texts.append(content)
            continue
        if isinstance(content, list):
            texts.extend(_extract_text_from_parts(content))

    for tool in request.tools:
        parts = [tool.name]
        if tool.description:
            parts.append(tool.description)
        if tool.parameters:
            parts.append(json.dumps(tool.parameters, ensure_ascii=False))
        text = " ".join(part for part in parts if part)
        if text:
            texts.append(text)

    return texts


def build_batch_embeddings_request(
    requests_payload: list[Any],
    route_model: str,
) -> NormalizedEmbeddingsRequest:
    """Build a canonical embeddings request from batchEmbedContents payload."""
    return NormalizedEmbeddingsRequest(
        model=normalize_model_name(route_model),
        input=extract_embed_texts(requests_payload, route_model),
    )


def build_single_embeddings_request(
    payload: dict[str, Any],
    route_model: str,
) -> NormalizedEmbeddingsRequest:
    """Build a canonical embeddings request from embedContent payload."""
    content = payload.get("content")
    if content is None and payload.get("contents") is not None:
        contents = payload.get("contents")
        if isinstance(contents, list) and len(contents) == 1:
            content = contents[0]
        else:
            content = (
                {"role": "user", "parts": contents}
                if isinstance(contents, list)
                else contents
            )
    if not isinstance(content, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`content` must be provided for `embedContent`.",
        )
    return build_batch_embeddings_request(
        [{"model": route_model, "content": content}],
        route_model,
    )
