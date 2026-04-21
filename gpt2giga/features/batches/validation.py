"""Batch input validation helpers and provider-aware diagnostics."""

from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace
from typing import Any, Iterable

from fastapi import HTTPException

from gpt2giga.api.anthropic.request_adapter import (
    build_normalized_chat_request as build_anthropic_chat_request,
)
from gpt2giga.api.gemini.request import GeminiAPIError, normalize_model_name
from gpt2giga.api.gemini.request_adapter import (
    build_normalized_chat_request as build_gemini_chat_request,
)
from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches.transforms import (
    get_batch_target,
    get_batch_warnings,
)
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationReport,
    BatchValidationSeverity,
    BatchValidationSummary,
)
from gpt2giga.providers.gigachat.embeddings_mapper import transform_embedding_body

GIGACHAT_BATCH_MAX_ROWS = 100


def validate_batch_input_bytes(
    content: bytes,
    *,
    api_format: str | NormalizedArtifactFormat,
) -> BatchValidationReport:
    """Validate raw JSONL bytes and return a generic diagnostic report."""
    rows, issues = parse_jsonl_with_diagnostics(content)
    if not rows and not _contains_error(issues):
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
    total_rows = _count_candidate_rows(content)
    issues.extend(
        _build_format_mismatch_issues(
            api_format=normalized_api_format,
            detected_format=detected_format,
        )
    )
    issues.extend(_build_row_limit_issues(total_rows))
    return _build_report(
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
            _build_issue(
                severity=BatchValidationSeverity.ERROR,
                code="empty_rows",
                message="The batch request does not include any rows to validate.",
                hint="Provide at least one request row.",
            )
        )

    normalized_api_format = _normalize_validation_api_format(api_format)
    detected_format = detect_batch_input_format(rows)
    total_rows = len(rows)
    issues.extend(
        _build_format_mismatch_issues(
            api_format=normalized_api_format,
            detected_format=detected_format,
        )
    )
    issues.extend(_build_row_limit_issues(total_rows))
    return _build_report(
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
        numbered_rows, issues = _parse_jsonl_rows_with_diagnostics(content)
        if not numbered_rows and not _contains_error(issues):
            issues.append(
                _build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="empty_file",
                    message="The batch input file does not contain any JSONL rows.",
                    hint="Add at least one JSON object per non-empty line.",
                )
            )

        normalized_api_format = _normalize_validation_api_format(api_format)
        detected_format = detect_batch_input_format(row for _, row in numbered_rows)
        total_rows = _count_candidate_rows(content)
        issues.extend(
            _build_format_mismatch_issues(
                api_format=normalized_api_format,
                detected_format=detected_format,
            )
        )
        issues.extend(_build_row_limit_issues(total_rows))
        issues.extend(
            await self._validate_numbered_rows(
                numbered_rows,
                api_format=normalized_api_format,
                fallback_model=fallback_model,
            )
        )
        return _build_report(
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
                _build_issue(
                    severity=BatchValidationSeverity.ERROR,
                    code="empty_rows",
                    message="The batch request does not include any rows to validate.",
                    hint="Provide at least one request row.",
                )
            )

        normalized_api_format = _normalize_validation_api_format(api_format)
        detected_format = detect_batch_input_format(row for _, row in numbered_rows)
        total_rows = len(numbered_rows)
        issues.extend(
            _build_format_mismatch_issues(
                api_format=normalized_api_format,
                detected_format=detected_format,
            )
        )
        issues.extend(_build_row_limit_issues(total_rows))
        issues.extend(
            await self._validate_numbered_rows(
                numbered_rows,
                api_format=normalized_api_format,
                fallback_model=fallback_model,
            )
        )
        return _build_report(
            api_format=normalized_api_format,
            detected_format=detected_format,
            total_rows=total_rows,
            issues=issues,
        )

    async def _validate_numbered_rows(
        self,
        numbered_rows: list[tuple[int, dict[str, Any]]],
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


class OpenAIBatchValidator:
    """Validate OpenAI-style batch input rows."""

    def __init__(
        self,
        *,
        request_transformer: Any | None,
        embeddings_model: str,
        gigachat_api_mode: str,
        default_model: str | None,
    ) -> None:
        self.request_transformer = request_transformer
        self.embeddings_model = embeddings_model
        self.gigachat_api_mode = gigachat_api_mode
        self.default_model = default_model

    async def validate(
        self, numbered_rows: list[tuple[int, dict[str, Any]]]
    ) -> list[BatchValidationIssue]:
        issues: list[BatchValidationIssue] = []
        seen_custom_ids: set[str] = set()
        selected_target = None
        emitted_chat_warning = False

        for line_number, row in numbered_rows:
            custom_id = row.get("custom_id")
            if custom_id is None:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.WARNING,
                        code="missing_identifier",
                        line=line_number,
                        field="custom_id",
                        message="`custom_id` is missing and will be auto-generated.",
                        hint="Provide a stable `custom_id` to make row-level debugging easier.",
                    )
                )
            elif not isinstance(custom_id, str) or not custom_id.strip():
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="invalid_field",
                        line=line_number,
                        field="custom_id",
                        message="Field `custom_id` must be a non-empty string when provided.",
                    )
                )
            elif custom_id in seen_custom_ids:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="duplicate_identifier",
                        line=line_number,
                        field="custom_id",
                        message=f"Duplicate `custom_id` detected: `{custom_id}`.",
                        hint="Use a unique identifier for each batch row.",
                    )
                )
            else:
                seen_custom_ids.add(custom_id)

            body = row.get("body")
            if not isinstance(body, dict):
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="body",
                        message="Field `body` is required and must be an object.",
                        hint="OpenAI rows must look like `{custom_id?, method?, url, body}`.",
                    )
                )
                continue

            raw_url = row.get("url")
            if not isinstance(raw_url, str) or not raw_url.strip():
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="url",
                        message="Field `url` is required.",
                    )
                )
                continue

            try:
                target = get_batch_target(raw_url)
            except HTTPException:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="unsupported_endpoint",
                        line=line_number,
                        field="url",
                        message=(
                            "Unsupported batch endpoint. Supported values are "
                            "`/v1/chat/completions` and `/v1/embeddings`."
                        ),
                    )
                )
                continue

            if selected_target is None:
                selected_target = target
            elif selected_target.kind != target.kind:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="mixed_endpoint_family",
                        line=line_number,
                        field="url",
                        message="All batch rows must target the same endpoint family.",
                        hint="Do not mix chat and embeddings requests in the same file.",
                    )
                )

            method = str(row.get("method", "POST")).upper()
            if method != "POST":
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="invalid_field",
                        line=line_number,
                        field="method",
                        message="Field `method` must be `POST` when provided.",
                    )
                )

            if target.kind == "chat":
                if not isinstance(body.get("messages"), list):
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.ERROR,
                            code="missing_field",
                            line=line_number,
                            field="body.messages",
                            message="Field `body.messages` is required for chat batches.",
                        )
                    )
                    continue

                if self.default_model and not str(body.get("model") or "").strip():
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.WARNING,
                            code="default_model_applied",
                            line=line_number,
                            field="body.model",
                            message="Field `body.model` is missing and will use the configured default model.",
                        )
                    )

                if not emitted_chat_warning:
                    warnings = get_batch_warnings(
                        target=target,
                        gigachat_api_mode=self.gigachat_api_mode,
                    )
                    if warnings:
                        issues.append(
                            _build_issue(
                                severity=BatchValidationSeverity.WARNING,
                                code="compatibility_warning",
                                message=warnings[0],
                            )
                        )
                        emitted_chat_warning = True

                if self.request_transformer is not None:
                    try:
                        await self.request_transformer.prepare_chat_completion(
                            body,
                            self._build_giga_client_stub(),
                        )
                    except Exception as exc:
                        issues.append(
                            _build_issue(
                                severity=BatchValidationSeverity.ERROR,
                                code="request_normalization_failed",
                                line=line_number,
                                field="body",
                                message=_extract_exception_message(exc),
                            )
                        )
            elif target.kind == "embeddings":
                if "input" not in body:
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.ERROR,
                            code="missing_field",
                            line=line_number,
                            field="body.input",
                            message="Field `body.input` is required for embeddings batches.",
                        )
                    )
                    continue

                if self.embeddings_model:
                    try:
                        await transform_embedding_body(body, self.embeddings_model)
                    except Exception as exc:
                        issues.append(
                            _build_issue(
                                severity=BatchValidationSeverity.ERROR,
                                code="request_normalization_failed",
                                line=line_number,
                                field="body",
                                message=_extract_exception_message(exc),
                            )
                        )

        return issues

    def _build_giga_client_stub(self) -> Any:
        settings = SimpleNamespace(model=self.default_model)
        return SimpleNamespace(_settings=settings)


