"""Gemini Developer API request helpers."""

from __future__ import annotations

import json
from urllib.parse import urlsplit
from typing import Any, Iterable, Optional

from fastapi import Request

from gpt2giga.providers.gigachat.tool_mapping import convert_tool_to_giga_functions


class GeminiAPIError(Exception):
    """Provider-specific API error for Gemini-compatible routes."""

    def __init__(
        self,
        *,
        status_code: int,
        status: str,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.status = status
        self.message = message
        self.details = details


def normalize_model_name(model: Optional[str]) -> str:
    """Normalize a Gemini model resource name to a plain model id."""
    value = (model or "").strip().strip("/")
    if not value:
        return ""

    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        value = parsed.path.strip("/")

    if "/models/" in value:
        value = value.rsplit("/models/", 1)[-1]
    elif value.startswith("models/"):
        value = value.split("/", 1)[1]

    if ":" in value:
        value = value.split(":", 1)[0]

    return value.strip("/")


def model_resource_name(model: str) -> str:
    """Return a Gemini `models/...` resource name."""
    normalized = normalize_model_name(model)
    if not normalized:
        return "models/unknown"
    return f"models/{normalized}"


async def read_gemini_request_json(request: Request) -> dict:
    """Read and validate a Gemini API request body."""
    body = await request.body()
    if not body or not body.strip():
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="Request body is empty (expected JSON object).",
        )
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=f"Invalid JSON body: {exc.msg}",
        ) from exc
    if not isinstance(data, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="Invalid JSON body: expected an object at the top level.",
        )
    return data


def _lowercase_schema_types(value: Any) -> Any:
    """Normalize JSON Schema `type` values to lowercase strings."""
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key == "type":
                if isinstance(item, str):
                    normalized[key] = item.lower()
                elif isinstance(item, list):
                    normalized[key] = [
                        part.lower() if isinstance(part, str) else part for part in item
                    ]
                else:
                    normalized[key] = item
            else:
                normalized[key] = _lowercase_schema_types(item)
        return normalized
    if isinstance(value, list):
        return [_lowercase_schema_types(item) for item in value]
    return value


def _get_function_parameters_schema(declaration: dict[str, Any]) -> dict[str, Any]:
    """Extract a Gemini function schema from either supported parameter field."""
    schema = declaration.get("parametersJsonSchema")
    if schema is None:
        schema = declaration.get("parameters_json_schema")
    if schema is None:
        schema = declaration.get("parameters", {"type": "object", "properties": {}})
    if not isinstance(schema, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=(
                "Each function declaration `parameters` schema must be an object."
            ),
        )
    return _lowercase_schema_types(schema)


def _thinking_to_reasoning_effort(thinking_config: Any) -> Optional[str]:
    """Map Gemini thinking config to the closest GigaChat reasoning effort."""
    if not isinstance(thinking_config, dict):
        return None

    thinking_level = str(thinking_config.get("thinkingLevel", "")).upper()
    if thinking_level == "HIGH":
        return "high"
    if thinking_level == "MEDIUM":
        return "medium"
    if thinking_level in {"LOW", "MINIMAL"}:
        return "low"

    budget = thinking_config.get("thinkingBudget")
    if budget is None:
        return None
    try:
        budget_value = int(budget)
    except (TypeError, ValueError):
        return None

    if budget_value == 0:
        return None
    if budget_value == -1 or budget_value >= 8000:
        return "high"
    if budget_value >= 3000:
        return "medium"
    return "low"


def _extract_text_from_parts(parts: Iterable[Any]) -> list[str]:
    """Extract visible text from Gemini parts."""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
            continue
        function_call = part.get("functionCall")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            args = function_call.get("args")
            if name:
                texts.append(str(name))
            if args:
                texts.append(json.dumps(args, ensure_ascii=False))
            continue
        function_response = part.get("functionResponse")
        if isinstance(function_response, dict):
            name = function_response.get("name")
            response = function_response.get("response")
            if name:
                texts.append(str(name))
            if response:
                texts.append(json.dumps(response, ensure_ascii=False))
    return texts


def _extract_text_from_system_instruction(system_instruction: Any) -> str:
    """Extract text content from a Gemini system instruction."""
    if isinstance(system_instruction, str):
        return system_instruction
    if isinstance(system_instruction, dict):
        return "\n".join(_extract_text_from_parts(system_instruction.get("parts", [])))
    if isinstance(system_instruction, list):
        return "\n".join(_extract_text_from_parts(system_instruction))
    return ""


