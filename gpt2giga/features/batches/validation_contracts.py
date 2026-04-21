"""Canonical contracts for batch input validation diagnostics."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from gpt2giga.core.contracts import NormalizedArtifactFormat


class BatchValidationSeverity(str, Enum):
    """Supported validation issue severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class BatchValidationIssue(BaseModel):
    """One validation issue tied to a row, field, or file-level condition."""

    model_config = ConfigDict(extra="forbid")

    severity: BatchValidationSeverity
    code: str
    message: str
    hint: str | None = None
    line: int | None = None
    column: int | None = None
    field: str | None = None
    raw_excerpt: str | None = None


class BatchValidationSummary(BaseModel):
    """Aggregated counters for one validation run."""

    model_config = ConfigDict(extra="forbid")

    total_rows: int = 0
    error_count: int = 0
    warning_count: int = 0


class BatchValidationReport(BaseModel):
    """Stable validation payload returned by the batch validation flow."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    api_format: NormalizedArtifactFormat
    detected_format: NormalizedArtifactFormat | None = None
    summary: BatchValidationSummary = Field(default_factory=BatchValidationSummary)
    issues: list[BatchValidationIssue] = Field(default_factory=list)
