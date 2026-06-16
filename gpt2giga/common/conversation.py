"""Local conversation stitching helpers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from starlette.requests import Request

from gpt2giga.core.context import (
    fingerprint_sensitive_value,
    get_request_context,
    update_request_context,
)
from gpt2giga.models.config import ProxySettings


@dataclass(frozen=True)
class ConversationKey:
    """Identify one local stitched conversation namespace."""

    namespace: str
    protocol: str
    conversation_id: str

    @property
    def storage_key(self) -> str:
        """Return a stable in-memory storage key."""
        return f"{self.namespace}:{self.protocol}:{self.conversation_id}"


@dataclass(frozen=True)
class ConversationRecord:
    """Store conversation messages and revision metadata."""

    messages: list[dict[str, Any]]
    revision: int
    updated_at: datetime


@dataclass(frozen=True)
class ConversationTurn:
    """Represent one request after optional conversation stitching."""

    key: ConversationKey
    save_key: ConversationKey
    request_messages: list[dict[str, Any]]
    history_messages: int
    stitched: bool
    divergent: bool
    revision: int


class MemoryConversationStore:
    """Async in-memory conversation store with lazy TTL cleanup."""

    def __init__(self) -> None:
        self._records: dict[str, ConversationRecord] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, key: ConversationKey, *, ttl_seconds: int
    ) -> ConversationRecord | None:
        """Return one non-expired conversation record."""
        now = _utc_now()
        async with self._lock:
            self._purge_expired(now, ttl_seconds=ttl_seconds)
            record = self._records.get(key.storage_key)
            if record is None:
                return None
            if _is_expired(record, now, ttl_seconds=ttl_seconds):
                self._records.pop(key.storage_key, None)
                return None
            return ConversationRecord(
                messages=deepcopy(record.messages),
                revision=record.revision,
                updated_at=record.updated_at,
            )

    async def set(
        self,
        key: ConversationKey,
        messages: list[dict[str, Any]],
        *,
        max_messages: int,
    ) -> ConversationRecord:
        """Store conversation messages and increment the revision."""
        now = _utc_now()
        async with self._lock:
            previous = self._records.get(key.storage_key)
            revision = 1 if previous is None else previous.revision + 1
            record = ConversationRecord(
                messages=_trim_messages(messages, max_messages=max_messages),
                revision=revision,
                updated_at=now,
            )
            self._records[key.storage_key] = record
            return ConversationRecord(
                messages=deepcopy(record.messages),
                revision=record.revision,
                updated_at=record.updated_at,
            )

    def _purge_expired(self, now: datetime, *, ttl_seconds: int) -> None:
        expired_keys = [
            key
            for key, record in self._records.items()
            if _is_expired(record, now, ttl_seconds=ttl_seconds)
        ]
        for key in expired_keys:
            self._records.pop(key, None)


async def stitch_chat_payload(
    request: Request,
    payload: dict[str, Any],
    *,
    protocol: Literal["openai", "anthropic"],
) -> ConversationTurn | None:
    """Apply local conversation history to a Chat Completions-shaped payload."""
    settings = _settings(request)
    key = _conversation_key(request, payload, settings=settings, protocol=protocol)
    if key is None:
        return None

    incoming = _coerce_message_list(payload.get("messages"))
    if incoming is None:
        return None

    turn = await _stitch_messages(request, key, incoming, settings=settings)
    payload["messages"] = deepcopy(turn.request_messages)
    return turn


async def stitch_responses_payload(
    request: Request,
    payload: dict[str, Any],
    *,
    mode: Literal["v1", "v2"],
) -> ConversationTurn | None:
    """Apply local conversation history to an OpenAI Responses v1 payload."""
    if mode != "v1":
        return None

    settings = _settings(request)
    key = _conversation_key(request, payload, settings=settings, protocol="openai")
    if key is None:
        return None

    incoming = _responses_input_to_messages(payload.get("input"))
    if incoming is None:
        return None

    turn = await _stitch_messages(request, key, incoming, settings=settings)
    payload["input"] = deepcopy(turn.request_messages)
    return turn


async def commit_conversation_turn(
    request: Request,
    turn: ConversationTurn | None,
    response_messages: list[dict[str, Any]],
) -> None:
    """Persist one completed stitched conversation turn."""
    if turn is None or not response_messages:
        return

    settings = _settings(request)
    if not settings.conversation_stitching_enabled:
        return

    store = _conversation_store(request)
    messages = deepcopy(turn.request_messages) + deepcopy(response_messages)
    record = await store.set(
        turn.save_key,
        messages,
        max_messages=settings.conversation_max_messages,
    )
    update_request_context(
        metadata={
            "conversation_saved_messages": len(record.messages),
            "conversation_saved_revision": record.revision,
        }
    )


async def commit_chat_completion_response(
    request: Request,
    turn: ConversationTurn | None,
    response_payload: Mapping[str, Any],
) -> None:
    """Persist a non-streaming Chat Completions response."""
    await commit_conversation_turn(
        request,
        turn,
        chat_completion_response_messages(response_payload),
    )


async def commit_responses_response(
    request: Request,
    turn: ConversationTurn | None,
    response_payload: Mapping[str, Any],
) -> None:
    """Persist a non-streaming OpenAI Responses response."""
    await commit_conversation_turn(
        request,
        turn,
        responses_response_messages(response_payload),
    )


async def commit_anthropic_response(
    request: Request,
    turn: ConversationTurn | None,
    response_payload: Mapping[str, Any],
) -> None:
    """Persist a non-streaming Anthropic Messages response."""
    await commit_conversation_turn(
        request,
        turn,
        anthropic_response_messages(response_payload),
    )


async def stitch_chat_completion_stream(
    request: Request,
    turn: ConversationTurn | None,
    body_iterator: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Observe Chat Completions SSE and save state after successful completion."""
    observer = _ChatCompletionStreamConversationObserver()
    async for chunk in body_iterator:
        observer.observe_chunk(chunk)
        yield chunk
    if observer.completed:
        await commit_conversation_turn(request, turn, observer.response_messages())


