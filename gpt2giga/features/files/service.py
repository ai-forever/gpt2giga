"""Files feature orchestration."""

from __future__ import annotations

import base64
from typing import Any

from gpt2giga.app.dependencies import get_runtime_services, set_runtime_service
from gpt2giga.features.batches.store import find_batch_metadata_by_output_file_id
from gpt2giga.features.files.contracts import (
    BatchResultProcessor,
    BatchesMetadataStore,
    FileMetadata,
    FileObjectData,
    FilesMetadataStore,
    FilesUpstreamClient,
    FileUploadData,
)
from gpt2giga.features.batches.transforms import (
    infer_openai_file_purpose,
    map_openai_file_purpose,
    transform_batch_output_file,
)


class FilesService:
    """Coordinate the internal files flow."""

    async def create_file(
        self,
        *,
        purpose: str,
        upload: FileUploadData,
        giga_client: FilesUpstreamClient,
        file_store: FilesMetadataStore | None = None,
    ) -> FileObjectData:
        """Upload a file and store its local metadata."""
        resolved_store = file_store if file_store is not None else {}
        uploaded = await giga_client.aupload_file(
            (
                upload["filename"],
                upload["content"],
                upload["content_type"],
            ),
            purpose=map_openai_file_purpose(purpose),
        )
        metadata: FileMetadata = {
            "purpose": purpose,
            "filename": upload["filename"],
            "status": "processed",
        }
        resolved_store[uploaded.id_] = metadata
        return _serialize_file_object(uploaded, metadata)

    async def list_files(
        self,
        *,
        giga_client: FilesUpstreamClient,
        file_store: FilesMetadataStore | None = None,
        after: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        """List uploaded files using OpenAI-compatible pagination and filtering."""
        resolved_store = file_store if file_store is not None else {}
        files = await giga_client.aget_files()
        data = [
            _serialize_file_object(file_obj, resolved_store.get(file_obj.id_))
            for file_obj in files.data
        ]
        if purpose:
            data = [item for item in data if item["purpose"] == purpose]
        if order == "desc":
            data = sorted(
                data,
                key=lambda item: item.get("created_at") or 0,
                reverse=True,
            )
        elif order == "asc":
            data = sorted(data, key=lambda item: item.get("created_at") or 0)
        paged, has_more = _paginate_items(data, after, limit)
        return {"data": paged, "has_more": has_more, "object": "list"}

    async def retrieve_file(
        self,
        file_id: str,
        *,
        giga_client: FilesUpstreamClient,
        file_store: FilesMetadataStore | None = None,
    ) -> FileObjectData:
        """Return file metadata."""
        resolved_store = file_store if file_store is not None else {}
        file_obj = await giga_client.aget_file(file=file_id)
        return _serialize_file_object(file_obj, resolved_store.get(file_id))

    async def delete_file(
        self,
        file_id: str,
        *,
        giga_client: FilesUpstreamClient,
        file_store: FilesMetadataStore | None = None,
    ) -> dict[str, Any]:
        """Delete a file and evict its local metadata."""
        deleted = await giga_client.adelete_file(file=file_id)
        if file_store is not None:
            file_store.pop(file_id, None)
        return {
            "id": deleted.id_,
            "deleted": deleted.deleted,
            "object": "file",
        }

    async def get_file_content(
        self,
        file_id: str,
        *,
        giga_client: FilesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
        response_processor: BatchResultProcessor | None = None,
    ) -> bytes:
        """Load file content and post-process batch outputs when needed."""
        file_response = await giga_client.aget_file_content(file_id=file_id)
        matching_batch = _resolve_batch_output_metadata(
            file_id,
            batch_store=batch_store,
            file_store=file_store,
        )
        if matching_batch is not None and response_processor is not None:
            input_file = await giga_client.aget_file_content(
                file_id=matching_batch["input_file_id"]
            )
            return await transform_batch_output_file(
                file_response.content,
                batch_metadata=matching_batch,
                input_content_b64=input_file.content,
                response_processor=response_processor,
            )

        return base64.b64decode(file_response.content)


def get_files_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped files service, creating it lazily if needed."""
    services = get_runtime_services(state)
    service = services.files
    if service is not None:
        return service

    service = FilesService()
    return set_runtime_service(state, "files", service)


def _serialize_file_object(
    file_obj: Any,
    stored_metadata: FileMetadata | None = None,
) -> FileObjectData:
    """Normalize a GigaChat file object into the OpenAI-compatible response shape."""
    stored_metadata = stored_metadata or {}
    purpose = infer_openai_file_purpose(
        getattr(file_obj, "purpose", None),
        stored_metadata.get("purpose"),
    )
    return {
        "id": getattr(file_obj, "id_", ""),
        "object": "file",
        "bytes": getattr(file_obj, "bytes_", 0),
        "created_at": getattr(file_obj, "created_at", None),
        "filename": getattr(file_obj, "filename", ""),
        "purpose": purpose,
        "status": stored_metadata.get("status", "processed"),
        "expires_at": stored_metadata.get("expires_at"),
        "status_details": stored_metadata.get("status_details"),
    }


def _resolve_batch_output_metadata(
    file_id: str,
    *,
    batch_store: BatchesMetadataStore | None,
    file_store: FilesMetadataStore | None,
) -> dict[str, Any] | None:
    """Resolve batch transform hints for an output file."""
    matching_batch = (
        find_batch_metadata_by_output_file_id(batch_store, file_id)
        if batch_store is not None
        else None
    )
    stored_file_metadata = (
        dict(file_store.get(file_id, {})) if file_store is not None else {}
    )

    input_file_id = str(
        (matching_batch or {}).get("input_file_id")
        or stored_file_metadata.get("batch_input_file_id")
        or ""
    ).strip()
    endpoint = str(
        (matching_batch or {}).get("endpoint")
        or stored_file_metadata.get("batch_endpoint")
        or ""
    ).strip()
    if not input_file_id or not endpoint:
        return None

    resolved_metadata = dict(matching_batch or {})
    resolved_metadata["input_file_id"] = input_file_id
    resolved_metadata["endpoint"] = endpoint
    resolved_metadata["output_file_id"] = file_id
    batch_id = str(stored_file_metadata.get("batch_id") or "").strip()
    if batch_id and "id" not in resolved_metadata:
        resolved_metadata["id"] = batch_id
    return resolved_metadata


def _paginate_items(
    items: list[dict[str, Any]],
    after: str | None,
    limit: int | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Apply simple cursor pagination."""
    if after:
        for index, item in enumerate(items):
            if item.get("id") == after:
                items = items[index + 1 :]
                break
    if limit is None:
        return items, False
    return items[:limit], len(items) > limit
