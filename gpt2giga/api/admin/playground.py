"""Protected playground helper endpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gpt2giga.api.admin.access import verify_admin_key
from gpt2giga.api.admin.routes import (
    _read_format,
    _read_json_object,
    _translate_payload,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.core.redaction import (
    REDACTION_REPLACEMENT,
    is_sensitive_key,
    redact_traffic_payload,
)


BLOCKED_PLAYGROUND_PREFIXES = ("/_admin", "/_debug", "/logs", "/ui")
SKIPPED_REQUEST_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "proxy-authorization",
        "x-admin-api-key",
    }
)


PLAYGROUND_EXAMPLES: dict[str, dict[str, Any]] = {
    "openai-chat": {
        "protocol": "openai",
        "operation": "chat",
        "model": "GigaChat-2-Max",
        "stream": False,
        "temperature": 0.3,
        "maxOutput": 512,
        "messages": [
            {"role": "system", "content": "Answer concisely."},
            {"role": "user", "content": "Summarize the release scope."},
        ],
        "tools": [],
        "responseConfig": {},
        "metadata": {"source": "playground"},
        "headers": {"Authorization": "Bearer <GPT2GIGA_API_KEY>"},
    },
    "anthropic-messages": {
        "protocol": "anthropic",
        "operation": "messages",
        "model": "GigaChat-2-Max",
        "stream": False,
        "temperature": 0.2,
        "maxOutput": 512,
        "messages": [{"role": "user", "content": "Draft a migration note."}],
        "tools": [],
        "responseConfig": {},
        "metadata": {"source": "playground"},
        "headers": {"x-api-key": "<GPT2GIGA_API_KEY>"},
    },
    "gemini-generate": {
        "protocol": "gemini",
        "operation": "generateContent",
        "model": "GigaChat-2-Max",
        "stream": False,
        "temperature": 0.3,
        "maxOutput": 512,
        "messages": [
            {
                "role": "user",
                "parts": [{"text": "Write a Gemini-compatible smoke prompt."}],
            }
        ],
        "tools": [],
        "responseConfig": {},
        "metadata": {"source": "playground"},
        "headers": {"x-goog-api-key": "<GPT2GIGA_API_KEY>"},
    },
    "gemini-stream": {
        "protocol": "gemini",
        "operation": "streamGenerateContent",
        "model": "GigaChat-2-Max",
        "stream": True,
        "temperature": 0.3,
        "maxOutput": 512,
        "messages": [
            {"role": "user", "parts": [{"text": "Stream three short bullet points."}]}
        ],
        "tools": [],
        "responseConfig": {},
        "metadata": {"source": "playground"},
        "headers": {"x-goog-api-key": "<GPT2GIGA_API_KEY>"},
    },
    "tools": {
        "protocol": "openai",
        "operation": "chat",
        "model": "GigaChat-2-Max",
        "stream": False,
        "temperature": 0.2,
        "maxOutput": 512,
        "messages": [{"role": "user", "content": "Call get_release_status."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_release_status",
                    "description": "Return release status for one version.",
                    "parameters": {
                        "type": "object",
                        "properties": {"version": {"type": "string"}},
                        "required": ["version"],
                    },
                },
            }
        ],
        "responseConfig": {},
        "metadata": {"source": "playground", "case": "tools"},
        "headers": {"Authorization": "Bearer <GPT2GIGA_API_KEY>"},
    },
    "structured-output": {
        "protocol": "gemini",
        "operation": "generateContent",
        "model": "GigaChat-2-Max",
        "stream": False,
        "temperature": 0.1,
        "maxOutput": 512,
        "messages": [
            {
                "role": "user",
                "parts": [{"text": "Return a JSON object with status and risks."}],
            }
        ],
        "tools": [],
        "responseConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["status", "risks"],
            },
        },
        "metadata": {"source": "playground", "case": "structured-output"},
        "headers": {"x-goog-api-key": "<GPT2GIGA_API_KEY>"},
    },
    "embeddings": {
        "protocol": "gemini",
        "operation": "embedContent",
        "model": "EmbeddingsGigaR",
        "stream": False,
        "temperature": 0,
        "maxOutput": 512,
        "messages": {"parts": [{"text": "Compatibility gateways normalize clients."}]},
        "tools": [],
        "responseConfig": {},
        "metadata": {"source": "playground", "case": "embeddings"},
        "headers": {"x-goog-api-key": "<GPT2GIGA_API_KEY>"},
    },
    "count-tokens": {
        "protocol": "gemini",
        "operation": "countTokens",
        "model": "GigaChat-2-Max",
        "stream": False,
        "temperature": 0,
        "maxOutput": 512,
        "messages": [{"role": "user", "parts": [{"text": "Count these tokens."}]}],
        "tools": [],
        "responseConfig": {},
        "metadata": {"source": "playground", "case": "count-tokens"},
        "headers": {"x-goog-api-key": "<GPT2GIGA_API_KEY>"},
    },
}


router = APIRouter(
    prefix="/_admin/playground",
    include_in_schema=False,
    dependencies=[Depends(verify_admin_key)],
)


@router.get("/examples")
@exceptions_handler
async def playground_examples():
    """Return built-in playground examples."""
    return {
        "data": [
            {"id": example_id, "request": request}
            for example_id, request in PLAYGROUND_EXAMPLES.items()
        ]
    }


@router.post("/translate")
@exceptions_handler
async def translate_playground_request(request: Request):
    """Translate a playground payload through existing debug adapters."""
    envelope = await _read_json_object(request)
    source = _read_format(envelope, "from")
    target = _read_format(envelope, "to")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected payload to be an object",
        )
    translated = await _translate_payload(
        request,
        source=source,
        target=target,
        payload=payload,
        requested_model=envelope.get("requested_model"),
    )
    response = {
        "from": source,
        "to": target,
        "payload": translated["payload"],
    }
    intermediate = translated.get("intermediate")
    if intermediate:
        response["intermediate"] = intermediate
    return response


@router.post("/send")
@exceptions_handler
async def send_playground_request(request: Request):
    """Dispatch one playground request through the local gateway app."""
    envelope = await _read_json_object(request)
    method = _read_method(envelope)
    path, query_string, redacted_path = _read_dispatch_path(envelope)
    headers = _read_headers(envelope.get("headers"))
    body = envelope.get("body", {})
    dispatched = await _dispatch_playground_request(
        request,
        method=method,
        path=path,
        query_string=query_string,
        headers=headers,
        body=body,
    )
    return {
        "request_id": dispatched.get("request_id"),
        "trace_id": dispatched.get("trace_id"),
        "traffic_log_id": None,
        "request": {
            "method": method,
            "path": redacted_path,
            "headers": redact_traffic_payload(headers),
            "body": redact_traffic_payload(body),
        },
        "response": dispatched,
    }


def _read_method(envelope: Mapping[str, Any]) -> str:
    method = envelope.get("method", "POST")
    if not isinstance(method, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected method to be a string",
        )
    method = method.strip().upper()
    if method != "POST":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playground send currently supports POST requests only",
        )
    return method


def _read_dispatch_path(envelope: Mapping[str, Any]) -> tuple[str, bytes, str]:
    value = envelope.get("path")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected path to be a non-empty string",
        )
    parsed = urlsplit(value.strip())
    if parsed.scheme or parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a local gateway path, not an absolute URL",
        )
    path = parsed.path
    if not path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected path to start with /",
        )
    if path.startswith(BLOCKED_PLAYGROUND_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin, debug, UI, and log routes cannot be sent from playground",
        )
    query = parsed.query
    return path, query.encode(), _redacted_path(path, query)


def _read_headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected headers to be an object",
        )
    headers: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name).strip()
        if not name:
            continue
        if name.lower() in SKIPPED_REQUEST_HEADERS:
            continue
        if isinstance(raw_value, str | int | float | bool):
            headers[name] = str(raw_value)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Expected header {name} to be a scalar value",
            )
    return headers


async def _dispatch_playground_request(
    request: Request,
    *,
    method: str,
    path: str,
    query_string: bytes,
    headers: Mapping[str, str],
    body: Any,
) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False, default=str).encode()
    raw_headers = _asgi_headers(headers)
    messages = [{"type": "http.request", "body": payload, "more_body": False}]
    response: dict[str, Any] = {
        "status_code": 500,
        "headers": {},
        "content_type": None,
        "body": None,
    }
    chunks: list[bytes] = []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            raw_response_headers = message.get("headers", [])
            response["status_code"] = int(message["status"])
            response_headers = {
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in raw_response_headers
            }
            response["headers"] = redact_traffic_payload(response_headers)
            response["content_type"] = _case_insensitive_header(
                response_headers,
                "content-type",
            )
            response["request_id"] = _case_insensitive_header(
                response_headers,
                "x-request-id",
            )
            response["trace_id"] = _case_insensitive_header(
                response_headers,
                "x-trace-id",
            )
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": raw_headers,
        "client": ("127.0.0.1", 0),
        "server": ("gpt2giga-playground", 80),
        "root_path": "",
    }
    try:
        await request.app(scope, receive, send)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Playground request failed",
        ) from exc
    response["body"] = _decode_response_body(b"".join(chunks))
    return response


def _asgi_headers(headers: Mapping[str, str]) -> list[tuple[bytes, bytes]]:
    normalized = {
        name.lower(): value
        for name, value in headers.items()
        if name.lower() not in SKIPPED_REQUEST_HEADERS
    }
    normalized.setdefault("content-type", "application/json")
    normalized["x-gpt2giga-playground"] = "true"
    return [
        (name.encode("latin-1"), str(value).encode("latin-1"))
        for name, value in normalized.items()
    ]


def _decode_response_body(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    text = raw_body.decode(errors="replace")
    try:
        return redact_traffic_payload(json.loads(text))
    except json.JSONDecodeError:
        return redact_traffic_payload(text)


def _case_insensitive_header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return None


def _redacted_path(path: str, query: str) -> str:
    if not query:
        return path
    redacted_pairs = [
        (
            key,
            REDACTION_REPLACEMENT if is_sensitive_key(key) else value,
        )
        for key, value in parse_qsl(query, keep_blank_values=True)
    ]
    return f"{path}?{urlencode(redacted_pairs, safe='*')}"
