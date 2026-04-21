"""Provider-specific normalization helpers for files and batches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from gpt2giga.core.contracts import (
    NormalizedArtifactFormat,
    NormalizedBatchRecord,
    NormalizedBatchRequestCounts,
    NormalizedFileRecord,
)

_FAILED_BATCH_STATUSES = {"failed", "cancelled", "expired"}


def normalize_openai_file(file_obj: dict[str, Any]) -> NormalizedFileRecord:
    """Normalize an OpenAI-compatible file payload."""
    file_id = str(file_obj.get("id") or "").strip()
    return NormalizedFileRecord(
        id=file_id,
        api_format=NormalizedArtifactFormat.OPENAI,
        filename=str(file_obj.get("filename") or file_id or "unknown"),
        purpose=_string_or_none(file_obj.get("purpose")),
        bytes=_int_or_none(file_obj.get("bytes")),
        status=_string_or_none(file_obj.get("status")) or "processed",
        created_at=_int_or_none(file_obj.get("created_at")),
        content_kind=_infer_openai_content_kind(file_obj),
        download_path=_admin_file_content_path(file_id) if file_id else None,
        content_path=_admin_file_content_path(file_id) if file_id else None,
        delete_path=f"/v1/files/{file_id}" if file_id else None,
        raw=deepcopy(file_obj),
    )


def normalize_openai_batch(batch_obj: dict[str, Any]) -> NormalizedBatchRecord:
    """Normalize an OpenAI-compatible batch payload."""
    batch_id = str(batch_obj.get("id") or "").strip()
    output_file_id = _string_or_none(batch_obj.get("output_file_id"))
    return NormalizedBatchRecord(
        id=batch_id,
        api_format=NormalizedArtifactFormat.OPENAI,
        endpoint=_string_or_none(batch_obj.get("endpoint")) or "/v1/chat/completions",
        status=_string_or_none(batch_obj.get("status")) or "in_progress",
        created_at=_int_or_none(batch_obj.get("created_at")),
        input_file_id=_string_or_none(batch_obj.get("input_file_id")),
        output_file_id=output_file_id,
        output_kind="file" if output_file_id else None,
        output_path=_admin_batch_output_path(batch_id)
        if batch_id and output_file_id
        else None,
        request_counts=_normalize_request_counts(batch_obj.get("request_counts")),
        model=_string_or_none(batch_obj.get("model")),
        display_name=batch_id or None,
        raw=deepcopy(batch_obj),
    )


def normalize_anthropic_batch(
    batch: Any,
    metadata: dict[str, Any] | None = None,
) -> NormalizedBatchRecord:
    """Normalize an Anthropic message-batch record."""
    batch_id = _batch_id(batch)
    metadata = dict(metadata or {})
    output_file_id = _string_or_none(getattr(batch, "output_file_id", None))
    return NormalizedBatchRecord(
        id=batch_id,
        api_format=NormalizedArtifactFormat.ANTHROPIC,
        endpoint=_string_or_none(metadata.get("endpoint")) or "/v1/chat/completions",
        status=_canonical_batch_status(getattr(batch, "status", None)),
        created_at=_int_or_none(getattr(batch, "created_at", None)),
        input_file_id=_string_or_none(metadata.get("input_file_id")),
        output_file_id=output_file_id,
        output_kind="results" if output_file_id else None,
        output_path=_admin_batch_output_path(batch_id)
        if batch_id and output_file_id
        else None,
        request_counts=_normalize_anthropic_request_counts(batch, metadata),
        model=_string_or_none(metadata.get("model")),
        display_name=_string_or_none(metadata.get("display_name")) or batch_id or None,
        raw=_build_batch_raw(batch, metadata),
    )


def normalize_anthropic_file(
    file_obj: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    batch_id: str | None = None,
    batch_metadata: dict[str, Any] | None = None,
) -> NormalizedFileRecord:
    """Normalize an Anthropic-oriented staged file or results artifact."""
    metadata = dict(metadata or {})
    if batch_id or batch_metadata or metadata.get("batch_id"):
        return normalize_anthropic_output_file(
            file_obj,
            metadata=metadata,
            batch_id=batch_id,
            batch_metadata=batch_metadata,
        )

    file_id = str(file_obj.get("id") or "").strip()
    purpose = _string_or_none(metadata.get("purpose")) or _string_or_none(
        file_obj.get("purpose")
    )
    filename = (
        _string_or_none(metadata.get("filename"))
        or _string_or_none(file_obj.get("filename"))
        or file_id
        or "unknown"
    )
    content_path = _admin_file_content_path(file_id) if file_id else None
    raw = deepcopy(file_obj)
    if metadata:
        raw["metadata"] = deepcopy(metadata)
    return NormalizedFileRecord(
        id=file_id,
        api_format=NormalizedArtifactFormat.ANTHROPIC,
        filename=filename,
        purpose=purpose,
        bytes=_int_or_none(file_obj.get("bytes")),
        status=_string_or_none(metadata.get("status"))
        or _string_or_none(file_obj.get("status"))
        or "processed",
        created_at=_int_or_none(file_obj.get("created_at")),
        content_kind=_infer_openai_content_kind(
            {"filename": filename, "purpose": purpose}
        ),
        download_path=content_path,
        content_path=content_path,
        delete_path=f"/v1/files/{file_id}" if file_id else None,
        raw=raw,
    )


def normalize_gemini_file(
    file_obj: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> NormalizedFileRecord:
    """Normalize a Gemini file resource backed by the files feature."""
    metadata = dict(metadata or {})
    file_id = str(file_obj.get("id") or "").strip()
    filename = (
        _string_or_none(metadata.get("display_name"))
        or _string_or_none(metadata.get("filename"))
        or _string_or_none(file_obj.get("filename"))
        or file_id
        or "unknown"
    )
    raw = deepcopy(file_obj)
    if metadata:
        raw["metadata"] = deepcopy(metadata)
    return NormalizedFileRecord(
        id=file_id,
        api_format=NormalizedArtifactFormat.GEMINI,
        filename=filename,
        purpose=_string_or_none(file_obj.get("purpose")),
        bytes=_int_or_none(file_obj.get("bytes")),
        status=_string_or_none(metadata.get("status"))
        or _string_or_none(file_obj.get("status"))
        or "processed",
        created_at=_int_or_none(file_obj.get("created_at")),
        content_kind=_infer_gemini_content_kind(file_obj, metadata),
        download_path=_admin_file_content_path(file_id) if file_id else None,
        content_path=_admin_file_content_path(file_id) if file_id else None,
        delete_path=f"/v1beta/files/{file_id}" if file_id else None,
        raw=raw,
    )


def normalize_gemini_batch(
    batch: Any,
    metadata: dict[str, Any] | None = None,
) -> NormalizedBatchRecord:
    """Normalize a Gemini batch record."""
    batch_id = _batch_id(batch)
    metadata = dict(metadata or {})
    output_file_id = _string_or_none(getattr(batch, "output_file_id", None))
    return NormalizedBatchRecord(
        id=batch_id,
        api_format=NormalizedArtifactFormat.GEMINI,
        endpoint=_string_or_none(metadata.get("endpoint")) or "/v1/chat/completions",
        status=_canonical_batch_status(getattr(batch, "status", None)),
        created_at=_int_or_none(getattr(batch, "created_at", None)),
        input_file_id=_string_or_none(metadata.get("input_file_id")),
        output_file_id=output_file_id,
        output_kind="file" if output_file_id else None,
        output_path=_admin_batch_output_path(batch_id)
        if batch_id and output_file_id
        else None,
        request_counts=_normalize_gemini_request_counts(batch, metadata),
        model=_string_or_none(metadata.get("model")),
        display_name=_string_or_none(metadata.get("display_name")) or batch_id or None,
        raw=_build_batch_raw(batch, metadata),
    )


def normalize_anthropic_output_file(
    file_obj: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    batch_id: str | None = None,
    batch_metadata: dict[str, Any] | None = None,
) -> NormalizedFileRecord:
    """Normalize an Anthropic batch results artifact exposed through local stores."""
    metadata = dict(metadata or {})
    file_id = str(file_obj.get("id") or "").strip()
    resolved_batch_id = _string_or_none(batch_id) or _string_or_none(
        metadata.get("batch_id")
    )
    filename = (
        _string_or_none(metadata.get("filename"))
        or (
            f"anthropic-results-{resolved_batch_id}.jsonl"
            if resolved_batch_id
            else None
        )
        or _string_or_none(file_obj.get("filename"))
        or file_id
        or "unknown"
    )
    content_path = _admin_file_content_path(file_id) if file_id else None
    raw = deepcopy(file_obj)
    if metadata:
        raw["metadata"] = deepcopy(metadata)
    if batch_metadata:
        raw["batch_metadata"] = deepcopy(batch_metadata)
    return NormalizedFileRecord(
        id=file_id,
        api_format=NormalizedArtifactFormat.ANTHROPIC,
        filename=filename,
        purpose=_string_or_none(file_obj.get("purpose")) or "batch_output",
        bytes=_int_or_none(file_obj.get("bytes")),
        status=_string_or_none(metadata.get("status"))
        or _string_or_none(file_obj.get("status"))
        or "processed",
        created_at=_int_or_none(file_obj.get("created_at")),
        content_kind="batch_results",
        download_path=content_path,
        content_path=content_path,
        delete_path=None,
        raw=raw,
    )


def _openai_file_content_path(file_id: str | None) -> str | None:
    normalized_file_id = _string_or_none(file_id)
    if normalized_file_id is None:
        return None
    return f"/v1/files/{normalized_file_id}/content"


def _admin_file_content_path(file_id: str | None) -> str | None:
    normalized_file_id = _string_or_none(file_id)
    if normalized_file_id is None:
        return None
    return f"/admin/api/files-batches/files/{normalized_file_id}/content"


def _admin_batch_output_path(batch_id: str | None) -> str | None:
    normalized_batch_id = _string_or_none(batch_id)
    if normalized_batch_id is None:
        return None
    return f"/admin/api/files-batches/batches/{normalized_batch_id}/output"


def _infer_openai_content_kind(file_obj: dict[str, Any]) -> str:
    purpose = _string_or_none(file_obj.get("purpose")) or ""
    if purpose == "batch_output":
        return "batch_output"
    if str(file_obj.get("filename") or "").lower().endswith(".jsonl"):
        return "jsonl"
    return "file"


def _infer_gemini_content_kind(
    file_obj: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    purpose = _string_or_none(file_obj.get("purpose")) or ""
    if purpose == "batch_output":
        return "batch_output"
    mime_type = _string_or_none(metadata.get("mime_type")) or ""
    if mime_type == "application/json":
        return "jsonl"
    if str(file_obj.get("filename") or "").lower().endswith(".jsonl"):
        return "jsonl"
    return "file"


def _normalize_request_counts(value: Any) -> NormalizedBatchRequestCounts:
    if isinstance(value, dict):
        payload = dict(value)
    elif hasattr(value, "model_dump"):
        payload = value.model_dump()
    else:
        payload = {}
    total = _int_or_none(payload.get("total"))
    completed = _int_or_none(payload.get("completed"))
    failed = _int_or_none(payload.get("failed"))
    processing = _int_or_none(payload.get("processing"))
    pending = _int_or_none(payload.get("pending"))
    return NormalizedBatchRequestCounts(
        total=total,
        completed=completed,
        failed=failed,
        succeeded=_int_or_none(payload.get("succeeded")) or completed,
        errored=_int_or_none(payload.get("errored")) or failed,
        processing=processing,
        pending=pending if pending is not None else processing,
        cancelled=_int_or_none(payload.get("cancelled"))
        or _int_or_none(payload.get("canceled")),
        expired=_int_or_none(payload.get("expired")),
    )


def _normalize_anthropic_request_counts(
    batch: Any,
    metadata: dict[str, Any],
) -> NormalizedBatchRequestCounts:
    request_counts = getattr(batch, "request_counts", None)
    dumped = (
        request_counts.model_dump() if hasattr(request_counts, "model_dump") else {}
    )
    total = _int_or_none(dumped.get("total"))
    if total is None:
        total = len(metadata.get("requests", []))
    failed = _int_or_none(dumped.get("failed")) or 0
    completed = _int_or_none(dumped.get("completed"))
    status = _canonical_batch_status(getattr(batch, "status", None))
    if status == "completed":
        succeeded = (
            completed if completed is not None else max(int(total or 0) - failed, 0)
        )
        processing = max(int(total or 0) - succeeded - failed, 0)
    else:
        succeeded = 0
        processing = int(total or 0)
    return NormalizedBatchRequestCounts(
        total=total,
        completed=completed,
        failed=failed,
        succeeded=succeeded,
        errored=failed,
        processing=processing,
        pending=processing,
        cancelled=0,
        expired=0,
    )


def _normalize_gemini_request_counts(
    batch: Any,
    metadata: dict[str, Any],
) -> NormalizedBatchRequestCounts:
    request_counts = getattr(batch, "request_counts", None)
    dumped = (
        request_counts.model_dump() if hasattr(request_counts, "model_dump") else {}
    )
    total = _int_or_none(dumped.get("total"))
    if total is None:
        total = len(metadata.get("requests", []))
    completed = _int_or_none(dumped.get("completed")) or 0
    failed = _int_or_none(dumped.get("failed")) or 0
    pending = max(int(total or 0) - completed - failed, 0)
    return NormalizedBatchRequestCounts(
        total=total,
        completed=completed,
        failed=failed,
        succeeded=completed,
        errored=failed,
        processing=pending,
        pending=pending,
        cancelled=0,
        expired=0,
    )


def _canonical_batch_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"created", "queued"}:
        return "queued"
    if normalized == "in_progress":
        return "in_progress"
    if normalized in _FAILED_BATCH_STATUSES:
        return normalized
    if normalized == "completed":
        return "completed"
    return "in_progress"


def _build_batch_raw(batch: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "batch": {
            "id": _batch_id(batch),
            "status": _string_or_none(getattr(batch, "status", None)),
            "created_at": _int_or_none(getattr(batch, "created_at", None)),
            "updated_at": _int_or_none(getattr(batch, "updated_at", None)),
            "output_file_id": _string_or_none(getattr(batch, "output_file_id", None)),
        },
        "metadata": deepcopy(metadata),
    }
    request_counts = getattr(batch, "request_counts", None)
    if hasattr(request_counts, "model_dump"):
        raw["batch"]["request_counts"] = request_counts.model_dump()
    return raw


def _batch_id(batch: Any) -> str:
    return _string_or_none(getattr(batch, "id_", None)) or ""


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
