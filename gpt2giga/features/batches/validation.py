"""Batch input validation helpers and diagnostic parsing primitives."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationReport,
    BatchValidationSeverity,
    BatchValidationSummary,
)


def validate_batch_input_bytes(
    content: bytes,
    *,
    api_format: str | NormalizedArtifactFormat,
) -> BatchValidationReport:
    """Validate raw JSONL bytes and return a structured diagnostic report."""
    rows, issues = parse_jsonl_with_diagnostics(content)
    if not rows and not issues:
        issues.append(
            _build_issue(
                severity=BatchValidationSeverity.ERROR,
                code="empty_file",
                message="The batch input file does not contain any JSONL rows.",
                hint="Add at least one JSON object per non-empty line.",
            )
        )

    normalized_api_format = _normalize_validation_api_format(api_format)
    detected_format = detect_batch_input_format(rows)
    issues.extend(
        _build_format_mismatch_issues(
            api_format=normalized_api_format,
            detected_format=detected_format,
        )
    )
    return _build_report(
        api_format=normalized_api_format,
        detected_format=detected_format,
        total_rows=_count_candidate_rows(content),
        issues=issues,
    )


def validate_batch_input_rows(
    rows: list[dict[str, Any]],
    *,
    api_format: str | NormalizedArtifactFormat,
) -> BatchValidationReport:
    """Validate pre-parsed JSON rows and return a structured report."""
    issues: list[BatchValidationIssue] = []
    if not rows:
        issues.append(
            _build_issue(
                severity=BatchValidationSeverity.ERROR,
                code="empty_rows",
                message="The batch request does not include any rows to validate.",
                hint="Provide at least one request row.",
            )
        )

    normalized_api_format = _normalize_validation_api_format(api_format)
    detected_format = detect_batch_input_format(rows)
    issues.extend(
        _build_format_mismatch_issues(
            api_format=normalized_api_format,
            detected_format=detected_format,
        )
    )
    return _build_report(
        api_format=normalized_api_format,
        detected_format=detected_format,
        total_rows=len(rows),
        issues=issues,
    )


def parse_jsonl_with_diagnostics(
    content: bytes,
) -> tuple[list[dict[str, Any]], list[BatchValidationIssue]]:
    """Parse JSONL content while collecting row-level diagnostics."""
    rows: list[dict[str, Any]] = []
    issues: list[BatchValidationIssue] = []

    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(
            _build_issue(
                severity=BatchValidationSeverity.ERROR,
                code="invalid_encoding",
                line=1,
                column=(exc.start or 0) + 1,
                message="Input file must be UTF-8 encoded JSONL.",
                hint="Re-save the file as UTF-8 without changing the JSONL structure.",
            )
        )
        return rows, issues

    for line_number, raw_line in enumerate(decoded.splitlines(), start=1):
        if not raw_line.strip():
            issues.append(
                _build_issue(
                    severity=BatchValidationSeverity.WARNING,
                    code="blank_line",
                    line=line_number,
                    message="Blank line ignored during validation.",
                    hint="Remove empty lines to keep row numbering stable.",
                )
            )
            continue

        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            issues.append(
                _build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="invalid_json",
                    line=line_number,
                    column=exc.colno,
                    message=f"Invalid JSON: {exc.msg}.",
                    hint="Each non-empty line must be one complete JSON object.",
                    raw_excerpt=_build_raw_excerpt(raw_line),
                )
            )
            continue

        if not isinstance(parsed, dict):
            issues.append(
                _build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="row_not_object",
                    line=line_number,
                    message="Each JSONL line must be an object.",
                    hint="Wrap the row in an object like `{...}`.",
                    raw_excerpt=_build_raw_excerpt(raw_line),
                )
            )
            continue

        rows.append(parsed)

    return rows, issues


def detect_batch_input_format(
    rows: Iterable[dict[str, Any]],
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


def _detect_row_format(
    row: dict[str, Any],
) -> NormalizedArtifactFormat | None:
    if not isinstance(row, dict):
        return None
    if isinstance(row.get("request"), dict):
        return NormalizedArtifactFormat.GEMINI
    if isinstance(row.get("params"), dict):
        return NormalizedArtifactFormat.ANTHROPIC
    if "url" in row or isinstance(row.get("body"), dict):
        return NormalizedArtifactFormat.OPENAI
    return None


def _normalize_validation_api_format(
    value: str | NormalizedArtifactFormat,
) -> NormalizedArtifactFormat:
    if isinstance(value, NormalizedArtifactFormat):
        return value

    normalized = str(value or "").strip().lower()
    if normalized in {"anthropic", "anthropic_messages"}:
        return NormalizedArtifactFormat.ANTHROPIC
    if normalized in {"gemini", "gemini_generate_content"}:
        return NormalizedArtifactFormat.GEMINI
    return NormalizedArtifactFormat.OPENAI


def _build_format_mismatch_issues(
    *,
    api_format: NormalizedArtifactFormat,
    detected_format: NormalizedArtifactFormat | None,
) -> list[BatchValidationIssue]:
    if detected_format is None or detected_format == api_format:
        return []
    return [
        _build_issue(
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


def _build_report(
    *,
    api_format: NormalizedArtifactFormat,
    detected_format: NormalizedArtifactFormat | None,
    total_rows: int,
    issues: list[BatchValidationIssue],
) -> BatchValidationReport:
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


def _count_candidate_rows(content: bytes) -> int:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        return 0
    return sum(1 for line in decoded.splitlines() if line.strip())


def _build_raw_excerpt(raw_line: str, *, max_length: int = 160) -> str:
    excerpt = raw_line.strip()
    if len(excerpt) <= max_length:
        return excerpt
    return f"{excerpt[: max_length - 3]}..."


def _build_issue(
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
