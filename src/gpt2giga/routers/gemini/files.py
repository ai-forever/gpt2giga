"""Gemini Files projection and durable resumable upload sessions."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from gpt2giga.app_state import get_resource_owner, get_resource_store
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.files import (
    file_content,
    file_metadata,
    file_not_found,
    remove_file,
    upload_file_resource,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import update_request_context
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_FILES
from gpt2giga.openapi_specs.gemini import gemini_files_openapi_extra
from gpt2giga.storage.resources import ResourceLimitError, ResourceStoreError

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_FILES])
upload_router = APIRouter(tags=[OPENAPI_TAG_GEMINI_FILES])


def _context() -> None:
    update_request_context(metadata={"protocol": "gemini", "api_format": "files"})


def _invalid(message: str, status: int = 400) -> HTTPException:
    return HTTPException(status, detail=message)


def _file_id(value: str) -> str:
    value = value.removeprefix("files/")
    if not value or "/" in value or ":" in value:
        raise file_not_found()
    return value


def _rfc3339(value: Any) -> str:
    return (
        datetime.fromtimestamp(float(value or 0), timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def gemini_file(metadata: dict, request: Request) -> dict[str, Any]:
    """Project only known file facts; uploaded files are not downloadable."""
    file_id = metadata["id"]
    result = {
        "name": f"files/{file_id}",
        "displayName": metadata.get("display_name")
        or metadata.get("filename", file_id),
        "mimeType": metadata.get("mime_type", "application/octet-stream"),
        "sizeBytes": str(metadata.get("bytes", 0)),
        "createTime": _rfc3339(metadata.get("created_at")),
        "updateTime": _rfc3339(metadata.get("created_at")),
        "uri": f"files/{file_id}",
        "state": "ACTIVE",
        "source": "GENERATED" if metadata.get("downloadable") else "UPLOADED",
    }
    if metadata.get("downloadable"):
        prefix = request.url.path.split("/files", 1)[0]
        result["downloadUri"] = (
            f"{str(request.base_url).rstrip('/')}{prefix}/files/{file_id}:download?alt=media"
        )
    return result


@upload_router.post("/files", openapi_extra=gemini_files_openapi_extra())
@exceptions_handler
async def resumable_upload(request: Request):
    """Start, query, append, or finalize one bounded upload under its owner."""
    _context()
    command = {
        part.strip()
        for part in request.headers.get("x-goog-upload-command", "").split(",")
    }
    if command == {"start"}:
        return await _start_upload(request)
    session_id = request.query_params.get("upload_id")
    if not session_id:
        raise _invalid("A resumable upload session is required.")
    store, owner = get_resource_store(request), get_resource_owner(request)
    session = await store.get(owner, "upload", session_id)
    if session is None:
        raise file_not_found()
    if command == {"query"}:
        return Response(
            headers={
                "X-Goog-Upload-Status": session.metadata["status"],
                "X-Goog-Upload-Size-Received": str(session.blob_size),
            }
        )
    if command == {"cancel"}:
        await store.delete(owner, "upload", session_id)
        return Response(headers={"X-Goog-Upload-Status": "cancelled"})
    if (
        not command
        or command - {"upload", "finalize"}
        or session.metadata.get("status") != "active"
    ):
        raise _invalid(
            "The upload session is not active or the command is unsupported.", 409
        )
    try:
        offset = int(request.headers.get("x-goog-upload-offset", "-1"))
    except ValueError as exc:
        raise _invalid("Upload offset must be an integer.") from exc
    content = await request.body()
    declared = session.metadata["size_bytes"]
    if offset < 0 or offset != session.blob_size:
        raise _invalid("Upload offset does not match received bytes.", 409)
    if len(content) + offset > declared:
        raise _invalid("Upload exceeds the declared file length.")
    if "upload" not in command and content:
        raise _invalid("Bytes require the upload command.")
    if "finalize" in command and offset + len(content) != declared:
        raise _invalid("Final upload length does not match the declared file length.")
    try:
        if content:
            await store.append_blob(owner, "upload", session_id, content, offset=offset)
        if "finalize" not in command:
            return Response(
                headers={
                    "X-Goog-Upload-Status": "active",
                    "X-Goog-Upload-Size-Received": str(offset + len(content)),
                }
            )

        def claim(metadata):
            if metadata.get("status") != "active":
                raise _invalid("Upload finalization has already started.", 409)
            if metadata.get("upload_offset", 0) != declared:
                raise _invalid("Upload content length is incomplete.")
            return {**metadata, "status": "finalizing"}

        claimed = await store.update(owner, "upload", session_id, claim)
        if claimed is None:
            raise file_not_found()
        try:
            content = await store.read_blob(owner, "upload", session_id)
            if content is None or len(content) != declared:
                raise _invalid("Upload content length is incomplete.")
            metadata = await upload_file_resource(
                request,
                content=content,
                filename=session.metadata["filename"],
                mime_type=session.metadata["mime_type"],
                protocol="gemini",
            )
            metadata["display_name"] = session.metadata["display_name"]
            await store.update(
                owner,
                "file",
                metadata["id"],
                {"display_name": metadata["display_name"]},
            )
            return JSONResponse(
                {"file": gemini_file(metadata, request)},
                headers={"X-Goog-Upload-Status": "final"},
            )
        finally:
            await store.delete(owner, "upload", session_id)
    except ResourceLimitError as exc:
        raise _invalid(str(exc), 413) from exc
    except ResourceStoreError as exc:
        raise _invalid("Upload state could not be updated.", 409) from exc


async def _start_upload(request: Request) -> Response:
    if request.headers.get("x-goog-upload-protocol") != "resumable":
        raise _invalid("Only the resumable upload protocol is supported.")
    data = await read_request_json(request)
    metadata = data.get("file")
    if not isinstance(metadata, dict):
        raise _invalid("Upload metadata must contain a file object.")
    try:
        length = int(request.headers.get("x-goog-upload-header-content-length", "-1"))
    except ValueError as exc:
        raise _invalid("Declared file length must be an integer.") from exc
    store = get_resource_store(request)
    if length <= 0:
        raise _invalid("Declared file length must be positive.")
    if length > store.max_blob_bytes:
        raise _invalid("File exceeds the configured upload limit.", 413)
    mime_type = (
        request.headers.get("x-goog-upload-header-content-type")
        or metadata.get("mimeType")
        or metadata.get("mime_type")
    )
    if not isinstance(mime_type, str) or "/" not in mime_type:
        raise _invalid("A file MIME type is required.")
    display_name = (
        metadata.get("displayName") or metadata.get("display_name") or "upload"
    )
    filename = request.headers.get("x-goog-upload-file-name") or display_name
    if not isinstance(filename, str) or not filename:
        raise _invalid("File displayName must be a string.")
    session_id = uuid.uuid4().hex
    await store.put(
        get_resource_owner(request),
        "upload",
        session_id,
        {
            "status": "active",
            "upload_offset": 0,
            "size_bytes": length,
            "mime_type": mime_type,
            "filename": filename,
            "display_name": display_name,
        },
        blob=b"",
        expires_at=time.time() + 86400,
    )
    url = str(request.url.replace(query=f"upload_id={session_id}"))
    return JSONResponse(
        {}, headers={"X-Goog-Upload-URL": url, "X-Goog-Upload-Status": "active"}
    )


@router.post("/files")
@exceptions_handler
async def create_file(request: Request):
    """Reject metadata-only publication; bytes use the resumable upload route."""
    _context()
    raise _invalid("Use /upload/v1beta/files with the resumable upload protocol.")


@router.get("/files")
@exceptions_handler
async def list_files(request: Request):
    """List owned durable Files with stable page tokens."""
    _context()
    records = await get_resource_store(request).list(
        get_resource_owner(request), "file"
    )
    try:
        limit = int(request.query_params.get("pageSize", "100"))
    except ValueError as exc:
        raise _invalid("pageSize must be an integer.") from exc
    if not 1 <= limit <= 100:
        raise _invalid("pageSize must be between 1 and 100.")
    token = request.query_params.get("pageToken")
    ids = [record.public_id for record in records]
    if token is not None and token not in ids:
        raise _invalid("Invalid pageToken.")
    start = ids.index(token) + 1 if token else 0
    page = records[start : start + limit]
    result = {"files": [gemini_file(record.metadata, request) for record in page]}
    if start + limit < len(records):
        result["nextPageToken"] = page[-1].public_id
    return result


@router.get("/files/{file_id}:download")
@exceptions_handler
async def download_file(file_id: str, request: Request):
    """Download only generated/batch artifacts with a real bytes resource."""
    _context()
    file_id = _file_id(file_id)
    metadata = await file_metadata(request, file_id)
    if not metadata.get("downloadable"):
        raise _invalid(
            "User-uploaded files cannot be downloaded through Gemini Files.", 403
        )
    return Response(
        await file_content(request, file_id),
        media_type=metadata.get("mime_type", "application/octet-stream"),
    )


@router.get("/files/{file_id}")
@exceptions_handler
async def get_file(file_id: str, request: Request):
    """Return facts for an owned file, including retained MIME and purpose."""
    _context()
    return gemini_file(await file_metadata(request, _file_id(file_id)), request)


@router.delete("/files/{file_id}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Remove bytes and owner metadata through the shared file lifecycle."""
    _context()
    await remove_file(request, _file_id(file_id))
    return {}


