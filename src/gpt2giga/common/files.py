"""Shared owner-scoped file lifecycle over GigaChat and durable resources."""

import asyncio
import time
import uuid
from types import SimpleNamespace

from fastapi import HTTPException, Request

from gpt2giga.app_state import (
    get_gigachat_client,
    get_resource_owner,
    get_resource_store,
)
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.protocol.files import _serialize_file_object
from gpt2giga.storage.resources import ResourceLimitError


def file_not_found() -> HTTPException:
    """Hide the existence of resources owned by another caller."""
    return HTTPException(404, detail="File not found.")


async def stored_file(request: Request, file_id: str):
    """Resolve a mapping without permitting legacy fallback across owners."""
    store = get_resource_store(request)
    resource = await store.get(get_resource_owner(request), "file", file_id)
    if resource is None and (
        file_id.startswith("file_g2g_") or await store.is_registered("file", file_id)
    ):
        raise file_not_found()
    return resource


async def upload_file_resource(
    request: Request,
    *,
    content: bytes,
    filename: str,
    mime_type: str,
    purpose: str = "user_data",
    protocol: str = "openai",
) -> dict:
    """Publish metadata only after a real upload or atomic local blob creation."""
    store = get_resource_store(request)
    owner = get_resource_owner(request)
    is_local = purpose in {"batch", "batch_output"} or filename.lower().endswith(
        ".jsonl"
    )
    limit = store.max_blob_bytes
    if not is_local:
        settings = request.app.state.config.proxy_settings
        kind = (
            "image"
            if mime_type.startswith("image/")
            else "audio"
            if mime_type.startswith("audio/")
            else "text"
        )
        limit = min(limit, getattr(settings, f"max_{kind}_file_size_bytes"))
    if len(content) > limit:
        raise HTTPException(
            413, detail="File exceeds the configured upload size limit."
        )
    if is_local:
        file_id = "file_g2g_" + uuid.uuid4().hex
        file = SimpleNamespace(
            id_=file_id,
            bytes_=len(content),
            filename=filename,
            created_at=int(time.time()),
            purpose="general",
        )
    else:
        options = extract_gigachat_request_options(request)
        async with gigachat_request_options(
            get_gigachat_client(request), options, include_body=False
        ) as client:
            file = await client.aupload_file(
                (filename, content, mime_type), purpose="general"
            )
        file_id = file.id_
    metadata = {
        **_serialize_file_object(file, {"purpose": purpose}),
        "mime_type": mime_type,
        "protocol": protocol,
        "upstream_id": None if is_local else file_id,
        "local": is_local,
        "downloadable": purpose == "batch_output",
    }
    existing = await store.get(owner, "file", file_id)
    try:
        await store.put(
            owner, "file", file_id, metadata, blob=content if is_local else None
        )
    except asyncio.CancelledError:
        # The store drains its write before propagating cancellation. Remove a
        # newly published resource before allowing the cancelled request to exit.
        if existing is None:

            async def cleanup() -> None:
                await store.delete(owner, "file", file_id)
                if not is_local:
                    async with gigachat_request_options(
                        get_gigachat_client(request), options, include_body=False
                    ) as client:
                        await client.adelete_file(file=file_id)

            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if cleanup_task.exception() is not None:
                logger = getattr(request.app.state, "logger", None)
                if logger is not None:
                    logger.warning("Cancelled file cleanup failed")
        raise
    except ResourceLimitError as exc:
        raise HTTPException(413, detail="Resource store blob quota exceeded.") from exc
    return metadata


async def file_metadata(request: Request, file_id: str) -> dict:
    """Return stored metadata, or obtain a legacy upstream file under caller credentials."""
    resource = await stored_file(request, file_id)
    if resource is not None:
        return resource.metadata
    options = extract_gigachat_request_options(request)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        file = await client.aget_file(file=file_id)
    return {
        **_serialize_file_object(file),
        "upstream_id": file.id_,
        "mime_type": "application/octet-stream",
    }


async def file_content(request: Request, file_id: str) -> bytes:
    """Read raw local/upstream bytes without base64 conversion."""
    resource = await stored_file(request, file_id)
    if resource is not None and resource.metadata.get("local"):
        content = await get_resource_store(request).read_blob(
            get_resource_owner(request), "file", file_id
        )
        if content is None:
            raise file_not_found()
        return content
    options = extract_gigachat_request_options(request)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        return await client.aget_file_content(file_id=file_id)


async def remove_file(request: Request, file_id: str) -> None:
    """Delete upstream bytes first, then the owner's metadata and local blob."""
    resource = await stored_file(request, file_id)
    if resource is None or not resource.metadata.get("local"):
        options = extract_gigachat_request_options(request)
        async with gigachat_request_options(
            get_gigachat_client(request), options, include_body=False
        ) as client:
            await client.adelete_file(file=file_id)
    await get_resource_store(request).delete(
        get_resource_owner(request), "file", file_id
    )


async def list_file_metadata(request: Request) -> list[dict]:
    """Combine durable metadata with request-scoped legacy upstream documents."""
    store = get_resource_store(request)
    records = await store.list(get_resource_owner(request), "file")
    known = {record.public_id: record.metadata for record in records}
    options = extract_gigachat_request_options(
        request,
        exclude_query_params=(
            "after",
            "limit",
            "order",
            "purpose",
            "page",
            "page_size",
        ),
    )
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        files = await client.aget_files()
    for file in files.data:
        if file.id_ not in known and not await store.is_registered("file", file.id_):
            known[file.id_] = _serialize_file_object(file)
    return list(known.values())
