"""Shared owner-scoped file lifecycle over GigaChat and durable resources."""

import asyncio
import time
import uuid
from types import SimpleNamespace

from anyio import CancelScope
from fastapi import HTTPException, Request
from gigachat.exceptions import ResponseError

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

_FILE_CLEANUP_TIMEOUT_SECONDS = 5.0


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


async def _file_for_read(request: Request, file_id: str):
    """Locate a caller's resource and bind its profile for Files operations only."""
    store = get_resource_store(request)
    resource = await store.get(get_resource_owner(request), "file", file_id)
    runtime = getattr(request.app.state, "bridge_provider_runtime", None)
    if resource is None and runtime is not None:
        for profile_id in runtime._giga_settings:
            resource = await store.get(
                get_resource_owner(request, profile=profile_id), "file", file_id
            )
            if resource is not None:
                from gpt2giga.app.providers import bind_gigachat_profile

                await bind_gigachat_profile(request, profile_id)
                break
    if resource is None:
        return await stored_file(request, file_id)
    return resource


async def validate_model_attachments(request: Request, data: dict) -> None:
    """Apply the Files ownership gate to every accepted model-input reference.

    Unknown native IDs retain their existing request-credential policy. Known
    foreign/deleted/expired resources never fall back to native lookup.
    """
    from gpt2giga.common.client_params import ClientCompatibilityError
    from gpt2giga.core.context import _infer_protocol
    from gpt2giga.routers.openai.helpers import request_attachment_ids

    references = set(request_attachment_ids(request))
    provider = (
        "anthropic" if _infer_protocol(request.url.path) == "anthropic" else "openai"
    )

    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for key in ("attachments", "file_ids"):
                ids = value.get(key)
                if isinstance(ids, list):
                    references.update(item for item in ids if isinstance(item, str))
            for key in ("file_id", "fileUri", "file_uri"):
                file_id = value.get(key)
                if isinstance(file_id, str) and file_id:
                    references.add(file_id.removeprefix("files/"))
            # Do not inspect user JSON, function arguments or tool schemas.
            for key in (
                "messages",
                "input",
                "contents",
                "content",
                "parts",
                "source",
                "file",
                "fileData",
                "file_data",
                "extra_body",
                "additional_fields",
                "tools",
                "container",
                "mask",
                "raw_extensions",
                "data",
            ):
                collect(value.get(key))

    collect(data)
    for file_id in references:
        try:
            resource = await stored_file(request, file_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            raise ClientCompatibilityError(
                "File not found.",
                provider=provider,
                status_code=404,
                param="attachments",
                code="file_not_found",
                error_type="not_found_error",
            ) from exc
        if resource is not None and (
            resource.metadata.get("local") or not resource.metadata.get("upstream_id")
        ):
            raise ClientCompatibilityError(
                "Local batch and result files cannot be used as model attachments.",
                param="attachments",
                provider=provider,
            )


def file_upload_size_limit(
    settings, mime_type: str, filename: str, purpose: str
) -> int:
    """Apply the same MIME and resource byte limits before reading or uploading."""
    limit = settings.resource_max_blob_bytes
    if purpose in {"batch", "batch_output"} or filename.lower().endswith(".jsonl"):
        return limit
    kind = (
        "image"
        if mime_type.startswith("image/")
        else "audio"
        if mime_type.startswith("audio/")
        else "text"
    )
    return min(limit, getattr(settings, f"max_{kind}_file_size_bytes"))


async def bind_file_upload_profile(request: Request) -> None:
    """Select one configured GigaChat target before deriving upload ownership."""
    profile_id = request.headers.get("x-gpt2giga-profile")
    if profile_id is None:
        return
    registry = getattr(request.app.state, "provider_registry", None)
    profiles = registry.config.profiles if registry is not None else []
    if not any(
        p.profile_id == profile_id and p.provider_kind.value == "gigachat"
        for p in profiles
    ):
        raise HTTPException(400, detail="Unknown or non-GigaChat upload profile.")
    from gpt2giga.app.providers import bind_gigachat_profile

    await bind_gigachat_profile(request, profile_id)


async def _bounded_cleanup(request: Request, operation) -> None:
    """Bound compensation; drain any already-started local transaction on cancel."""

    async def run():
        try:
            await asyncio.wait_for(operation(), timeout=_FILE_CLEANUP_TIMEOUT_SECONDS)
        except Exception:
            logger = getattr(request.app.state, "logger", None)
            if logger is not None:
                logger.warning("File cleanup incomplete; durable intent retained")

    task = asyncio.create_task(run())
    with CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
    task.result()


async def upload_file_resource(
    request: Request,
    *,
    content: bytes,
    filename: str,
    mime_type: str,
    purpose: str = "user_data",
    protocol: str = "openai",
    upload_session_id: str | None = None,
) -> dict:
    """Publish metadata only after a real upload or atomic local blob creation."""
    if upload_session_id is None:
        await bind_file_upload_profile(request)
    store = get_resource_store(request)
    owner = get_resource_owner(request)
    is_local = purpose in {"batch", "batch_output"} or filename.lower().endswith(
        ".jsonl"
    )
    limit = min(
        store.max_blob_bytes,
        file_upload_size_limit(
            request.app.state.config.proxy_settings, mime_type, filename, purpose
        ),
    )
    if len(content) > limit:
        raise HTTPException(
            413, detail="File exceeds the configured upload size limit."
        )
    reservation_id = "upload_g2g_" + uuid.uuid4().hex
    file_id = "file_g2g_" + uuid.uuid4().hex if is_local else None
    started = False
    existing = None
    compensate = False
    options = extract_gigachat_request_options(request)

    async def cleanup() -> None:
        # Never drop the durable intent until remote deletion is confirmed.
        if not is_local and started:
            if file_id is None:
                return  # Unknown upload outcome needs operator reconciliation.
            if compensate:
                async with gigachat_request_options(
                    get_gigachat_client(request), options, include_body=False
                ) as client:
                    await client.with_options(max_retries=0).adelete_file(file=file_id)
            elif existing is None:
                return  # Cannot prove a previously owned ID is safe to delete.
        if file_id is not None and existing is None:
            await store.delete(owner, "file", file_id)
        if not is_local:
            await store.delete(owner, "file_upload", reservation_id)

    try:
        if is_local:
            file = SimpleNamespace(
                id_=file_id,
                bytes_=len(content),
                filename=filename,
                created_at=int(time.time()),
                purpose="general",
            )
        else:
            # Reserve count and conservative metadata capacity transactionally.
            # Unknown outcomes deliberately do not expire or become retryable.
            await store.put(
                owner,
                "file_upload",
                reservation_id,
                {
                    "status": "upload_outcome_unknown",
                    "upstream_id": None,
                    "provider_profile": getattr(
                        request.state, "provider_profile_id", None
                    ),
                    "filename": filename,
                    "mime_type": mime_type,
                    "purpose": purpose,
                    "reserved_metadata": " " * 1024,
                },
                expires_at=float("inf"),
            )
            async with gigachat_request_options(
                get_gigachat_client(request), options, include_body=False
            ) as client:
                started = True
                file = await client.with_options(max_retries=0).aupload_file(
                    (filename, content, mime_type), purpose="general"
                )
                file_id = file.id_
            existing = await store.get(owner, "file", file_id)
            compensate = not await store.is_registered("file", file_id)
            await store.update(
                owner,
                "file_upload",
                reservation_id,
                {"upstream_id": file_id, "status": "publication_pending"},
            )
        metadata = {
            **_serialize_file_object(file, {"purpose": purpose}),
            "mime_type": mime_type,
            "protocol": protocol,
            "provider_profile": getattr(request.state, "provider_profile_id", None),
            "upstream_id": None if is_local else file_id,
            "local": is_local,
            "downloadable": purpose == "batch_output",
        }
        if is_local:
            existing = await store.get(owner, "file", file_id)
        if not is_local:
            await store.promote_blob(
                owner, "file_upload", reservation_id, "file", file_id, metadata
            )
        elif upload_session_id is not None:
            await store.promote_blob(
                owner, "upload", upload_session_id, "file", file_id, metadata
            )
        else:
            await store.put(owner, "file", file_id, metadata, blob=content)
    except BaseException as exc:
        if (
            isinstance(exc, ResponseError)
            and file_id is None
            and exc.status_code in {400, 401, 403, 404, 405, 413, 415, 422, 429}
        ):
            started = False  # A definite rejection created no upstream object.
        await _bounded_cleanup(request, cleanup)
        if isinstance(exc, ResourceLimitError):
            raise HTTPException(413, detail=str(exc)) from exc
        raise
    return metadata


async def file_metadata(request: Request, file_id: str) -> dict:
    """Return stored metadata, or obtain a legacy upstream file under caller credentials."""
    resource = await _file_for_read(request, file_id)
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
    resource = await _file_for_read(request, file_id)
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
    resource = await _file_for_read(request, file_id)
    if resource is None or not resource.metadata.get("local"):
        options = extract_gigachat_request_options(request)
        async with gigachat_request_options(
            get_gigachat_client(request), options, include_body=False
        ) as client:
            await client.adelete_file(file=file_id)
    await get_resource_store(request).delete(
        get_resource_owner(request), "file", file_id
    )


async def list_stored_files(request: Request):
    """List registered files across only the caller's configured profile scopes."""
    store = get_resource_store(request)
    owners = {get_resource_owner(request)}
    runtime = getattr(request.app.state, "bridge_provider_runtime", None)
    if runtime is not None:
        owners.update(
            get_resource_owner(request, profile=profile_id)
            for profile_id in runtime._giga_settings
        )
    records = {}
    for owner in sorted(owners):
        for record in await store.list(owner, "file"):
            records.setdefault(record.public_id, record)
    return sorted(records.values(), key=lambda row: (row.created_at, row.public_id))


async def list_file_metadata(request: Request) -> list[dict]:
    """Combine durable metadata with request-scoped legacy upstream documents."""
    store = get_resource_store(request)
    records = await list_stored_files(request)
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
