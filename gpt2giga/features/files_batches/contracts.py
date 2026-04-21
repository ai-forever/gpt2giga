"""Internal contracts for normalized files and batches inventory."""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

from gpt2giga.core.contracts import NormalizedArtifactFormat

ArtifactKind = Literal["file", "batch"]


class FilesBatchesInventoryFilters(TypedDict, total=False):
    """Optional filters supported by the normalized inventory service."""

    api_format: str
    kind: ArtifactKind
    query: str
    status: str
    endpoint: str
    purpose: str


class FilesServiceProtocol(Protocol):
    """Minimal files service surface required by the inventory feature."""

    async def list_files(
        self,
        *,
        giga_client: Any,
        file_store: Any | None = None,
        after: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        """List provider files."""

    async def retrieve_file(
        self,
        file_id: str,
        *,
        giga_client: Any,
        file_store: Any | None = None,
    ) -> dict[str, Any]:
        """Retrieve provider file metadata."""


class BatchesServiceProtocol(Protocol):
    """Minimal batches service surface required by the inventory feature."""

    async def list_batch_records(
        self,
        *,
        giga_client: Any,
        batch_store: Any | None = None,
        file_store: Any | None = None,
        default_metadata_factory: Any | None = None,
    ) -> list[dict[str, Any]]:
        """List provider batch records."""

    async def get_batch_record(
        self,
        batch_id: str,
        *,
        giga_client: Any,
        batch_store: Any | None = None,
        file_store: Any | None = None,
        default_metadata_factory: Any | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a provider batch record."""


def normalize_api_format(value: Any) -> NormalizedArtifactFormat:
    """Map feature-specific format tags into canonical format values."""
    normalized = str(value or "").strip().lower()
    if normalized == "anthropic_messages":
        return NormalizedArtifactFormat.ANTHROPIC
    if normalized == "gemini_generate_content":
        return NormalizedArtifactFormat.GEMINI
    if normalized == "anthropic":
        return NormalizedArtifactFormat.ANTHROPIC
    if normalized == "gemini":
        return NormalizedArtifactFormat.GEMINI
    return NormalizedArtifactFormat.OPENAI
