"""Gemini Files API compatible routes."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from gpt2giga.api.gemini.batches import build_gemini_batch_output_file
from gpt2giga.api.gemini.request import (
    GeminiAPIError,
    normalize_file_name,
    read_gemini_request_json,
)
from gpt2giga.api.gemini.response import gemini_exceptions_handler
from gpt2giga.api.tags import TAG_FILES
from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.core.http.form_body import read_request_multipart
from gpt2giga.features.batches.store import (
    find_batch_metadata_by_output_file_id,
    get_batch_store,
)
from gpt2giga.features.files import get_files_service_from_state
from gpt2giga.features.files.store import get_file_store
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=[TAG_FILES])
upload_router = APIRouter(tags=[TAG_FILES])


def _timestamp_to_rfc3339(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _guess_mime_type(filename: str | None) -> str:
    guessed, _ = mimetypes.guess_type(filename or "")
    if guessed:
        return guessed
    if filename and filename.lower().endswith(".jsonl"):
        return "application/json"
    return "application/octet-stream"


def _build_file_resource(
    file_obj: dict[str, Any],
    *,
    request: Request,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    file_id = file_obj.get("id", "")
    filename = metadata.get("filename") or file_obj.get("filename") or file_id
    mime_type = metadata.get("mime_type") or _guess_mime_type(filename)
    status = str(metadata.get("status") or file_obj.get("status") or "processed")
    state = {
        "uploaded": "PROCESSING",
        "processing": "PROCESSING",
        "processed": "ACTIVE",
        "failed": "FAILED",
    }.get(status, "ACTIVE")
    payload: dict[str, Any] = {
        "name": f"files/{file_id}",
        "displayName": metadata.get("display_name") or filename,
        "mimeType": mime_type,
        "sizeBytes": str(file_obj.get("bytes", 0)),
        "createTime": _timestamp_to_rfc3339(file_obj.get("created_at")),
        "updateTime": _timestamp_to_rfc3339(file_obj.get("created_at")),
        "sha256Hash": metadata.get("sha256_hash"),
        "uri": str(request.url_for("gemini_get_file", file_id=file_id)),
        "downloadUri": str(request.url_for("gemini_download_file", file_id=file_id)),
        "state": state,
        "source": metadata.get("source", "UPLOADED"),
    }
    expires_at = metadata.get("expires_at") or file_obj.get("expires_at")
    if isinstance(expires_at, int):
        payload["expirationTime"] = _timestamp_to_rfc3339(expires_at)
    status_details = metadata.get("status_details") or file_obj.get("status_details")
    if status_details:
        payload["error"] = {
            "code": 13 if state == "FAILED" else 0,
            "message": (
                status_details
                if isinstance(status_details, str)
                else json.dumps(status_details, ensure_ascii=False)
            ),
        }
    return {key: value for key, value in payload.items() if value is not None}


def _infer_internal_purpose(filename: str, mime_type: str) -> str:
    if filename.lower().endswith(".jsonl") or mime_type == "application/json":
        return "batch"
    return "user_data"


def _store_uploaded_file_metadata(
    file_store: dict[str, dict[str, Any]],
    *,
    file_id: str,
    filename: str,
    content: bytes,
    content_type: str,
    display_name: str | None = None,
) -> None:
    entry = file_store.setdefault(file_id, {})
    entry.update(
        {
            "filename": filename,
            "display_name": display_name or filename,
            "mime_type": content_type,
            "sha256_hash": base64.b64encode(hashlib.sha256(content).digest()).decode(
                "ascii"
            ),
            "source": "UPLOADED",
        }
    )


def _get_upload_store(state: Any) -> dict[str, dict[str, Any]]:
    return get_runtime_stores(state).gemini_uploads


async def _create_gemini_file(
    request: Request,
    *,
    upload: dict[str, Any],
    display_name: str | None = None,
) -> dict[str, Any]:
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    file_store = get_file_store(request)
    created = await files_service.create_file(
        purpose=_infer_internal_purpose(upload["filename"], upload["content_type"]),
        upload=upload,
        giga_client=giga_client,
        file_store=file_store,
    )
    _store_uploaded_file_metadata(
        file_store,
        file_id=created["id"],
        filename=upload["filename"],
        content=upload["content"],
        content_type=upload["content_type"],
        display_name=display_name,
    )
    return created


async def _create_file_from_multipart(request: Request) -> JSONResponse:
    multipart = await read_request_multipart(request)
    upload = (multipart.get("files") or {}).get("file")
    if upload is None:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="Multipart upload requires a `file` field.",
        )
    form = multipart.get("form") or {}
    display_name = form.get("displayName") or form.get("display_name")
    created = await _create_gemini_file(
        request,
        upload=upload,
        display_name=display_name,
    )
    return JSONResponse(
        {
            "file": _build_file_resource(
                created,
                request=request,
                metadata=get_file_store(request).get(created["id"]),
            )
        },
        headers={"X-Goog-Upload-Status": "final"},
    )


@router.post("/files")
@gemini_exceptions_handler
async def create_file(request: Request):
    """Create a Gemini file using multipart upload or metadata-only JSON."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        return await _create_file_from_multipart(request)

    await read_gemini_request_json(request)
    raise GeminiAPIError(
        status_code=501,
        status="UNIMPLEMENTED",
        message=(
            "Metadata-only Gemini file creation is not supported by this proxy. "
            "Use multipart `/v1beta/files` or resumable `/upload/v1beta/files`."
        ),
    )


