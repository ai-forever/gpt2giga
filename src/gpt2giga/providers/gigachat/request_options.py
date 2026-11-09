"""Public orchestration for request-scoped GigaChat SDK options."""

from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Mapping, Optional

from gigachat.context import (
    agent_id_cvar,
    authorization_cvar,
    client_id_cvar,
    custom_headers_cvar,
    operation_id_cvar,
    request_id_cvar,
    service_id_cvar,
    session_id_cvar,
    trace_id_cvar,
)
from starlette.requests import Request

from gpt2giga.common.client_params import (
    filter_safe_extra_headers,
    filter_safe_query_items,
    normalize_header_name,
)


@dataclass(frozen=True)
class GigaRequestOptions:
    """Request-scoped HTTP options to add to GigaChat calls."""

    headers: Mapping[str, str]
    query: tuple[tuple[str, str], ...]
    body: Mapping[str, Any]

    @property
    def is_empty(self) -> bool:
        return not self.headers and not self.query and not self.body


_GIGACHAT_HEADER_CONTEXT_VARS: Mapping[str, ContextVar[Optional[str]]] = {
    "authorization": authorization_cvar,
    "x-agent-id": agent_id_cvar,
    "x-client-id": client_id_cvar,
    "x-operation-id": operation_id_cvar,
    "x-request-id": request_id_cvar,
    "x-service-id": service_id_cvar,
    "x-session-id": session_id_cvar,
    "x-trace-id": trace_id_cvar,
}


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
    *,
    include_body: bool = True,
) -> AsyncIterator[Any]:
    """Yield a public SDK view while preserving request header context."""
    if not options or options.is_empty:
        yield giga_client
        return
    body = options.body if include_body else {}
    request_client = (
        giga_client.with_options(extra_query=options.query, extra_body=body)
        if options.query or body
        else giga_client
    )
    header_tokens = _set_gigachat_header_context(options.headers)
    try:
        yield request_client
    finally:
        _reset_context_tokens(header_tokens)


def _extract_request_headers(request: Request) -> dict[str, str]:
    return filter_safe_extra_headers(request.headers)


def _extract_request_query(
    request: Request, exclude_query_params: Iterable[str]
) -> list[tuple[str, str]]:
    excluded = {item.lower() for item in exclude_query_params} | {"x-api-key", "key"}
    items = (
        (key, value)
        for key, value in request.query_params.multi_items()
        if key.lower() not in excluded
    )
    return list(filter_safe_query_items(items))


def _normalize_headers(raw: Any) -> dict[str, str]:
    return filter_safe_extra_headers(raw)


def _set_gigachat_header_context(
    headers: Mapping[str, str],
) -> list[tuple[ContextVar[Any], Token]]:
    tokens: list[tuple[ContextVar[Any], Token]] = []
    custom_headers: dict[str, str] = {}

    for name, value in headers.items():
        normalized = normalize_header_name(name)
        cvar = _GIGACHAT_HEADER_CONTEXT_VARS.get(normalized)
        if cvar is not None:
            tokens.append((cvar, cvar.set(value)))
        else:
            custom_headers[normalized] = value

    if custom_headers:
        existing_headers = custom_headers_cvar.get() or {}
        tokens.append(
            (
                custom_headers_cvar,
                custom_headers_cvar.set({**existing_headers, **custom_headers}),
            )
        )

    return tokens


def _reset_context_tokens(tokens: list[tuple[ContextVar[Any], Token]]) -> None:
    for cvar, token in reversed(tokens):
        cvar.reset(token)


def _normalize_query(raw: Any) -> list[tuple[str, str]]:
    if not isinstance(raw, Mapping):
        return []

    items: list[tuple[str, Any]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is not None:
                    items.append((key, item))
        else:
            items.append((key, value))
    return list(filter_safe_query_items(items))


def _normalize_body(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}