class AnthropicBatchValidator:
    """Validate Anthropic-style batch input rows."""

    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger

    def validate(
        self, numbered_rows: list[tuple[int, dict[str, Any]]]
    ) -> list[BatchValidationIssue]:
        issues: list[BatchValidationIssue] = []
        seen_custom_ids: set[str] = set()

        for line_number, row in numbered_rows:
            custom_id = row.get("custom_id")
            if not isinstance(custom_id, str) or not custom_id.strip():
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="custom_id",
                        message="Field `custom_id` is required and must be a non-empty string.",
                        hint="Anthropic rows must look like `{custom_id, params}`.",
                    )
                )
            elif custom_id in seen_custom_ids:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="duplicate_identifier",
                        line=line_number,
                        field="custom_id",
                        message=f"Duplicate `custom_id` detected: `{custom_id}`.",
                    )
                )
            else:
                seen_custom_ids.add(custom_id)

            params = row.get("params")
            if not isinstance(params, dict):
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="params",
                        message="Field `params` is required and must be an object.",
                    )
                )
                continue

            if not isinstance(params.get("messages"), list):
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="params.messages",
                        message="Field `params.messages` is required.",
                    )
                )

            if params.get("stream") is True:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="invalid_field",
                        line=line_number,
                        field="params.stream",
                        message="Streaming requests are not supported inside Anthropic message batches.",
                    )
                )

            ignored_fields = sorted(set(row) - {"custom_id", "params"})
            if ignored_fields:
                ignored_fields_rendered = ", ".join(
                    f"`{field}`" for field in ignored_fields
                )
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.WARNING,
                        code="ignored_fields",
                        line=line_number,
                        message=(
                            "Optional fields are present but ignored by the current "
                            "Anthropic batch implementation: "
                            f"{ignored_fields_rendered}."
                        ),
                    )
                )

            try:
                build_anthropic_chat_request(params, logger=self.logger)
            except Exception as exc:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="request_normalization_failed",
                        line=line_number,
                        field="params",
                        message=_extract_exception_message(exc),
                    )
                )

        return issues


