"""HTTP helpers for admin files/batches routes."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Response
from starlette.requests import Request

from gpt2giga.api.anthropic.batches import _build_anthropic_batch_results
from gpt2giga.api.batch_validation import resolve_batch_input_bytes
from gpt2giga.api.gemini.batches import build_gemini_batch_output_file
from gpt2giga.app.dependencies import (
    get_logger_from_state,
    get_runtime_providers,
)
from gpt2giga.core.http.form_body import read_request_multipart
from gpt2giga.features.batches import get_batches_service_from_state
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.batches.transforms import parse_jsonl
from gpt2giga.features.files import get_files_service_from_state
from gpt2giga.features.files.store import get_file_store
from gpt2giga.features.files_batches import get_files_batches_service_from_state
from gpt2giga.providers.gigachat.client import get_gigachat_client


@dataclass(slots=True)
class AdminFilesBatchesContext:
    """Runtime handles shared by admin files/batches routes."""

    request: Request
    service: Any
    giga_client: Any
    files_service: Any
    batches_service: Any
    file_store: Any
    batch_store: Any
    logger: Any
    response_processor: Any


@dataclass(slots=True)
class AdminFileCreatePayload:
    """Normalized admin file-create request fields."""

    api_format: str
    purpose: str
    display_name: str | None
    upload: dict[str, Any]


def build_admin_files_batches_context(request: Request) -> AdminFilesBatchesContext:
    """Collect shared runtime dependencies for admin files/batches routes."""
    app_state = request.app.state
    return AdminFilesBatchesContext(
        request=request,
        service=get_files_batches_service_from_state(app_state),
        giga_client=get_gigachat_client(request),
        files_service=get_files_service_from_state(app_state),
        batches_service=get_batches_service_from_state(app_state),
        file_store=get_file_store(request),
        batch_store=get_batch_store(request),
        logger=get_logger_from_state(app_state),
        response_processor=get_runtime_providers(app_state).response_processor,
    )


async def read_admin_file_create_payload(request: Request) -> AdminFileCreatePayload:
    """Read and normalize the multipart payload for admin file creation."""
    multipart = await read_request_multipart(request)
    form = multipart.get("form") or {}
    upload = (multipart.get("files") or {}).get("file")
    if upload is None:
        raise HTTPException(status_code=400, detail="`file` is required.")
    return AdminFileCreatePayload(
        api_format=str(form.get("api_format") or "openai").strip() or "openai",
        purpose=str(form.get("purpose") or "batch").strip() or "batch",
        display_name=str(form.get("display_name") or "").strip() or None,
        upload=upload,
    )


async def resolve_admin_batch_input_bytes(
    request: Request,
    *,
    input_file_id: str | None,
    requests: list[dict[str, Any]] | None,
    input_content_base64: str | None = None,
) -> bytes | None:
    """Resolve staged or inline batch input bytes for validation/create flows."""
    if input_content_base64:
        return base64.b64decode(input_content_base64)
    if input_file_id and not requests:
        return await resolve_batch_input_bytes(request, file_id=input_file_id)
    return None


async def require_admin_batch_record(
    batch_id: str,
    *,
    context: AdminFilesBatchesContext,
):
    """Load one batch record or raise the admin 404 response."""
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


async def load_admin_batch_output_content(
    batch_record,
    *,
    context: AdminFilesBatchesContext,
) -> tuple[bytes, str]:
    """Load canonical batch output content for preview/download routes."""
    output_file_id = batch_record.output_file_id
    if not output_file_id:
        raise HTTPException(
            status_code=409,
            detail=f"Batch `{batch_record.id}` output is not available yet.",
        )

    raw_metadata = dict(batch_record.raw.get("metadata") or {})
    status = str(batch_record.status or "").strip().lower()
    output_api_format = await resolve_batch_output_api_format(
        batch_record,
        raw_metadata=raw_metadata,
        giga_client=context.giga_client,
        file_store=context.file_store,
    )

    if output_api_format == "openai":
        content = await context.files_service.get_file_content(
            output_file_id,
            giga_client=context.giga_client,
            batch_store=context.batch_store,
            file_store=context.file_store,
            response_processor=context.response_processor,
        )
        return content, "application/octet-stream"

    if status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Batch `{batch_record.id}` output is not available yet.",
        )

    file_response = await context.giga_client.aget_file_content(file_id=output_file_id)
    if output_api_format == "anthropic":
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


async def resolve_batch_output_api_format(
    batch_record,
    *,
    raw_metadata: dict[str, Any],
    giga_client: Any,
    file_store: Any,
) -> str:
    """Resolve the batch output format, falling back to the original input rows."""
    inferred_format = infer_batch_api_format_from_rows(raw_metadata.get("requests"))
    if inferred_format is not None:
        return inferred_format

    input_file_id = str(raw_metadata.get("input_file_id") or "").strip()
    if not input_file_id and file_store is not None and batch_record.output_file_id:
        stored_output_metadata = dict(file_store.get(batch_record.output_file_id, {}))
        input_file_id = str(
            stored_output_metadata.get("batch_input_file_id") or ""
        ).strip()

    if input_file_id:
        try:
            input_file_response = await giga_client.aget_file_content(
                file_id=input_file_id
            )
            input_rows = parse_jsonl(base64.b64decode(input_file_response.content))
        except Exception:
            input_rows = []
        inferred_format = infer_batch_api_format_from_rows(input_rows)
        if inferred_format is not None:
            return inferred_format

    return batch_record.api_format.value


def infer_batch_api_format_from_rows(rows: Any) -> str | None:
    """Infer the API format from stored batch rows when possible."""
    if not isinstance(rows, list):
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        if "params" in row:
            return "anthropic"
        if "request" in row:
            return "gemini"
        if "body" in row or "url" in row or "method" in row:
            return "openai"

    return None


def resolve_output_batch_id(
    file_id: str,
    *,
    file_store: Any,
    batch_store: Any,
) -> str | None:
    """Resolve the owning batch for an output file id."""
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


def build_content_response(
    content: bytes,
    *,
    media_type: str,
    preview_bytes: int | None,
) -> Response:
    """Build the admin content response with optional preview headers."""
    preview_content, preview_headers = limit_preview_content(
        content,
        media_type=media_type,
        preview_bytes=preview_bytes,
    )
    return Response(
        content=preview_content,
        media_type=media_type,
        headers=preview_headers,
    )


def limit_preview_content(
    content: bytes,
    *,
    media_type: str,
    preview_bytes: int | None,
) -> tuple[bytes, dict[str, str]]:
    """Trim preview payloads while preserving line boundaries when possible."""
    if preview_bytes is None or preview_bytes <= 0:
        return content, {}
    if media_type.startswith("image/") or len(content) <= preview_bytes:
        content_length = str(len(content))
        return content, {
            "X-Admin-Preview-Truncated": "false",
            "X-Admin-Preview-Bytes": content_length,
            "X-Admin-Preview-Total-Bytes": content_length,
        }

    preview_content = content[:preview_bytes]
    last_newline = preview_content.rfind(b"\n")
    if last_newline > 0:
        preview_content = preview_content[: last_newline + 1]
    if not preview_content:
        preview_content = content[:preview_bytes]
    return preview_content, {
        "X-Admin-Preview-Truncated": "true",
        "X-Admin-Preview-Bytes": str(len(preview_content)),
        "X-Admin-Preview-Total-Bytes": str(len(content)),
    }
