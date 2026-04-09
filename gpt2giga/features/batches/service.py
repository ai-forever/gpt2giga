"""Batches feature orchestration."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import HTTPException

from gpt2giga.app.dependencies import (
    get_config_from_state,
    get_request_transformer_from_state,
    get_runtime_services,
    set_runtime_service,
)
from gpt2giga.features.batches.contracts import (
    BatchCreateData,
    BatchMetadata,
    BatchRecord,
    BatchResponseData,
    BatchesMetadataStore,
    BatchesUpstreamClient,
    FilesMetadataStore,
)
from gpt2giga.protocol.batches import (
    build_openai_batch_object,
    get_batch_target,
    transform_batch_input_file,
)


class BatchesService:
    """Coordinate the internal batches flow."""

    def __init__(self, request_transformer: Any, *, embeddings_model: str):
        self.request_transformer = request_transformer
        self.embeddings_model = embeddings_model

    async def create_batch(
        self,
        data: BatchCreateData,
        *,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
    ) -> BatchResponseData:
        """Create an OpenAI-compatible batch from an uploaded input file."""
        completion_window = data.get("completion_window", "24h")
        if completion_window is None:
            completion_window = "24h"
        if completion_window != "24h":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": 'Only `completion_window="24h"` is supported.',
                        "type": "invalid_request_error",
                        "param": "completion_window",
                        "code": None,
                    }
                },
            )

        input_file_id = data.get("input_file_id")
        if not input_file_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": "`input_file_id` is required.",
                        "type": "invalid_request_error",
                        "param": "input_file_id",
                        "code": None,
                    }
                },
            )

        file_content = await giga_client.aget_file_content(file_id=input_file_id)
        record = await self.create_batch_from_content(
            base64.b64decode(file_content.content),
            endpoint=str(data.get("endpoint", "")),
            completion_window=completion_window,
            metadata={
                "input_file_id": input_file_id,
                "metadata": data.get("metadata"),
            },
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
        )
        return build_openai_batch_object(record["batch"], record["metadata"])

    async def create_batch_from_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        endpoint: str,
        completion_window: str,
        metadata: BatchMetadata | None = None,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
    ) -> BatchRecord:
        """Create a batch from already-normalized OpenAI-style JSONL rows."""
        raw_input = (
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
        ).encode("utf-8")
        return await self.create_batch_from_content(
            raw_input,
            endpoint=endpoint,
            completion_window=completion_window,
            metadata=metadata,
            giga_client=giga_client,
            batch_store=batch_store,
            file_store=file_store,
        )

    async def create_batch_from_content(
        self,
        content: bytes,
        *,
        endpoint: str,
        completion_window: str,
        metadata: BatchMetadata | None = None,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
    ) -> BatchRecord:
        """Create a batch from raw OpenAI JSONL input."""
        target = get_batch_target(endpoint)
        transformed_content = await transform_batch_input_file(
            content,
            target=target,
            request_transformer=self.request_transformer,
            giga_client=giga_client,
            embeddings_model=self.embeddings_model,
        )
        batch = await giga_client.acreate_batch(
            transformed_content,
            method=target.method,
        )
        stored_metadata: BatchMetadata = dict(metadata or {})
        stored_metadata["endpoint"] = target.endpoint
        stored_metadata["completion_window"] = completion_window
        stored_metadata["output_file_id"] = batch.output_file_id
        return self._sync_batch_record(
            batch,
            stored_metadata,
            batch_store=batch_store,
            file_store=file_store,
        )

    async def list_batches(
        self,
        *,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List OpenAI-compatible batches."""
        batches = await giga_client.aget_batches()
        data = []
        for batch in batches.batches:
            record = self._sync_batch_record(
                batch,
                self._build_openai_metadata(batch.id_, batch_store),
                batch_store=batch_store,
                file_store=file_store,
            )
            data.append(build_openai_batch_object(record["batch"], record["metadata"]))
        paged, has_more = _paginate_items(data, after, limit)
        return {"data": paged, "has_more": has_more, "object": "list"}

    async def retrieve_batch(
        self,
        batch_id: str,
        *,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
    ) -> BatchResponseData:
        """Return OpenAI-compatible batch metadata."""
        batches = await giga_client.aget_batches(batch_id=batch_id)
        if not batches.batches:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "message": f"Batch `{batch_id}` not found.",
                        "type": "not_found_error",
                        "param": "batch_id",
                        "code": None,
                    }
                },
            )
        record = self._sync_batch_record(
            batches.batches[0],
            self._build_openai_metadata(batch_id, batch_store),
            batch_store=batch_store,
            file_store=file_store,
        )
        return build_openai_batch_object(record["batch"], record["metadata"])

    async def list_anthropic_batches(
        self,
        *,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
    ) -> list[BatchRecord]:
        """List stored Anthropic message-batch records."""
        batches = await giga_client.aget_batches()
        data = []
        sorted_batches = sorted(
            batches.batches,
            key=lambda batch: getattr(batch, "created_at", 0),
            reverse=True,
        )
        for batch in sorted_batches:
            metadata = self._get_batch_metadata(batch.id_, batch_store)
            if not metadata or metadata.get("api_format") != "anthropic_messages":
                continue
            data.append(
                self._sync_batch_record(
                    batch,
                    metadata,
                    batch_store=batch_store,
                    file_store=file_store,
                )
            )
        return data

    async def get_anthropic_batch(
        self,
        batch_id: str,
        *,
        giga_client: BatchesUpstreamClient,
        batch_store: BatchesMetadataStore | None = None,
        file_store: FilesMetadataStore | None = None,
    ) -> BatchRecord | None:
        """Return a stored Anthropic message-batch record."""
        metadata = self._get_batch_metadata(batch_id, batch_store)
        if not metadata or metadata.get("api_format") != "anthropic_messages":
            return None

        batches = await giga_client.aget_batches(batch_id=batch_id)
        if not batches.batches:
            return None
        return self._sync_batch_record(
            batches.batches[0],
            metadata,
            batch_store=batch_store,
            file_store=file_store,
        )

    def _build_openai_metadata(
        self,
        batch_id: str,
        batch_store: BatchesMetadataStore | None,
    ) -> BatchMetadata:
        metadata: BatchMetadata = {
            "endpoint": "/v1/chat/completions",
            "input_file_id": "",
            "completion_window": "24h",
        }
        stored_metadata = self._get_batch_metadata(batch_id, batch_store)
        if stored_metadata:
            metadata.update(stored_metadata)
        return metadata

    def _get_batch_metadata(
        self,
        batch_id: str,
        batch_store: BatchesMetadataStore | None,
    ) -> BatchMetadata | None:
        if batch_store is None:
            return None
        metadata = batch_store.get(batch_id)
        if metadata is None:
            return None
        return dict(metadata)

    def _sync_batch_record(
        self,
        batch: Any,
        metadata: BatchMetadata,
        *,
        batch_store: BatchesMetadataStore | None,
        file_store: FilesMetadataStore | None,
    ) -> BatchRecord:
        normalized_metadata: BatchMetadata = dict(metadata)
        normalized_metadata["output_file_id"] = batch.output_file_id
        if batch_store is not None:
            batch_store[batch.id_] = normalized_metadata
        if file_store is not None and batch.output_file_id:
            file_store[batch.output_file_id] = {"purpose": "batch_output"}
        return {
            "batch": batch,
            "metadata": normalized_metadata,
        }


def get_batches_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped batches service, creating it lazily if needed."""
    services = get_runtime_services(state)
    service = services.batches
    if service is not None:
        return service

    request_transformer = get_request_transformer_from_state(state)
    config = get_config_from_state(state)
    service = BatchesService(
        request_transformer,
        embeddings_model=config.proxy_settings.embeddings,
    )
    return set_runtime_service(state, "batches", service)


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
