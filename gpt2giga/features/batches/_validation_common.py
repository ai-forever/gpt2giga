"""Shared helpers for batch validation diagnostics and reports."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationReport,
    BatchValidationSeverity,
    BatchValidationSummary,
)

BatchRow = dict[str, Any]
NumberedBatchRow = tuple[int, BatchRow]
NumberedBatchRows = list[NumberedBatchRow]


def build_report(
    *,
    api_format: NormalizedArtifactFormat,
    detected_format: NormalizedArtifactFormat | None,
    total_rows: int,
    issues: list[BatchValidationIssue],
) -> BatchValidationReport:
    """Construct a stable validation report from accumulated issues."""
    error_count = sum(
        1 for issue in issues if issue.severity is BatchValidationSeverity.ERROR
    )
    warning_count = sum(
        1 for issue in issues if issue.severity is BatchValidationSeverity.WARNING
    )
    return BatchValidationReport(
        valid=error_count == 0,
        api_format=api_format,
        detected_format=detected_format,
        summary=BatchValidationSummary(
            total_rows=total_rows,
            error_count=error_count,
            warning_count=warning_count,
        ),
        issues=issues,
    )


def contains_error(issues: list[BatchValidationIssue]) -> bool:
    """Return whether any accumulated issue is fatal."""
    return any(issue.severity is BatchValidationSeverity.ERROR for issue in issues)


def build_issue(
    *,
    severity: BatchValidationSeverity,
    code: str,
    message: str,
    hint: str | None = None,
    line: int | None = None,
    column: int | None = None,
    field: str | None = None,
    raw_excerpt: str | None = None,
) -> BatchValidationIssue:
    """Create a normalized validation issue payload."""
    return BatchValidationIssue(
        severity=severity,
        code=code,
        message=message,
        hint=hint,
        line=line,
        column=column,
        field=field,
        raw_excerpt=raw_excerpt,
    )


def extract_exception_message(exc: Exception) -> str:
    """Extract the most user-meaningful error detail from an exception."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    if isinstance(detail, str) and detail:
        return detail
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        return message
    return str(exc)
