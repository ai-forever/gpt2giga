"""OpenAI transport adapter over the canonical internal contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from gpt2giga.core.contracts import (
    NormalizedChatRequest,
    NormalizedEmbeddingsRequest,
    NormalizedMessage,
    NormalizedResponsesRequest,
    NormalizedTool,
)
from gpt2giga.providers.gigachat.tool_mapping import convert_tool_to_giga_functions


def _build_normalized_tools(payload: dict[str, Any]) -> list[NormalizedTool]:
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        return [
            NormalizedTool.from_openai_tool(tool)
            for tool in tools
            if isinstance(tool, dict)
        ]

    functions = payload.get("functions")
    if isinstance(functions, list) and functions:
        return [
            NormalizedTool.from_openai_function(function)
            for function in functions
            if isinstance(function, dict)
        ]

    return []


def _build_functions(
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> list[Any] | None:
    if "tools" not in payload and "functions" not in payload:
        return None
    functions = convert_tool_to_giga_functions(payload)
    if logger is not None:
        logger.debug(f"Functions count: {len(functions)}")
    return functions


def _coerce_chat_messages(payload: dict[str, Any]) -> list[NormalizedMessage]:
    messages = payload.get("messages")
    if isinstance(messages, list):
        return [
            NormalizedMessage.from_openai_message(message)
            for message in messages
            if isinstance(message, dict)
        ]

    input_ = payload.get("input")
    if isinstance(input_, str):
        return [NormalizedMessage(role="user", content=input_)]
    if isinstance(input_, list):
        normalized_messages: list[NormalizedMessage] = []
        for item in input_:
            if isinstance(item, dict) and item.get("role"):
                normalized_messages.append(NormalizedMessage.from_openai_message(item))
            elif isinstance(item, str):
                normalized_messages.append(NormalizedMessage(role="user", content=item))
        return normalized_messages
    return []


def build_normalized_chat_request(
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> NormalizedChatRequest:
    """Build a canonical internal request from an OpenAI chat payload."""
    request_payload = deepcopy(payload)
    tools = _build_normalized_tools(request_payload)
    functions = _build_functions(request_payload, logger=logger)
    options = deepcopy(request_payload)
    options.pop("model", None)
    options.pop("messages", None)
    options.pop("input", None)
    options.pop("stream", None)
    options.pop("tools", None)
    options.pop("functions", None)
    if functions is not None:
        options["functions"] = functions
    return NormalizedChatRequest(
        model=str(request_payload.get("model", "unknown")),
        messages=_coerce_chat_messages(request_payload),
        stream=bool(request_payload.get("stream", False)),
        tools=tools,
        options=options,
    )


def _normalize_responses_input(
    payload: dict[str, Any],
) -> str | list[NormalizedMessage | dict[str, Any] | str] | None:
    input_ = payload.get("input")
    if isinstance(input_, list):
        normalized_input: list[NormalizedMessage | dict[str, Any] | str] = []
        for item in input_:
            if isinstance(item, dict) and item.get("role"):
                normalized_input.append(NormalizedMessage.from_openai_message(item))
            elif isinstance(item, (dict, str)):
                normalized_input.append(deepcopy(item))
        return normalized_input
    if isinstance(input_, str):
        return input_
    return None


def build_normalized_responses_request(
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> NormalizedResponsesRequest:
    """Build a canonical internal request from an OpenAI Responses payload."""
    request_payload = deepcopy(payload)
    raw_model = request_payload.get("model")
    tools = _build_normalized_tools(request_payload)
    functions = _build_functions(request_payload, logger=logger)
    options = deepcopy(request_payload)
    options.pop("model", None)
    options.pop("input", None)
    options.pop("instructions", None)
    options.pop("stream", None)
    options.pop("tools", None)
    options.pop("functions", None)
    if functions is not None:
        options["functions"] = functions
    return NormalizedResponsesRequest(
        model=raw_model if isinstance(raw_model, str) and raw_model else None,
        input=_normalize_responses_input(request_payload),
        instructions=request_payload.get("instructions"),
        stream=bool(request_payload.get("stream", False)),
        tools=tools,
        options=options,
    )


def build_normalized_embeddings_request(
    payload: dict[str, Any],
) -> NormalizedEmbeddingsRequest:
    """Build a canonical internal request from an OpenAI embeddings payload."""
    request_payload = deepcopy(payload)
    options = deepcopy(request_payload)
    options.pop("model", None)
    options.pop("input", None)
    return NormalizedEmbeddingsRequest(
        model=str(request_payload.get("model", "unknown")),
        input=deepcopy(request_payload.get("input", [])),
        options=options,
    )
