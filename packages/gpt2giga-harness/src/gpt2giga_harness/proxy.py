"""Small synchronous client helpers for the local gpt2giga proxy."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import os
from queue import Empty, Full, Queue
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gpt2giga_harness.config import DEFAULT_MODEL_HINTS, HarnessConfig
from gpt2giga_harness.gpt2giga_preset import (
    GPT2GIGA_PRESET_EXTRA,
    gpt2giga_preset_available,
)
from gpt2giga_harness.types import GigaChatApiMode, HarnessContext, redact_secrets


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


@dataclass(frozen=True)
class SidecarPreflight:
    """Explain whether the local proxy sidecar can be started."""

    ok: bool
    reason: str


@dataclass(frozen=True)
class ProxyStartup:
    """Result of preparing a local proxy for a harness request."""

    ok: bool
    proxy_url: str | None = None
    started: bool = False
    api_key: str | None = None
    pid: int | None = None
    ownership_id: str | None = None
    health_path: str | None = None
    health_status_code: int | None = None
    detail: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ProxyRoutePreflight:
    """Route-aware proxy preparation result for one CLI execution."""

    ok: bool
    proxy_url: str
    api_mode: GigaChatApiMode
    route_path: str
    startup: ProxyStartup
    status_code: int | None = None
    detail: str | None = None
    error: str | None = None

    @property
    def api_key(self) -> str | None:
        """Return the transient proxy key without serializing it as evidence."""
        return self.startup.api_key


_SIDECAR_API_KEYS: dict[str, str] = {}
_OWNED_SIDECARS: dict[str, subprocess.Popen[Any]] = {}
_OWNED_SIDECARS_LOCK = threading.RLock()
_STREAM_POLL_SECONDS = 0.02
_STREAM_QUEUE_SIZE = 128


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


def stream_sse_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
    cancel_event: Any | None = None,
    idle_callback: Callable[[], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON objects from an SSE response."""
    if _cancel_requested(cancel_event):
        return
    body = None
    headers = {"Accept": "text/event-stream"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    request = Request(url, data=body, headers=headers, method=method.upper())
    data_lines: list[str] = []
    saw_event = False
    output_queue: Queue[tuple[str, Any]] = Queue(maxsize=_STREAM_QUEUE_SIZE)
    stop_event = threading.Event()
    response_holder: dict[str, Any] = {}

    def publish(kind: str, value: Any) -> None:
        while not stop_event.is_set():
            try:
                output_queue.put((kind, value), timeout=_STREAM_POLL_SECONDS)
                return
            except Full:
                continue

    def read_response() -> None:
        try:
            with urlopen(request, timeout=timeout) as response:
                response_holder["response"] = response
                for raw_line in response:
                    if stop_event.is_set():
                        break
                    publish("line", raw_line)
        except Exception as exc:
            publish("error", exc)
        finally:
            response_holder.pop("response", None)
            publish("done", None)

    reader = threading.Thread(
        target=read_response,
        name="gpt2giga-harness-sse-reader",
        daemon=True,
    )
    reader.start()
    try:
        while True:
            if _cancel_requested(cancel_event):
                return
            try:
                kind, value = output_queue.get(timeout=_STREAM_POLL_SECONDS)
            except Empty:
                if idle_callback is not None:
                    idle_callback()
                continue
            if kind == "done":
                break
            if kind == "error":
                raise value
            raw_line = value
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if not data_lines:
                    continue
                data = "\n".join(data_lines)
                data_lines.clear()
                if data == "[DONE]":
                    return
                yield _decode_sse_json(data)
                saw_event = True
                continue
            if line.startswith(":"):
                continue
            field, separator, field_value = line.partition(":")
            if field == "data":
                data_lines.append(field_value.lstrip(" ") if separator else "")
        if data_lines:
            data = "\n".join(data_lines)
            if data != "[DONE]":
                yield _decode_sse_json(data)
                saw_event = True
    except HTTPError as exc:
        error_body = _read_error_body(exc)
        message = f"proxy returned HTTP {exc.code}"
        if error_body:
            message = f"{message}: {error_body}"
        raise ProxyRequestError(message, status_code=exc.code) from exc
    except URLError as exc:
        raise ProxyRequestError(f"proxy is not reachable: {exc.reason}") from exc
    except (OSError, TimeoutError) as exc:
        raise ProxyRequestError(f"proxy stream failed: {exc}") from exc
    finally:
        stop_event.set()
        response = response_holder.get("response")
        close = getattr(response, "close", None)
        if callable(close):
            close()
        reader.join(timeout=_STREAM_POLL_SECONDS * 2)
    if not saw_event and not _cancel_requested(cancel_event):
        raise ProxyRequestError("proxy returned an empty SSE stream")


def health_check(config: HarnessConfig) -> ProxyHealth:
    """Check common local proxy health paths without requiring credentials."""
    return _health_check_url(config.proxy_url)


def sidecar_preflight(context: HarnessContext) -> SidecarPreflight:
    """Validate whether this process can start a local gpt2giga sidecar."""
    if not context.auto_start_proxy:
        return SidecarPreflight(ok=False, reason="auto-start disabled")
    parsed = urlparse(context.proxy_url)
    if parsed.scheme != "http":
        return SidecarPreflight(
            ok=False,
            reason="auto-start supports only http:// local proxy URLs",
        )
    host = parsed.hostname or ""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return SidecarPreflight(
            ok=False,
            reason="auto-start is limited to 127.0.0.1, localhost, or ::1",
        )
    path = parsed.path.rstrip("/")
    if path:
        return SidecarPreflight(
            ok=False,
            reason="auto-start requires a proxy URL without a path component",
        )
    if not gpt2giga_preset_available():
        return SidecarPreflight(
            ok=False,
            reason=(
                "optional gpt2giga preset is not installed; install "
                f"gpt2giga-harness[{GPT2GIGA_PRESET_EXTRA}]"
            ),
        )
    if not _has_upstream_credentials(os.environ):
        return SidecarPreflight(
            ok=False,
            reason=(
                "missing GigaChat credentials; set GIGACHAT_CREDENTIALS or "
                "GIGACHAT_ACCESS_TOKEN"
            ),
        )
    return SidecarPreflight(ok=True, reason="ready")


def cached_sidecar_api_key(proxy_url: str) -> str | None:
    """Return the generated sidecar API key for this process, if any."""
    return _SIDECAR_API_KEYS.get(proxy_url)


def ensure_proxy_available(
    context: HarnessContext,
    api_mode: GigaChatApiMode,
    *,
    use_cached_sidecar_key: bool = True,
) -> ProxyStartup:
    """Return a reachable proxy or start a local sidecar when allowed."""
    cached_api_key = context.api_key
    if cached_api_key is None and use_cached_sidecar_key:
        cached_api_key = cached_sidecar_api_key(context.proxy_url)
    health = _health_check_url(context.proxy_url)
    if health.ok:
        return ProxyStartup(
            ok=True,
            proxy_url=context.proxy_url,
            api_key=cached_api_key,
            health_path=health.path,
            health_status_code=health.status_code,
            detail=f"proxy already reachable via {health.path}",
        )

    preflight = sidecar_preflight(context)
    if not preflight.ok:
        return ProxyStartup(
            ok=False,
            proxy_url=context.proxy_url,
            api_key=cached_api_key,
            error=preflight.reason,
        )

    return _start_local_sidecar(context, api_mode, cached_api_key)


def ensure_proxy_route_available(
    context: HarnessContext,
    api_mode: GigaChatApiMode,
) -> ProxyRoutePreflight:
    """Prepare a proxy and prove the selected compatibility route is usable."""
    route_path = f"/{api_mode.value}/models"
    startup = ensure_proxy_available(
        context,
        api_mode,
        use_cached_sidecar_key=False,
    )
    if not startup.ok:
        return ProxyRoutePreflight(
            ok=False,
            proxy_url=context.proxy_url,
            api_mode=api_mode,
            route_path=route_path,
            startup=startup,
            error=redact_secrets(startup.error or "proxy is not reachable"),
        )
    try:
        request_json(
            "GET",
            f"{context.proxy_url.rstrip('/')}{route_path}",
            api_key=startup.api_key or context.api_key,
            timeout=5,
        )
    except ProxyRequestError as exc:
        stop_owned_sidecar(startup)
        if exc.status_code in {401, 403}:
            error = (
                f"proxy route {route_path} rejected authentication; configure "
                "GPT2GIGA_HARNESS_API_KEY for an existing auth-enabled proxy"
            )
        else:
            error = f"proxy compatibility route {route_path} is unavailable: {exc}"
        return ProxyRoutePreflight(
            ok=False,
            proxy_url=context.proxy_url,
            api_mode=api_mode,
            route_path=route_path,
            startup=startup,
            status_code=exc.status_code,
            error=redact_secrets(error),
        )
    return ProxyRoutePreflight(
        ok=True,
        proxy_url=context.proxy_url,
        api_mode=api_mode,
        route_path=route_path,
        startup=startup,
        status_code=200,
        detail="selected compatibility route accepted authenticated model discovery",
    )


def proxy_route_preflight_to_dict(
    result: ProxyRoutePreflight,
) -> dict[str, Any]:
    """Serialize route evidence without exposing the transient proxy key."""
    ownership = "owned" if result.startup.started else "external"
    return {
        "ok": result.ok,
        "proxy_url": _public_proxy_url(result.proxy_url),
        "api_mode": result.api_mode.value,
        "route_path": result.route_path,
        "route_status_code": result.status_code,
        "health_path": result.startup.health_path,
        "health_status_code": result.startup.health_status_code,
        "auth": "configured" if result.api_key else "not_configured",
        "ownership": ownership,
        "sidecar_pid": result.startup.pid if result.startup.started else None,
        "ownership_id": (
            result.startup.ownership_id if result.startup.started else None
        ),
        "detail": redact_secrets(result.detail or result.startup.detail),
        "error": redact_secrets(result.error),
    }


def stop_owned_sidecar(startup: ProxyStartup) -> bool:
    """Stop a sidecar only when this process owns the exact startup handle."""
    ownership_id = startup.ownership_id
    if not startup.started or ownership_id is None:
        return False
    with _OWNED_SIDECARS_LOCK:
        process = _OWNED_SIDECARS.pop(ownership_id, None)
    if process is None:
        return False
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    if startup.proxy_url and startup.api_key == _SIDECAR_API_KEYS.get(
        startup.proxy_url
    ):
        _SIDECAR_API_KEYS.pop(startup.proxy_url, None)
    return True


def _health_check_url(proxy_url: str) -> ProxyHealth:
    """Check common local proxy health paths without requiring credentials."""
    last_error = "proxy did not respond"
    for path in ("/health", "/ping", "/"):
        url = f"{proxy_url}{path}"
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=5) as response:
                return ProxyHealth(
                    ok=200 <= response.status < 500,
                    url=proxy_url,
                    path=path,
                    status_code=response.status,
                )
        except HTTPError as exc:
            if exc.code < 500:
                return ProxyHealth(
                    ok=True,
                    url=proxy_url,
                    path=path,
                    status_code=exc.code,
                )
        except URLError as exc:
            last_error = str(exc.reason)
    return ProxyHealth(ok=False, url=proxy_url, error=last_error)


