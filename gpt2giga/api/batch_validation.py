"""Shared helpers for batch input validation endpoints."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

from gpt2giga.app.dependencies import (
    get_config_from_state,
    get_logger_from_state,
    get_request_transformer_from_state,
    get_runtime_stores,
)
from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches import (
    BatchInputValidator,
    BatchValidationReport,
)
from gpt2giga.providers.gigachat.client import get_gigachat_client


def build_batch_input_validator(request: Request) -> BatchInputValidator:
    """Build a request-scoped batch validator from app state."""
    app_state = request.app.state
    config = get_config_from_state(app_state)
    return BatchInputValidator(
        request_transformer=get_request_transformer_from_state(app_state),
        embeddings_model=config.proxy_settings.embeddings,
        gigachat_api_mode=config.proxy_settings.chat_backend_mode,
        logger=get_logger_from_state(app_state),
        default_model=getattr(config.gigachat_settings, "model", None),
    )


async def run_batch_input_validation(
    *,
    request: Request,
    api_format: str | NormalizedArtifactFormat,
    input_file_id: str | None,
    input_bytes: bytes | None,
    fallback_model: str | None,
    requests: list[dict[str, Any]] | None,
) -> BatchValidationReport | None:
    """Validate staged or inline batch input and return a report when possible."""
    validator = build_batch_input_validator(request)
    if input_bytes is not None:
        return await validator.validate_bytes(
            input_bytes,
            api_format=api_format,
            fallback_model=fallback_model,
        )
    resolved_input_file_id = _normalize_optional_string(input_file_id)
    if resolved_input_file_id is not None:
        cached_report = _get_cached_validation_report(
            request=request,
            file_id=resolved_input_file_id,
            api_format=api_format,
            fallback_model=fallback_model,
        )
        if cached_report is not None:
            return cached_report

        content = await resolve_batch_input_bytes(
            request,
            file_id=resolved_input_file_id,
        )
        report = await validator.validate_bytes(
            content,
            api_format=api_format,
            fallback_model=fallback_model,
        )
        _cache_validation_report(
            request=request,
            file_id=resolved_input_file_id,
            api_format=api_format,
            fallback_model=fallback_model,
            report=report,
        )
        return report
    if requests is not None:
        return await validator.validate_rows(
            list(requests),
            api_format=api_format,
            fallback_model=fallback_model,
        )
    return None


async def validate_batch_input_request(
    *,
    request: Request,
    api_format: str | NormalizedArtifactFormat,
    input_file_id: str | None,
    input_bytes: bytes | None,
    fallback_model: str | None,
    requests: list[dict[str, Any]] | None,
) -> BatchValidationReport:
    """Validate batch input or raise when no file/rows were provided."""
    report = await run_batch_input_validation(
        request=request,
        api_format=api_format,
        input_file_id=input_file_id,
        input_bytes=input_bytes,
        fallback_model=fallback_model,
        requests=requests,
    )
    if report is not None:
        return report
    raise HTTPException(
        status_code=400,
        detail=(
            "`input_file_id`, `input_content_base64`, or `requests` is required "
            "for validation."
        ),
    )


def _normalize_optional_string(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


async def resolve_batch_input_bytes(
    request: Request,
    *,
    file_id: str,
) -> bytes:
    """Load staged batch input bytes, preferring the local runtime cache."""
    stores = get_runtime_stores(request.app.state)
    cached_bytes = stores.batch_input_bytes.get(file_id)
    if isinstance(cached_bytes, bytes):
        return cached_bytes

    file_response = await get_gigachat_client(request).aget_file_content(
        file_id=file_id
    )
    content = base64.b64decode(file_response.content)
    stores.batch_input_bytes[file_id] = content
    return content


def cache_batch_input_bytes(
    request: Request,
    *,
    file_id: str,
    content: bytes,
) -> None:
    """Seed the local runtime cache for one staged batch input file."""
    get_runtime_stores(request.app.state).batch_input_bytes[file_id] = bytes(content)


def _get_cached_validation_report(
    *,
    request: Request,
    file_id: str,
    api_format: str | NormalizedArtifactFormat,
    fallback_model: str | None,
) -> BatchValidationReport | None:
    stores = get_runtime_stores(request.app.state)
    cache_key = _build_validation_cache_key(
        file_id=file_id,
        api_format=api_format,
        fallback_model=fallback_model,
    )
    cached_payload = stores.batch_validation_reports.get(cache_key)
    if not isinstance(cached_payload, dict):
        return None
    return BatchValidationReport.model_validate(cached_payload)


def _cache_validation_report(
    *,
    request: Request,
    file_id: str,
    api_format: str | NormalizedArtifactFormat,
    fallback_model: str | None,
    report: BatchValidationReport,
) -> None:
    stores = get_runtime_stores(request.app.state)
    cache_key = _build_validation_cache_key(
        file_id=file_id,
        api_format=api_format,
        fallback_model=fallback_model,
    )
    stores.batch_validation_reports[cache_key] = report.model_dump(mode="json")


def _build_validation_cache_key(
    *,
    file_id: str,
    api_format: str | NormalizedArtifactFormat,
    fallback_model: str | None,
) -> str:
    if isinstance(api_format, NormalizedArtifactFormat):
        normalized_api_format = api_format.value
    else:
        normalized_api_format = str(api_format or "").strip().lower() or "openai"
    normalized_model = _normalize_optional_string(fallback_model) or ""
    return "::".join((file_id, normalized_api_format, normalized_model))