async def stitch_responses_stream(
    request: Request,
    turn: ConversationTurn | None,
    body_iterator: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Observe Responses SSE and save state after successful completion."""
    observer = _ResponsesStreamConversationObserver()
    async for chunk in body_iterator:
        observer.observe_chunk(chunk)
        yield chunk
    if observer.completed:
        await commit_conversation_turn(request, turn, observer.response_messages())


async def stitch_anthropic_stream(
    request: Request,
    turn: ConversationTurn | None,
    body_iterator: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Observe Anthropic SSE and save state after successful completion."""
    observer = _AnthropicStreamConversationObserver()
    async for chunk in body_iterator:
        observer.observe_chunk(chunk)
        yield chunk
    if observer.completed:
        await commit_conversation_turn(request, turn, observer.response_messages())


def chat_completion_response_messages(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Extract assistant messages from a Chat Completions response."""
    messages: list[dict[str, Any]] = []
    for choice in payload.get("choices") or []:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message")
        if isinstance(message, Mapping):
            messages.append(_assistant_message_from_openai_message(message))
    return messages


def responses_response_messages(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract assistant messages from an OpenAI Responses response."""
    messages: list[dict[str, Any]] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type == "message":
            text_parts: list[str] = []
            for part in item.get("content") or []:
                if isinstance(part, Mapping):
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            messages.append({"role": "assistant", "content": "".join(text_parts)})
        elif item_type == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": item.get("name"),
                        "arguments": item.get("arguments"),
                    },
                }
            )
    return messages


