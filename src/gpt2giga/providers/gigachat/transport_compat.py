"""Isolate private SDK/httpx hooks needed for per-request query and JSON body.

GigaChat SDK 0.2.3 exposes public ContextVars for headers, but not public
per-request query/body options. This feature-detected boundary is the only module
allowed to touch the SDK async client or httpx request content internals. Remove
it when the SDK provides an equivalent public request-options API.
"""

import json
from contextvars import ContextVar
from typing import Any, Mapping

import httpx

from gpt2giga.common.client_params import ClientCompatibilityError

_OPTIONS_HOOK_MARKER = "_gpt2giga_request_options_hook"
_UNAVAILABLE_MESSAGE = (
    "GigaChat SDK transport does not expose the request hook required for "
    "extra_query or extra_body"
)


class GigaChatTransportCompatibilityError(ClientCompatibilityError):
    """Report unavailable private transport support with a stable safe message."""

    def __init__(self) -> None:
        super().__init__(
            _UNAVAILABLE_MESSAGE,
            code="transport_options_unavailable",
        )


def install_request_options_hook(
    giga_client: Any,
    current_options: ContextVar[Any],
) -> None:
    """Install the feature-detected request hook once on an SDK async client."""
    try:
        http_client = getattr(giga_client, "_aclient")
        event_hooks = getattr(http_client, "event_hooks")
    except Exception:
        raise GigaChatTransportCompatibilityError from None

    if not isinstance(event_hooks, dict):
        raise GigaChatTransportCompatibilityError
    request_hooks = event_hooks.setdefault("request", [])
    if not isinstance(request_hooks, list):
        raise GigaChatTransportCompatibilityError
    if any(getattr(hook, _OPTIONS_HOOK_MARKER, False) for hook in request_hooks):
        return

    async def apply_request_options(request: httpx.Request) -> None:
        options = current_options.get()
        if not options or _is_auth_request(request):
            return
        if options.query:
            _merge_query(request, options.query)
        if options.body:
            _merge_extra_body(request, options.body)

    setattr(apply_request_options, _OPTIONS_HOOK_MARKER, True)
    request_hooks.append(apply_request_options)


def _merge_query(request: httpx.Request, query: tuple[tuple[str, str], ...]) -> None:
    merged_query = httpx.QueryParams(
        list(request.url.params.multi_items()) + list(query)
    )
    request.url = request.url.copy_with(query=str(merged_query).encode("ascii"))


def _is_auth_request(request: httpx.Request) -> bool:
    path = request.url.path.lower().rstrip("/")
    return path.endswith("/oauth") or path.endswith("/token") or "/oauth/" in path


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
