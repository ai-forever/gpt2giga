"""FastAPI app for the minimal Unified Harness browser UI."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from gpt2giga.harness import proxy
from gpt2giga.harness.config import HarnessConfig, pass_model_env_note
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
            ]
        }

    @app.get("/api/models")
    async def models(api_mode: str = Query(default="v2")) -> dict[str, Any]:
        mode = parse_api_mode(api_mode)
        discovery = proxy.discover_models(config, mode)
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
        request = HarnessRequest(
            prompt=str(payload.get("prompt") or ""),
            model=_optional_text(payload.get("model")),
            api_mode=parse_api_mode(payload.get("api_mode")),
            capability=parse_capability(
                payload.get("capability") or HarnessCapability.CHAT_COMPLETIONS.value
            ),
            mode=str(payload.get("mode") or "plan"),
            workspace=resolve_workspace(_optional_text(payload.get("workspace"))),
        )
        result = harness.run(request, config.to_context())
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
