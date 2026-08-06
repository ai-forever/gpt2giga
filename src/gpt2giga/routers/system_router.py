from inspect import isawaitable

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, Response

from gpt2giga.app_state import (
    get_gigachat_client,
    get_gigachat_model_catalog,
    get_gigachat_model_catalog_profile_id,
    record_gigachat_model_catalog_snapshot,
)
from gpt2giga.capabilities import resolve_gigachat_route_capabilities
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.openapi_tags import OPENAPI_TAG_SYSTEM_HEALTH
from gpt2giga.protocols.normalized import bridge_loss_matrix_json
from gpt2giga.providers.profiles import not_ready_manifest

system_router = APIRouter(tags=[OPENAPI_TAG_SYSTEM_HEALTH])


@system_router.get("/health", response_class=Response)
@exceptions_handler
async def health() -> Response:
    """Health check."""
    return Response(status_code=200)


@system_router.get("/ping", response_class=Response)
@system_router.post("/ping", response_class=Response)
@exceptions_handler
async def ping() -> Response:
    return await health()


@system_router.get("/ready")
@exceptions_handler
async def ready(request: Request) -> JSONResponse:
    """Return route readiness separately from process liveness."""
    contracts = getattr(request.app.state, "provider_machine_contracts", None)
    runtime = getattr(request.app.state, "bridge_provider_runtime", None)
    if contracts is None:
        manifest = not_ready_manifest()
    else:
        manifest = contracts.readiness_manifest(
            adapters_ready=runtime is not None and runtime.adapters_ready,
            catalog_readiness=getattr(
                request.app.state,
                "model_catalog_readiness",
                None,
            ),
            shutting_down=getattr(
                request.app.state,
                "bridge_shutting_down",
                False,
            ),
        )
    return JSONResponse(
        manifest,
        status_code=200 if manifest["ready"] else 503,
    )


@system_router.get("/bridge/models")
@exceptions_handler
async def bridge_models(request: Request) -> dict:
    """Project the compatibility endpoint from the shared model catalog."""
    snapshot = await _list_model_catalog(request)
    return request.app.state.provider_machine_contracts.models_manifest(snapshot)


@system_router.get("/bridge/capabilities")
@exceptions_handler
async def bridge_capabilities(
    request: Request,
    model: str | None = None,
    protocol: str | None = None,
    api_mode: str | None = None,
) -> dict:
    """Return route support, or effective capabilities when a model is given."""
    if model is None and protocol is None and api_mode is None:
        return request.app.state.provider_machine_contracts.capabilities_manifest(
            bridge_loss_matrix_json()
        )
    if model is None or protocol is None:
        raise HTTPException(
            status_code=400,
            detail={"reason_id": "incomplete_capability_query"},
        )

    resolver = getattr(request.app.state, "effective_capability_resolver", None)
    descriptor = await _get_catalog_model(request, model)
    if resolver is None:
        resolution = resolve_gigachat_route_capabilities(
            model_id=descriptor.id,
            public_protocol=protocol,
            api_mode=api_mode or "v2",
            route_id=descriptor.provider_profile_id,
        )
    else:
        resolution = resolver.resolve(
            model=descriptor,
            public_protocol=protocol,
            api_mode=api_mode,
        )
        if isawaitable(resolution):
            resolution = await resolution
    return request.app.state.provider_machine_contracts.effective_capabilities_manifest(
        model=descriptor,
        resolution=resolution,
        public_protocol=protocol,
        api_mode=api_mode,
    )


def _injected_catalog_context(request: Request):
    return getattr(
        request.state,
        "model_discovery_context",
        getattr(request.app.state, "model_discovery_context", None),
    )


async def _list_model_catalog(request: Request):
    static_snapshot = getattr(
        request.app.state,
        "static_model_catalog_snapshot",
        None,
    )
    if static_snapshot is not None:
        return static_snapshot

    injected_catalog = getattr(request.app.state, "model_catalog", None)
    injected_context = _injected_catalog_context(request)
    if injected_catalog is not None and injected_context is not None:
        return await injected_catalog.list_models(injected_context)

    giga_client = _configured_gigachat_client(
        request,
        reason_id="model_catalog_unavailable",
    )
    catalog = get_gigachat_model_catalog(request)
    snapshot = await catalog.list_models(
        giga_client,
        provider_profile_id=get_gigachat_model_catalog_profile_id(request),
    )
    record_gigachat_model_catalog_snapshot(request, snapshot)
    return snapshot


async def _get_catalog_model(request: Request, model_id: str):
    injected_catalog = getattr(request.app.state, "model_catalog", None)
    injected_context = _injected_catalog_context(request)
    if injected_catalog is not None and injected_context is not None:
        return await injected_catalog.get_model(model_id, injected_context)

    giga_client = _configured_gigachat_client(
        request,
        reason_id="effective_capabilities_unavailable",
    )
    catalog = get_gigachat_model_catalog(request)
    return await catalog.get_model(
        model_id,
        giga_client,
        provider_profile_id=get_gigachat_model_catalog_profile_id(request),
    )


def _configured_gigachat_client(request: Request, *, reason_id: str):
    try:
        return get_gigachat_client(request)
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"reason_id": reason_id},
        ) from exc
