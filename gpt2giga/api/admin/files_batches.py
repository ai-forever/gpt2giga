"""Normalized admin endpoints for files and batches inventory."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from starlette.requests import Request

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.api.batch_validation import (
    validate_batch_input_request,
    run_batch_input_validation,
)
from gpt2giga.api.anthropic.batches import _build_anthropic_batch_results
from gpt2giga.api.gemini.batches import build_gemini_batch_output_file
from gpt2giga.app.dependencies import (
    get_logger_from_state,
    get_runtime_providers,
)
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.form_body import read_request_multipart
from gpt2giga.features.batches import (
    get_batches_service_from_state,
)
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.files import get_files_service_from_state
from gpt2giga.features.files.store import get_file_store
from gpt2giga.features.files_batches import get_files_batches_service_from_state
from gpt2giga.providers.gigachat.client import get_gigachat_client

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


@admin_files_batches_api_router.post("/admin/api/files-batches/files")
@exceptions_handler
async def create_files_batches_file(request: Request):
    """Create a normalized staged file through the admin API."""
    verify_logs_ip_allowlist(request)
    multipart = await read_request_multipart(request)
    form = multipart.get("form") or {}
    upload = (multipart.get("files") or {}).get("file")
    if upload is None:
        raise HTTPException(status_code=400, detail="`file` is required.")

    app_state = request.app.state
    service = get_files_batches_service_from_state(app_state)
    purpose = str(form.get("purpose") or "batch").strip() or "batch"
    api_format = str(form.get("api_format") or "openai").strip() or "openai"
    display_name = str(form.get("display_name") or "").strip() or None
    return await service.create_file(
        api_format=api_format,
        purpose=purpose,
        upload=upload,
        display_name=display_name,
        giga_client=get_gigachat_client(request),
        files_service=get_files_service_from_state(app_state),
        file_store=get_file_store(request),
    )


@admin_files_batches_api_router.post("/admin/api/files-batches/batches")
@exceptions_handler
async def create_files_batches_batch(
    payload: AdminBatchCreateRequest,
    request: Request,
):
    """Create a normalized batch artifact through the admin API."""
    verify_logs_ip_allowlist(request)
    validation_report = await run_batch_input_validation(
        request=request,
        api_format=payload.api_format,
        input_file_id=payload.input_file_id,
        input_bytes=None,
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
    app_state = request.app.state
    service = get_files_batches_service_from_state(app_state)
    return await service.create_batch(
        api_format=payload.api_format,
        endpoint=payload.endpoint,
        input_file_id=payload.input_file_id,
        metadata=payload.metadata,
        display_name=payload.display_name,
        model=payload.model,
        requests=payload.requests,
        giga_client=get_gigachat_client(request),
        batches_service=get_batches_service_from_state(app_state),
        logger=get_logger_from_state(app_state),
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )


@admin_files_batches_api_router.post("/admin/api/files-batches/batches/validate")
@exceptions_handler
async def validate_files_batches_batch(
    payload: AdminBatchValidateRequest,
    request: Request,
):
    """Validate staged or inline batch input and return a diagnostic report."""
    verify_logs_ip_allowlist(request)
    input_bytes = (
        base64.b64decode(payload.input_content_base64)
        if payload.input_content_base64
        else None
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
async def get_files_batches_file_content(file_id: str, request: Request):
    """Return canonical file content for admin preview/download."""
    verify_logs_ip_allowlist(request)
    app_state = request.app.state
    giga_client = get_gigachat_client(request)
    files_service = get_files_service_from_state(app_state)
    batches_service = get_batches_service_from_state(app_state)
    file_store = get_file_store(request)
    batch_store = get_batch_store(request)
    batch_id = _resolve_output_batch_id(
        file_id,
        file_store=file_store,
        batch_store=batch_store,
    )
    if batch_id is not None:
        batch_record = await _require_batch_record(
            batch_id,
            request=request,
            batches_service=batches_service,
            file_store=file_store,
            batch_store=batch_store,
        )
        if batch_record.output_file_id == file_id:
            content, media_type = await _load_batch_output_content(
                batch_record,
                request=request,
                giga_client=giga_client,
                files_service=files_service,
                batch_store=batch_store,
                file_store=file_store,
            )
            return Response(content=content, media_type=media_type)

    content = await files_service.get_file_content(
        file_id,
        giga_client=giga_client,
        batch_store=batch_store,
        file_store=file_store,
        response_processor=_get_response_processor_or_none(app_state),
    )
    media_type = (file_store.get(file_id) or {}).get(
        "mime_type", "application/octet-stream"
    )
    return Response(content=content, media_type=media_type)


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


@admin_files_batches_api_router.get(
    "/admin/api/files-batches/batches/{batch_id}/output"
)
@exceptions_handler
async def get_files_batches_batch_output(batch_id: str, request: Request):
    """Return canonical batch output for admin preview/download."""
    verify_logs_ip_allowlist(request)
    batch_record = await _require_batch_record(
        batch_id,
        request=request,
        batches_service=get_batches_service_from_state(request.app.state),
        file_store=get_file_store(request),
        batch_store=get_batch_store(request),
    )
    content, media_type = await _load_batch_output_content(
        batch_record,
        request=request,
        giga_client=get_gigachat_client(request),
        files_service=get_files_service_from_state(request.app.state),
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    return Response(content=content, media_type=media_type)


async def _require_batch_record(
    batch_id: str,
    *,
    request: Request,
    batches_service: object,
    file_store: object,
    batch_store: object,
):
    app_state = request.app.state
    service = get_files_batches_service_from_state(app_state)
    record = await service.retrieve_batch(
        batch_id,
        giga_client=get_gigachat_client(request),
        batches_service=batches_service,
        batch_store=batch_store,
        file_store=file_store,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Batch `{batch_id}` not found.")
    return record


async def _load_batch_output_content(
    batch_record,
    *,
    request: Request,
    giga_client: object,
    files_service: object,
    batch_store: object,
    file_store: object,
) -> tuple[bytes, str]:
    output_file_id = batch_record.output_file_id
    if not output_file_id:
        raise HTTPException(
            status_code=409,
            detail=f"Batch `{batch_record.id}` output is not available yet.",
        )

    raw_metadata = dict(batch_record.raw.get("metadata") or {})
    raw_batch = dict(batch_record.raw.get("batch") or {})
    status = str(raw_batch.get("status") or batch_record.status or "").strip().lower()

    if batch_record.api_format.value == "openai":
        content = await files_service.get_file_content(
            output_file_id,
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
            response_processor=_get_response_processor_or_none(request.app.state),
        )
        return content, "application/octet-stream"

    if status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Batch `{batch_record.id}` output is not available yet.",
        )

    file_response = await giga_client.aget_file_content(file_id=output_file_id)
    if batch_record.api_format.value == "anthropic":
        return (
            _build_anthropic_batch_results(file_response.content, raw_metadata),
            "application/binary",
        )

    return (
        build_gemini_batch_output_file(
            file_response.content,
            batch_metadata=raw_metadata,
        ),
        "application/json",
    )


def _get_response_processor_or_none(state: object):
    providers = get_runtime_providers(state)
    return providers.response_processor


def _resolve_output_batch_id(
    file_id: str,
    *,
    file_store: object,
    batch_store: object,
) -> str | None:
    stored_file = file_store.get(file_id, {}) if file_store is not None else {}
    stored_batch_id = str(stored_file.get("batch_id") or "").strip()
    if stored_batch_id:
        return stored_batch_id
    if batch_store is None:
        return None
    for batch_id, metadata in batch_store.items():
        if metadata.get("output_file_id") == file_id:
            return str(batch_id)
    return None
