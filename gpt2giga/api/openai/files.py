"""File endpoints."""

from typing import Optional

from fastapi import APIRouter, Query, Request, Response

from gpt2giga.api.openai.openapi import files_openapi_extra
from gpt2giga.api.tags import PROVIDER_OPENAI, TAG_FILES, provider_tag
from gpt2giga.app.dependencies import get_response_processor_from_state
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.form_body import read_request_multipart
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.files import get_files_service_from_state
from gpt2giga.features.files.store import get_file_store
from gpt2giga.providers.openai import openai_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=[provider_tag(TAG_FILES, PROVIDER_OPENAI)])


@router.post("/files", openapi_extra=files_openapi_extra())
@exceptions_handler
async def create_file(request: Request):
    """Upload a file."""
    multipart = await read_request_multipart(request)
    purpose, upload = openai_provider_adapters.files.extract_create_file_args(multipart)

    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    return await files_service.create_file(
        purpose=purpose,
        upload=upload,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )


@router.get("/files")
@exceptions_handler
async def list_files(
    request: Request,
    after: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
    order: Optional[str] = Query(default=None),
    purpose: Optional[str] = Query(default=None),
):
    """List uploaded files."""
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    return await files_service.list_files(
        giga_client=giga_client,
        file_store=get_file_store(request),
        after=after,
        limit=limit,
        order=order,
        purpose=purpose,
    )


@router.get("/files/{file_id}")
@exceptions_handler
async def retrieve_file(file_id: str, request: Request):
    """Return file metadata."""
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    return await files_service.retrieve_file(
        file_id,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )


@router.delete("/files/{file_id}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Delete a file."""
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    return await files_service.delete_file(
        file_id,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )


@router.get("/files/{file_id}/content")
@exceptions_handler
async def get_file_content(file_id: str, request: Request):
    """Return the raw file content."""
    giga_client = get_gigachat_client(request)
    app_state = request.app.state
    files_service = get_files_service_from_state(app_state)
    content = await files_service.get_file_content(
        file_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
        response_processor=get_response_processor_from_state(app_state),
    )
    return Response(content=content, media_type="application/octet-stream")
