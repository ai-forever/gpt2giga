"""Normalized admin endpoints for files and batches inventory."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from starlette.requests import Request

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.features.files_batches import get_files_batches_service_from_state
from gpt2giga.features.files import get_files_service_from_state
from gpt2giga.features.batches import get_batches_service_from_state
from gpt2giga.features.files.store import get_file_store
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.providers.gigachat.client import get_gigachat_client

admin_files_batches_api_router = APIRouter(tags=["Admin"])


@admin_files_batches_api_router.get("/admin/api/files-batches/inventory")
@exceptions_handler
async def get_files_batches_inventory(
    request: Request,
    api_format: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    query: str | None = Query(default=None),
    status: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    purpose: str | None = Query(default=None),
):
    """Return a normalized mixed-provider files and batches inventory."""
    verify_logs_ip_allowlist(request)
    app_state = request.app.state
    service = get_files_batches_service_from_state(app_state)
    giga_client = get_gigachat_client(request)
    return await service.list_inventory(
        giga_client=giga_client,
        files_service=get_files_service_from_state(app_state),
        batches_service=get_batches_service_from_state(app_state),
        api_format=api_format,
        kind=kind,
        query=query,
        status=status,
        endpoint=endpoint,
        purpose=purpose,
        file_store=get_file_store(request),
        batch_store=get_batch_store(request),
    )


@admin_files_batches_api_router.get("/admin/api/files-batches/files/{file_id}")
@exceptions_handler
async def get_files_batches_file(file_id: str, request: Request):
    """Return one normalized file artifact for admin inspection."""
    verify_logs_ip_allowlist(request)
    app_state = request.app.state
    service = get_files_batches_service_from_state(app_state)
    try:
        return await service.retrieve_file(
            file_id,
            giga_client=get_gigachat_client(request),
            files_service=get_files_service_from_state(app_state),
            file_store=get_file_store(request),
            batch_store=get_batch_store(request),
        )
    except HTTPException:
        raise
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            raise HTTPException(
                status_code=404, detail=f"File `{file_id}` not found."
            ) from exc
        raise


@admin_files_batches_api_router.get("/admin/api/files-batches/batches/{batch_id}")
@exceptions_handler
async def get_files_batches_batch(batch_id: str, request: Request):
    """Return one normalized batch artifact for admin inspection."""
    verify_logs_ip_allowlist(request)
    app_state = request.app.state
    service = get_files_batches_service_from_state(app_state)
    record = await service.retrieve_batch(
        batch_id,
        giga_client=get_gigachat_client(request),
        batches_service=get_batches_service_from_state(app_state),
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Batch `{batch_id}` not found.")
    return record
