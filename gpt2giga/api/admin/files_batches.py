"""Normalized admin endpoints for files and batches inventory."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from starlette.requests import Request

from gpt2giga.api.admin.access import verify_admin_ip_allowlist
from gpt2giga.api.admin.files_batches_helpers import (
    build_admin_files_batches_context,
    build_content_response,
    load_admin_batch_output_content,
    read_admin_file_create_payload,
    require_admin_batch_record,
    resolve_admin_batch_input_bytes,
    resolve_output_batch_id,
)
from gpt2giga.api.batch_validation import (
    cache_batch_input_bytes,
    validate_batch_input_request,
    run_batch_input_validation,
)
from gpt2giga.core.errors import exceptions_handler

admin_files_batches_api_router = APIRouter(tags=["Admin"])


class AdminBatchCreateRequest(BaseModel):
    """Admin-only normalized batch-create payload."""

    api_format: str = "openai"
    endpoint: str | None = None
    input_file_id: str | None = None
    metadata: dict[str, Any] | None = None
    display_name: str | None = None
    model: str | None = None
    requests: list[dict[str, Any]] | None = None


class AdminBatchValidateRequest(BaseModel):
    """Admin-only normalized batch-validation payload."""

    api_format: str = "openai"
    input_file_id: str | None = None
    input_content_base64: str | None = None
    model: str | None = None
    requests: list[dict[str, Any]] | None = None


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
    verify_admin_ip_allowlist(request)
    context = build_admin_files_batches_context(request)
    return await context.service.list_inventory(
        giga_client=context.giga_client,
        files_service=context.files_service,
        batches_service=context.batches_service,
        api_format=api_format,
        kind=kind,
        query=query,
        status=status,
        endpoint=endpoint,
        purpose=purpose,
        file_store=context.file_store,
        batch_store=context.batch_store,
    )


@admin_files_batches_api_router.get("/admin/api/files-batches/files/{file_id}")
@exceptions_handler
async def get_files_batches_file(file_id: str, request: Request):
    """Return one normalized file artifact for admin inspection."""
    verify_admin_ip_allowlist(request)
    context = build_admin_files_batches_context(request)
    try:
        return await context.service.retrieve_file(
            file_id,
            giga_client=context.giga_client,
            files_service=context.files_service,
            file_store=context.file_store,
            batch_store=context.batch_store,
        )
    except HTTPException:
        raise
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            raise HTTPException(
                status_code=404, detail=f"File `{file_id}` not found."
            ) from exc
        raise


@admin_files_batches_api_router.post("/admin/api/files-batches/files")
@exceptions_handler
async def create_files_batches_file(request: Request):
    """Create a normalized staged file through the admin API."""
    verify_admin_ip_allowlist(request)
    payload = await read_admin_file_create_payload(request)
    context = build_admin_files_batches_context(request)
    created = await context.service.create_file(
        api_format=payload.api_format,
        purpose=payload.purpose,
        upload=payload.upload,
        display_name=payload.display_name,
        giga_client=context.giga_client,
        files_service=context.files_service,
        file_store=context.file_store,
    )
    created_file_id = str(created.id or "").strip()
    if created_file_id and payload.purpose == "batch":
        cache_batch_input_bytes(
            request,
            file_id=created_file_id,
            content=payload.upload["content"],
        )
    return created


@admin_files_batches_api_router.post("/admin/api/files-batches/batches")
@exceptions_handler
async def create_files_batches_batch(
    payload: AdminBatchCreateRequest,
    request: Request,
):
    """Create a normalized batch artifact through the admin API."""
    verify_admin_ip_allowlist(request)
    input_bytes = await resolve_admin_batch_input_bytes(
        request,
        input_file_id=payload.input_file_id,
        requests=payload.requests,
    )
    validation_report = await run_batch_input_validation(
        request=request,
        api_format=payload.api_format,
        input_file_id=payload.input_file_id,
        input_bytes=input_bytes,
        fallback_model=payload.model,
        requests=payload.requests,
    )
    if validation_report is not None and not validation_report.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Batch input validation failed. "
                    "Run validation and fix blocking issues before creating the batch."
                ),
                "validation_report": validation_report.model_dump(mode="json"),
            },
        )
    context = build_admin_files_batches_context(request)
    return await context.service.create_batch(
        api_format=payload.api_format,
        endpoint=payload.endpoint,
        input_file_id=payload.input_file_id,
        input_bytes=input_bytes,
        metadata=payload.metadata,
        display_name=payload.display_name,
        model=payload.model,
        requests=payload.requests,
        giga_client=context.giga_client,
        batches_service=context.batches_service,
        logger=context.logger,
        batch_store=context.batch_store,
        file_store=context.file_store,
    )


@admin_files_batches_api_router.post("/admin/api/files-batches/batches/validate")
@exceptions_handler
async def validate_files_batches_batch(
    payload: AdminBatchValidateRequest,
    request: Request,
):
    """Validate staged or inline batch input and return a diagnostic report."""
    verify_admin_ip_allowlist(request)
    input_bytes = await resolve_admin_batch_input_bytes(
        request,
        input_file_id=payload.input_file_id,
        requests=payload.requests,
        input_content_base64=payload.input_content_base64,
    )
    return await validate_batch_input_request(
        request=request,
        api_format=payload.api_format,
        input_file_id=payload.input_file_id,
        input_bytes=input_bytes,
        fallback_model=payload.model,
        requests=payload.requests,
    )


@admin_files_batches_api_router.get("/admin/api/files-batches/files/{file_id}/content")
@exceptions_handler
async def get_files_batches_file_content(
    file_id: str,
    request: Request,
    preview_bytes: int | None = Query(default=None, ge=1, le=1_048_576),
):
    """Return canonical file content for admin preview/download."""
    verify_admin_ip_allowlist(request)
    context = build_admin_files_batches_context(request)
    batch_id = resolve_output_batch_id(
        file_id,
        file_store=context.file_store,
        batch_store=context.batch_store,
    )
    if batch_id is not None:
        batch_record = await require_admin_batch_record(
            batch_id,
            context=context,
        )
        if batch_record.output_file_id == file_id:
            content, media_type = await load_admin_batch_output_content(
                batch_record,
                context=context,
            )
            return build_content_response(
                content,
                media_type=media_type,
                preview_bytes=preview_bytes,
            )

    content = await context.files_service.get_file_content(
        file_id,
        giga_client=context.giga_client,
        batch_store=context.batch_store,
        file_store=context.file_store,
        response_processor=context.response_processor,
    )
    media_type = (context.file_store.get(file_id) or {}).get(
        "mime_type", "application/octet-stream"
    )
    return build_content_response(
        content,
        media_type=media_type,
        preview_bytes=preview_bytes,
    )


@admin_files_batches_api_router.get("/admin/api/files-batches/batches/{batch_id}")
@exceptions_handler
async def get_files_batches_batch(batch_id: str, request: Request):
    """Return one normalized batch artifact for admin inspection."""
    verify_admin_ip_allowlist(request)
    context = build_admin_files_batches_context(request)
    record = await context.service.retrieve_batch(
        batch_id,
        giga_client=context.giga_client,
        batches_service=context.batches_service,
        batch_store=context.batch_store,
        file_store=context.file_store,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Batch `{batch_id}` not found.")
    return record


@admin_files_batches_api_router.get(
    "/admin/api/files-batches/batches/{batch_id}/output"
)
@exceptions_handler
async def get_files_batches_batch_output(
    batch_id: str,
    request: Request,
    preview_bytes: int | None = Query(default=None, ge=1, le=1_048_576),
):
    """Return canonical batch output for admin preview/download."""
    verify_admin_ip_allowlist(request)
    context = build_admin_files_batches_context(request)
    batch_record = await require_admin_batch_record(
        batch_id,
        context=context,
    )
    content, media_type = await load_admin_batch_output_content(
        batch_record,
        context=context,
    )
    return build_content_response(
        content,
        media_type=media_type,
        preview_bytes=preview_bytes,
    )