def anthropic_response_messages(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract assistant messages from an Anthropic Messages response."""
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in payload.get("content") or []:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": block.get("input"),
                    },
                }
            )
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return [message]


async def _stitch_messages(
    request: Request,
    key: ConversationKey,
    incoming: list[dict[str, Any]],
    *,
    settings: ProxySettings,
) -> ConversationTurn:
    store = _conversation_store(request)
    record = await store.get(key, ttl_seconds=settings.conversation_ttl_seconds)
    history = record.messages if record is not None else []
    revision = record.revision if record is not None else 0
    merged, stitched, divergent = _merge_messages(
        history,
        incoming,
        on_divergence=settings.conversation_on_divergence,
    )
    save_key = key
    if divergent and settings.conversation_on_divergence == "fork":
        save_key = ConversationKey(
            namespace=key.namespace,
            protocol=key.protocol,
            conversation_id=f"{key.conversation_id}:fork:{revision + 1}",
        )

    request_messages = _trim_messages(
        merged,
        max_messages=settings.conversation_max_messages,
    )
    turn = ConversationTurn(
        key=key,
        save_key=save_key,
        request_messages=request_messages,
        history_messages=len(history),
        stitched=stitched,
        divergent=divergent,
        revision=revision,
    )
    _update_conversation_context(turn)
    return turn


def _merge_messages(
    history: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    on_divergence: Literal["client_wins", "fork"],
) -> tuple[list[dict[str, Any]], bool, bool]:
    if not history:
        return deepcopy(incoming), False, False

    if _starts_with(incoming, history):
        return deepcopy(incoming), False, False

    overlap = _suffix_prefix_overlap(history, incoming)
    if overlap > 0:
        return deepcopy(history) + deepcopy(incoming[overlap:]), True, False

    if _is_single_new_turn(incoming):
        return deepcopy(history) + deepcopy(incoming), True, False

    if on_divergence in {"client_wins", "fork"}:
        return deepcopy(incoming), False, True

    return deepcopy(incoming), False, True


def _is_single_new_turn(messages: list[dict[str, Any]]) -> bool:
    if len(messages) != 1:
        return False
    role = messages[0].get("role")
    return role in {"function", "tool", "user"}


def _starts_with(messages: list[dict[str, Any]], prefix: list[dict[str, Any]]) -> bool:
    if len(messages) < len(prefix):
        return False
    return [_canonical_message(item) for item in messages[: len(prefix)]] == [
        _canonical_message(item) for item in prefix
    ]


def _suffix_prefix_overlap(
    history: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> int:
    limit = min(len(history), len(incoming))
    history_canonical = [_canonical_message(item) for item in history]
    incoming_canonical = [_canonical_message(item) for item in incoming]
    for size in range(limit, 0, -1):
        if history_canonical[-size:] == incoming_canonical[:size]:
            return size
    return 0


def _canonical_message(message: Mapping[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False, sort_keys=True, default=str)


def _trim_messages(
    messages: list[dict[str, Any]],
    *,
    max_messages: int,
) -> list[dict[str, Any]]:
    if len(messages) <= max_messages:
        return deepcopy(messages)
    if max_messages <= 1:
        return deepcopy(messages[-max_messages:])
    first = messages[0]
    if isinstance(first, Mapping) and first.get("role") == "system":
        return [deepcopy(first)] + deepcopy(messages[-(max_messages - 1) :])
    return deepcopy(messages[-max_messages:])


def _conversation_key(
    request: Request,
    payload: Mapping[str, Any],
    *,
    settings: ProxySettings,
    protocol: Literal["openai", "anthropic"],
) -> ConversationKey | None:
    if not settings.conversation_stitching_enabled:
        return None
    conversation_id = _conversation_id(request, payload, settings=settings)
    if conversation_id is None:
        return None
    namespace = _conversation_namespace(request)
    return ConversationKey(
        namespace=namespace,
        protocol=protocol,
        conversation_id=conversation_id,
    )


def _conversation_id(
    request: Request,
    payload: Mapping[str, Any],
    *,
    settings: ProxySettings,
) -> str | None:
    body_conversation = _non_empty_string(payload.get("conversation"))
    if body_conversation:
        return body_conversation

    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        metadata_conversation = _non_empty_string(metadata.get("conversation_id"))
        if metadata_conversation:
            return metadata_conversation

    header_conversation = _non_empty_string(
        request.headers.get("x-gpt2giga-conversation-id")
    )
    if header_conversation:
        return header_conversation

    if settings.conversation_use_session_id:
        return _non_empty_string(request.headers.get("x-session-id"))
    return None


def _conversation_namespace(request: Request) -> str:
    context = get_request_context()
    if context is not None and context.api_key_hash:
        return context.api_key_hash
    raw_key = _request_api_key(request) or "anonymous"
    return fingerprint_sensitive_value(raw_key) or "anonymous"


def _request_api_key(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization:
        return authorization.strip()
    api_key = (
        request.headers.get("x-api-key")
        or request.headers.get("x-goog-api-key")
        or request.query_params.get("x-api-key")
        or request.query_params.get("key")
    )
    if api_key:
        return api_key.strip()
    return None


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _settings(request: Request) -> ProxySettings:
    return request.app.state.config.proxy_settings


def _conversation_store(request: Request) -> MemoryConversationStore:
    state = request.app.state
    store = getattr(state, "conversation_store", None)
    if store is None:
        store = MemoryConversationStore()
        state.conversation_store = store
    return store


def _coerce_message_list(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    return [deepcopy(item) for item in value if isinstance(item, Mapping)]


def _responses_input_to_messages(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if not isinstance(value, list):
        return None

    messages: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            messages.append({"role": "user", "content": _content_to_text(item)})
            continue
        if item.get("type") == "function_call_output":
            messages.append(
                {
                    "role": "tool",
                    "content": _content_to_text(item.get("output")),
                    "tool_call_id": item.get("call_id") or item.get("id"),
                }
            )
            continue
        if item.get("type") == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": item.get("name"),
                        "arguments": item.get("arguments"),
                    },
                }
            )
            continue
        role = _non_empty_string(item.get("role")) or "user"
        content = item.get("content", item.get("text", ""))
        messages.append({"role": role, "content": deepcopy(content)})
    return messages


def _content_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _assistant_message_from_openai_message(
    message: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {"role": "assistant", "content": deepcopy(message.get("content", ""))}
    for key in ("function_call", "tool_calls", "name"):
        if key in message:
            payload[key] = deepcopy(message[key])
    return payload


class _ChatCompletionStreamConversationObserver:
    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.function_call: dict[str, Any] | None = None
        self.tool_calls: dict[int, dict[str, Any]] = {}
        self.completed = False
        self.error = False

    def observe_chunk(self, chunk: Any) -> None:
        for payload in _iter_sse_data_payloads(chunk):
            if "error" in payload:
                self.error = True
                continue
            for choice in payload.get("choices") or []:
                if isinstance(choice, Mapping):
                    self._observe_choice(choice)

    def response_messages(self) -> list[dict[str, Any]]:
        if self.error:
            return []
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(self.content_parts),
        }
        if self.function_call:
            message["function_call"] = self.function_call
        if self.tool_calls:
            message["tool_calls"] = [
                value for _, value in sorted(self.tool_calls.items())
            ]
        return [message]

    def _observe_choice(self, choice: Mapping[str, Any]) -> None:
        if choice.get("finish_reason") is not None:
            self.completed = True
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            return
        content = delta.get("content")
        if isinstance(content, str):
            self.content_parts.append(content)
        function_call = delta.get("function_call")
        if isinstance(function_call, Mapping):
            target = self.function_call
            if target is None:
                target = {"arguments": ""}
                self.function_call = target
            if function_call.get("name") is not None:
                target["name"] = function_call.get("name")
            arguments = function_call.get("arguments")
            if isinstance(arguments, str):
                target["arguments"] = target.get("arguments", "") + arguments
            elif arguments is not None:
                target["arguments"] = arguments
        for raw_tool_call in delta.get("tool_calls") or []:
            if isinstance(raw_tool_call, Mapping):
                self._observe_tool_call(raw_tool_call)

    def _observe_tool_call(self, raw_tool_call: Mapping[str, Any]) -> None:
        index = raw_tool_call.get("index", len(self.tool_calls))
        if not isinstance(index, int):
            index = len(self.tool_calls)
        tool_call = self.tool_calls.setdefault(
            index,
            {"type": "function", "function": {"arguments": ""}},
        )
        for key in ("id", "type"):
            if raw_tool_call.get(key) is not None:
                tool_call[key] = raw_tool_call.get(key)
        function = raw_tool_call.get("function")
        if isinstance(function, Mapping):
            target = tool_call.setdefault("function", {"arguments": ""})
            if function.get("name") is not None:
                target["name"] = function.get("name")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                target["arguments"] = target.get("arguments", "") + arguments


class _ResponsesStreamConversationObserver:
    def __init__(self) -> None:
        self.completed = False
        self.error = False
        self.response_payload: Mapping[str, Any] | None = None

    def observe_chunk(self, chunk: Any) -> None:
        for event_type, payload in _iter_event_sse_payloads(chunk):
            if event_type == "error" or payload.get("type") == "error":
                self.error = True
            response = payload.get("response")
            if isinstance(response, Mapping):
                self.response_payload = response
            if event_type == "response.completed":
                self.completed = True

    def response_messages(self) -> list[dict[str, Any]]:
        if self.error or self.response_payload is None:
            return []
        return responses_response_messages(self.response_payload)


class _AnthropicStreamConversationObserver:
    def __init__(self) -> None:
        self.completed = False
        self.error = False
        self.text_parts: list[str] = []
        self.tool_calls: list[dict[str, Any]] = []
        self._active_tool_call: dict[str, Any] | None = None

    def observe_chunk(self, chunk: Any) -> None:
        for _event_type, payload in _iter_event_sse_payloads(chunk):
            payload_type = payload.get("type")
            if payload_type == "error":
                self.error = True
            elif payload_type == "content_block_start":
                self._observe_content_block_start(payload)
            elif payload_type == "content_block_delta":
                self._observe_content_block_delta(payload)
            elif payload_type == "message_stop":
                self.completed = True

    def response_messages(self) -> list[dict[str, Any]]:
        if self.error:
            return []
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(self.text_parts),
        }
        if self.tool_calls:
            message["tool_calls"] = deepcopy(self.tool_calls)
        return [message]

    def _observe_content_block_start(self, payload: Mapping[str, Any]) -> None:
        block = payload.get("content_block")
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            return
        self._active_tool_call = {
            "type": "function",
            "function": {"name": block.get("name"), "arguments": ""},
        }
        self.tool_calls.append(self._active_tool_call)

    def _observe_content_block_delta(self, payload: Mapping[str, Any]) -> None:
        delta = payload.get("delta")
        if not isinstance(delta, Mapping):
            return
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = delta.get("text")
            if isinstance(text, str):
                self.text_parts.append(text)
        elif delta_type == "input_json_delta" and self._active_tool_call is not None:
            partial = delta.get("partial_json")
            if isinstance(partial, str):
                function = self._active_tool_call.setdefault("function", {})
                function["arguments"] = function.get("arguments", "") + partial


def _iter_sse_data_payloads(chunk: Any) -> list[Mapping[str, Any]]:
    return [payload for _event_type, payload in _iter_event_sse_payloads(chunk)]


def _iter_event_sse_payloads(chunk: Any) -> list[tuple[str | None, Mapping[str, Any]]]:
    text = (
        chunk.decode("utf-8", errors="replace")
        if isinstance(chunk, bytes)
        else str(chunk)
    )
    events: list[tuple[str | None, Mapping[str, Any]]] = []
    event_type: str | None = None
    data_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if data_lines:
                _append_sse_event(events, event_type, data_lines)
            event_type = None
            data_lines = []
            continue
        if line.startswith("event:"):
            event_type = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        _append_sse_event(events, event_type, data_lines)
    return events


def _append_sse_event(
    events: list[tuple[str | None, Mapping[str, Any]]],
    event_type: str | None,
    data_lines: list[str],
) -> None:
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return
    if isinstance(payload, Mapping):
        events.append((event_type, payload))


def _update_conversation_context(turn: ConversationTurn) -> None:
    update_request_context(
        metadata={
            "conversation_id": turn.key.conversation_id,
            "conversation_save_id": turn.save_key.conversation_id,
            "conversation_stitched": turn.stitched,
            "conversation_divergent": turn.divergent,
            "conversation_forked": turn.save_key.conversation_id
            != turn.key.conversation_id,
            "conversation_history_messages": turn.history_messages,
            "conversation_revision": turn.revision,
        }
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(
    record: ConversationRecord,
    now: datetime,
    *,
    ttl_seconds: int,
) -> bool:
    return now - record.updated_at > timedelta(seconds=ttl_seconds)
