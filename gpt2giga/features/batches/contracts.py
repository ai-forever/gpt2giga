"""Internal contracts for the batches feature."""

from __future__ import annotations

from typing import Any, MutableMapping, Protocol, TypeAlias, TypedDict

BatchCreateData: TypeAlias = dict[str, Any]
BatchRowData: TypeAlias = dict[str, Any]
BatchResponseData: TypeAlias = dict[str, Any]
BatchesMetadataStore: TypeAlias = MutableMapping[str, "BatchMetadata"]
FilesMetadataStore: TypeAlias = MutableMapping[str, dict[str, Any]]


class BatchMetadata(TypedDict, total=False):
    """In-memory metadata tracked for a batch."""

    endpoint: str
    input_file_id: str
    completion_window: str
    metadata: Any
    output_file_id: str | None
    model: str
    api_format: str
    requests: list[dict[str, Any]]
    archived_at: str | None
    cancel_initiated_at: str | None


class BatchRecord(TypedDict):
    """Provider batch plus the local metadata tracked for it."""

    batch: Any
    metadata: BatchMetadata


class BatchesUpstreamClient(Protocol):
    """Minimal upstream client surface required by the batches feature."""

    async def aget_file_content(self, file_id: str) -> Any:
        """Return provider file contents as a base64 payload."""

    async def acreate_batch(self, file: bytes, method: str) -> Any:
        """Create a provider batch."""

    async def aget_batches(self, batch_id: str | None = None) -> Any:
        """List provider batches or return a single batch by ID."""
