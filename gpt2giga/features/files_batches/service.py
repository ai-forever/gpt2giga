"""Files and batches normalization service."""

from __future__ import annotations

from typing import Any

from gpt2giga.app.dependencies import get_runtime_services, set_runtime_service
from gpt2giga.core.contracts import (
    NormalizedArtifactFormat,
    NormalizedArtifactsInventory,
    NormalizedArtifactsInventoryCounts,
    NormalizedBatchRecord,
    NormalizedFileRecord,
)
from gpt2giga.features.batches.transforms import build_openai_batch_object
from gpt2giga.features.files_batches.contracts import normalize_api_format
from gpt2giga.features.files_batches.normalizers import (
    normalize_anthropic_batch,
    normalize_anthropic_output_file,
    normalize_gemini_batch,
    normalize_gemini_file,
    normalize_openai_batch,
    normalize_openai_file,
)

_NEEDS_ATTENTION_STATUSES = {"failed", "cancelled", "expired"}


class FilesBatchesService:
    """Build a normalized mixed-provider inventory for the admin UI."""

    async def list_inventory(
        self,
        *,
        giga_client: Any,
        files_service: Any,
        batches_service: Any,
        api_format: str | None = None,
        kind: str | None = None,
        query: str | None = None,
        status: str | None = None,
        endpoint: str | None = None,
        purpose: str | None = None,
        file_store: Any | None = None,
        batch_store: Any | None = None,
    ) -> NormalizedArtifactsInventory:
        """Return normalized files and batches with optional filtering."""
        normalized_kind = _normalize_kind(kind)
        files: list[NormalizedFileRecord] = []
        batches: list[NormalizedBatchRecord] = []

        if normalized_kind != "batch":
            listed_files = await files_service.list_files(
                giga_client=giga_client,
                file_store=file_store,
                order="desc",
            )
            files = self._normalize_files(
                listed_files.get("data", []),
                file_store=file_store,
                batch_store=batch_store,
            )

        if normalized_kind != "file":
            records = await batches_service.list_batch_records(
                giga_client=giga_client,
                batch_store=batch_store,
                file_store=file_store,
            )
            batches = self._normalize_batches(records)

        files = _filter_files(
            files,
            api_format=api_format,
            query=query,
            status=status,
            purpose=purpose,
        )
        batches = _filter_batches(
            batches,
            api_format=api_format,
            query=query,
            status=status,
            endpoint=endpoint,
        )
        files.sort(key=_file_sort_key, reverse=True)
        batches.sort(key=_batch_sort_key, reverse=True)
        return NormalizedArtifactsInventory(
            files=files,
            batches=batches,
            counts=_build_inventory_counts(files, batches),
        )

    async def retrieve_file(
        self,
        file_id: str,
        *,
        giga_client: Any,
        files_service: Any,
        file_store: Any | None = None,
        batch_store: Any | None = None,
    ) -> NormalizedFileRecord:
        """Retrieve a single normalized file record."""
        file_obj = await files_service.retrieve_file(
            file_id,
            giga_client=giga_client,
            file_store=file_store,
        )
        file_metadata = (
            dict(file_store.get(file_id, {})) if file_store is not None else {}
        )
        batch_id, batch_metadata = _resolve_file_batch_context(
            file_id,
            file_metadata=file_metadata,
            batch_store=batch_store,
        )
        return _normalize_file_record(
            file_obj,
            file_metadata=file_metadata,
            batch_id=batch_id,
            batch_metadata=batch_metadata,
        )

    async def retrieve_batch(
        self,
        batch_id: str,
        *,
        giga_client: Any,
        batches_service: Any,
        batch_store: Any | None = None,
        file_store: Any | None = None,
    ) -> NormalizedBatchRecord | None:
        """Retrieve a single normalized batch record."""
        record = await batches_service.get_batch_record(
            batch_id,
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
        )
        if record is None:
            return None
        return _normalize_batch_record(record)

    def _normalize_files(
        self,
        file_records: list[dict[str, Any]],
        *,
        file_store: Any | None,
        batch_store: Any | None,
    ) -> list[NormalizedFileRecord]:
        normalized: list[NormalizedFileRecord] = []
        for file_obj in file_records:
            file_id = str(file_obj.get("id") or "").strip()
            file_metadata = (
                dict(file_store.get(file_id, {})) if file_store is not None else {}
            )
            batch_id, batch_metadata = _resolve_file_batch_context(
                file_id,
                file_metadata=file_metadata,
                batch_store=batch_store,
            )
            normalized.append(
                _normalize_file_record(
                    file_obj,
                    file_metadata=file_metadata,
                    batch_id=batch_id,
                    batch_metadata=batch_metadata,
                )
            )
        return normalized

    def _normalize_batches(
        self,
        records: list[dict[str, Any]],
    ) -> list[NormalizedBatchRecord]:
        return [_normalize_batch_record(record) for record in records]


