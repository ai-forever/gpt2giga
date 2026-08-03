from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

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
    """Return deterministic public aliases without provider discovery I/O."""
    return request.app.state.provider_machine_contracts.models_manifest()


@system_router.get("/bridge/capabilities")
@exceptions_handler
async def bridge_capabilities(request: Request) -> dict:
    """Return the complete frozen protocol/provider capability matrix."""
    return request.app.state.provider_machine_contracts.capabilities_manifest(
        bridge_loss_matrix_json()
    )