class GeminiBatchValidator:
    """Validate Gemini-style batch input rows."""

    def __init__(
        self,
        *,
        logger: Any = None,
        fallback_model: str | None = None,
    ) -> None:
        self.logger = logger
        self.fallback_model = normalize_model_name(fallback_model)

    def validate(
        self, numbered_rows: list[tuple[int, dict[str, Any]]]
    ) -> list[BatchValidationIssue]:
        issues: list[BatchValidationIssue] = []
        seen_keys: set[str] = set()

        for line_number, row in numbered_rows:
            request_payload = row.get("request")
            if not isinstance(request_payload, dict):
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="request",
                        message="Field `request` is required and must be an object.",
                        hint="Gemini rows must look like `{key?, request, metadata?}`.",
                    )
                )
                continue

            key = row.get("key")
            if key is not None:
                if not isinstance(key, str) or not key.strip():
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.ERROR,
                            code="invalid_field",
                            line=line_number,
                            field="key",
                            message="Field `key` must be a non-empty string when provided.",
                        )
                    )
                elif key in seen_keys:
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.ERROR,
                            code="duplicate_identifier",
                            line=line_number,
                            field="key",
                            message=f"Duplicate `key` detected: `{key}`.",
                        )
                    )
                else:
                    seen_keys.add(key)

            if "metadata" in row:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.WARNING,
                        code="metadata_ignored",
                        line=line_number,
                        field="metadata",
                        message=(
                            "Field `metadata` is stored for output mapping but is not "
                            "used by downstream provider execution."
                        ),
                    )
                )

            request_model = normalize_model_name(request_payload.get("model"))
            if not request_model:
                if self.fallback_model:
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.WARNING,
                            code="default_model_applied",
                            line=line_number,
                            field="request.model",
                            message="Field `request.model` is missing and the selected fallback model will be injected.",
                        )
                    )
                else:
                    issues.append(
                        _build_issue(
                            severity=BatchValidationSeverity.ERROR,
                            code="missing_field",
                            line=line_number,
                            field="request.model",
                            message="Field `request.model` is required when no fallback model is provided.",
                        )
                    )

            try:
                validation_payload = dict(request_payload)
                validation_payload["model"] = request_model or self.fallback_model
                build_gemini_chat_request(validation_payload, logger=self.logger)
            except GeminiAPIError as exc:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="request_normalization_failed",
                        line=line_number,
                        field="request",
                        message=exc.message,
                    )
                )
            except Exception as exc:
                issues.append(
                    _build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="request_normalization_failed",
                        line=line_number,
                        field="request",
                        message=_extract_exception_message(exc),
                    )
                )

        return issues


def parse_jsonl_with_diagnostics(
    content: bytes,
) -> tuple[list[dict[str, Any]], list[BatchValidationIssue]]:
    """Parse JSONL content while collecting row-level diagnostics."""
    numbered_rows, issues = _parse_jsonl_rows_with_diagnostics(content)
    return [row for _, row in numbered_rows], issues


def _parse_jsonl_rows_with_diagnostics(
    content: bytes,
) -> tuple[list[tuple[int, dict[str, Any]]], list[BatchValidationIssue]]:
    """Parse JSONL content while preserving original line numbers."""
    rows: list[tuple[int, dict[str, Any]]] = []
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

        rows.append((line_number, parsed))

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


def _detect_row_format(row: dict[str, Any]) -> NormalizedArtifactFormat | None:
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


def _build_row_limit_issues(total_rows: int) -> list[BatchValidationIssue]:
    if total_rows <= GIGACHAT_BATCH_MAX_ROWS:
        return []
    return [
        _build_issue(
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


def _contains_error(issues: list[BatchValidationIssue]) -> bool:
    return any(issue.severity is BatchValidationSeverity.ERROR for issue in issues)


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


def _extract_exception_message(exc: Exception) -> str:
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
