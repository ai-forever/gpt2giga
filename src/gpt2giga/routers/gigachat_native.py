"""Explicit GigaChat utilities, sharing normal request authentication and SDK options."""

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.native import utility_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_GIGACHAT_NATIVE
from gpt2giga.providers.gigachat.native import (
    native_operation_model,
    require_native_gigachat,
)

router = APIRouter(prefix="/bridge/gigachat", tags=[OPENAPI_TAG_GIGACHAT_NATIVE])


@router.post("/tokens/count", openapi_extra=utility_openapi_extra("tokens/count"))
@exceptions_handler
async def count_tokens(request: Request):
    """Estimate tokens for text using GigaChat's tokenizer service."""
    data = await read_request_json(request)
    text = data.get("input")
    if not isinstance(text, str) and not (
        isinstance(text, list) and text and all(isinstance(item, str) for item in text)
    ):
        raise ClientCompatibilityError(
            "input must be text or a nonempty list of text.", param="input"
        )
    model = native_operation_model(request, data.get("model"))
    options = extract_gigachat_request_options(request, data)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        result = await client.atokens_count(text, model=model)
    return [
        item.model_dump(by_alias=True, exclude_none=True, exclude={"x_headers"})
        for item in result
    ]


@router.post(
    "/functions/validate", openapi_extra=utility_openapi_extra("functions/validate")
)
@exceptions_handler
async def validate_function(request: Request):
    """Validate a function schema; this does not execute the function."""
    require_native_gigachat(request)
    data = await read_request_json(request)
    options = extract_gigachat_request_options(request, data)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        result = await client.afunctions_validate(data)
    return result.model_dump(by_alias=True, exclude_none=True, exclude={"x_headers"})


@router.get("/balance")
@exceptions_handler
async def balance(request: Request):
    """Return the account balance where the upstream account supports it."""
    require_native_gigachat(request)
    options = extract_gigachat_request_options(request)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        result = await client.aget_balance()
    return result.model_dump(by_alias=True, exclude_none=True, exclude={"x_headers"})


@router.post("/ai/check", openapi_extra=utility_openapi_extra("ai/check"))
@exceptions_handler
async def check_ai(request: Request):
    """Detect likely AI-generated Russian text; this is not content moderation."""
    data = await read_request_json(request)
    text = data.get("input")
    if not isinstance(text, str) or not text.strip():
        raise ClientCompatibilityError(
            "input must be a nonempty string.", param="input"
        )
    model = native_operation_model(request, data.get("model"))
    options = extract_gigachat_request_options(request, data)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        result = await client.acheck_ai(text, model=model)
    return result.model_dump(by_alias=True, exclude_none=True, exclude={"x_headers"})