def probe_json_route(
    config: HarnessConfig,
    path: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
    model: str | None = None,
) -> RouteProbe:
    """Probe whether a JSON route is mounted without requiring upstream success."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    try:
        request_json(
            method,
            f"{config.proxy_url}{normalized_path}",
            payload=payload
            if payload is not None
            else _default_route_probe_payload(config, model=model),
            api_key=config.api_key or cached_sidecar_api_key(config.proxy_url),
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
    *,
    include_compat_paths: bool = True,
    include_fallback: bool = True,
) -> ModelDiscovery:
    """Try proxy model endpoints and fall back to local hints."""
    paths = (
        _model_paths(api_mode)
        if include_compat_paths
        else (f"/{api_mode.value}/models",)
    )
    errors: list[str] = []
    for path in paths:
        try:
            data = request_json(
                "GET",
                f"{config.proxy_url}{path}",
                api_key=config.api_key or cached_sidecar_api_key(config.proxy_url),
                timeout=10,
            )
        except ProxyRequestError as exc:
            errors.append(f"{path}: {exc}")
            continue
        models = _extract_model_ids(data)
        if models:
            return ModelDiscovery(ok=True, models=tuple(models), source=path)

    if not include_fallback:
        return ModelDiscovery(
            ok=False,
            models=(),
            source=paths[0],
            error="; ".join(errors) or f"{paths[0]} returned no models",
        )

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


def _start_local_sidecar(
    context: HarnessContext,
    api_mode: GigaChatApiMode,
    api_key: str | None,
) -> ProxyStartup:
    parsed = urlparse(context.proxy_url)
    port = parsed.port or 80
    bind_host = "::1" if parsed.hostname == "::1" else "127.0.0.1"
    api_key = api_key or secrets.token_urlsafe(32)
    env = _sidecar_env(
        context,
        api_mode,
        host=bind_host,
        port=port,
        api_key=api_key,
    )
    process = subprocess.Popen(
        [sys.executable, "-c", "from gpt2giga import run; run()"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + context.proxy_start_timeout_seconds
    ownership_id = f"sidecar_{secrets.token_hex(12)}"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return ProxyStartup(
                ok=False,
                proxy_url=context.proxy_url,
                api_key=api_key,
                error=f"proxy sidecar exited early with code {process.returncode}",
            )
        health = _health_check_url(context.proxy_url)
        if health.ok:
            _SIDECAR_API_KEYS[context.proxy_url] = api_key
            with _OWNED_SIDECARS_LOCK:
                _OWNED_SIDECARS[ownership_id] = process
            return ProxyStartup(
                ok=True,
                proxy_url=context.proxy_url,
                started=True,
                api_key=api_key,
                pid=process.pid,
                ownership_id=ownership_id,
                health_path=health.path,
                health_status_code=health.status_code,
                detail=f"started local proxy sidecar on port {port}",
            )
        time.sleep(0.2)

    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
    return ProxyStartup(
        ok=False,
        proxy_url=context.proxy_url,
        api_key=api_key,
        error=(
            f"timed out waiting for local proxy sidecar to start at {context.proxy_url}"
        ),
    )


def _sidecar_env(
    context: HarnessContext,
    api_mode: GigaChatApiMode,
    *,
    host: str,
    port: int,
    api_key: str,
) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GPT2GIGA_MODE": "DEV",
            "GPT2GIGA_HOST": host,
            "GPT2GIGA_PORT": str(port),
            "GPT2GIGA_ENABLE_API_KEY_AUTH": "True",
            "GPT2GIGA_API_KEY": api_key,
            "GPT2GIGA_GIGACHAT_API_MODE": api_mode.value,
            "GPT2GIGA_PASS_MODEL": "False",
            "GPT2GIGA_DISABLE_REASONING": "True",
        }
    )
    if context.default_model and not env.get("GIGACHAT_MODEL"):
        env["GIGACHAT_MODEL"] = context.default_model
    return env


def _has_upstream_credentials(env: dict[str, str]) -> bool:
    for name in ("GIGACHAT_CREDENTIALS", "GIGACHAT_ACCESS_TOKEN", "GIGACHAT_USER"):
        value = env.get(name)
        if value and value.strip():
            return True
    return False


def _public_proxy_url(proxy_url: str) -> str:
    """Remove userinfo, query, and fragment from persisted proxy evidence."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    return parsed._replace(netloc=netloc, query="", fragment="").geturl()


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
        metadata = item.get("metadata")
        model_type = item.get("type")
        if model_type is None and isinstance(metadata, Mapping):
            model_type = metadata.get("type")
        if model_type is not None and model_type != "chat":
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


def _decode_sse_json(data: str) -> dict[str, Any]:
    try:
        decoded = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProxyRequestError("proxy returned invalid JSON in SSE stream") from exc
    if not isinstance(decoded, Mapping):
        raise ProxyRequestError("proxy returned SSE JSON that is not an object")
    return dict(decoded)


def _cancel_requested(cancel_event: Any | None) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def _default_route_probe_payload(
    config: HarnessConfig,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model or config.default_model or DEFAULT_MODEL_HINTS[0],
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
    }
    return payload


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
