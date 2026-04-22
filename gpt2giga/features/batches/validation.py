"""Batch input validation helpers and provider-aware diagnostics."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches._validation_common import (
    NumberedBatchRows,
    build_issue,
    build_report,
    contains_error,
)
from gpt2giga.features.batches._validation_parsing import (
    count_candidate_rows,
    parse_jsonl_with_diagnostics,
    parse_numbered_jsonl_rows_with_diagnostics,
)
from gpt2giga.features.batches._validation_providers import (
    AnthropicBatchValidator,
    GeminiBatchValidator,
    OpenAIBatchValidator,
)
from gpt2giga.features.batches._validation_structure import (
    GIGACHAT_BATCH_MAX_ROWS,
    build_format_mismatch_issues,
    build_row_limit_issues,
    detect_batch_input_format,
    normalize_validation_api_format,
)
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationReport,
    BatchValidationSeverity,
    BatchValidationSummary,
)

__all__ = [
    "GIGACHAT_BATCH_MAX_ROWS",
    "BatchValidationIssue",
    "BatchValidationReport",
    "BatchValidationSeverity",
    "BatchValidationSummary",
    "BatchInputValidator",
    "OpenAIBatchValidator",
    "AnthropicBatchValidator",
    "GeminiBatchValidator",
    "detect_batch_input_format",
    "parse_jsonl_with_diagnostics",
    "validate_batch_input_bytes",
    "validate_batch_input_rows",
]


def validate_batch_input_bytes(
    content: bytes,
    *,
    api_format: str | NormalizedArtifactFormat,
) -> BatchValidationReport:
    """Validate raw JSONL bytes and return a generic diagnostic report."""
    rows, issues = parse_jsonl_with_diagnostics(content)
    if not rows and not contains_error(issues):
        issues.append(
            build_issue(
                severity=BatchValidationSeverity.ERROR,
                code="empty_file",
                message="The batch input file does not contain any JSONL rows.",
                hint="Add at least one JSON object per non-empty line.",
            )
        )

    normalized_api_format = normalize_validation_api_format(api_format)
    detected_format = detect_batch_input_format(rows)
    total_rows = count_candidate_rows(content)
    issues.extend(
        build_format_mismatch_issues(
            api_format=normalized_api_format,
            detected_format=detected_format,
        )
    )
    issues.extend(build_row_limit_issues(total_rows))
    return build_report(
        api_format=normalized_api_format,
        detected_format=detected_format,
        total_rows=total_rows,
        issues=issues,
    )


def validate_batch_input_rows(
    rows: list[dict[str, Any]],
    *,
    api_format: str | NormalizedArtifactFormat,
) -> BatchValidationReport:
    """Validate pre-parsed JSON rows and return a generic report."""
    issues: list[BatchValidationIssue] = []
    if not rows:
        issues.append(
            build_issue(
                severity=BatchValidationSeverity.ERROR,
                code="empty_rows",
                message="The batch request does not include any rows to validate.",
                hint="Provide at least one request row.",
            )
        )

    normalized_api_format = normalize_validation_api_format(api_format)
    detected_format = detect_batch_input_format(rows)
    total_rows = len(rows)
    issues.extend(
        build_format_mismatch_issues(
            api_format=normalized_api_format,
            detected_format=detected_format,
        )
    )
    issues.extend(build_row_limit_issues(total_rows))
    return build_report(
        api_format=normalized_api_format,
        detected_format=detected_format,
        total_rows=total_rows,
        issues=issues,
    )


class BatchInputValidator:
    """Provider-aware async batch validator."""

    def __init__(
        self,
        *,
        request_transformer: Any | None = None,
        embeddings_model: str = "",
        gigachat_api_mode: str = "v1",
        logger: Any = None,
        default_model: str | None = None,
        gemini_fallback_model: str | None = None,
    ) -> None:
        self.request_transformer = request_transformer
        self.embeddings_model = embeddings_model
        self.gigachat_api_mode = gigachat_api_mode
        self.logger = logger
        self.default_model = default_model
        self.gemini_fallback_model = gemini_fallback_model

    async def validate_bytes(
        self,
        content: bytes,
        *,
        api_format: str | NormalizedArtifactFormat,
        fallback_model: str | None = None,
    ) -> BatchValidationReport:
        """Validate raw JSONL bytes with provider-specific checks."""
        numbered_rows, issues = parse_numbered_jsonl_rows_with_diagnostics(content)
        if not numbered_rows and not contains_error(issues):
            issues.append(
                build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="empty_file",
                    message="The batch input file does not contain any JSONL rows.",
                    hint="Add at least one JSON object per non-empty line.",
                )
            )

        normalized_api_format = normalize_validation_api_format(api_format)
        detected_format = detect_batch_input_format(row for _, row in numbered_rows)
        total_rows = count_candidate_rows(content)
        issues.extend(
            build_format_mismatch_issues(
                api_format=normalized_api_format,
                detected_format=detected_format,
            )
        )
        issues.extend(build_row_limit_issues(total_rows))
        issues.extend(
            await self._validate_numbered_rows(
                numbered_rows,
                api_format=normalized_api_format,
                fallback_model=fallback_model,
            )
        )
        return build_report(
            api_format=normalized_api_format,
            detected_format=detected_format,
            total_rows=total_rows,
            issues=issues,
        )

    async def validate_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        api_format: str | NormalizedArtifactFormat,
        fallback_model: str | None = None,
    ) -> BatchValidationReport:
        """Validate pre-parsed rows with provider-specific checks."""
        numbered_rows = list(enumerate(rows, start=1))
        issues: list[BatchValidationIssue] = []
        if not numbered_rows:
            issues.append(
                build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="empty_rows",
                    message="The batch request does not include any rows to validate.",
                    hint="Provide at least one request row.",
                )
            )

        normalized_api_format = normalize_validation_api_format(api_format)
        detected_format = detect_batch_input_format(row for _, row in numbered_rows)
        total_rows = len(numbered_rows)
        issues.extend(
            build_format_mismatch_issues(
                api_format=normalized_api_format,
                detected_format=detected_format,
            )
        )
        issues.extend(build_row_limit_issues(total_rows))
        issues.extend(
            await self._validate_numbered_rows(
                numbered_rows,
                api_format=normalized_api_format,
                fallback_model=fallback_model,
            )
        )
        return build_report(
            api_format=normalized_api_format,
            detected_format=detected_format,
            total_rows=total_rows,
            issues=issues,
        )

    async def _validate_numbered_rows(
        self,
        numbered_rows: NumberedBatchRows,
        *,
        api_format: NormalizedArtifactFormat,
        fallback_model: str | None,
    ) -> list[BatchValidationIssue]:
        if api_format is NormalizedArtifactFormat.ANTHROPIC:
            validator = AnthropicBatchValidator(logger=self.logger)
            return validator.validate(numbered_rows)
        if api_format is NormalizedArtifactFormat.GEMINI:
            validator = GeminiBatchValidator(
                logger=self.logger,
                fallback_model=fallback_model or self.gemini_fallback_model,
            )
            return validator.validate(numbered_rows)

        validator = OpenAIBatchValidator(
            request_transformer=self.request_transformer,
            embeddings_model=self.embeddings_model,
            gigachat_api_mode=self.gigachat_api_mode,
            default_model=self.default_model,
        )
        return await validator.validate(numbered_rows)
