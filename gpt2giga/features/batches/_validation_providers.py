"""Provider-specific batch input validators."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from gpt2giga.api.anthropic.request_adapter import (
    build_normalized_chat_request as build_anthropic_chat_request,
)
from gpt2giga.api.gemini.request import GeminiAPIError, normalize_model_name
from gpt2giga.api.gemini.request_adapter import (
    build_normalized_chat_request as build_gemini_chat_request,
)
from gpt2giga.features.batches._validation_common import (
    NumberedBatchRows,
    build_issue,
    extract_exception_message,
)
from gpt2giga.features.batches.transforms import (
    get_batch_target,
    get_batch_warnings,
)
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationSeverity,
)
from gpt2giga.providers.gigachat.embeddings_mapper import transform_embedding_body


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
        self, numbered_rows: NumberedBatchRows
    ) -> list[BatchValidationIssue]:
        """Validate OpenAI-style batch rows."""
        issues: list[BatchValidationIssue] = []
        seen_custom_ids: set[str] = set()
        selected_target = None
        emitted_chat_warning = False

        for line_number, row in numbered_rows:
            custom_id = row.get("custom_id")
            if custom_id is None:
                issues.append(
                    build_issue(
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
                    build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="invalid_field",
                        line=line_number,
                        field="custom_id",
                        message="Field `custom_id` must be a non-empty string when provided.",
                    )
                )
            elif custom_id in seen_custom_ids:
                issues.append(
                    build_issue(
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
                    build_issue(
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
                    build_issue(
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
                    build_issue(
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
                    build_issue(
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
                    build_issue(
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
                        build_issue(
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
                        build_issue(
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
                            build_issue(
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
                            build_issue(
                                severity=BatchValidationSeverity.ERROR,
                                code="request_normalization_failed",
                                line=line_number,
                                field="body",
                                message=extract_exception_message(exc),
                            )
                        )
            elif target.kind == "embeddings":
                if "input" not in body:
                    issues.append(
                        build_issue(
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
                            build_issue(
                                severity=BatchValidationSeverity.ERROR,
                                code="request_normalization_failed",
                                line=line_number,
                                field="body",
                                message=extract_exception_message(exc),
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

    def validate(self, numbered_rows: NumberedBatchRows) -> list[BatchValidationIssue]:
        """Validate Anthropic-style batch rows."""
        issues: list[BatchValidationIssue] = []
        seen_custom_ids: set[str] = set()

        for line_number, row in numbered_rows:
            custom_id = row.get("custom_id")
            if not isinstance(custom_id, str) or not custom_id.strip():
                issues.append(
                    build_issue(
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
                    build_issue(
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
                    build_issue(
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
                    build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="missing_field",
                        line=line_number,
                        field="params.messages",
                        message="Field `params.messages` is required.",
                    )
                )

            if params.get("stream") is True:
                issues.append(
                    build_issue(
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
                    build_issue(
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
                    build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="request_normalization_failed",
                        line=line_number,
                        field="params",
                        message=extract_exception_message(exc),
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

    def validate(self, numbered_rows: NumberedBatchRows) -> list[BatchValidationIssue]:
        """Validate Gemini-style batch rows."""
        issues: list[BatchValidationIssue] = []
        seen_keys: set[str] = set()

        for line_number, row in numbered_rows:
            request_payload = row.get("request")
            if not isinstance(request_payload, dict):
                issues.append(
                    build_issue(
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
                        build_issue(
                            severity=BatchValidationSeverity.ERROR,
                            code="invalid_field",
                            line=line_number,
                            field="key",
                            message="Field `key` must be a non-empty string when provided.",
                        )
                    )
                elif key in seen_keys:
                    issues.append(
                        build_issue(
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
                    build_issue(
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
                        build_issue(
                            severity=BatchValidationSeverity.WARNING,
                            code="default_model_applied",
                            line=line_number,
                            field="request.model",
                            message="Field `request.model` is missing and the selected fallback model will be injected.",
                        )
                    )
                else:
                    issues.append(
                        build_issue(
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
                    build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="request_normalization_failed",
                        line=line_number,
                        field="request",
                        message=exc.message,
                    )
                )
            except Exception as exc:
                issues.append(
                    build_issue(
                        severity=BatchValidationSeverity.ERROR,
                        code="request_normalization_failed",
                        line=line_number,
                        field="request",
                        message=extract_exception_message(exc),
                    )
                )

        return issues
