"""Protected playground helper endpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast, get_args
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gpt2giga.api.admin.access import verify_admin_key
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.core.redaction import redact_traffic_payload
from gpt2giga.diagnostics import analyze_compatibility_request
from gpt2giga.diagnostics.models import CompatibilityProtocol
from gpt2giga.openapi_tags import OPENAPI_TAG_ADMIN_PLAYGROUND


_SUPPORTED_PROTOCOLS = frozenset(get_args(CompatibilityProtocol))
_PUBLIC_PROTOCOLS = frozenset({"openai", "anthropic", "gemini", "litellm"})
_SUPPORTED_METHODS = frozenset({"GET", "POST"})
_BLOCKED_PREFIXES = ("/_admin", "/_debug", "/logs", "/ui")
_SENSITIVE_FORWARD_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "proxy-authorization",
        "set-cookie",
        "x-admin-api-key",
        "x-api-key",
        "x-goog-api-key",
    }
)
_SENSITIVE_FORWARD_QUERY = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "key",
        "token",
        "x-api-key",
        "x-goog-api-key",
    }
)
_SENSITIVE_HEADER_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "key",
    "secret",
    "token",
)


router = APIRouter(
    prefix="/_admin/playground",
    tags=[OPENAPI_TAG_ADMIN_PLAYGROUND],
    dependencies=[Depends(verify_admin_key)],
)


@router.get("/examples")
@exceptions_handler
async def examples() -> dict[str, Any]:
    """Return safe starter request envelopes for the built-in playground."""
    return {"examples": _PLAYGROUND_EXAMPLES}


@router.post("/analyze")
@exceptions_handler
async def analyze(request: Request) -> dict[str, Any]:
    """Analyze a playground request envelope through Compatibility Doctor."""
    envelope = await _read_json_object(request)
    return _analyze_envelope(request, envelope).to_json_dict()


@router.post("/send")
@exceptions_handler
async def send(request: Request) -> dict[str, Any]:
    """Dispatch a playground request through the mounted public gateway routes."""
    envelope = await _read_json_object(request)
    method = _read_method(envelope)
    route = _read_route(envelope)
    headers = _read_mapping(envelope, "headers")
    query = _read_mapping(envelope, "query")
    body = _read_body(envelope)
    analysis = _analyze_envelope(request, envelope)
    path, query_string = _safe_dispatch_target(
        route=route,
        query=query,
        analysis=analysis.to_json_dict(),
    )
    response = await _dispatch_playground_request(
        request,
        method=method,
        path=path,
        query_string=query_string,
        headers=headers,
        body=body,
    )
    return {
        "sent": True,
        "method": method,
        "route": path,
        "request_id": response.get("request_id"),
        "trace_id": response.get("trace_id"),
        "traffic_log_id": None,
        "response": response,
        "analysis": analysis.to_json_dict(),
    }


async def _read_json_object(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        )
    return payload


def _analyze_envelope(request: Request, envelope: Mapping[str, Any]):
    return analyze_compatibility_request(
        protocol=_read_protocol(envelope),
        route=_read_route(envelope),
        headers=_read_mapping(envelope, "headers"),
        query=_read_mapping(envelope, "query"),
        body=_read_body(envelope),
        config=getattr(request.app.state, "config", None),
    )


def _read_protocol(envelope: Mapping[str, Any]) -> CompatibilityProtocol | None:
    value = envelope.get("protocol")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected protocol to be a supported string",
        )
    normalized = value.strip().lower()
    if normalized not in _SUPPORTED_PROTOCOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported protocol",
        )
    return cast(CompatibilityProtocol, normalized)


def _read_method(envelope: Mapping[str, Any]) -> str:
    value = envelope.get("method", "POST")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected method to be GET or POST",
        )
    method = value.strip().upper()
    if method not in _SUPPORTED_METHODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected method to be GET or POST",
        )
    return method


def _read_route(envelope: Mapping[str, Any]) -> str:
    value = envelope.get("route")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected route to be a non-empty string",
        )
    return value.strip()


def _read_mapping(envelope: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    value = envelope.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected {field_name} to be an object",
        )
    return dict(value)


def _read_body(envelope: Mapping[str, Any]) -> dict[str, Any]:
    value = envelope.get("body")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected body to be an object",
        )
    return dict(value)


def _safe_dispatch_target(
    *,
    route: str,
    query: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> tuple[str, bytes]:
    parsed = urlsplit(route)
    if parsed.scheme or parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected route to be a local gateway path",
        )
    path = parsed.path or route
    if not path.startswith("/"):
        path = f"/{path}"
    if _is_blocked_path(path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin, debug, log, and UI routes cannot be sent from playground",
        )
    if analysis.get("protocol") not in _PUBLIC_PROTOCOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playground send supports only public compatibility routes",
        )
    if analysis.get("operation") == "unknown":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playground send supports only known compatibility operations",
        )
    return path, _query_string(parsed.query, query)


def _is_blocked_path(path: str) -> bool:
    candidates = [path]
    if path.startswith("/v1/") and not path.startswith("/v1/v1beta/"):
        candidates.append(path.removeprefix("/v1"))
    if path.startswith("/v2/") and not path.startswith("/v2/v1beta/"):
        candidates.append(path.removeprefix("/v2"))
    return any(candidate.startswith(_BLOCKED_PREFIXES) for candidate in candidates)


def _query_string(route_query: str, query: Mapping[str, Any]) -> bytes:
    pairs: list[tuple[str, Any]] = [
        (key, value)
        for key, value in parse_qsl(route_query, keep_blank_values=True)
        if key.lower() not in _SENSITIVE_FORWARD_QUERY
    ]
    for key, value in query.items():
        if not isinstance(key, str) or key.lower() in _SENSITIVE_FORWARD_QUERY:
            continue
        if isinstance(value, list):
            pairs.extend((key, item) for item in value)
        elif value is not None:
            pairs.append((key, value))
    return urlencode(pairs, doseq=True).encode()


async def _dispatch_playground_request(
    request: Request,
    *,
    method: str,
    path: str,
    query_string: bytes,
    headers: Mapping[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    payload = (
        b""
        if method == "GET"
        else json.dumps(body, ensure_ascii=False, default=str).encode()
    )
    response: dict[str, Any] = {"status_code": 500, "headers": {}, "body": None}
    chunks: list[bytes] = []
    messages = [{"type": "http.request", "body": payload, "more_body": False}]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send_message(message):
        if message["type"] == "http.response.start":
            raw_headers = message.get("headers", [])
            response["status_code"] = int(message["status"])
            response["headers"] = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in raw_headers
            }
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": _forward_headers(request, method=method, headers=headers),
        "client": ("127.0.0.1", 0),
        "server": ("gpt2giga-playground", 80),
        "root_path": "",
    }
    try:
        await request.app(scope, receive, send_message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Playground request failed",
        ) from exc

    response_headers = cast(dict[str, str], response["headers"])
    raw_body = b"".join(chunks)
    response["headers"] = _redact_response_headers(response_headers)
    response["body"] = redact_traffic_payload(
        _decode_response_body(raw_body, response_headers.get("content-type", ""))
    )
    response["request_id"] = response_headers.get("x-request-id")
    response["trace_id"] = response_headers.get("traceparent") or response_headers.get(
        "x-trace-id"
    )
    return response


def _redact_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    redacted = redact_traffic_payload(dict(headers))
    if not isinstance(redacted, dict):
        return {}
    return {
        key: "***" if _is_sensitive_header_name(key) else str(value)
        for key, value in redacted.items()
    }


def _is_sensitive_header_name(name: str) -> bool:
    normalized = name.strip().lower()
    return any(fragment in normalized for fragment in _SENSITIVE_HEADER_FRAGMENTS)


def _forward_headers(
    request: Request,
    *,
    method: str,
    headers: Mapping[str, Any],
) -> list[tuple[bytes, bytes]]:
    forwarded: list[tuple[bytes, bytes]] = []
    for key, value in headers.items():
        if not isinstance(key, str) or value is None:
            continue
        normalized = key.strip().lower()
        if not normalized or normalized in _SENSITIVE_FORWARD_HEADERS:
            continue
        forwarded.append((normalized.encode(), str(value).encode()))
    if method != "GET":
        forwarded.append((b"content-type", b"application/json"))

    settings = request.app.state.config.proxy_settings
    if (settings.enable_api_key_auth or settings.mode == "PROD") and settings.api_key:
        forwarded.append((b"authorization", f"Bearer {settings.api_key}".encode()))
    forwarded.append((b"x-gpt2giga-playground", b"true"))
    return forwarded


def _decode_response_body(raw_body: bytes, content_type: str) -> Any:
    if not raw_body:
        return None
    text = raw_body.decode(errors="replace")
    if "application/json" in content_type:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


_PLAYGROUND_EXAMPLES = [
    {
        "id": "openai_chat",
        "label": "OpenAI chat",
        "protocol": "openai",
        "method": "POST",
        "route": "/v2/chat/completions",
        "headers": {},
        "query": {},
        "body": {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "Reply with one sentence."}],
            "temperature": 0.2,
            "max_tokens": 128,
        },
    },
    {
        "id": "anthropic_messages",
        "label": "Anthropic messages",
        "protocol": "anthropic",
        "method": "POST",
        "route": "/v2/messages",
        "headers": {"anthropic-version": "2023-06-01"},
        "query": {},
        "body": {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "Reply with one sentence."}],
            "max_tokens": 128,
        },
    },
    {
        "id": "gemini_generate_content",
        "label": "Gemini generateContent",
        "protocol": "gemini",
        "method": "POST",
        "route": "/v2/v1beta/models/GigaChat-2-Max:generateContent",
        "headers": {},
        "query": {},
        "body": {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Reply with one sentence."}],
                }
            ],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 128},
        },
    },
]
