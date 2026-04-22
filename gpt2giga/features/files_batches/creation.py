"""Pure helpers for files/batches creation flows."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from fastapi import HTTPException

from gpt2giga.api.gemini.request import normalize_model_name
from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.files_batches.normalizers import (
    resolve_anthropic_batch_endpoint,
    resolve_gemini_batch_endpoint,
)


def normalize_openai_batch_endpoint(value: str | None) -> str:
    """Return the canonical OpenAI batch endpoint."""
    normalized = string_or_none(value)
    if normalized is None:
        return "/v1/chat/completions"
    return normalized


def build_uploaded_file_metadata(
    *,
    api_format: NormalizedArtifactFormat,
    purpose: str,
    upload: dict[str, Any],
    display_name: str | None,
) -> dict[str, Any]:
    """Build stored metadata for an uploaded input file."""
    metadata = {
        "api_format": api_format.value,
        "purpose": purpose,
        "filename": upload["filename"],
        "status": "processed",
    }
    if api_format is not NormalizedArtifactFormat.GEMINI:
        return metadata
    metadata.update(
        {
            "display_name": string_or_none(display_name) or upload["filename"],
            "mime_type": upload["content_type"],
            "sha256_hash": base64.b64encode(
                hashlib.sha256(upload["content"]).digest()
            ).decode("ascii"),
            "source": "UPLOADED",
        }
    )
    return metadata


def build_openai_inline_batch_metadata(
    *,
    input_file_id: str | None,
    metadata: dict[str, Any] | None,
    model: str | None,
) -> dict[str, Any]:
    """Build stored metadata for inline OpenAI batch creation."""
    stored_metadata: dict[str, Any] = {"metadata": dict(metadata or {})}
    resolved_input_file_id = string_or_none(input_file_id)
    if resolved_input_file_id:
        stored_metadata["input_file_id"] = resolved_input_file_id
    normalized_model = string_or_none(model)
    if normalized_model:
        stored_metadata["model"] = normalized_model
    return stored_metadata


def build_openai_staged_batch_metadata(
    *,
    input_file_id: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build stored metadata for staged OpenAI batch creation."""
    return {
        "input_file_id": input_file_id,
        "metadata": dict(metadata or {}),
    }


def build_anthropic_batch_metadata(
    *,
    input_file_id: str | None,
    metadata: dict[str, Any] | None,
    display_name: str | None,
    model: str | None,
    stored_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build stored metadata for Anthropic batch creation."""
    stored_metadata: dict[str, Any] = {
        "api_format": "anthropic_messages",
        "provider_endpoint": resolve_anthropic_batch_endpoint(),
        "requests": stored_requests,
    }
    resolved_input_file_id = string_or_none(input_file_id)
    if resolved_input_file_id:
        stored_metadata["input_file_id"] = resolved_input_file_id
    if metadata:
        stored_metadata["metadata"] = dict(metadata)
    normalized_display_name = string_or_none(display_name)
    if normalized_display_name:
        stored_metadata["display_name"] = normalized_display_name
    normalized_model = string_or_none(model)
    if normalized_model:
        stored_metadata["model"] = normalized_model
    return stored_metadata


def build_gemini_batch_metadata(
    *,
    input_file_id: str | None,
    metadata: dict[str, Any] | None,
    display_name: str | None,
    model: str,
    stored_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build stored metadata for Gemini batch creation."""
    stored_metadata: dict[str, Any] = {
        "api_format": "gemini_generate_content",
        "display_name": resolve_gemini_batch_display_name(
            display_name,
            input_file_id=input_file_id,
        ),
        "model": model,
        "provider_model": model,
        "priority": 0,
        "requests": stored_requests,
    }
    stored_metadata["provider_endpoint"] = resolve_gemini_batch_endpoint(
        stored_metadata
    )
    if metadata:
        stored_metadata["metadata"] = dict(metadata)
    resolved_input_file_id = string_or_none(input_file_id)
    if resolved_input_file_id:
        stored_metadata["input_file_id"] = resolved_input_file_id
    return stored_metadata


def apply_openai_fallback_model(
    requests_payload: list[dict[str, Any]],
    *,
    fallback_model: str | None,
) -> list[dict[str, Any]]:
    """Inject a fallback model into OpenAI batch rows that omit one."""
    normalized_fallback = string_or_none(fallback_model)
    if normalized_fallback is None:
        return requests_payload

    normalized_requests: list[dict[str, Any]] = []
    for request_item in requests_payload:
        if not isinstance(request_item, dict):
            normalized_requests.append(request_item)
            continue

        next_request = dict(request_item)
        body = next_request.get("body")
        if isinstance(body, dict) and not string_or_none(body.get("model")):
            next_body = dict(body)
            next_body["model"] = normalized_fallback
            next_request["body"] = next_body
        normalized_requests.append(next_request)
    return normalized_requests


def apply_anthropic_fallback_model(
    requests_payload: list[dict[str, Any]],
    *,
    fallback_model: str | None,
) -> list[dict[str, Any]]:
    """Inject a fallback model into Anthropic batch rows that omit one."""
    normalized_fallback = string_or_none(fallback_model)
    if normalized_fallback is None:
        return requests_payload

    normalized_requests: list[dict[str, Any]] = []
    for request_item in requests_payload:
        if not isinstance(request_item, dict):
            normalized_requests.append(request_item)
            continue

        next_request = dict(request_item)
        params = next_request.get("params")
        if isinstance(params, dict) and not string_or_none(params.get("model")):
            next_params = dict(params)
            next_params["model"] = normalized_fallback
            next_request["params"] = next_params
        normalized_requests.append(next_request)
    return normalized_requests


def resolve_gemini_batch_model(
    requests_payload: list[dict[str, Any]],
    *,
    fallback_model: str | None,
) -> str:
    """Resolve the model to use for Gemini batch creation."""
    normalized_fallback = normalize_model_name(string_or_none(fallback_model))
    request_models = {
        normalize_model_name(
            str(
                request_item.get("request", {}).get("model")
                or request_item.get("model")
                or ""
            )
        )
        for request_item in requests_payload
        if isinstance(request_item, dict)
        and (
            (
                isinstance(request_item.get("request"), dict)
                and string_or_none(request_item.get("request", {}).get("model"))
            )
            or string_or_none(request_item.get("model"))
        )
    }
    if normalized_fallback:
        return normalized_fallback
    if len(request_models) == 1:
        return next(iter(request_models))
    if request_models:
        raise HTTPException(
            status_code=400,
            detail={
                "model": (
                    "`model` is required when Gemini batch rows mix multiple request models."
                )
            },
        )
    raise HTTPException(
        status_code=400,
        detail={
            "model": (
                "`model` is required for Gemini batches when request rows omit `request.model`."
            )
        },
    )


def resolve_gemini_batch_display_name(
    display_name: str | None,
    *,
    input_file_id: str | None,
) -> str:
    """Resolve the admin display name for a Gemini batch."""
    normalized_display_name = string_or_none(display_name)
    if normalized_display_name is not None:
        return normalized_display_name
    normalized_input_file_id = string_or_none(input_file_id)
    if normalized_input_file_id is not None:
        return f"Gemini batch for {normalized_input_file_id}"
    return "Gemini batch"


def string_or_none(value: Any) -> str | None:
    """Return a stripped string or None for empty input."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
