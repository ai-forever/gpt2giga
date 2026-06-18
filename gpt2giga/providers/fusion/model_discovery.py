"""Virtual model discovery helpers for Fusion aliases."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request

from gpt2giga.models.config import FusionSettings, ProxySettings

FUSION_MODEL_OWNER = "gpt2giga"
FUSION_MODEL_DESCRIPTION = "Fusion model exposed through gpt2giga."
FUSION_MODEL_CREATED = 1_781_740_800  # 2026-06-18T00:00:00Z


def get_request_fusion_settings(request: Request) -> FusionSettings:
    """Return Fusion settings from app config or defaults."""
    config = getattr(request.app.state, "config", None)
    proxy_settings = getattr(config, "proxy_settings", None)
    if proxy_settings is None:
        proxy_settings = ProxySettings()
    return proxy_settings.fusion


def build_fusion_openai_models(
    settings: FusionSettings,
    *,
    created: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Build OpenAI-compatible virtual Fusion model objects."""
    if not settings.enabled:
        return []
    timestamp = FUSION_MODEL_CREATED if created is None else created
    return [
        {
            "id": alias,
            "object": "model",
            "created": timestamp,
            "owned_by": FUSION_MODEL_OWNER,
            "display_name": _display_name(alias),
        }
        for alias in settings.aliases
    ]


def find_fusion_openai_model(
    model: str,
    settings: FusionSettings,
    *,
    created: Optional[int] = None,
) -> dict[str, Any] | None:
    """Return one OpenAI-compatible Fusion model by alias."""
    normalized = _normalize_model_id(model)
    for item in build_fusion_openai_models(settings, created=created):
        if _normalize_model_id(str(item["id"])) == normalized:
            return item
    return None


def build_fusion_gemini_models(settings: FusionSettings) -> list[dict[str, Any]]:
    """Build Gemini-compatible virtual Fusion model objects."""
    if not settings.enabled:
        return []
    return [
        {
            "name": f"models/{alias}",
            "baseModelId": alias,
            "version": "",
            "displayName": _display_name(alias),
            "description": FUSION_MODEL_DESCRIPTION,
            "inputTokenLimit": 0,
            "outputTokenLimit": 0,
            "supportedGenerationMethods": [
                "generateContent",
                "streamGenerateContent",
                "countTokens",
            ],
        }
        for alias in settings.aliases
    ]


def find_fusion_gemini_model(
    model: str,
    settings: FusionSettings,
) -> dict[str, Any] | None:
    """Return one Gemini-compatible Fusion model by alias."""
    normalized = _normalize_model_id(model)
    for item in build_fusion_gemini_models(settings):
        if _normalize_model_id(str(item["baseModelId"])) == normalized:
            return item
    return None


def build_fusion_litellm_model_info(settings: FusionSettings) -> list[dict[str, Any]]:
    """Build LiteLLM-compatible virtual Fusion model info entries."""
    if not settings.enabled:
        return []
    return [
        {
            "model_name": alias,
            "litellm_params": {"model": alias},
            "model_info": {
                "id": alias,
                "owned_by": FUSION_MODEL_OWNER,
                "display_name": _display_name(alias),
            },
        }
        for alias in settings.aliases
    ]


def find_fusion_litellm_model_info(
    model: str,
    settings: FusionSettings,
) -> dict[str, Any] | None:
    """Return one LiteLLM-compatible Fusion model info entry by alias."""
    normalized = _normalize_model_id(model)
    for item in build_fusion_litellm_model_info(settings):
        if _normalize_model_id(str(item["model_name"])) == normalized:
            return item
    return None


def _display_name(alias: str) -> str:
    lower_alias = alias.lower()
    if "budget" in lower_alias:
        return "GigaFusion Code Budget"
    if "general" in lower_alias:
        return "GigaFusion General"
    return "GigaFusion Code" if "code" in lower_alias else "GigaFusion"


def _normalize_model_id(model: str) -> str:
    return model.strip().removeprefix("models/")
