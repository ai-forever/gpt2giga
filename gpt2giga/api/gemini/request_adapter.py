"""Gemini transport adapter over canonical internal contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from gpt2giga.api.gemini.request import (
    GeminiAPIError,
    extract_file_id_from_uri,
    _extract_text_from_parts,
    _extract_text_from_system_instruction,
    _get_function_parameters_schema,
    _lowercase_schema_types,
    _normalize_contents,
    _raise_if_unsupported_part,
    _thinking_to_reasoning_effort,
    extract_embed_texts,
    model_resource_name,
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

        content_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        tool_messages: list[NormalizedMessage] = []

        for index, part in enumerate(parts):
            if isinstance(part, str):
                content_parts.append({"type": "text", "text": part})
                continue
            if not isinstance(part, dict):
                raise GeminiAPIError(
                    status_code=400,
                    status="INVALID_ARGUMENT",
                    message="Each Gemini part must be an object or string.",
                )

            text = part.get("text")
            if isinstance(text, str):
                content_parts.append({"type": "text", "text": text})
                continue

            file_data = part.get("fileData")
            if isinstance(file_data, dict):
                file_uri = file_data.get("fileUri") or file_data.get("file_uri")
                file_id = extract_file_id_from_uri(file_uri)
                file_payload: dict[str, Any] = {}
                if file_id:
                    file_payload["file_id"] = file_id
                elif isinstance(file_uri, str) and file_uri:
                    file_payload["file_url"] = file_uri

                filename = file_data.get("displayName") or file_data.get("display_name")
                if isinstance(filename, str) and filename:
                    file_payload["filename"] = filename
                mime_type = file_data.get("mimeType") or file_data.get("mime_type")
                if isinstance(mime_type, str) and mime_type:
                    file_payload["mime_type"] = mime_type

                if not file_payload:
                    raise GeminiAPIError(
                        status_code=400,
                        status="INVALID_ARGUMENT",
                        message=(
                            "Gemini part `fileData` must include a valid `fileUri`."
                        ),
                    )
                content_parts.append({"type": "file", "file": file_payload})
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
            normalized_content: str | list[dict[str, Any]] = ""
            if content_parts:
                text_only = all(part.get("type") == "text" for part in content_parts)
                if text_only:
                    normalized_content = "\n".join(
                        part.get("text", "") for part in content_parts
                    )
                else:
                    normalized_content = content_parts
            normalized_messages.append(
                NormalizedMessage(
                    role="assistant",
                    content=normalized_content,
                    tool_calls=tool_calls,
                )
            )
            continue

        if content_parts:
            text_only = all(part.get("type") == "text" for part in content_parts)
            normalized_messages.append(
                NormalizedMessage(
                    role="user",
                    content=(
                        "\n".join(part.get("text", "") for part in content_parts)
                        if text_only
                        else content_parts
                    ),
                )
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


def serialize_normalized_chat_request(
    request: NormalizedChatRequest,
) -> tuple[dict[str, Any], list[str]]:
    """Render a canonical chat request as a Gemini generateContent payload."""
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []

    for message in request.messages:
        if message.role == "system":
            system_parts.extend(_message_content_to_gemini_parts(message.content))
            continue
        if message.role == "assistant":
            parts = _message_content_to_gemini_parts(message.content)
            parts.extend(_tool_calls_to_gemini_parts(message.tool_calls))
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue
        if message.role == "user":
            parts = _message_content_to_gemini_parts(message.content)
            if parts:
                contents.append({"role": "user", "parts": parts})
            continue
        if message.role in {"tool", "function"}:
            contents.append(
                {
                    "role": "user",
                    "parts": [_tool_message_to_gemini_part(message)],
                }
            )
            continue

        text = _stringify_content(message.content)
        if text:
            contents.append({"role": "user", "parts": [{"text": text}]})

    payload: dict[str, Any] = {
        "model": model_resource_name(request.model),
        "contents": contents,
    }
    warnings: list[str] = []

    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}

    generation_config: dict[str, Any] = {}
    _set_if_present(generation_config, "temperature", request.options, "temperature")
    _set_if_present(generation_config, "topP", request.options, "top_p")
    _set_if_present(generation_config, "maxOutputTokens", request.options, "max_tokens")

    stop_sequences = request.options.get("stop")
    if stop_sequences is not None:
        generation_config["stopSequences"] = deepcopy(stop_sequences)

    response_format = request.options.get("response_format")
    if isinstance(response_format, dict):
        if response_format.get("type") == "json_object":
            generation_config["responseMimeType"] = "application/json"
        elif response_format.get("type") == "json_schema":
            json_schema = response_format.get("json_schema")
            if isinstance(json_schema, dict):
                schema = json_schema.get("schema")
                if isinstance(schema, dict):
                    generation_config["responseJsonSchema"] = deepcopy(schema)

    reasoning_effort = request.options.get("reasoning_effort")
    if reasoning_effort in {"low", "medium", "high"}:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": reasoning_effort.upper(),
        }

    if generation_config:
        payload["generationConfig"] = generation_config

    if request.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": deepcopy(tool.parameters),
                    }
                    for tool in request.tools
                ]
            }
        ]

    function_call = request.options.get("function_call")
    if isinstance(function_call, dict):
        tool_name = function_call.get("name")
        if isinstance(tool_name, str) and tool_name:
            payload["toolConfig"] = {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [tool_name],
                }
            }

    ignored_options = sorted(
        set(request.options)
        - {
            "function_call",
            "functions",
            "max_tokens",
            "reasoning_effort",
            "response_format",
            "stop",
            "temperature",
            "top_p",
        }
    )
    if ignored_options:
        warnings.append(
            "Gemini translation ignored unsupported options: "
            + ", ".join(ignored_options)
        )

    return payload, warnings


def _message_content_to_gemini_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        text = _stringify_content(content)
        return [{"text": text}] if text else []

    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                parts.append({"text": text})
            continue
        if part_type == "image_url":
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                continue
            url = image_url.get("url")
            if not isinstance(url, str) or not url:
                continue
            parts.append(_image_url_to_gemini_part(url))
            continue
        raise ValueError(f"Unsupported Gemini content part type: {part_type}")
    return parts


def _tool_calls_to_gemini_parts(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if not isinstance(function, dict):
            continue
        parts.append(
            {
                "functionCall": {
                    "id": tool_call.get("id") or f"call_{index}",
                    "name": function.get("name", ""),
                    "args": _decode_json_value(function.get("arguments")),
                }
            }
        )
    return parts


def _tool_message_to_gemini_part(message: NormalizedMessage) -> dict[str, Any]:
    response = _decode_json_value(message.content)
    if not isinstance(response, dict):
        response = {"content": response}
    return {
        "functionResponse": {
            "name": message.name or "",
            "response": response,
        }
    }


def _image_url_to_gemini_part(url: str) -> dict[str, Any]:
    if not url.startswith("data:") or ";base64," not in url:
        raise ValueError(
            "Gemini translation supports image parts only as `data:` URLs."
        )
    prefix, data = url.split(",", 1)
    media_type = prefix[5:].split(";", 1)[0] or "image/png"
    return {"inlineData": {"mimeType": media_type, "data": data}}


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return deepcopy(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_extract_text_from_parts(content))
    if content is None:
        return ""
    return str(content)


def _set_if_present(
    payload: dict[str, Any],
    payload_key: str,
    options: dict[str, Any],
    option_key: str,
) -> None:
    value = options.get(option_key)
    if value is not None:
        payload[payload_key] = deepcopy(value)
