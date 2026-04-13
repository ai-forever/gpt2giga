"""Batch endpoints."""

from typing import Optional

from fastapi import APIRouter, Query, Request

from gpt2giga.api.openai.openapi import batches_openapi_extra
from gpt2giga.api.tags import PROVIDER_OPENAI, TAG_BATCHES, provider_tag
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.features.batches import get_batches_service_from_state
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.files.store import get_file_store
from gpt2giga.providers.openai import openai_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=[provider_tag(TAG_BATCHES, PROVIDER_OPENAI)])


@router.post("/batches", openapi_extra=batches_openapi_extra())
@exceptions_handler
async def create_batch(request: Request):
    """Create a batch job."""
    data = openai_provider_adapters.batches.build_create_payload(
        await read_request_json(request)
    )
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    return await batches_service.create_batch(
        data,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )


@router.get("/batches")
@exceptions_handler
async def list_batches(
    request: Request,
    after: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
):
    """List batch jobs."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    return await batches_service.list_batches(
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
        after=after,
        limit=limit,
    )


@router.get("/batches/{batch_id}")
@exceptions_handler
async def retrieve_batch(batch_id: str, request: Request):
    """Return batch metadata."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    return await batches_service.retrieve_batch(
        batch_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