async def resolve_file_references(request: Request, normalized_request: Any) -> None:
    """Resolve gateway file URIs to verified owner-scoped native attachments."""
    for message in normalized_request.messages:
        if not isinstance(message.content, list):
            continue
        retained_parts = []
        attachments = list(message.raw_extensions.get("attachments", []))
        for part in message.content:
            if part.type != "file" or not isinstance(part.data, dict):
                retained_parts.append(part)
                continue
            uri = part.data.get("file_id")
            if uri is None:
                retained_parts.append(part)
                continue
            if not isinstance(uri, str) or not uri.startswith("files/"):
                raise _invalid("fileUri must reference an uploaded gateway file.")
            file_id = _file_id(uri)
            resource = await get_resource_store(request).get(
                get_resource_owner(request), "file", file_id
            )
            if resource is None:
                raise file_not_found()
            metadata = resource.metadata
            if metadata.get("local") or not metadata.get("upstream_id"):
                raise _invalid(
                    "Batch JSONL and local result files cannot be used as document attachments."
                )
            mime = metadata.get("mime_type")
            if part.mime_type and mime and part.mime_type != mime:
                raise _invalid("fileData MIME type does not match the uploaded file.")
            attachments.append(metadata["upstream_id"])
        message.content = retained_parts
        if attachments:
            message.raw_extensions["attachments"] = attachments
