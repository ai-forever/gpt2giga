"""Shared Files dispatch with durable metadata and protocol-specific projection."""

from fastapi import APIRouter, HTTPException, Request, Response

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.files import (
    file_content,
    file_metadata,
    list_file_metadata,
    remove_file,
    upload_file_resource,
)
from gpt2giga.common.request_form import read_request_multipart
from gpt2giga.openapi_specs.openai import files_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_FILES
from gpt2giga.protocol.anthropic.files import anthropic_file, is_anthropic_files
from gpt2giga.routers.openai.helpers import _paginate_items

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_FILES])
_OPENAI_FIELDS = (
    "id",
    "object",
    "bytes",
    "created_at",
    "filename",
    "purpose",
    "status",
    "expires_at",
    "status_details",
)


def _project(request: Request, metadata: dict) -> dict:
    if is_anthropic_files(request):
        return anthropic_file(metadata)
    return {key: metadata.get(key) for key in _OPENAI_FIELDS}


def _positive_query(request: Request, key: str, default: int, maximum: int) -> int:
    try:
        value = int(request.query_params.get(key, default))
        if not 1 <= value <= maximum:
            raise ValueError
        return value
    except ValueError as exc:
        raise HTTPException(400, detail=f"Invalid {key}.") from exc


@router.post("/files", openapi_extra=files_openapi_extra())
@exceptions_handler
async def create_file(request: Request):
    """Upload an OpenAI or Anthropic file under the current resource owner."""
    multipart = await read_request_multipart(request)
    anthropic = is_anthropic_files(request)
    purpose = "user_data" if anthropic else multipart["form"].get("purpose")
    upload = multipart["files"].get("file")
    if not purpose or upload is None:
        raise HTTPException(
            400, detail="Multipart upload requires file and, for OpenAI, purpose."
        )
    if any(
        name in multipart["form"]
        for name in ("expires_at", "expires_after", "expires_in_seconds", "scope")
    ):
        raise HTTPException(
            400, detail="Custom scope and expiration are not supported."
        )
    result = await upload_file_resource(
        request,
        content=upload["content"],
        filename=upload["filename"],
        mime_type=upload["content_type"],
        purpose=purpose,
        protocol="anthropic" if anthropic else "openai",
    )
    return _project(request, result)


@router.get("/files")
@exceptions_handler
async def list_files(request: Request):
    """List files with the selected protocol's pagination contract."""
    data = await list_file_metadata(request)
    purpose = request.query_params.get("purpose")
    if purpose:
        data = [item for item in data if item["purpose"] == purpose]
    order = request.query_params.get("order", "desc")
    if order not in {"asc", "desc"}:
        raise HTTPException(400, detail="Invalid order.")
    data.sort(
        key=lambda item: (item.get("created_at") or 0, item["id"]),
        reverse=order == "desc",
    )
    if is_anthropic_files(request):
        size = _positive_query(request, "limit", 100, 1000)
        page = _positive_query(request, "page", 1, 2**31 - 1)
        offset = (page - 1) * size
        selected = data[offset : offset + size]
        result = {
            "data": [_project(request, item) for item in selected],
            "has_more": offset + size < len(data),
        }
        if request.headers.get("anthropic-version") == "2026-10-21":
            result["next_page"] = str(page + 1) if result["has_more"] else None
        else:
            selected, more = _paginate_items(
                data, request.query_params.get("after_id"), size
            )
            result = {
                "data": [_project(request, item) for item in selected],
                "has_more": more,
                "first_id": selected[0]["id"] if selected else None,
                "last_id": selected[-1]["id"] if selected else None,
            }
        return result
    limit = _positive_query(request, "limit", 10000, 10000)
    selected, more = _paginate_items(data, request.query_params.get("after"), limit)
    return {
        "data": [_project(request, item) for item in selected],
        "has_more": more,
        "object": "list",
    }


@router.get("/files/{file_id}")
@exceptions_handler
async def retrieve_file(file_id: str, request: Request):
    """Return preserved public metadata."""
    return _project(request, await file_metadata(request, file_id))


@router.delete("/files/{file_id}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Delete a file and its metadata."""
    await remove_file(request, file_id)
    if is_anthropic_files(request):
        return {"id": file_id, "type": "file_deleted"}
    return {"id": file_id, "deleted": True, "object": "file"}


@router.get("/files/{file_id}/content")
@exceptions_handler
async def get_file_content(file_id: str, request: Request):
    """Download raw file bytes when allowed by the selected protocol."""
    if is_anthropic_files(request):
        metadata = await file_metadata(request, file_id)
        if not metadata.get("downloadable"):
            raise HTTPException(
                400,
                detail="This uploaded file is not downloadable through Anthropic Files.",
            )
    content = await file_content(request, file_id)
    return Response(content=content, media_type="application/octet-stream")
