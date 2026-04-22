"""JSONL parsing helpers for batch validation."""

from __future__ import annotations

import json

from gpt2giga.features.batches._validation_common import (
    BatchRow,
    NumberedBatchRows,
    build_issue,
)
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationSeverity,
)


def parse_jsonl_with_diagnostics(
    content: bytes,
) -> tuple[list[BatchRow], list[BatchValidationIssue]]:
    """Parse JSONL content while collecting row-level diagnostics."""
    numbered_rows, issues = parse_numbered_jsonl_rows_with_diagnostics(content)
    return [row for _, row in numbered_rows], issues


def parse_numbered_jsonl_rows_with_diagnostics(
    content: bytes,
) -> tuple[NumberedBatchRows, list[BatchValidationIssue]]:
    """Parse JSONL content while preserving original line numbers."""
    rows: NumberedBatchRows = []
    issues: list[BatchValidationIssue] = []

    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(
            build_issue(
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
                build_issue(
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
                build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="invalid_json",
                    line=line_number,
                    column=exc.colno,
                    message=f"Invalid JSON: {exc.msg}.",
                    hint="Each non-empty line must be one complete JSON object.",
                    raw_excerpt=build_raw_excerpt(raw_line),
                )
            )
            continue

        if not isinstance(parsed, dict):
            issues.append(
                build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="row_not_object",
                    line=line_number,
                    message="Each JSONL line must be an object.",
                    hint="Wrap the row in an object like `{...}`.",
                    raw_excerpt=build_raw_excerpt(raw_line),
                )
            )
            continue

        rows.append((line_number, parsed))

    return rows, issues


def count_candidate_rows(content: bytes) -> int:
    """Count non-empty candidate rows in raw JSONL content."""
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        return 0
    return sum(1 for line in decoded.splitlines() if line.strip())


def build_raw_excerpt(raw_line: str, *, max_length: int = 160) -> str:
    """Return a clipped single-line excerpt for diagnostics."""
    excerpt = raw_line.strip()
    if len(excerpt) <= max_length:
        return excerpt
    return f"{excerpt[: max_length - 3]}..."
