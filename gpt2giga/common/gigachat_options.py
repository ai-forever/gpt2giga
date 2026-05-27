"""Helpers for forwarding request-scoped GigaChat options."""

import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Mapping, Optional

import httpx
from starlette.requests import Request

_BLOCKED_HEADER_NAMES = {
    "accept",
    "accept-encoding",
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "expect",
    "forwarded",
    "host",
    "keep-alive",
    "proxy-authorization",
    "set-cookie",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
    "x-api-key",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
    "x-real-ip",
}
_BLOCKED_HEADER_PREFIXES = ("x-stainless-",)
_PROXY_QUERY_PARAMS = {"x-api-key"}
_OPTIONS_HOOK_MARKER = "_gpt2giga_request_options_hook"


@dataclass(frozen=True)
class GigaRequestOptions:
    """Request-scoped HTTP options to add to GigaChat calls."""

    headers: Mapping[str, str]
    query: tuple[tuple[str, str], ...]
    body: Mapping[str, Any]

    @property
    def is_empty(self) -> bool:
        return not self.headers and not self.query and not self.body


_current_options: ContextVar[Optional[GigaRequestOptions]] = ContextVar(
    "gpt2giga_current_gigachat_request_options",
    default=None,
)


def extract_gigachat_request_options(
    request: Request,
    data: Optional[dict[str, Any]] = None,
    *,
    include_extra_body: bool = False,
    exclude_query_params: Iterable[str] = (),
) -> GigaRequestOptions:
    """Extract OpenAI/Anthropic extra_* request options for upstream calls."""
    headers: dict[str, str] = {}
    query: list[tuple[str, str]] = []
    body: dict[str, Any] = {}

    headers.update(_extract_request_headers(request))
    query.extend(_extract_request_query(request, exclude_query_params))

    if data is not None:
        headers.update(_normalize_headers(data.pop("extra_headers", None)))
        query.extend(_normalize_query(data.pop("extra_query", None)))
        if include_extra_body:
            body.update(_normalize_body(data.pop("extra_body", None)))

    return GigaRequestOptions(headers=headers, query=tuple(query), body=body)


@asynccontextmanager
async def gigachat_request_options(
    giga_client: Any,
    options: Optional[GigaRequestOptions],
) -> AsyncIterator[None]:
    """Apply request-scoped HTTP options while a GigaChat SDK call is running."""
    if not options or options.is_empty:
        yield
        return

    _ensure_request_options_hook(giga_client)
    token = _current_options.set(options)
    try:
        yield
    finally:
        _current_options.reset(token)


def _extract_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        normalized = name.lower()
        if _is_blocked_header(normalized):
            continue
        headers[normalized] = value
    return headers


def _extract_request_query(
    request: Request, exclude_query_params: Iterable[str]
) -> list[tuple[str, str]]:
    excluded = {item.lower() for item in exclude_query_params} | _PROXY_QUERY_PARAMS
    query: list[tuple[str, str]] = []
    for key, value in request.query_params.multi_items():
        if key.lower() in excluded:
            continue
        query.append((key, value))
    return query


def _normalize_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}

    headers: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or value is None:
            continue
        normalized = name.lower()
        if _is_blocked_header(normalized):
            continue
        if isinstance(value, (str, int, float, bool)):
            headers[normalized] = str(value)
    return headers


def _normalize_query(raw: Any) -> list[tuple[str, str]]:
    if not isinstance(raw, Mapping):
        return []

    query: list[tuple[str, str]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is not None:
                    query.append((key, _stringify_query_value(item)))
        else:
            query.append((key, _stringify_query_value(value)))
    return query


def _normalize_body(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def _stringify_query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _is_blocked_header(normalized_name: str) -> bool:
    return normalized_name in _BLOCKED_HEADER_NAMES or normalized_name.startswith(
        _BLOCKED_HEADER_PREFIXES
    )


def _ensure_request_options_hook(giga_client: Any) -> None:
    try:
        http_client = getattr(giga_client, "_aclient")
    except Exception:
        return

    event_hooks = getattr(http_client, "event_hooks", None)
    if not isinstance(event_hooks, dict):
        return

    request_hooks = event_hooks.setdefault("request", [])
    if any(getattr(hook, _OPTIONS_HOOK_MARKER, False) for hook in request_hooks):
        return

    setattr(_apply_request_options_hook, _OPTIONS_HOOK_MARKER, True)
    request_hooks.append(_apply_request_options_hook)


async def _apply_request_options_hook(request: httpx.Request) -> None:
    options = _current_options.get()
    if not options:
        return

    if _is_auth_request(request):
        return

    for name, value in options.headers.items():
        request.headers[name] = value

    if options.query:
        merged_query = httpx.QueryParams(
            list(request.url.params.multi_items()) + list(options.query)
        )
        request.url = request.url.copy_with(query=str(merged_query).encode("ascii"))

    if options.body:
        _merge_extra_body(request, options.body)


def _is_auth_request(request: httpx.Request) -> bool:
    path = request.url.path.lower()
    return path.endswith("/oauth") or "/oauth/" in path


def _merge_extra_body(request: httpx.Request, extra_body: Mapping[str, Any]) -> None:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return

    try:
        current = json.loads(request.content or b"{}")
    except (AttributeError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(current, dict):
        return

    content = json.dumps({**current, **extra_body}, ensure_ascii=False).encode("utf-8")
    request._content = content
    request.stream = httpx.ByteStream(content)
    request.headers["content-length"] = str(len(content))
