"""Files and batches normalization service."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from fastapi import HTTPException

from gpt2giga.api.gemini.request import normalize_model_name
from gpt2giga.api.gemini.batches import _build_batch_rows
from gpt2giga.app.dependencies import get_runtime_services, set_runtime_service
from gpt2giga.core.contracts import (
    NormalizedArtifactFormat,
    NormalizedArtifactsInventory,
    NormalizedArtifactsInventoryCounts,
    NormalizedBatchRecord,
    NormalizedFileRecord,
)
from gpt2giga.features.batches.transforms import build_openai_batch_object
from gpt2giga.features.batches.transforms import parse_jsonl
from gpt2giga.features.files_batches.contracts import normalize_api_format
from gpt2giga.features.files_batches.normalizers import (
    normalize_anthropic_file,
    normalize_anthropic_batch,
    normalize_gemini_batch,
    normalize_gemini_file,
    normalize_openai_batch,
    normalize_openai_file,
)
from gpt2giga.providers.anthropic import anthropic_provider_adapters

_NEEDS_ATTENTION_STATUSES = {"failed", "cancelled", "expired"}


class FilesBatchesService:
    """Build a normalized mixed-provider inventory for the admin UI."""

    async def create_file(
        self,
        *,
        api_format: str,
        purpose: str,
        upload: dict[str, Any],
        giga_client: Any,
        files_service: Any,
        file_store: Any | None = None,
        display_name: str | None = None,
    ) -> NormalizedFileRecord:
        """Create a normalized staged file for the admin UI."""
        normalized_api_format = normalize_api_format(api_format)
        resolved_purpose = _require_non_empty(
            purpose,
            field_name="purpose",
            message="`purpose` is required for file uploads.",
        )
        created = await files_service.create_file(
            purpose=resolved_purpose,
            upload=upload,
            giga_client=giga_client,
            file_store=file_store,
        )
        created_file_id = str(created.get("id") or "").strip()
        file_metadata = dict(file_store.get(created_file_id, {})) if file_store else {}
        file_metadata.update(
            _build_uploaded_file_metadata(
                api_format=normalized_api_format,
                purpose=resolved_purpose,
                upload=upload,
                display_name=display_name,
            )
        )
        if file_store is not None and created_file_id:
            file_store[created_file_id] = file_metadata
        return _normalize_file_record(
            created,
            file_metadata=file_metadata,
            batch_id=None,
            batch_metadata=None,
        )

    async def create_batch(
        self,
        *,
        api_format: str,
        input_file_id: str | None = None,
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
        display_name: str | None = None,
        model: str | None = None,
        requests: list[dict[str, Any]] | None = None,
        giga_client: Any,
        batches_service: Any,
        logger: Any = None,
        file_store: Any | None = None,
        batch_store: Any | None = None,
    ) -> NormalizedBatchRecord:
        """Create a normalized batch through the provider-aware admin surface."""
        normalized_api_format = normalize_api_format(api_format)
        print(normalized_api_format)
        if normalized_api_format is NormalizedArtifactFormat.ANTHROPIC:
            record = await self._create_anthropic_batch(
                input_file_id=input_file_id,
                metadata=metadata,
                display_name=display_name,
                model=model,
                requests=requests,
                giga_client=giga_client,
                batches_service=batches_service,
                logger=logger,
                file_store=file_store,
                batch_store=batch_store,
            )
        elif normalized_api_format is NormalizedArtifactFormat.GEMINI:
            record = await self._create_gemini_batch(
                input_file_id=input_file_id,
                metadata=metadata,
                display_name=display_name,
                model=model,
                requests=requests,
                giga_client=giga_client,
                batches_service=batches_service,
                logger=logger,
                file_store=file_store,
                batch_store=batch_store,
            )
        else:
            record = await self._create_openai_batch(
                input_file_id=input_file_id,
                endpoint=endpoint,
                metadata=metadata,
                requests=requests,
                giga_client=giga_client,
                batches_service=batches_service,
                file_store=file_store,
                batch_store=batch_store,
            )
        return _normalize_batch_record(record)

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

    async def _create_openai_batch(
        self,
        *,
        input_file_id: str | None,
        endpoint: str | None,
        metadata: dict[str, Any] | None,
        requests: list[dict[str, Any]] | None,
        giga_client: Any,
        batches_service: Any,
        file_store: Any | None,
        batch_store: Any | None,
    ) -> dict[str, Any]:
        normalized_endpoint = _normalize_openai_endpoint(endpoint)
        if requests:
            stored_metadata: dict[str, Any] = {
                "metadata": dict(metadata or {}),
            }
            resolved_input_file_id = _string_or_none(input_file_id)
            if resolved_input_file_id:
                stored_metadata["input_file_id"] = resolved_input_file_id
            return await batches_service.create_batch_from_rows(
                list(requests),
                endpoint=normalized_endpoint,
                completion_window="24h",
                metadata=stored_metadata,
                giga_client=giga_client,
                batch_store=batch_store,
                file_store=file_store,
            )

        resolved_input_file_id = _require_non_empty(
            input_file_id,
            field_name="input_file_id",
            message="`input_file_id` or `requests` is required for OpenAI batches.",
        )
        content = await _load_file_bytes(
            giga_client,
            file_id=resolved_input_file_id,
        )
        return await batches_service.create_batch_from_content(
            content,
            endpoint=normalized_endpoint,
            completion_window="24h",
            metadata={
                "input_file_id": resolved_input_file_id,
                "metadata": dict(metadata or {}),
            },
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
        )

    async def _create_anthropic_batch(
        self,
        *,
        input_file_id: str | None,
        metadata: dict[str, Any] | None,
        display_name: str | None,
        model: str | None,
        requests: list[dict[str, Any]] | None,
        giga_client: Any,
        batches_service: Any,
        logger: Any,
        file_store: Any | None,
        batch_store: Any | None,
    ) -> dict[str, Any]:
        resolved_input_file_id = _string_or_none(input_file_id)
        requests_payload: list[dict[str, Any]]
        if requests:
            requests_payload = list(requests)
        else:
            resolved_input_file_id = _require_non_empty(
                input_file_id,
                field_name="input_file_id",
                message=(
                    "`input_file_id` or `requests` is required for Anthropic batches."
                ),
            )
            requests_payload = parse_jsonl(
                await _load_file_bytes(
                    giga_client,
                    file_id=resolved_input_file_id,
                )
            )
        batch_payload = anthropic_provider_adapters.batches.build_create_payload(
            {
                "completion_window": "24h",
                "requests": requests_payload,
            },
            logger=logger,
        )
        stored_metadata: dict[str, Any] = {
            "api_format": "anthropic_messages",
            "requests": batch_payload.stored_requests,
        }
        if resolved_input_file_id:
            stored_metadata["input_file_id"] = resolved_input_file_id
        if metadata:
            stored_metadata["metadata"] = dict(metadata)
        if display_name:
            stored_metadata["display_name"] = display_name.strip()
        if model:
            stored_metadata["model"] = model.strip()
        return await batches_service.create_batch_from_rows(
            batch_payload.rows,
            endpoint="/v1/chat/completions",
            completion_window=batch_payload.completion_window,
            metadata=stored_metadata,
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
        )

    async def _create_gemini_batch(
        self,
        *,
        input_file_id: str | None,
        metadata: dict[str, Any] | None,
        display_name: str | None,
        model: str | None,
        requests: list[dict[str, Any]] | None,
        giga_client: Any,
        batches_service: Any,
        logger: Any,
        file_store: Any | None,
        batch_store: Any | None,
    ) -> dict[str, Any]:
        (
            requests_payload,
            resolved_input_file_id,
        ) = await _resolve_gemini_requests_payload(
            giga_client,
            input_file_id=input_file_id,
            requests=requests,
        )
        print("RESOLVE REQUESTS OK")
        resolved_model = _resolve_gemini_model(
            requests_payload,
            fallback_model=model,
        )
        print("RESOLVE MODEL OK")
        rows, stored_requests = _build_batch_rows(
            requests_payload,
            model=resolved_model,
            logger=logger,
        )
        print("BUILD BATCH ROWS OK")
        stored_metadata: dict[str, Any] = {
            "api_format": "gemini_generate_content",
            "display_name": _resolve_gemini_display_name(
                display_name,
                input_file_id=resolved_input_file_id,
            ),
            "model": resolved_model,
            "priority": 0,
            "requests": stored_requests,
        }
        if metadata:
            stored_metadata["metadata"] = dict(metadata)
        if resolved_input_file_id:
            stored_metadata["input_file_id"] = resolved_input_file_id
        print("HERE")
        return await batches_service.create_batch_from_rows(
            rows,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata=stored_metadata,
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
        )


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
        return normalize_anthropic_file(
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
    if file_metadata.get("api_format"):
        return normalize_api_format(file_metadata.get("api_format"))
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


def _require_non_empty(
    value: str | None,
    *,
    field_name: str,
    message: str,
) -> str:
    normalized = _string_or_none(value)
    if normalized is None:
        raise HTTPException(status_code=400, detail={field_name: message})
    return normalized


async def _load_file_bytes(
    giga_client: Any,
    *,
    file_id: str,
) -> bytes:
    file_response = await giga_client.aget_file_content(file_id=file_id)
    return base64.b64decode(file_response.content)


def _normalize_openai_endpoint(value: str | None) -> str:
    normalized = _string_or_none(value)
    if normalized is None:
        return "/v1/chat/completions"
    return normalized


def _build_uploaded_file_metadata(
    *,
    api_format: NormalizedArtifactFormat,
    purpose: str,
    upload: dict[str, Any],
    display_name: str | None,
) -> dict[str, Any]:
    metadata = {
        "api_format": api_format.value,
        "purpose": purpose,
        "filename": upload["filename"],
        "status": "processed",
    }
    if api_format is not NormalizedArtifactFormat.GEMINI:
        return metadata
    metadata.update(
        {
            "display_name": _string_or_none(display_name) or upload["filename"],
            "mime_type": upload["content_type"],
            "sha256_hash": base64.b64encode(
                hashlib.sha256(upload["content"]).digest()
            ).decode("ascii"),
            "source": "UPLOADED",
        }
    )
    return metadata


async def _resolve_gemini_requests_payload(
    giga_client: Any,
    *,
    input_file_id: str | None,
    requests: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str | None]:
    if requests:
        return list(requests), _string_or_none(input_file_id)
    resolved_input_file_id = _require_non_empty(
        input_file_id,
        field_name="input_file_id",
        message=("`input_file_id` or `requests` is required for Gemini batches."),
    )
    return (
        parse_jsonl(
            await _load_file_bytes(
                giga_client,
                file_id=resolved_input_file_id,
            )
        ),
        resolved_input_file_id,
    )


def _resolve_gemini_model(
    requests_payload: list[dict[str, Any]],
    *,
    fallback_model: str | None,
) -> str:
    normalized_fallback = normalize_model_name(_string_or_none(fallback_model))
    request_models = {
        normalize_model_name(
            str(
                request_item.get("request", {}).get("model")
                or request_item.get("model")
                or ""
            )
        )
        for request_item in requests_payload
        if isinstance(request_item, dict)
        and (
            (
                isinstance(request_item.get("request"), dict)
                and str(request_item.get("request", {}).get("model") or "").strip()
            )
            or str(request_item.get("model") or "").strip()
        )
    }
    if normalized_fallback:
        return normalized_fallback
    if len(request_models) == 1:
        return next(iter(request_models))
    if request_models:
        raise HTTPException(
            status_code=400,
            detail={
                "model": (
                    "`model` is required when Gemini batch rows mix multiple request models."
                )
            },
        )
    raise HTTPException(
        status_code=400,
        detail={
            "model": (
                "`model` is required for Gemini batches when request rows omit `request.model`."
            )
        },
    )


def _resolve_gemini_display_name(
    display_name: str | None,
    *,
    input_file_id: str | None,
) -> str:
    normalized_display_name = _string_or_none(display_name)
    if normalized_display_name is not None:
        return normalized_display_name
    normalized_input_file_id = _string_or_none(input_file_id)
    if normalized_input_file_id is not None:
        return f"Gemini batch for {normalized_input_file_id}"
    return "Gemini batch"
