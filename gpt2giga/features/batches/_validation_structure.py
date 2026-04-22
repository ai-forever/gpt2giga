"""Structural checks and format detection for batch validation."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches._validation_common import BatchRow, build_issue
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationSeverity,
)

GIGACHAT_BATCH_MAX_ROWS = 100


def detect_batch_input_format(
    rows: Iterable[BatchRow],
) -> NormalizedArtifactFormat | None:
    """Guess the likely provider format from row shapes."""
    counts = Counter(_detect_row_format(row) for row in rows)
    counts.pop(None, None)
    if not counts:
        return None

    ranked = counts.most_common(2)
    top_format, top_count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == top_count:
        return None
    return top_format


def normalize_validation_api_format(
    value: str | NormalizedArtifactFormat,
) -> NormalizedArtifactFormat:
    """Normalize API-format aliases used by validation endpoints."""
    if isinstance(value, NormalizedArtifactFormat):
        return value

    normalized = str(value or "").strip().lower()
    if normalized in {"anthropic", "anthropic_messages"}:
        return NormalizedArtifactFormat.ANTHROPIC
    if normalized in {"gemini", "gemini_generate_content"}:
        return NormalizedArtifactFormat.GEMINI
    return NormalizedArtifactFormat.OPENAI


def build_format_mismatch_issues(
    *,
    api_format: NormalizedArtifactFormat,
    detected_format: NormalizedArtifactFormat | None,
) -> list[BatchValidationIssue]:
    """Build warnings for obvious provider-shape mismatches."""
    if detected_format is None or detected_format == api_format:
        return []
    return [
        build_issue(
            severity=BatchValidationSeverity.WARNING,
            code="format_mismatch",
            message=(
                f"The file looks like `{detected_format.value}`, but "
                f"`{api_format.value}` was selected."
            ),
            hint=(
                f"Switch the selected format to `{detected_format.value}` or "
                f"reshape the rows for `{api_format.value}`."
            ),
        )
    ]


def build_row_limit_issues(total_rows: int) -> list[BatchValidationIssue]:
    """Build diagnostics for GigaChat backend row-count limits."""
    if total_rows <= GIGACHAT_BATCH_MAX_ROWS:
        return []
    return [
        build_issue(
            severity=BatchValidationSeverity.ERROR,
            code="row_limit_exceeded",
            message=(
                "GigaChat backend does not support more than "
                f"{GIGACHAT_BATCH_MAX_ROWS} batch rows."
            ),
            hint=(
                "Split the input into multiple batches with "
                f"{GIGACHAT_BATCH_MAX_ROWS} rows or fewer."
            ),
        )
    ]


def _detect_row_format(row: BatchRow) -> NormalizedArtifactFormat | None:
    if not isinstance(row, dict):
        return None
    if isinstance(row.get("request"), dict):
        return NormalizedArtifactFormat.GEMINI
    if isinstance(row.get("params"), dict):
        return NormalizedArtifactFormat.ANTHROPIC
    if "url" in row or isinstance(row.get("body"), dict):
        return NormalizedArtifactFormat.OPENAI
    return None