def get_files_batches_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped files/batches normalization service."""
    services = get_runtime_services(state)
    service = services.files_batches
    if service is not None:
        return service

    service = FilesBatchesService()
    return set_runtime_service(state, "files_batches", service)


def get_inventory_dependencies(state: Any) -> tuple[Any, Any, Any]:
    """Resolve the inventory service plus its file and batch dependencies."""
    services = get_runtime_services(state)
    return (
        get_files_batches_service_from_state(state),
        services.files,
        services.batches,
    )


def _normalize_file_record(
    file_obj: dict[str, Any],
    *,
    file_metadata: dict[str, Any],
    batch_id: str | None,
    batch_metadata: dict[str, Any] | None,
) -> NormalizedFileRecord:
    api_format = _resolve_file_api_format(
        file_metadata=file_metadata,
        batch_metadata=batch_metadata,
    )
    if api_format is NormalizedArtifactFormat.GEMINI:
        return normalize_gemini_file(file_obj, metadata=file_metadata)
    if api_format is NormalizedArtifactFormat.ANTHROPIC:
        return normalize_anthropic_output_file(
            file_obj,
            metadata=file_metadata,
            batch_id=batch_id,
            batch_metadata=batch_metadata,
        )
    return normalize_openai_file(file_obj)


def _normalize_batch_record(record: dict[str, Any]) -> NormalizedBatchRecord:
    batch = record["batch"]
    metadata = dict(record.get("metadata") or {})
    api_format = normalize_api_format(metadata.get("api_format"))
    if api_format is NormalizedArtifactFormat.ANTHROPIC:
        return normalize_anthropic_batch(batch, metadata)
    if api_format is NormalizedArtifactFormat.GEMINI:
        return normalize_gemini_batch(batch, metadata)
    return normalize_openai_batch(build_openai_batch_object(batch, metadata))


def _resolve_file_batch_context(
    file_id: str,
    *,
    file_metadata: dict[str, Any],
    batch_store: Any | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if batch_store is None:
        return _string_or_none(file_metadata.get("batch_id")), None
    batch_id = _string_or_none(file_metadata.get("batch_id"))
    if batch_id and batch_id in batch_store:
        return batch_id, dict(batch_store[batch_id])
    for stored_batch_id, metadata in batch_store.items():
        if metadata.get("output_file_id") == file_id:
            return str(stored_batch_id), dict(metadata)
    return batch_id, None


def _resolve_file_api_format(
    *,
    file_metadata: dict[str, Any],
    batch_metadata: dict[str, Any] | None,
) -> NormalizedArtifactFormat:
    if batch_metadata is not None:
        return normalize_api_format(batch_metadata.get("api_format"))
    if any(
        key in file_metadata
        for key in ("display_name", "mime_type", "source", "sha256_hash")
    ):
        return NormalizedArtifactFormat.GEMINI
    return NormalizedArtifactFormat.OPENAI


def _filter_files(
    records: list[NormalizedFileRecord],
    *,
    api_format: str | None,
    query: str | None,
    status: str | None,
    purpose: str | None,
) -> list[NormalizedFileRecord]:
    normalized_api_format = str(api_format or "").strip().lower()
    normalized_query = str(query or "").strip().casefold()
    normalized_status = str(status or "").strip().casefold()
    normalized_purpose = str(purpose or "").strip().casefold()
    filtered: list[NormalizedFileRecord] = []
    for record in records:
        if normalized_api_format and record.api_format.value != normalized_api_format:
            continue
        if (
            normalized_status
            and str(record.status or "").casefold() != normalized_status
        ):
            continue
        if (
            normalized_purpose
            and str(record.purpose or "").casefold() != normalized_purpose
        ):
            continue
        if normalized_query and normalized_query not in _file_search_blob(record):
            continue
        filtered.append(record)
    return filtered


def _filter_batches(
    records: list[NormalizedBatchRecord],
    *,
    api_format: str | None,
    query: str | None,
    status: str | None,
    endpoint: str | None,
) -> list[NormalizedBatchRecord]:
    normalized_api_format = str(api_format or "").strip().lower()
    normalized_query = str(query or "").strip().casefold()
    normalized_status = str(status or "").strip().casefold()
    normalized_endpoint = str(endpoint or "").strip().casefold()
    filtered: list[NormalizedBatchRecord] = []
    for record in records:
        if normalized_api_format and record.api_format.value != normalized_api_format:
            continue
        if (
            normalized_status
            and str(record.status or "").casefold() != normalized_status
        ):
            continue
        if (
            normalized_endpoint
            and str(record.endpoint or "").casefold() != normalized_endpoint
        ):
            continue
        if normalized_query and normalized_query not in _batch_search_blob(record):
            continue
        filtered.append(record)
    return filtered


def _build_inventory_counts(
    files: list[NormalizedFileRecord],
    batches: list[NormalizedBatchRecord],
) -> NormalizedArtifactsInventoryCounts:
    output_ready = sum(1 for record in batches if record.output_path)
    needs_attention = sum(1 for record in files if _file_needs_attention(record))
    needs_attention += sum(1 for record in batches if _batch_needs_attention(record))
    return NormalizedArtifactsInventoryCounts(
        files=len(files),
        batches=len(batches),
        output_ready=output_ready,
        needs_attention=needs_attention,
    )


def _file_needs_attention(record: NormalizedFileRecord) -> bool:
    return str(record.status or "").strip().lower() == "failed"


def _batch_needs_attention(record: NormalizedBatchRecord) -> bool:
    status = str(record.status or "").strip().lower()
    if status in _NEEDS_ATTENTION_STATUSES:
        return True
    counts = record.request_counts
    return bool((counts.failed or 0) > 0 or (counts.errored or 0) > 0)


def _file_search_blob(record: NormalizedFileRecord) -> str:
    return " ".join(
        part.casefold()
        for part in (
            record.id,
            record.filename,
            record.purpose or "",
            record.status or "",
            record.api_format.value,
        )
        if part
    )


def _batch_search_blob(record: NormalizedBatchRecord) -> str:
    return " ".join(
        part.casefold()
        for part in (
            record.id,
            record.endpoint or "",
            record.status or "",
            record.model or "",
            record.display_name or "",
            record.input_file_id or "",
            record.output_file_id or "",
            record.api_format.value,
        )
        if part
    )


def _file_sort_key(record: NormalizedFileRecord) -> tuple[int, str]:
    return (record.created_at or 0, record.id)


def _batch_sort_key(record: NormalizedBatchRecord) -> tuple[int, str]:
    return (record.created_at or 0, record.id)


def _normalize_kind(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"file", "batch"}:
        return normalized
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
