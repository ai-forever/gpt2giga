"""Gemini-compatible Files API handlers.

These routes are intentionally not mounted by ``gpt2giga.api.gemini.routes`` yet.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from gpt2giga.app_state import get_file_store, get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.request_form import read_request_multipart
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.gemini import gemini_files_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_FILES

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_FILES])


@router.post("/files", openapi_extra=gemini_files_openapi_extra())
@exceptions_handler
async def create_file(request: Request):
    """Create Gemini-compatible file metadata or upload multipart content."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        return await _create_multipart_file(request)

    data = await read_request_json(request)
    file_payload = data.get("file") if isinstance(data.get("file"), dict) else {}
    store = get_file_store(request)
    name = str(file_payload.get("name") or f"files/{len(store) + 1}")
    metadata = _file_metadata(
        name=name,
        display_name=file_payload.get("displayName")
        or file_payload.get("display_name"),
        mime_type=file_payload.get("mimeType") or file_payload.get("mime_type"),
        size_bytes=file_payload.get("sizeBytes")
        or file_payload.get("size_bytes")
        or "0",
        uri=file_payload.get("uri"),
    )
    store[name] = metadata
    return {"file": metadata}


@router.get("/files")
@exceptions_handler
async def list_files(request: Request):
    """List Gemini-compatible files."""
    store = get_file_store(request)
    return {"files": list(store.values()), "nextPageToken": ""}


@router.get("/files/{file_id:path}")
@exceptions_handler
async def get_file(file_id: str, request: Request):
    """Return Gemini-compatible file metadata."""
    name = _file_name(file_id)
    store = get_file_store(request)
    if name in store:
        return store[name]

    giga_client = get_gigachat_client(request)
    if not hasattr(giga_client, "aget_file"):
        raise _not_found(name)
    request_options = extract_gigachat_request_options(request)
    async with gigachat_request_options(giga_client, request_options):
        file_obj = await giga_client.aget_file(file=name.removeprefix("files/"))
    metadata = _gigachat_file_to_gemini(file_obj, stored=None)
    store[name] = metadata
    return metadata


@router.delete("/files/{file_id:path}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    """Delete a Gemini-compatible file."""
    name = _file_name(file_id)
    giga_client = get_gigachat_client(request)
    if hasattr(giga_client, "adelete_file"):
        request_options = extract_gigachat_request_options(request)
        async with gigachat_request_options(giga_client, request_options):
            await giga_client.adelete_file(file=name.removeprefix("files/"))
    get_file_store(request).pop(name, None)
    return {}


async def _create_multipart_file(request: Request) -> dict[str, Any]:
    multipart = await read_request_multipart(request)
    upload = multipart["files"].get("file")
    if upload is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Multipart upload requires a `file` field.",
                    "type": "invalid_request_error",
                    "param": "file",
                    "code": "invalid_multipart",
                }
            },
        )

    giga_client = get_gigachat_client(request)
    uploaded = None
    if hasattr(giga_client, "aupload_file"):
        request_options = extract_gigachat_request_options(request)
        async with gigachat_request_options(giga_client, request_options):
            uploaded = await giga_client.aupload_file(
                (
                    upload["filename"],
                    upload["content"],
                    upload["content_type"],
                ),
                purpose="general",
            )
    name = f"files/{getattr(uploaded, 'id_', None) or len(get_file_store(request)) + 1}"
    metadata = _gigachat_file_to_gemini(
        uploaded,
        stored={
            "name": name,
            "displayName": upload["filename"],
            "mimeType": upload["content_type"],
            "sizeBytes": str(len(upload["content"])),
        },
    )
    get_file_store(request)[metadata["name"]] = metadata
    return {"file": metadata}


def _gigachat_file_to_gemini(
    file_obj: Any,
    *,
    stored: dict[str, Any] | None,
) -> dict[str, Any]:
    if file_obj is None:
        file_obj = {}
    data = file_obj.model_dump(by_alias=True) if hasattr(file_obj, "model_dump") else {}
    if isinstance(file_obj, dict):
        data = dict(file_obj)
    stored = stored or {}
    file_id = data.get("id") or data.get("id_") or stored.get("name", "files/unknown")
    name = str(file_id)
    if not name.startswith("files/"):
        name = f"files/{name}"
    return _file_metadata(
        name=name,
        display_name=stored.get("displayName") or data.get("filename") or name,
        mime_type=stored.get("mimeType") or data.get("mime_type"),
        size_bytes=stored.get("sizeBytes")
        or data.get("bytes")
        or data.get("bytes_")
        or "0",
        uri=data.get("uri") or name,
    )


def _file_metadata(
    *,
    name: str,
    display_name: Any,
    mime_type: Any,
    size_bytes: Any,
    uri: Any,
) -> dict[str, Any]:
    now = _rfc3339_now()
    return {
        "name": name if name.startswith("files/") else f"files/{name}",
        "displayName": str(display_name or name),
        "mimeType": str(mime_type or "application/octet-stream"),
        "sizeBytes": str(size_bytes or "0"),
        "createTime": now,
        "updateTime": now,
        "uri": str(uri or name),
        "state": "ACTIVE",
        "source": "UPLOADED",
    }


def _file_name(value: str) -> str:
    return value if value.startswith("files/") else f"files/{value}"


def _not_found(name: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "message": f"File `{name}` not found.",
                "type": "not_found_error",
                "param": "name",
                "code": None,
            }
        },
    )


def _rfc3339_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