def _raise_if_unsupported_part(part: Any) -> None:
    """Reject Gemini multimodal parts that are not supported in the MVP."""
    if not isinstance(part, dict):
        return
    unsupported_fields = (
        "inlineData",
        "executableCode",
        "codeExecutionResult",
        "videoMetadata",
    )
    for field in unsupported_fields:
        if part.get(field) is not None:
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message=f"Gemini part `{field}` is not supported by this proxy yet.",
            )


def normalize_file_name(name: str | None) -> str:
    """Normalize a Gemini file resource name or bare id to a file id."""
    value = (name or "").strip().strip("/")
    if value.startswith("files/"):
        return value.split("/", 1)[1]
    return value


def extract_file_id_from_uri(uri: str | None) -> str | None:
    """Extract a Gemini file id from a resource name or proxy URI."""
    value = (uri or "").strip()
    if not value:
        return None
    if value.startswith("files/"):
        return normalize_file_name(value)

    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if "/files/" not in path:
        return None

    file_id = path.rsplit("/files/", maxsplit=1)[-1]
    if not file_id:
        return None
    file_id = file_id.split("/", 1)[0]
    file_id = file_id.split(":", 1)[0]
    normalized = normalize_file_name(file_id)
    return normalized or None


def _normalize_contents(contents: Any) -> list[dict[str, Any]]:
    """Normalize Gemini contents to a list of content objects."""
    if contents is None:
        return []
    if isinstance(contents, str):
        return [{"role": "user", "parts": [{"text": contents}]}]
    if isinstance(contents, dict):
        return [contents]
    if isinstance(contents, list):
        if not contents:
            return []
        if all(isinstance(item, str) for item in contents):
            return [{"role": "user", "parts": [{"text": "\n".join(contents)}]}]
        return [
            item if isinstance(item, dict) else {"role": "user", "parts": [item]}
            for item in contents
        ]
    raise GeminiAPIError(
        status_code=400,
        status="INVALID_ARGUMENT",
        message="`contents` must be a string, object, or array.",
    )


def _convert_gemini_contents_to_openai(contents: Any) -> list[dict[str, Any]]:
    """Convert Gemini contents into the OpenAI-style intermediary format."""
    openai_messages: list[dict[str, Any]] = []

    for content in _normalize_contents(contents):
        role = content.get("role") or "user"
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
        tool_messages: list[dict[str, Any]] = []

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

            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
                continue

            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                tool_calls.append(
                    {
                        "id": function_call.get("id")
                        or f"call_{len(openai_messages)}_{index}",
                        "type": "function",
                        "function": {
                            "name": function_call.get("name", ""),
                            "arguments": json.dumps(
                                function_call.get("args", {}), ensure_ascii=False
                            ),
                        },
                    }
                )
                continue

            function_response = part.get("functionResponse")
            if isinstance(function_response, dict):
                tool_messages.append(
                    {
                        "role": "tool",
                        "name": function_response.get("name", ""),
                        "content": json.dumps(
                            function_response.get("response", {}), ensure_ascii=False
                        ),
                    }
                )
                continue

        if role == "model":
            message: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else "",
            }
            if tool_calls:
                message["tool_calls"] = tool_calls
            openai_messages.append(message)
            continue

        if text_parts:
            openai_messages.append({"role": "user", "content": "\n".join(text_parts)})
        openai_messages.extend(tool_messages)

    return openai_messages


def _convert_gemini_tools_to_openai(tools: list[Any]) -> list[dict[str, Any]]:
    """Convert Gemini function declarations to OpenAI tools format."""
    openai_tools: list[dict[str, Any]] = []

    for tool in tools:
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
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": declaration.get("name", ""),
                        "description": declaration.get("description", ""),
                        "parameters": parameters,
                    },
                }
            )
    return openai_tools


def _extract_tool_definition_text(tools: list[Any]) -> list[str]:
    """Extract tool definition text for token counting."""
    texts: list[str] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        declarations = tool.get("functionDeclarations")
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if not isinstance(declaration, dict):
                continue
            parts = [
                str(declaration.get("name", "")),
                str(declaration.get("description", "")),
            ]
            parameters = _get_function_parameters_schema(declaration)
            if parameters:
                parts.append(json.dumps(parameters, ensure_ascii=False))
            text = " ".join(part for part in parts if part)
            if text:
                texts.append(text)
    return texts


