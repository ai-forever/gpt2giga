"""File endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from gpt2giga.app_state import get_file_store, get_gigachat_client
from gpt2giga.api.openai.helpers import (
    _load_batch_output_content,
    _paginate_items,
    _serialize_file_object,
)
from gpt2giga.api.openai.openapi import files_openapi_extra
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_form import read_request_multipart
from gpt2giga.protocol.batches import map_openai_file_purpose

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

    giga_client = get_gigachat_client(request)
    uploaded = await giga_client.aupload_file(
        (upload["filename"], upload["content"], upload["content_type"]),
        purpose=map_openai_file_purpose(purpose),
    )

    file_store = get_file_store(request)
    file_store[uploaded.id_] = {
        "purpose": purpose,
        "filename": upload["filename"],
        "status": "processed",
    }
    return _serialize_file_object(uploaded, file_store[uploaded.id_])


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
    files = await giga_client.aget_files()
    file_store = get_file_store(request)
    data = [
        _serialize_file_object(file_obj, file_store.get(file_obj.id_))
        for file_obj in files.data
    ]
    if purpose:
        data = [item for item in data if item["purpose"] == purpose]
    if order == "desc":
        data = sorted(data, key=lambda item: item.get("created_at") or 0, reverse=True)
    elif order == "asc":
        data = sorted(data, key=lambda item: item.get("created_at") or 0)
    paged, has_more = _paginate_items(data, after, limit)
    return {"data": paged, "has_more": has_more, "object": "list"}


@router.get("/files/{file_id}")
@exceptions_handler
async def retrieve_file(file_id: str, request: Request):
    """Return file metadata."""
    giga_client = get_gigachat_client(request)
    file_store = get_file_store(request)
    file_obj = await giga_client.aget_file(file=file_id)
    return _serialize_file_object(file_obj, file_store.get(file_id))


@router.delete("/files/{file_id}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Delete a file."""
    giga_client = get_gigachat_client(request)
    deleted = await giga_client.adelete_file(file=file_id)
    get_file_store(request).pop(file_id, None)
    return {
        "id": deleted.id_,
        "deleted": deleted.deleted,
        "object": "file",
    }


@router.get("/files/{file_id}/content")
@exceptions_handler
async def get_file_content(file_id: str, request: Request):
    """Return the raw file content."""
    content = await _load_batch_output_content(request, file_id)
    return Response(content=content, media_type="application/octet-stream")
