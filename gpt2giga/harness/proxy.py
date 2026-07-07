"""Small synchronous client helpers for the local gpt2giga proxy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gpt2giga.harness.config import DEFAULT_MODEL_HINTS, HarnessConfig
from gpt2giga.harness.types import GigaChatApiMode, redact_secrets


class ProxyRequestError(RuntimeError):
    """Raised when the local proxy request fails."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ProxyHealth:
    """Proxy health check result."""

    ok: bool
    url: str
    path: str | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class ModelDiscovery:
    """Model discovery result for CLI/UI."""

    ok: bool
    models: tuple[str, ...]
    source: str
    error: str | None = None


@dataclass(frozen=True)
class RouteProbe:
    """Route-level diagnostic result for doctor output."""

    ok: bool
    path: str
    method: str
    status_code: int | None = None
    detail: str | None = None
    error: str | None = None


def build_chat_completions_url(
    proxy_url: str,
    api_mode: GigaChatApiMode,
) -> str:
    """Return explicit v1/v2 Chat Completions URL."""
    return f"{proxy_url.rstrip('/')}/{api_mode.value}/chat/completions"


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Send a JSON request and return decoded JSON."""
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    request = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except HTTPError as exc:
        error_body = _read_error_body(exc)
        message = f"proxy returned HTTP {exc.code}"
        if error_body:
            message = f"{message}: {error_body}"
        raise ProxyRequestError(message, status_code=exc.code) from exc
    except URLError as exc:
        raise ProxyRequestError(f"proxy is not reachable: {exc.reason}") from exc
    if not data:
        return {}
    try:
        decoded = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProxyRequestError("proxy returned non-JSON response") from exc
    if not isinstance(decoded, dict):
        raise ProxyRequestError("proxy returned JSON that is not an object")
    return decoded


def health_check(config: HarnessConfig) -> ProxyHealth:
    """Check common local proxy health paths without requiring credentials."""
    last_error = "proxy did not respond"
    for path in ("/health", "/ping", "/"):
        url = f"{config.proxy_url}{path}"
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=5) as response:
                return ProxyHealth(
                    ok=200 <= response.status < 500,
                    url=config.proxy_url,
                    path=path,
                    status_code=response.status,
                )
        except HTTPError as exc:
            if exc.code < 500:
                return ProxyHealth(
                    ok=True,
                    url=config.proxy_url,
                    path=path,
                    status_code=exc.code,
                )
        except URLError as exc:
            last_error = str(exc.reason)
    return ProxyHealth(ok=False, url=config.proxy_url, error=last_error)


def probe_json_route(
    config: HarnessConfig,
    path: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
) -> RouteProbe:
    """Probe whether a JSON route is mounted without requiring upstream success."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    try:
        request_json(
            method,
            f"{config.proxy_url}{normalized_path}",
            payload=payload or {},
            api_key=config.api_key,
            timeout=5,
        )
    except ProxyRequestError as exc:
        status_code = exc.status_code
        return RouteProbe(
            ok=_status_indicates_mounted_route(status_code),
            path=normalized_path,
            method=method.upper(),
            status_code=status_code,
            detail=_route_probe_detail(status_code),
            error=str(exc),
        )
    return RouteProbe(
        ok=True,
        path=normalized_path,
        method=method.upper(),
        status_code=200,
        detail="accepted probe request",
    )


def discover_models(
    config: HarnessConfig,
    api_mode: GigaChatApiMode,
) -> ModelDiscovery:
    """Try proxy model endpoints and fall back to local hints."""
    paths = _model_paths(api_mode)
    errors: list[str] = []
    for path in paths:
        try:
            data = request_json(
                "GET",
                f"{config.proxy_url}{path}",
                api_key=config.api_key,
                timeout=10,
            )
        except ProxyRequestError as exc:
            errors.append(f"{path}: {exc}")
            continue
        models = _extract_model_ids(data)
        if models:
            return ModelDiscovery(ok=True, models=tuple(models), source=path)

    fallback = tuple(
        model for model in (config.default_model, *DEFAULT_MODEL_HINTS) if model
    )
    return ModelDiscovery(
        ok=False,
        models=tuple(dict.fromkeys(fallback)),
        source="fallback",
        error="; ".join(errors) or "model discovery failed",
    )


def extract_text(data: dict[str, Any]) -> str:
    """Extract text from common Chat Completions-like response shapes."""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
            delta = first.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    return content
            text = first.get("text")
            if isinstance(text, str):
                return text
    for key in ("output_text", "text"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


def safe_raw(data: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted shallow JSON object for results."""
    return redact_secrets(data)


def _model_paths(api_mode: GigaChatApiMode) -> tuple[str, ...]:
    preferred = f"/{api_mode.value}/models"
    other = "/v1/models" if api_mode == GigaChatApiMode.V2 else "/v2/models"
    return (preferred, other, "/models")


def _extract_model_ids(data: dict[str, Any]) -> list[str]:
    raw_models = data.get("data")
    if raw_models is None:
        raw_models = data.get("models")
    if not isinstance(raw_models, list):
        return []
    ids: list[str] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or item.get("model")
        if model_id:
            ids.append(str(model_id))
    return list(dict.fromkeys(ids))


def _read_error_body(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return body[:500]


def _status_indicates_mounted_route(status_code: int | None) -> bool:
    return status_code in {400, 401, 403, 405, 422}


def _route_probe_detail(status_code: int | None) -> str:
    if status_code in {400, 422}:
        return "route rejected the intentionally minimal JSON probe"
    if status_code in {401, 403}:
        return "route is protected by proxy auth"
    if status_code == 405:
        return "path exists but rejected the probe method"
    if status_code == 404:
        return "route not found"
    if status_code is None:
        return "proxy did not respond"
    return "unexpected route probe response"
