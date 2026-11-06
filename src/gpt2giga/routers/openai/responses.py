"""OpenAI Responses endpoint orchestration."""

from fastapi import APIRouter, Request

from gpt2giga.app.responses_mode import (
    ResponsesExecutionMode,
    select_responses_execution,
)
from gpt2giga.app.responses_execution import (
    NativeGigaChatResponsesExecutor,
    NormalizedBridgeResponsesExecutor,
)
from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.gigachat_options import extract_gigachat_request_options
from gpt2giga.core.context import get_request_context
from gpt2giga.common.client_params import (
    ClientCompatibilityError,
    client_compatibility_response,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.response_storage import (
    finish_snapshot,
    prepare_snapshot,
    require_gateway_storage,
    owned_resource,
    paged_items,
    gateway_storage_enabled,
    response_resource_owner,
)
from gpt2giga.openapi_specs.openai import (
    responses_openapi_extra,
    responses_input_tokens_openapi_extra,
)
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_RESPONSES
from gpt2giga.protocols.normalized import (
    BridgeMatrixAdmissionError,
    NormalizedTokenCountRequest,
)
from gpt2giga.protocols.openai.responses_request import responses_request_to_normalized
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.gigachat.model_resolution import resolve_upstream_model
from gpt2giga.providers.profiles import ProviderAliasError

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_RESPONSES])


@router.post(
    "/responses/input_tokens", openapi_extra=responses_input_tokens_openapi_extra()
)
@exceptions_handler
async def input_tokens(request: Request):
    """Estimate supported textual input using GigaChat's token-count API."""
    data = await read_request_json(request)
    options = extract_gigachat_request_options(request, data)
    for key in ("previous_response_id", "conversation", "store", "background"):
        if data.get(key):
            raise ClientCompatibilityError(
                "Token estimation supports stateless textual input only.", param=key
            )
    try:
        selection = select_responses_execution(
            request.app.state, requested_model=data.get("model")
        )
    except ProviderAliasError as exc:
        raise ClientCompatibilityError(
            exc.message, param="model", code=exc.code
        ) from exc
    if selection.mode is not ResponsesExecutionMode.NATIVE_GIGACHAT:
        raise ClientCompatibilityError(
            "Token estimation requires a GigaChat provider.", param="model"
        )
    forced_model = selection.route.upstream_model if selection.route else None
    resolution = resolve_upstream_model(
        data, request.app.state.config, forced_model=forced_model
    )
    normalized = responses_request_to_normalized({**data, "model": resolution.model})
    for message in normalized.messages:
        if isinstance(message.content, list) and any(
            part.type != "text" for part in message.content
        ):
            raise ClientCompatibilityError(
                "Files and images cannot be included in this text-only estimate.",
                param="input",
            )
    if any(tool.type != "function" for tool in normalized.tools):
        raise ClientCompatibilityError(
            "Hosted tools cannot be included in this estimate.", param="tools"
        )
    provider = GigaChatProviderAdapter(
        config=request.app.state.config,
        request_transformer=request.app.state.request_transformer,
        giga_client=get_gigachat_client(request),
        model_limiter=get_model_concurrency_limiter(request),
        request_options=options,
        forced_model=resolution.model,
    )
    counted = await provider.count_tokens(
        NormalizedTokenCountRequest(
            model=resolution.model, input=normalized, protocol="openai"
        ),
        context=get_request_context(),
    )
    return {"object": "response.input_tokens", "input_tokens": counted.input_tokens}


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Select and invoke exactly one explicit Responses execution owner."""
    data = await read_request_json(request)
    state = request.app.state
    try:
        selection = select_responses_execution(
            state,
            requested_model=data.get("model"),
        )
        if gateway_storage_enabled(request):
            if selection.mode is not ResponsesExecutionMode.NATIVE_GIGACHAT:
                raise ClientCompatibilityError(
                    "Gateway snapshots currently support GigaChat execution only.",
                    param="model",
                    code="unsupported_provider",
                )
            if selection.route is not None:
                request.state.response_provider_profile = selection.route.profile_id
        data, snapshot_turn = await prepare_snapshot(request, data)
        if selection.mode is ResponsesExecutionMode.NATIVE_GIGACHAT:
            executor = NativeGigaChatResponsesExecutor()
        else:
            executor = NormalizedBridgeResponsesExecutor()
        result = await executor.execute(request, data)
        return await finish_snapshot(request, snapshot_turn, result)
    except (BridgeMatrixAdmissionError, ProviderAliasError) as exc:
        if isinstance(exc, BridgeMatrixAdmissionError):
            error = exc.as_public_error()
            compatibility_error = ClientCompatibilityError(
                error["message"],
                param=error["param"],
                code=error["code"],
                error_type=error["type"],
            )
        else:
            compatibility_error = ClientCompatibilityError(
                exc.message,
                param="model",
                code=exc.code,
            )
        return client_compatibility_response(compatibility_error)
    except ClientCompatibilityError as exc:
        return client_compatibility_response(exc)


@router.get("/responses/{response_id}")
@exceptions_handler
async def retrieve_response(response_id: str, request: Request):
    """Retrieve an immutable gateway snapshot."""
    require_gateway_storage(request)
    return (await owned_resource(request, "response", response_id)).metadata["response"]


@router.get("/responses/{response_id}/input_items")
@exceptions_handler
async def response_input_items(response_id: str, request: Request):
    """List the input context used for one gateway snapshot."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "response", response_id)
    return paged_items(request, resource.metadata["input_items"])


@router.delete("/responses/{response_id}")
@exceptions_handler
async def delete_response(response_id: str, request: Request):
    """Delete one snapshot without deleting its ancestors or conversations."""
    from gpt2giga.app_state import get_resource_store

    require_gateway_storage(request)
    resource = await owned_resource(request, "response", response_id)
    await get_resource_store(request).delete(
        response_resource_owner(request, resource), "response", response_id
    )
    return {"id": response_id, "object": "response.deleted", "deleted": True}
