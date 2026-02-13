"""Router for Anthropic Messages API compatibility.

Translates Anthropic Messages API requests to GigaChat format
and converts responses back to Anthropic format.
"""

import json
import traceback
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import gigachat
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from gigachat import GigaChat

from gpt2giga.logger import rquid_context
from gpt2giga.openapi_docs import anthropic_messages_openapi_extra
from gpt2giga.protocol.content_utils import ensure_json_object_str
from gpt2giga.utils import (
    convert_tool_to_giga_functions,
    exceptions_handler,
    read_request_json,
)

router = APIRouter(tags=["Anthropic"])


# ---------------------------------------------------------------------------
# Request conversion helpers (Anthropic → OpenAI/GigaChat)
# ---------------------------------------------------------------------------


def _convert_anthropic_tools_to_openai(tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic tool definitions to OpenAI format.

    Anthropic uses ``input_schema`` while OpenAI uses ``parameters``.
    """
    openai_tools: List[Dict] = []
    for tool in tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return openai_tools


def _convert_anthropic_messages_to_openai(
    system: Optional[Any],
    messages: List[Dict],
) -> List[Dict]:
    """Convert Anthropic messages to OpenAI messages format.

    Handles system prompt, content blocks, tool_use, tool_result,
    and image content.
    """
    openai_messages: List[Dict] = []

    # Track tool_use id → function name for tool_result conversion
    tool_use_names: Dict[str, str] = {}

    # System prompt → system message
    if system:
        if isinstance(system, str):
            openai_messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            texts = [
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if texts:
                openai_messages.append({"role": "system", "content": "\n".join(texts)})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Simple string content
        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            openai_messages.append({"role": role, "content": str(content)})
            continue

        # --- Content block arrays ---
        if role == "assistant":
            # Collect tool_use id → name for later tool_result references
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_names[block.get("id", "")] = block.get("name", "")
            _convert_assistant_blocks(content, openai_messages)
        elif role == "user":
            _convert_user_blocks(content, openai_messages, tool_use_names)
        else:
            openai_messages.append({"role": role, "content": str(content)})

    return openai_messages


def _convert_assistant_blocks(
    content_blocks: List[Dict],
    openai_messages: List[Dict],
) -> None:
    """Convert Anthropic assistant content blocks to OpenAI format."""
    text_parts: List[str] = []
    tool_uses: List[Dict] = []

    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_uses.append(block)

    if tool_uses:
        tool_calls = [
            {
                "id": tu.get("id", f"call_{uuid.uuid4()}"),
                "type": "function",
                "function": {
                    "name": tu["name"],
                    "arguments": json.dumps(tu.get("input", {}), ensure_ascii=False),
                },
            }
            for tu in tool_uses
        ]
        openai_messages.append(
            {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else "",
                "tool_calls": tool_calls,
            }
        )
    else:
        openai_messages.append({"role": "assistant", "content": "\n".join(text_parts)})


def _convert_user_blocks(
    content_blocks: List[Dict],
    openai_messages: List[Dict],
    tool_use_names: Optional[Dict[str, str]] = None,
) -> None:
    """Convert Anthropic user content blocks (text, image, tool_result)."""
    text_parts: List[str] = []
    openai_content_parts: List[Dict] = []
    tool_results: List[Dict] = []
    has_images = False

    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
            openai_content_parts.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            has_images = True
            source = block.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                url = f"data:{media_type};base64,{data}"
                openai_content_parts.append(
                    {"type": "image_url", "image_url": {"url": url}}
                )
            elif source.get("type") == "url":
                openai_content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": source.get("url", "")},
                    }
                )
        elif btype == "tool_result":
            tool_results.append(block)

    # Emit tool results as function-role messages first
    names = tool_use_names or {}
    for tr in tool_results:
        tr_content = tr.get("content", "")
        if isinstance(tr_content, list):
            parts = [
                p.get("text", "")
                for p in tr_content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            tr_content = "\n".join(parts)
        tool_use_id = tr.get("tool_use_id", "")
        openai_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_use_id,
                "name": names.get(tool_use_id, ""),
                "content": ensure_json_object_str(tr_content),
            }
        )

    # Emit text / image content
    if has_images and openai_content_parts:
        openai_messages.append({"role": "user", "content": openai_content_parts})
    elif text_parts:
        openai_messages.append({"role": "user", "content": "\n".join(text_parts)})


# ---------------------------------------------------------------------------
# Response conversion helpers (GigaChat → Anthropic)
# ---------------------------------------------------------------------------


def _map_stop_reason(finish_reason: Optional[str]) -> str:
    """Map GigaChat finish_reason to Anthropic stop_reason."""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "function_call": "tool_use",
        "content_filter": "end_turn",
    }
    return mapping.get(finish_reason or "stop", "end_turn")


def _build_anthropic_response(
    giga_dict: Dict,
    model: str,
    response_id: str,
) -> Dict:
    """Build Anthropic Messages API response from GigaChat response."""
    choice = giga_dict["choices"][0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")
    usage = giga_dict.get("usage", {})

    content_blocks: List[Dict] = []

    # Add thinking block if GigaChat returned reasoning_content
    reasoning = message.get("reasoning_content")
    if reasoning:
        content_blocks.append({"type": "thinking", "thinking": reasoning})

    if message.get("function_call"):
        fc = message["function_call"]
        args = fc.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        content_blocks.append(
            {
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex[:24]}",
                "name": fc.get("name", ""),
                "input": args,
            }
        )
        stop_reason = "tool_use"
    else:
        text_content = message.get("content", "") or ""
        content_blocks.append({"type": "text", "text": text_content})
        stop_reason = _map_stop_reason(finish_reason)

    return {
        "id": f"msg_{response_id}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------


async def _stream_anthropic_generator(
    request: Request,
    model: str,
    chat_messages: Dict[str, Any],
    response_id: str,
    giga_client: GigaChat,
) -> AsyncGenerator[str, None]:
    """SSE generator producing Anthropic Messages streaming events."""
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()

    def sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        # message_start
        yield sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": f"msg_{response_id}",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )

        # ping
        yield sse("ping", {"type": "ping"})

        full_text = ""
        function_call_data: Optional[Dict[str, str]] = None
        content_block_started = False
        thinking_block_emitted = False
        content_index = 0  # current content block index
        output_tokens = 0

        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = chunk.model_dump()
            choice = giga_dict["choices"][0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content", "")
            delta_fc = delta.get("function_call")
            delta_reasoning = delta.get("reasoning_content", "")

            # --- Reasoning / thinking ---
            if delta_reasoning and not thinking_block_emitted:
                yield sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {
                            "type": "thinking_delta",
                            "thinking": delta_reasoning,
                        },
                    },
                )
                yield sse(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
                content_index += 1
                thinking_block_emitted = True

            # --- Function call (tool_use) ---
            if delta_fc:
                if function_call_data is None:
                    tool_id = f"toolu_{uuid.uuid4().hex[:24]}"
                    function_call_data = {
                        "name": delta_fc.get("name", ""),
                        "arguments": "",
                        "tool_id": tool_id,
                    }
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": function_call_data["name"],
                                "input": {},
                            },
                        },
                    )
                    content_block_started = True

                if delta_fc.get("name"):
                    function_call_data["name"] = delta_fc["name"]

                args = delta_fc.get("arguments")
                if args is not None:
                    args_str = (
                        json.dumps(args, ensure_ascii=False)
                        if isinstance(args, dict)
                        else str(args)
                    )
                    if args_str:
                        function_call_data["arguments"] += args_str
                        yield sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": args_str,
                                },
                            },
                        )

            # --- Text content ---
            elif delta_content:
                if not content_block_started:
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    content_block_started = True

                full_text += delta_content
                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {
                            "type": "text_delta",
                            "text": delta_content,
                        },
                    },
                )

            # Track usage
            chunk_usage = giga_dict.get("usage")
            if chunk_usage and chunk_usage.get("completion_tokens"):
                output_tokens = chunk_usage["completion_tokens"]

        # --- Finalize ---
        stop_reason = "tool_use" if function_call_data else "end_turn"

        if content_block_started:
            yield sse(
                "content_block_stop",
                {"type": "content_block_stop", "index": content_index},
            )

        yield sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": output_tokens},
            },
        )

        yield sse("message_stop", {"type": "message_stop"})

    except gigachat.exceptions.GigaChatException as e:
        if logger:
            logger.error(f"[{rquid}] GigaChat streaming error: {type(e).__name__}: {e}")
        yield sse(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": str(e)},
            },
        )

    except Exception as e:
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {type(e).__name__}: {e}\n{tb}"
            )
        yield sse(
            "error",
            {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": f"Stream interrupted: {e}",
                },
            },
        )


# ---------------------------------------------------------------------------
# Token counting helpers
# ---------------------------------------------------------------------------


def _extract_text_from_openai_messages(messages: List[Dict]) -> List[str]:
    """Extract text strings from OpenAI-formatted messages for token counting.

    Concatenate all textual content from each message into a flat list of strings.
    """
    texts: List[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            if content:
                texts.append(content)
        elif isinstance(content, list):
            # Multimodal content blocks (text parts only)
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        texts.append(text)
        # Include tool/function call names and arguments as countable text
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            name = func.get("name", "")
            args = func.get("arguments", "")
            if name:
                texts.append(name)
            if args:
                texts.append(args)
    return texts


def _extract_tool_definitions_text(tools: List[Dict]) -> List[str]:
    """Extract text from Anthropic tool definitions for token counting.

    Tool schemas consume tokens in the input context.
    """
    texts: List[str] = []
    for tool in tools:
        parts: List[str] = []
        name = tool.get("name", "")
        if name:
            parts.append(name)
        desc = tool.get("description", "")
        if desc:
            parts.append(desc)
        schema = tool.get("input_schema")
        if schema:
            parts.append(json.dumps(schema, ensure_ascii=False))
        if parts:
            texts.append(" ".join(parts))
    return texts


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/messages/count_tokens")
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint.

    Count the number of tokens in a message request without creating a message.
    Uses GigaChat atokens_count for the actual counting.
    """
    data = await read_request_json(request)
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)

    model = data.get("model", "unknown")

    # Convert Anthropic messages → OpenAI messages (reuse existing conversion)
    openai_messages = _convert_anthropic_messages_to_openai(
        data.get("system"), data.get("messages", [])
    )

    # Extract all text content for token counting
    texts = _extract_text_from_openai_messages(openai_messages)

    # Include tool definitions in token count (they consume input tokens)
    if "tools" in data and data["tools"]:
        texts.extend(_extract_tool_definitions_text(data["tools"]))

    if not texts:
        return {"input_tokens": 0}

    # Call GigaChat token counting
    token_counts = await giga_client.atokens_count(texts, model=model)
    total_tokens = sum(tc.tokens for tc in token_counts)

    return {"input_tokens": total_tokens}


