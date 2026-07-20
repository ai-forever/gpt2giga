"""Backend-authoritative, redaction-safe Cockpit Settings APIs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.config import DEFAULT_MODEL_HINTS
from gpt2giga_harness.mcp import MCPProbeHistoryStore, build_mcp_inventory
from gpt2giga_harness.project import (
    load_project_config,
    load_project_state,
    resolve_project,
)
from gpt2giga_harness.provider_settings import (
    ProviderRegistryConflict,
    ProviderSettingsNotFoundError,
    ProviderSettingsService,
    ProviderSettingsValidationError,
)
from gpt2giga_harness.runtime.policy import permission_profile
from gpt2giga_harness.settings import (
    SETTINGS_FIELDS,
    HarnessDefaultsSnapshot,
    SettingsConflictError,
)
from gpt2giga_harness.types import parse_api_mode
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.workbench_execution import workbench_transport_projection


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/settings")
def settings_read_model(
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return bounded settings categories without credentials or raw paths."""
    config = request.app.state.harness_config
    snapshot = request.app.state.harness_settings_store.load()
    try:
        project = resolve_project(workspace, data_dir=config.data_dir)
        project_config = load_project_config(project.root)
        project_state = load_project_state(project)
        descriptors, mcp_errors = build_mcp_inventory(project_config.tool_profiles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    history = MCPProbeHistoryStore(config.data_dir)
    defaults = snapshot.defaults
    provider_registry = request.app.state.harness_provider_settings_service.list()
    configured_providers = provider_registry["providers"]
    harnesses = []
    for harness in request.app.state.harness_registry.list():
        spec = harness.spec()
        availability = harness.availability()
        harnesses.append(
            {
                "id": spec.id,
                "title": spec.title,
                "native_supported": spec.supports_native_sessions,
                "status": availability.status.value,
                "workbench_transport": workbench_transport_projection(harness),
            }
        )
    models = list(
        dict.fromkeys(
            model
            for model in (
                defaults.default_model,
                defaults.default_title_model,
                *DEFAULT_MODEL_HINTS,
            )
            if model
        )
    )[:20]
    return {
        "revision": snapshot.revision,
        "runtime": {
            "proxy_url": _public_url(config.proxy_url),
            "proxy_source": _runtime_source("GPT2GIGA_HARNESS_PROXY_URL"),
            "proxy_health": "not_checked",
            "auto_start_proxy": config.auto_start_proxy,
            "change_effect": "restart_required",
            "editable": False,
            "proxy_auth_configured": config.api_key is not None,
        },
        "provider": {
            "configured": bool(configured_providers),
            "count": len(configured_providers),
            "source": "user_registry" if configured_providers else "unconfigured",
            "health": _provider_health(configured_providers),
            "secret_readable": False,
            "change_effect": "new_session_required",
            "registry_path_readable": False,
        },
        "routes": {
            "default_api_mode": defaults.default_api_mode,
            "default_model": defaults.default_model,
            "default_api_mode_source": snapshot.sources["default_api_mode"],
            "default_model_source": snapshot.sources["default_model"],
            "models": models,
            "models_source": "configured_default_and_fallbacks",
            "health": "not_checked",
            "change_effect": "new_runs",
        },
        "harness_defaults": {
            **asdict(defaults),
            "harnesses": harnesses[:100],
            "sources": dict(snapshot.sources),
            "locked_fields": list(snapshot.locked_fields),
            "change_effect": "new_runs",
        },
        "workspace": {
            "project_id": project.id,
            "name": project.name,
            "is_git_repo": project.is_git_repo,
            "trusted": project_state.trusted,
            "workspace_policies": ["auto", "current", "worktree"],
            "permission_profiles": [
                "interactive",
                "review_every_action",
                "unattended",
            ],
            "source": "project_state",
        },
        "mcp": {
            "servers": [
                {
                    "id": descriptor.id,
                    "title": descriptor.title,
                    "transport": descriptor.transport.value,
                    "enabled": descriptor.enabled,
                    "trusted": descriptor.trusted,
                    "source": descriptor.source,
                    "health": _mcp_health(history, descriptor.id),
                }
                for descriptor in descriptors[:100]
            ],
            "errors": list(mcp_errors)[:20],
            "change_effect": "managed_home_restart",
        },
        "diagnostics": {
            "content_free": True,
            "actions": [
                {"id": "check_runtime", "method": "GET", "path": "/api/health"},
                {
                    "id": "provider_settings",
                    "method": "GET",
                    "path": "/api/providers",
                },
            ],
            "async_data_plane": request.app.state.harness_async_diagnostics.snapshot(),
        },
    }


@router.get("/api/providers")
def list_provider_settings(request: Request) -> dict[str, Any]:
    """Return the reference-only provider registry and template catalog."""
    return request.app.state.harness_provider_settings_service.list()


@router.get("/api/providers/{provider_id}")
def get_provider_settings(request: Request, provider_id: str) -> dict[str, Any]:
    """Return one backend-owned provider projection."""
    try:
        return request.app.state.harness_provider_settings_service.get(provider_id)
    except ProviderSettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except ProviderSettingsValidationError as exc:
        raise _provider_field_error(exc) from exc


@router.post("/api/providers")
def create_provider_settings(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Create and authoritatively read back one reference-only provider."""
    provider_id = payload.get("id")
    spec = {key: value for key, value in payload.items() if key != "id"}
    try:
        result = request.app.state.harness_provider_settings_service.create(
            provider_id,
            spec,
        )
    except ProviderSettingsValidationError as exc:
        raise _provider_field_error(exc) from exc
    except ProviderRegistryConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "provider_conflict", "message": str(exc)},
        ) from exc
    return {"saved": True, "provider": result.provider, "effects": result.effects}


@router.patch("/api/providers/{provider_id}")
def update_provider_settings(
    request: Request,
    provider_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Optimistically edit and read back one reference-only provider."""
    expected_revision = payload.get("expected_revision")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise _field_error({"expected_revision": "expected an integer revision"})
    spec = {key: value for key, value in payload.items() if key != "expected_revision"}
    try:
        result = request.app.state.harness_provider_settings_service.update(
            provider_id,
            spec,
            expected_revision=expected_revision,
        )
    except ProviderSettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except ProviderSettingsValidationError as exc:
        raise _provider_field_error(exc) from exc
    except ProviderRegistryConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "provider_conflict", "message": str(exc)},
        ) from exc
    return {"saved": True, "provider": result.provider, "effects": result.effects}


