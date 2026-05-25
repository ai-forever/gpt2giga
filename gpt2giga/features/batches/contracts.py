"""Internal contracts for the batches feature."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, MutableMapping, Protocol, TypeAlias, TypedDict

if TYPE_CHECKING:
    from gpt2giga.features.files.contracts import FileMetadata

BatchCreateData: TypeAlias = dict[str, Any]
BatchRowData: TypeAlias = dict[str, Any]
BatchResponseData: TypeAlias = dict[str, Any]
BatchesMetadataStore: TypeAlias = MutableMapping[str, "BatchMetadata"]
FilesMetadataStore: TypeAlias = MutableMapping[str, "FileMetadata"]


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


class BatchFilesResource(Protocol):
    """GigaChat files resource surface required by batches."""

    async def retrieve_content(self, file_id: str) -> Any:
        """Return provider file contents as a base64 payload."""


class BatchesResource(Protocol):
    """GigaChat batches resource surface."""

    async def create(self, file: bytes, method: str) -> Any:
        """Create a provider batch."""

    async def list(self) -> Any:
        """List provider batches."""

    async def retrieve(self, batch_id: str) -> Any:
        """Return a single batch by ID."""


class BatchesUpstreamClient(Protocol):
    """Minimal upstream client surface required by the batches feature."""

    a_files: BatchFilesResource
    a_batches: BatchesResource
