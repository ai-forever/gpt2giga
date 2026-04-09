"""File endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from gpt2giga.api.openai.openapi import files_openapi_extra
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_form import read_request_multipart
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.files import get_files_service_from_state
from gpt2giga.features.files.store import get_file_store
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.post("/files", openapi_extra=files_openapi_extra())
@exceptions_handler
async def create_file(request: Request):
    """Upload a file."""
    multipart = await read_request_multipart(request)
    purpose = multipart["form"].get("purpose")
    upload = multipart["files"].get("file")
    if not purpose or upload is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Multipart upload requires both `file` and `purpose`.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_multipart",
                }
            },
        )

    state = request.app.state
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(state)
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
    state = request.app.state
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(state)
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
    state = request.app.state
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(state)
    return await files_service.retrieve_file(
        file_id,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )


@router.delete("/files/{file_id}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Delete a file."""
    state = request.app.state
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(state)
    return await files_service.delete_file(
        file_id,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )


@router.get("/files/{file_id}/content")
@exceptions_handler
async def get_file_content(file_id: str, request: Request):
    """Return the raw file content."""
    state = request.app.state
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(state)
    content = await files_service.get_file_content(
        file_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        response_processor=getattr(state, "response_processor", None),
    )
    return Response(content=content, media_type="application/octet-stream")