@router.post("/api/providers/{provider_id}/test")
def test_provider_settings(request: Request, provider_id: str) -> dict[str, Any]:
    """Run one explicit bounded provider connection check."""
    return _run_provider_check(request, provider_id, discover_models=False)


@router.post("/api/providers/{provider_id}/discover")
def discover_provider_models(request: Request, provider_id: str) -> dict[str, Any]:
    """Run one explicit bounded provider model-discovery check."""
    return _run_provider_check(request, provider_id, discover_models=True)


@router.patch("/api/settings/defaults")
def update_settings_defaults(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Validate, atomically persist, and read back new-run defaults."""
    store = request.app.state.harness_settings_store
    current = store.load()
    patch = payload.get("defaults", payload)
    if not isinstance(patch, Mapping):
        raise _field_error({"defaults": "expected an object"})
    expected_revision = payload.get("expected_revision")
    unknown = sorted(set(patch) - SETTINGS_FIELDS - {"expected_revision"})
    if unknown:
        raise _field_error({field: "unknown setting" for field in unknown})
    locked = set(current.locked_fields)
    locked_changes = {
        field: "owned by the environment; restart with a new environment value"
        for field in patch
        if field in locked and getattr(current.defaults, field) != patch[field]
    }
    if locked_changes:
        raise HTTPException(
            status_code=409,
            detail={"code": "environment_owned", "field_errors": locked_changes},
        )
    values = {**asdict(current.defaults), **dict(patch)}
    field_errors = _validate_defaults(request, values)
    if field_errors:
        raise _field_error(field_errors)
    try:
        saved = store.save(values, expected_revision=_optional_text(expected_revision))
    except SettingsConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "revision_conflict", "message": str(exc)},
        ) from exc
    return _saved_defaults(saved)


def _validate_defaults(request: Request, values: Mapping[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    harness_id = _optional_text(values.get("default_harness_id"))
    harness = None
    if harness_id is None:
        errors["default_harness_id"] = "select a harness"
    else:
        try:
            harness = request.app.state.harness_registry.get(harness_id)
        except KeyError:
            errors["default_harness_id"] = "unknown harness"
    try:
        api_mode = parse_api_mode(values.get("default_api_mode"))
    except ValueError:
        errors["default_api_mode"] = "expected v1 or v2"
        api_mode = None
    for field in ("default_model", "default_title_model"):
        model = values.get(field)
        if model is not None and (
            not isinstance(model, str)
            or not model.strip()
            or len(model.strip()) > 200
            or any(ord(character) < 32 for character in model)
        ):
            errors[field] = "expected a non-empty model name up to 200 characters"
    invocation = values.get("invocation_mode")
    if invocation not in {"headless", "native"}:
        errors["invocation_mode"] = "expected headless or native"
    elif invocation == "native" and harness is not None:
        if not harness.spec().supports_native_sessions:
            errors["invocation_mode"] = (
                "selected harness does not support native sessions"
            )
    transport = values.get("execution_transport")
    if transport not in {"native_structured", "native_terminal", "one_shot"}:
        errors["execution_transport"] = (
            "expected native_structured, native_terminal, or one_shot"
        )
    elif transport == "native_terminal" and harness is not None:
        if not harness.spec().supports_native_sessions:
            errors["execution_transport"] = (
                "selected harness does not support native terminal sessions"
            )
    if transport == "native_terminal" and invocation != "native":
        errors.setdefault(
            "invocation_mode", "native_terminal requires native invocation"
        )
    elif transport in {"native_structured", "one_shot"} and invocation != "headless":
        errors.setdefault(
            "invocation_mode", f"{transport} requires headless invocation"
        )
    if values.get("mode") not in {"plan", "act"}:
        errors["mode"] = "expected plan or act"
    if values.get("workspace_policy") not in {"auto", "current", "worktree"}:
        errors["workspace_policy"] = "expected auto, current, or worktree"
    try:
        permission_profile(values.get("permission_profile"), origin="manual")
    except ValueError as exc:
        errors["permission_profile"] = str(exc)
    if not isinstance(values.get("stream"), bool):
        errors["stream"] = "expected true or false"
    if harness is not None and api_mode is not None:
        spec = harness.spec()
        if not spec.supports_api_mode_selection and api_mode.value != "v2":
            errors["default_api_mode"] = "selected harness fixes its API mode"
    return errors


def _saved_defaults(snapshot: HarnessDefaultsSnapshot) -> dict[str, Any]:
    return {
        "saved": True,
        "revision": snapshot.revision,
        "defaults": asdict(snapshot.defaults),
        "sources": dict(snapshot.sources),
        "locked_fields": list(snapshot.locked_fields),
        "change_effect": "new_runs",
    }


def _field_error(errors: Mapping[str, str]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "invalid_settings", "field_errors": dict(errors)},
    )


def _public_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _runtime_source(name: str) -> str:
    import os

    return "environment" if os.getenv(name) else "built_in"


def _provider_health(providers: list[dict[str, Any]]) -> str:
    states = {
        item["health"]["status"] for item in providers if item.get("health") is not None
    }
    if "unhealthy" in states or "blocked" in states:
        return "attention_required"
    if "ready" in states:
        return "ready"
    return "not_checked"


def _provider_field_error(exc: ProviderSettingsValidationError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "invalid_provider", "field_errors": exc.field_errors},
    )


def _run_provider_check(
    request: Request,
    provider_id: str,
    *,
    discover_models: bool,
) -> dict[str, Any]:
    service: ProviderSettingsService = (
        request.app.state.harness_provider_settings_service
    )
    try:
        return service.check(provider_id, discover_models=discover_models)
    except ProviderSettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except ProviderSettingsValidationError as exc:
        raise _provider_field_error(exc) from exc


def _mcp_health(history: MCPProbeHistoryStore, server_id: str) -> str:
    latest = history.list(server_id, limit=1)
    return str(latest[0].get("status") or "not_checked") if latest else "not_checked"


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
