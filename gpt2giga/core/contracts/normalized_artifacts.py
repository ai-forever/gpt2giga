"""Canonical artifact contracts shared across provider adapters."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NormalizedArtifactFormat(str, Enum):
    """Supported canonical API formats for files and batches."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class NormalizedFileRef(BaseModel):
    """Canonical reference to a file-like artifact."""

    model_config = ConfigDict(extra="forbid")

    id: str
    api_format: NormalizedArtifactFormat
    filename: str | None = None
    content_kind: str | None = None
    content_path: str | None = None
    download_path: str | None = None


class NormalizedFileRecord(BaseModel):
    """Canonical file metadata used by the admin inventory."""

    model_config = ConfigDict(extra="forbid")

    id: str
    api_format: NormalizedArtifactFormat
    filename: str
    purpose: str | None = None
    bytes: int | None = None
    status: str | None = None
    created_at: int | None = None
    content_kind: str | None = None
    download_path: str | None = None
    content_path: str | None = None
    delete_path: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedBatchRequestCounts(BaseModel):
    """Unified request counters across provider batch formats."""

    model_config = ConfigDict(extra="forbid")

    total: int | None = None
    completed: int | None = None
    failed: int | None = None
    succeeded: int | None = None
    errored: int | None = None
    processing: int | None = None
    pending: int | None = None
    cancelled: int | None = None
    expired: int | None = None


class NormalizedBatchRecord(BaseModel):
    """Canonical batch metadata for the admin inventory and inspector."""

    model_config = ConfigDict(extra="forbid")

    id: str
    api_format: NormalizedArtifactFormat
    endpoint: str | None = None
    status: str
    created_at: int | None = None
    input_file_id: str | None = None
    output_file_id: str | None = None
    output_kind: Literal["file", "results"] | None = None
    output_path: str | None = None
    request_counts: NormalizedBatchRequestCounts = Field(
        default_factory=NormalizedBatchRequestCounts
    )
    model: str | None = None
    display_name: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedArtifactsInventoryCounts(BaseModel):
    """Summary counters for the normalized inventory response."""

    model_config = ConfigDict(extra="forbid")

    files: int = 0
    batches: int = 0
    output_ready: int = 0
    needs_attention: int = 0


class NormalizedArtifactsInventory(BaseModel):
    """Normalized files and batches inventory returned to the admin UI."""

    model_config = ConfigDict(extra="forbid")

    files: list[NormalizedFileRecord] = Field(default_factory=list)
    batches: list[NormalizedBatchRecord] = Field(default_factory=list)
    counts: NormalizedArtifactsInventoryCounts = Field(
        default_factory=NormalizedArtifactsInventoryCounts
    )
