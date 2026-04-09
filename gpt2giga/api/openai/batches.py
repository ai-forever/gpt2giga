"""Batch endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from gpt2giga.app_state import get_batch_store, get_file_store
from gpt2giga.api.openai.helpers import _paginate_items
from gpt2giga.api.openai.openapi import batches_openapi_extra
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.protocol.batches import (
    build_openai_batch_object,
    get_batch_target,
    transform_batch_input_file,
)
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.post("/batches", openapi_extra=batches_openapi_extra())
@exceptions_handler
async def create_batch(request: Request):
    """Create a batch job."""
    data = await read_request_json(request)
    completion_window = data.get("completion_window", "24h")
    if completion_window is None:
        completion_window = "24h"
    input_file_id = data.get("input_file_id")
    if completion_window != "24h":
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": 'Only `completion_window="24h"` is supported.',
                    "type": "invalid_request_error",
                    "param": "completion_window",
                    "code": None,
                }
            },
        )
    if not input_file_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "`input_file_id` is required.",
                    "type": "invalid_request_error",
                    "param": "input_file_id",
                    "code": None,
                }
            },
        )

    target = get_batch_target(data.get("endpoint", ""))
    giga_client = get_gigachat_client(request)
    file_content = await giga_client.aget_file_content(file_id=input_file_id)

    import base64

    transformed_content = await transform_batch_input_file(
        base64.b64decode(file_content.content),
        target=target,
        request_transformer=request.app.state.request_transformer,
        giga_client=giga_client,
        embeddings_model=request.app.state.config.proxy_settings.embeddings,
    )
    batch = await giga_client.acreate_batch(
        transformed_content,
        method=target.method,
    )

    metadata = {
        "endpoint": target.endpoint,
        "input_file_id": input_file_id,
        "completion_window": completion_window,
        "metadata": data.get("metadata"),
        "output_file_id": batch.output_file_id,
    }
    get_batch_store(request)[batch.id_] = metadata
    if batch.output_file_id:
        get_file_store(request)[batch.output_file_id] = {"purpose": "batch_output"}
    return build_openai_batch_object(batch, metadata)


@router.get("/batches")
@exceptions_handler
async def list_batches(
    request: Request,
    after: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
):
    """List batch jobs."""
    giga_client = get_gigachat_client(request)
    batch_store = get_batch_store(request)
    file_store = get_file_store(request)
    batches = await giga_client.aget_batches()
    data = []
    for batch in batches.batches:
        metadata = batch_store.get(batch.id_) or {
            "endpoint": "/v1/chat/completions",
            "input_file_id": "",
            "completion_window": "24h",
        }
        metadata["output_file_id"] = batch.output_file_id
        batch_store[batch.id_] = metadata
        if batch.output_file_id:
            file_store[batch.output_file_id] = {"purpose": "batch_output"}
        data.append(build_openai_batch_object(batch, metadata))
    paged, has_more = _paginate_items(data, after, limit)
    return {"data": paged, "has_more": has_more, "object": "list"}


@router.get("/batches/{batch_id}")
@exceptions_handler
async def retrieve_batch(batch_id: str, request: Request):
    """Return batch metadata."""
    giga_client = get_gigachat_client(request)
    batch_store = get_batch_store(request)
    file_store = get_file_store(request)
    batches = await giga_client.aget_batches(batch_id=batch_id)
    if not batches.batches:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"Batch `{batch_id}` not found.",
                    "type": "not_found_error",
                    "param": "batch_id",
                    "code": None,
                }
            },
        )
    batch = batches.batches[0]
    metadata = batch_store.get(batch_id) or {
        "endpoint": "/v1/chat/completions",
        "input_file_id": "",
        "completion_window": "24h",
    }
    metadata["output_file_id"] = batch.output_file_id
    batch_store[batch_id] = metadata
    if batch.output_file_id:
        file_store[batch.output_file_id] = {"purpose": "batch_output"}
    return build_openai_batch_object(batch, metadata)
