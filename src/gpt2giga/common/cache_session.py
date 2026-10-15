"""Reuse the GigaChat prompt cache by reusing an upstream ``X-Session-ID``.

GigaChat keeps a prefix key-value cache for a short window (observed ~30s) and
exposes cache hits as ``precached_prompt_tokens``. Requests that carry a stable
``X-Session-ID`` keep landing on the same cache entry, so repeated calls that
share a long, unchanged prefix reuse it instead of reprocessing the tokens.

Many OpenAI/Anthropic/Gemini clients cannot send custom headers, so the gateway
can build a session identifier from the request's own stable prefix. The value
is a one-way hash of the caller's own prompt text; it is deterministic, so the
same prefix maps to the same identifier across requests, workers, and restarts.
The module materializes the prefix text transiently only to hash it and never
logs, stores, or returns it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
from typing import TYPE_CHECKING, Any, Literal

from starlette.requests import Request

if TYPE_CHECKING:
    from gpt2giga.providers.gigachat.request_options import GigaRequestOptions

CacheSessionScope = Literal["prefix", "system"]

_SESSION_HEADER = "x-session-id"
_SESSION_ID_PREFIX = "gpt2giga-cache-"
_DEFAULT_MIN_PREFIX_TOKENS = 1024
_CHARS_PER_TOKEN = 4
_SYSTEM_ROLES = frozenset({"system", "developer"})
_CHAT_PATH_SUFFIXES = (
    "/chat/completions",
    "/messages",
    "/responses",
    ":generatecontent",
    ":streamgeneratecontent",
)


def apply_cache_session_id(
    request: Request,
    payload: Any,
    options: GigaRequestOptions,
    *,
    model: str | None = None,
) -> GigaRequestOptions:
    """Return options carrying a built ``X-Session-ID`` when reuse applies.

    The session id is skipped unless it is explicitly enabled, the route is a
    chat-like endpoint, no session identifier is already supplied by the client,
    and no global default session is configured. Execution owners pass the
    prepared upstream payload and resolved model or assistant/thread identity.
    """
    settings = _proxy_settings(request)
    if settings is None or not settings.cache_session_enabled:
        return options
    if not _is_chat_like_path(request.url.path):
        return options
    if _has_client_session(request, options):
        return options
    if _configured_default_session(request) is not None:
        return options

    if not isinstance(payload, Mapping):
        model_dump = getattr(payload, "model_dump", None)
        payload = (
            model_dump(mode="json", exclude_none=True) if callable(model_dump) else None
        )
    session_id = build_cache_session_id(
        payload,
        min_prefix_tokens=settings.cache_session_min_prefix_tokens,
        scope=settings.cache_session_scope,
        model=model if model is not None else _payload_model(payload),
    )
    if session_id is None:
        return options
    headers = dict(options.headers)
    headers[_SESSION_HEADER] = session_id
    return replace(options, headers=headers)


def build_cache_session_id(
    payload: Mapping[str, Any] | None,
    *,
    min_prefix_tokens: int = _DEFAULT_MIN_PREFIX_TOKENS,
    scope: CacheSessionScope = "prefix",
    model: str | None = None,
) -> str | None:
    """Return a stable session identifier for a request's stable prefix.

    ``model`` is mixed into the hash so an identical prefix sent to different
    models does not share one upstream cache entry. Returns ``None`` when the
    payload carries no usable prefix or the prefix is shorter than
    ``min_prefix_tokens`` (the GigaChat cache only helps for long prompts, so
    short ones are left untouched).
    """
    if not isinstance(payload, Mapping):
        return None
    prefix_text = _stable_prefix_text(payload, scope)
    if not prefix_text:
        return None
    if _estimate_tokens(prefix_text) < min_prefix_tokens:
        return None
    material = f"{model or ''}\x00{prefix_text.strip()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{_SESSION_ID_PREFIX}{digest[:32]}"


def _payload_model(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) and model.strip() else None


def _stable_prefix_text(
    payload: Mapping[str, Any],
    scope: CacheSessionScope,
) -> str | None:
    parts: list[str] = []

    for key in ("system", "systemInstruction", "system_instruction"):
        text = _content_text(payload.get(key))
        if text:
            parts.append(text)

    messages = payload.get("messages")
    if isinstance(messages, list):
        text = _messages_prefix_text(messages, scope)
        if text:
            parts.append(text)
    else:
        contents = payload.get("contents")
        if isinstance(contents, list):
            text = _contents_prefix_text(contents, scope)
            if text:
                parts.append(text)
        else:
            instructions = _content_text(payload.get("instructions"))
            if instructions:
                parts.append(instructions)
            text = _input_prefix_text(payload.get("input"), scope)
            if text:
                parts.append(text)

    if not parts:
        return None
    return "\n\n".join(parts)


def _messages_prefix_text(
    messages: list[Any],
    scope: CacheSessionScope,
) -> str | None:
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        role = role.lower() if isinstance(role, str) else ""
        if role in _SYSTEM_ROLES:
            text = _content_text(message.get("content"))
            if text:
                parts.append(text)
            continue
        if scope == "system":
            break
        if role == "user":
            text = _content_text(message.get("content"))
            if text:
                parts.append(text)
        break
    return "\n\n".join(parts) or None


def _contents_prefix_text(
    contents: list[Any],
    scope: CacheSessionScope,
) -> str | None:
    parts: list[str] = []
    for item in contents:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "user").lower()
        if role in _SYSTEM_ROLES:
            text = _content_text(item.get("parts"))
            if text:
                parts.append(text)
            continue
        if scope == "system":
            break
        if role == "user":
            text = _content_text(item.get("parts"))
            if text:
                parts.append(text)
        break
    return "\n\n".join(parts) or None


def _input_prefix_text(input_value: Any, scope: CacheSessionScope) -> str | None:
    """Return the leading stable text of a Responses ``input``.

    The input is a list of role-tagged items (``message`` with a ``role``, or
    items such as ``function_call_output`` that carry no role). Include leading
    system/developer messages and, in prefix scope, the first user turn. Stop
    before assistant/tool items or later turns, as with chat-shaped messages.
    """
    if scope != "system":
        direct = _content_text(input_value)
        if direct:
            return direct
    if not isinstance(input_value, list):
        return None
    parts: list[str] = []
    for item in input_value:
        if not isinstance(item, Mapping):
            break
        role = str(item.get("role") or "").lower()
        if role in _SYSTEM_ROLES:
            text = _content_text(item.get("content"))
            if text:
                parts.append(text)
            continue
        if scope != "system" and role == "user":
            text = _content_text(item.get("content"))
            if text:
                parts.append(text)
        break
    return "\n\n".join(parts) or None


def _content_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        text = value.get("text")
        if isinstance(text, str):
            return text.strip() or None
        parts = value.get("parts")
        if parts is not None:
            return _content_text(parts)
        return None
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    texts.append(item)
                continue
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        joined = "\n".join(texts).strip()
        return joined or None
    return None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _is_chat_like_path(path: str) -> bool:
    normalized = path.rstrip("/").lower()
    return normalized.endswith(_CHAT_PATH_SUFFIXES)


def _has_client_session(request: Request, options: GigaRequestOptions) -> bool:
    if any(name.lower() == _SESSION_HEADER for name in options.headers):
        return True
    return bool(_non_empty(request.headers.get(_SESSION_HEADER)))


def _configured_default_session(request: Request) -> str | None:
    config = getattr(request.app.state, "config", None)
    gigachat_settings = getattr(config, "gigachat_settings", None)
    return _non_empty(getattr(gigachat_settings, "session_id", None))


def _proxy_settings(request: Request) -> Any | None:
    config = getattr(request.app.state, "config", None)
    return getattr(config, "proxy_settings", None)


def _non_empty(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
