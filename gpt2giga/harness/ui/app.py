"""FastAPI app for the minimal Unified Harness browser UI."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from gpt2giga.harness import proxy
from gpt2giga.harness.config import (
    DEFAULT_MODEL_HINTS,
    HarnessConfig,
    pass_model_env_note,
)
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry
from gpt2giga.harness.types import (
    HarnessCapability,
    HarnessRequest,
    availability_to_dict,
    parse_api_mode,
    parse_capability,
    result_to_dict,
    spec_to_dict,
)
from gpt2giga.harness.ui.static import INDEX_HTML
from gpt2giga.harness.workspace import resolve_workspace


def create_app(
    config: HarnessConfig | None = None,
    registry: HarnessRegistry | None = None,
) -> FastAPI:
    """Create the Unified Harness UI app."""
    config = config or HarnessConfig.from_env()
    registry = registry or create_default_registry()
    app = FastAPI(title="gpt2giga Unified Harness", docs_url=None, redoc_url=None)
    app.state.harness_config = config
    app.state.harness_registry = registry

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    @app.get("/api/harnesses")
    async def harnesses() -> dict[str, Any]:
        return {
            "harnesses": [
                {
                    "spec": spec_to_dict(harness.spec()),
                    "availability": availability_to_dict(harness.availability()),
                }
                for harness in registry.list()
            ],
            "discovery_errors": list(registry.discovery_errors),
        }

    @app.get("/api/defaults")
    async def defaults() -> dict[str, Any]:
        return {
            "proxy_url": config.proxy_url,
            "default_model": config.default_model or DEFAULT_MODEL_HINTS[0],
            "default_api_mode": config.default_api_mode.value,
            "auto_start_proxy": config.auto_start_proxy,
            "proxy_start_timeout_seconds": config.proxy_start_timeout_seconds,
            "note": pass_model_env_note(),
        }

    @app.get("/api/models")
    async def models(api_mode: str = Query(default="v2")) -> dict[str, Any]:
        try:
            mode = parse_api_mode(api_mode)
        except ValueError:
            return {
                "ok": False,
                "models": _fallback_models(config),
                "source": "fallback",
                "error": "invalid api_mode; expected v1 or v2",
                "note": pass_model_env_note(),
            }
        try:
            discovery = proxy.discover_models(config, mode)
        except Exception:
            return {
                "ok": False,
                "models": _fallback_models(config),
                "source": "fallback",
                "error": "model discovery failed",
                "note": pass_model_env_note(),
            }
        return {
            "ok": discovery.ok,
            "models": list(discovery.models),
            "source": discovery.source,
            "error": discovery.error,
            "note": pass_model_env_note(),
        }

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        status = proxy.health_check(config)
        return {
            "ok": status.ok,
            "proxy_url": status.url,
            "path": status.path,
            "status_code": status.status_code,
            "error": status.error,
        }

    @app.post("/api/run")
    async def run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        harness_id = str(payload.get("harness_id") or "echo")
        try:
            harness = registry.get(harness_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        extra = dict(extra)
        if bool(payload.get("dry_run")):
            extra["dry_run"] = True
        try:
            api_mode = parse_api_mode(payload.get("api_mode"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid api_mode; expected v1 or v2",
            ) from exc
        try:
            capability = parse_capability(
                payload.get("capability") or HarnessCapability.CHAT_COMPLETIONS.value
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid capability",
            ) from exc
        request = HarnessRequest(
            prompt=str(payload.get("prompt") or ""),
            model=_optional_text(payload.get("model")),
            api_mode=api_mode,
            capability=capability,
            mode=str(payload.get("mode") or "plan"),
            stream=bool(payload.get("stream")),
            workspace=resolve_workspace(_optional_text(payload.get("workspace"))),
            extra=extra,
        )
        try:
            result = harness.run(request, config.to_context())
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Harness run failed",
            ) from exc
        return result_to_dict(result)

    return app


def validate_ui_bind(host: str, *, allow_remote: bool) -> None:
    """Reject unsafe remote UI binding unless explicitly allowed."""
    if host == "0.0.0.0" and not allow_remote:
        raise ValueError(
            "Refusing to bind UI to 0.0.0.0 without --allow-remote. "
            "The UI may expose local harness execution."
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fallback_models(config: HarnessConfig) -> list[str]:
    return list(
        dict.fromkeys(
            model for model in (config.default_model, *DEFAULT_MODEL_HINTS) if model
        )
    )