@router.get("/files")
@gemini_exceptions_handler
async def list_files(
    request: Request,
    pageSize: int = Query(default=50, ge=1, le=1000),
    pageToken: str | None = Query(default=None),
):
    """List Gemini files."""
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    result = await files_service.list_files(
        giga_client=giga_client,
        file_store=get_file_store(request),
        after=normalize_file_name(pageToken) if pageToken else None,
        limit=pageSize,
    )
    files = [
        _build_file_resource(
            file_obj,
            request=request,
            metadata=get_file_store(request).get(file_obj["id"]),
        )
        for file_obj in result["data"]
    ]
    payload: dict[str, Any] = {"files": files}
    if result["has_more"] and files:
        payload["nextPageToken"] = files[-1]["name"]
    return payload


@router.get("/files/{file_id}", name="gemini_get_file")
@gemini_exceptions_handler
async def get_file(file_id: str, request: Request):
    """Get Gemini file metadata."""
    if file_id.endswith(":download"):
        return await download_file(file_id[: -len(":download")], request)
    normalized_file_id = normalize_file_name(file_id)
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    file_obj = await files_service.retrieve_file(
        normalized_file_id,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )
    return _build_file_resource(
        file_obj,
        request=request,
        metadata=get_file_store(request).get(normalized_file_id),
    )


@router.get("/files/{file_id}:download", name="gemini_download_file")
@gemini_exceptions_handler
async def download_file(file_id: str, request: Request):
    """Download raw file bytes from a Gemini file resource."""
    normalized_file_id = normalize_file_name(file_id)
    giga_client = get_gigachat_client(request)
    batch_metadata = find_batch_metadata_by_output_file_id(
        get_batch_store(request),
        normalized_file_id,
    )
    if batch_metadata and batch_metadata.get("api_format") == "gemini_generate_content":
        file_response = await giga_client.aget_file_content(file_id=normalized_file_id)
        content = build_gemini_batch_output_file(
            file_response.content,
            batch_metadata=batch_metadata,
        )
        return Response(content=content, media_type="application/json")

    files_service = get_files_service_from_state(request.app.state)
    content = await files_service.get_file_content(
        normalized_file_id,
        giga_client=giga_client,
        batch_store=None,
    )
    file_metadata = get_file_store(request).get(normalized_file_id) or {}
    return Response(
        content=content,
        media_type=file_metadata.get("mime_type", "application/octet-stream"),
    )


@router.delete("/files/{file_id}")
@gemini_exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Delete a Gemini file."""
    normalized_file_id = normalize_file_name(file_id)
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(request.app.state)
    await files_service.delete_file(
        normalized_file_id,
        giga_client=giga_client,
        file_store=get_file_store(request),
    )
    return {}


@upload_router.post("/files")
@gemini_exceptions_handler
async def upload_file(request: Request):
    """Start or complete a Gemini resumable upload session."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        return await _create_file_from_multipart(request)

    protocol = request.headers.get("X-Goog-Upload-Protocol", "").lower()
    command = request.headers.get("X-Goog-Upload-Command", "").lower()
    upload_store = _get_upload_store(request.app.state)

    if protocol == "resumable" and "start" in command:
        body = await request.body()
        payload = {}
        if body.strip():
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise GeminiAPIError(
                    status_code=400,
                    status="INVALID_ARGUMENT",
                    message=f"Invalid JSON body: {exc.msg}",
                ) from exc
        file_metadata = payload.get("file") if isinstance(payload, dict) else {}
        if file_metadata is None:
            file_metadata = {}
        if not isinstance(file_metadata, dict):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="`file` must be an object when provided.",
            )
        upload_id = uuid.uuid4().hex
        upload_store[upload_id] = {
            "file": file_metadata,
            "content_type": request.headers.get(
                "X-Goog-Upload-Header-Content-Type",
                "application/octet-stream",
            ),
        }
        return Response(
            status_code=200,
            headers={
                "X-Goog-Upload-Status": "active",
                "X-Goog-Upload-URL": str(
                    request.url_for("gemini_finalize_upload", upload_id=upload_id)
                ),
            },
        )

    raise GeminiAPIError(
        status_code=400,
        status="INVALID_ARGUMENT",
        message="Unsupported Gemini upload request. Expected multipart or resumable start.",
    )


@upload_router.post("/files/{upload_id}", name="gemini_finalize_upload")
@gemini_exceptions_handler
async def finalize_upload(upload_id: str, request: Request):
    """Finalize a Gemini resumable upload."""
    upload_store = _get_upload_store(request.app.state)
    session = upload_store.pop(upload_id, None)
    if session is None:
        raise GeminiAPIError(
            status_code=404,
            status="NOT_FOUND",
            message="Upload session not found.",
        )

    command = request.headers.get("X-Goog-Upload-Command", "").lower()
    if "upload" not in command or "finalize" not in command:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=(
                "Final upload request must set `X-Goog-Upload-Command: upload, finalize`."
            ),
        )

    body = await request.body()
    file_metadata = session.get("file") or {}
    display_name = file_metadata.get("displayName") or file_metadata.get("display_name")
    filename = display_name or f"upload-{upload_id}"
    created = await _create_gemini_file(
        request,
        upload={
            "filename": filename,
            "content": body,
            "content_type": session.get("content_type", "application/octet-stream"),
        },
        display_name=display_name,
    )
    return JSONResponse(
        {
            "file": _build_file_resource(
                created,
                request=request,
                metadata=get_file_store(request).get(created["id"]),
            )
        },
        headers={"X-Goog-Upload-Status": "final"},
    )