@router.post("/messages", openapi_extra=anthropic_messages_openapi_extra())
@exceptions_handler
async def messages(request: Request):
    """Anthropic Messages API compatible endpoint.

    Accept requests in Anthropic format, translate them to GigaChat,
    and return responses in Anthropic format.
    """
    data = await read_request_json(request)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)

    model = data.get("model", "unknown")

    # Convert Anthropic messages → OpenAI messages
    openai_messages = _convert_anthropic_messages_to_openai(
        data.get("system"), data.get("messages", [])
    )

    # Build OpenAI-compatible payload for the request transformer
    openai_data: Dict[str, Any] = {
        "model": model,
        "messages": openai_messages,
    }

    if "max_tokens" in data:
        openai_data["max_tokens"] = data["max_tokens"]
    if "temperature" in data:
        openai_data["temperature"] = data["temperature"]
    if "top_p" in data:
        openai_data["top_p"] = data["top_p"]
    if "stop_sequences" in data:
        openai_data["stop"] = data["stop_sequences"]

    # Convert Anthropic thinking → GigaChat reasoning_effort
    thinking = data.get("thinking")
    if thinking and isinstance(thinking, dict) and thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens", 10000)
        if budget >= 8000:
            openai_data["reasoning_effort"] = "high"
        elif budget >= 3000:
            openai_data["reasoning_effort"] = "medium"
        else:
            openai_data["reasoning_effort"] = "low"

    # Convert Anthropic tools → OpenAI → GigaChat functions
    if "tools" in data and data["tools"]:
        openai_data["tools"] = _convert_anthropic_tools_to_openai(data["tools"])
        openai_data["functions"] = convert_tool_to_giga_functions(openai_data)
        state.logger.debug(f"Functions count: {len(openai_data['functions'])}")

    # Handle tool_choice
    tool_choice = data.get("tool_choice")
    if tool_choice and isinstance(tool_choice, dict):
        tc_type = tool_choice.get("type")
        if tc_type == "tool":
            openai_data["function_call"] = {"name": tool_choice.get("name")}
        elif tc_type == "none":
            openai_data.pop("tools", None)
            openai_data.pop("functions", None)

    # Use existing request transformer (OpenAI → GigaChat)
    chat_messages = await state.request_transformer.prepare_chat_completion(
        openai_data, giga_client
    )

    if not stream:
        response = await giga_client.achat(chat_messages)
        giga_dict = response.model_dump()
        return _build_anthropic_response(giga_dict, model, current_rquid)

    return StreamingResponse(
        _stream_anthropic_generator(
            request, model, chat_messages, current_rquid, giga_client
        ),
        media_type="text/event-stream",
    )
