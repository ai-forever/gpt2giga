"""Internal contracts for the files feature."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, MutableMapping, Protocol, TypeAlias, TypedDict

if TYPE_CHECKING:
    from gpt2giga.features.batches.contracts import BatchMetadata

FileUploadData: TypeAlias = dict[str, Any]
FileObjectData: TypeAlias = dict[str, Any]
FilesMetadataStore: TypeAlias = MutableMapping[str, "FileMetadata"]
BatchesMetadataStore: TypeAlias = MutableMapping[str, "BatchMetadata"]


class FileMetadata(TypedDict, total=False):
    """In-memory metadata tracked for an uploaded file."""

    api_format: str
    purpose: str
    filename: str
    status: str
    expires_at: int | None
    status_details: Any
    batch_id: str
    batch_endpoint: str
    batch_input_file_id: str
    display_name: str
    mime_type: str
    source: str
    sha256_hash: str


class FilesResource(Protocol):
    """GigaChat files resource surface."""

    async def upload(
        self,
        file: tuple[str | None, bytes, str],
        purpose: str,
    ) -> Any:
        """Upload a file to the provider."""

    async def list(self) -> Any:
        """List provider files."""

    async def retrieve(self, file: str) -> Any:
        """Retrieve provider file metadata."""

    async def delete(self, file: str) -> Any:
        """Delete a provider file."""

    async def retrieve_content(self, file_id: str) -> Any:
        """Return provider file contents as a base64 payload."""


class FilesUpstreamClient(Protocol):
    """Minimal upstream client surface required by the files feature."""

    a_files: FilesResource


class BatchResultProcessor(Protocol):
    """Minimal response-processor surface used for batch output files."""

    def process_response(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Map a chat-completions batch result row."""

    def process_response_api(
        self,
        data: dict[str, Any],
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
    ) -> dict[str, Any]:
        """Map a Responses API batch result row."""