def build_openai_data_from_gemini_request(
    data: dict[str, Any],
    logger: Any,
) -> dict[str, Any]:
    """Translate a Gemini generateContent request into the shared intermediary."""
    contents = data.get("contents")
    if contents is None:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`contents` is required.",
        )

    generation_config = data.get("generationConfig") or {}
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

    openai_data: dict[str, Any] = {
        "model": normalize_model_name(data.get("model", "unknown")),
        "messages": _convert_gemini_contents_to_openai(contents),
    }

    system_text = _extract_text_from_system_instruction(data.get("systemInstruction"))
    if system_text:
        openai_data["messages"].insert(0, {"role": "system", "content": system_text})

    if generation_config.get("temperature") is not None:
        openai_data["temperature"] = generation_config["temperature"]
    if generation_config.get("topP") is not None:
        openai_data["top_p"] = generation_config["topP"]
    if generation_config.get("maxOutputTokens") is not None:
        openai_data["max_tokens"] = generation_config["maxOutputTokens"]
    if generation_config.get("stopSequences") is not None:
        openai_data["stop"] = generation_config["stopSequences"]

    response_mime_type = generation_config.get("responseMimeType")
    response_schema = generation_config.get("responseJsonSchema")
    if response_schema is None:
        response_schema = generation_config.get("responseSchema")

    if response_schema is not None:
        openai_data["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "gemini_structured_output",
                "schema": _lowercase_schema_types(response_schema),
            },
        }
    elif response_mime_type == "application/json":
        openai_data["response_format"] = {"type": "json_object"}

    reasoning_effort = _thinking_to_reasoning_effort(
        generation_config.get("thinkingConfig")
    )
    if reasoning_effort:
        openai_data["reasoning_effort"] = reasoning_effort

    tools = data.get("tools")
    if tools:
        openai_data["tools"] = _convert_gemini_tools_to_openai(tools)
        openai_data["functions"] = convert_tool_to_giga_functions(openai_data)
        if logger:
            logger.debug(f"Functions count: {len(openai_data['functions'])}")

    tool_config = data.get("toolConfig") or {}
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
        openai_data.pop("tools", None)
        openai_data.pop("functions", None)
    elif mode in {"ANY", "VALIDATED"} and len(allowed_names) == 1:
        openai_data["function_call"] = {"name": allowed_names[0]}

    return openai_data


def extract_text_for_token_count(data: dict[str, Any]) -> list[str]:
    """Extract text and tool definitions for Gemini countTokens."""
    texts: list[str] = []
    contents = data.get("contents")
    if contents is not None:
        for content in _normalize_contents(contents):
            if isinstance(content, dict):
                texts.extend(_extract_text_from_parts(content.get("parts", [])))
    system_text = _extract_text_from_system_instruction(data.get("systemInstruction"))
    if system_text:
        texts.append(system_text)
    tools = data.get("tools")
    if isinstance(tools, list):
        _convert_gemini_tools_to_openai(tools)
        texts.extend(_extract_tool_definition_text(tools))
    return [text for text in texts if text]


def extract_embed_texts(requests_payload: list[Any], route_model: str) -> list[str]:
    """Extract embedding inputs from Gemini batchEmbedContents requests."""
    texts: list[str] = []
    normalized_route_model = normalize_model_name(route_model)
    for index, item in enumerate(requests_payload):
        if not isinstance(item, dict):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each item in `requests` must be an object.",
            )
        request_model = normalize_model_name(item.get("model"))
        if request_model and request_model != normalized_route_model:
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message=(
                    f"Embedding request at index {index} targets model "
                    f"`{item.get('model')}`, but the route model is `{route_model}`."
                ),
            )
        content = item.get("content")
        if not isinstance(content, dict):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each embedding request must contain a `content` object.",
            )
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each embedding request content must contain a non-empty `parts` array.",
            )
        for part in parts:
            _raise_if_unsupported_part(part)
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        joined = "\n".join(
            text for text in text_parts if isinstance(text, str) and text
        )
        if not joined:
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Only text embeddings are supported by this proxy.",
            )
        texts.append(joined)
    return texts
