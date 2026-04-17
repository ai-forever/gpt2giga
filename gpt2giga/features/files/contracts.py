"""Internal contracts for the files feature."""

from __future__ import annotations

from typing import Any, MutableMapping, Protocol, TypeAlias, TypedDict

FileUploadData: TypeAlias = dict[str, Any]
FileObjectData: TypeAlias = dict[str, Any]
FilesMetadataStore: TypeAlias = MutableMapping[str, "FileMetadata"]
BatchesMetadataStore: TypeAlias = MutableMapping[str, dict[str, Any]]


class FileMetadata(TypedDict, total=False):
    """In-memory metadata tracked for an uploaded file."""

    purpose: str
    filename: str
    status: str
    expires_at: int | None
    status_details: Any
    batch_id: str
    batch_endpoint: str
    batch_input_file_id: str


class FilesUpstreamClient(Protocol):
    """Minimal upstream client surface required by the files feature."""

    async def aupload_file(
        self,
        file: tuple[str | None, bytes, str],
        purpose: str,
    ) -> Any:
        """Upload a file to the provider."""

    async def aget_files(self) -> Any:
        """List provider files."""

    async def aget_file(self, file: str) -> Any:
        """Retrieve provider file metadata."""

    async def adelete_file(self, file: str) -> Any:
        """Delete a provider file."""

    async def aget_file_content(self, file_id: str) -> Any:
        """Return provider file contents as a base64 payload."""


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
