"""Fusion request detection and per-request config extraction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from gpt2giga.models.config import (
    FusionPipelineMode,
    FusionPresetSettings,
    FusionSettings,
    FusionToolsMode,
)
from gpt2giga.providers.fusion.errors import FusionConfigurationError
from gpt2giga.providers.fusion.presets import get_fusion_presets

FusionSource = Literal["tool", "plugin", "metadata", "model"]


class FusionRequestConfig(BaseModel):
    """Resolved Fusion options for one public request."""

    source: FusionSource
    requested_model: Optional[str] = None
    preset: str
    analysis_models: list[str] = Field(min_length=1, max_length=8)
    judge_model: str
    final_model: Optional[str] = None
    panel_roles: list[str] = Field(default_factory=list)
    temperature: Optional[float] = 0.2
    max_completion_tokens: Optional[int] = None
    reasoning: Optional[dict[str, Any]] = None
    min_successful_panels: int = 1
    timeout_seconds: float = 120.0
    tools_mode: FusionToolsMode = "schema_only"
    pipeline_mode: FusionPipelineMode = "compact"
    max_tool_calls: int = Field(default=1, ge=1, le=1)
    raw_parameters: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


def is_fusion_model(model: str | None, settings: FusionSettings) -> bool:
    """Return whether a model id is configured as a Fusion alias."""
    if not settings.enabled or not model:
        return False
    return _normalize_model_id(model) in {
        _normalize_model_id(alias) for alias in settings.aliases
    }


def extract_fusion_request(
    payload: Mapping[str, Any],
    settings: FusionSettings,
) -> FusionRequestConfig | None:
    """Extract Fusion request config from OpenRouter-style or alias payloads."""
    if not settings.enabled:
        return None

    requested_model = _string_or_none(payload.get("model"))

    tool_config = _extract_tool_config(payload)
    if tool_config is not None:
        if _is_explicitly_disabled(tool_config):
            return None
        return _build_request_config(
            source="tool",
            params=tool_config,
            requested_model=requested_model,
            settings=settings,
        )

    plugin_config = _extract_plugin_config(payload)
    if plugin_config is not None:
        if _is_explicitly_disabled(plugin_config):
            return None
        return _build_request_config(
            source="plugin",
            params=plugin_config,
            requested_model=requested_model,
            settings=settings,
        )

    metadata_config = _extract_metadata_config(payload)
    if metadata_config is not None:
        if _is_explicitly_disabled(metadata_config):
            return None
        return _build_request_config(
            source="metadata",
            params=metadata_config,
            requested_model=requested_model,
            settings=settings,
        )

    if is_fusion_model(requested_model, settings):
        return _build_request_config(
            source="model",
            params={},
            requested_model=requested_model,
            settings=settings,
        )

    return None


def _extract_tool_config(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    tools = payload.get("tools")
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        return None
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if tool.get("type") != "openrouter:fusion":
            continue
        parameters = tool.get("parameters")
        if parameters is None:
            parameters = tool.get("parameter")
        if isinstance(parameters, Mapping):
            return dict(parameters)
        return {}
    return None


def _extract_plugin_config(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    plugins = payload.get("plugins")
    if not isinstance(plugins, Sequence) or isinstance(plugins, (str, bytes)):
        return None
    for plugin in plugins:
        if not isinstance(plugin, Mapping):
            continue
        if plugin.get("id") != "fusion":
            continue
        return dict(plugin)
    return None


def _extract_metadata_config(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    for container_key in ("metadata", "extra_body"):
        container = payload.get(container_key)
        if not isinstance(container, Mapping):
            continue
        config = container.get("gpt2giga_fusion")
        if isinstance(config, Mapping):
            return dict(config)
    config = payload.get("gpt2giga_fusion")
    if isinstance(config, Mapping):
        return dict(config)
    return None


def _build_request_config(
    *,
    source: FusionSource,
    params: Mapping[str, Any],
    requested_model: str | None,
    settings: FusionSettings,
) -> FusionRequestConfig:
    preset_name = _string_or_none(params.get("preset")) or settings.default_preset
    presets = get_fusion_presets(settings.presets)
    preset = presets.get(preset_name)
    if preset is None:
        if not {"analysis_models", "model", "judge_model"} & set(params):
            raise FusionConfigurationError(f"Unknown Fusion preset: {preset_name}")
        preset = FusionPresetSettings(
            analysis_models=_string_list(params.get("analysis_models")),
            judge_model=_required_model(params, "model", "judge_model"),
            final_model=_string_or_none(params.get("final_model")),
        )

    analysis_models = _string_list(
        params.get("analysis_models"), fallback=preset.analysis_models
    )
    judge_model = (
        _string_or_none(params.get("judge_model"))
        or _string_or_none(params.get("model"))
        or preset.judge_model
    )
    final_model = (
        _string_or_none(params.get("final_model"))
        if "final_model" in params
        else preset.final_model
    )
    if final_model is not None:
        raise FusionConfigurationError(
            "Fusion final_model is reserved; current implementation supports "
            "only compact panel -> judge/finalizer pipeline."
        )
    panel_roles = _string_list(params.get("panel_roles"), fallback=preset.panel_roles)
    tools_mode = _string_or_none(params.get("tools_mode")) or preset.tools_mode
    max_tool_calls = _optional_int(
        params.get("max_tool_calls"), settings.max_tool_calls
    )
    if max_tool_calls != 1:
        raise FusionConfigurationError(
            "Fusion currently supports exactly one final tool call."
        )

    resolved = FusionRequestConfig(
        source=source,
        requested_model=requested_model,
        preset=preset_name,
        analysis_models=analysis_models,
        judge_model=judge_model,
        final_model=final_model,
        panel_roles=panel_roles,
        temperature=_optional_float(params.get("temperature"), preset.temperature),
        max_completion_tokens=_optional_int(
            params.get("max_completion_tokens", params.get("max_tokens")),
            preset.max_completion_tokens,
        ),
        reasoning=_optional_mapping(params.get("reasoning"), preset.reasoning),
        min_successful_panels=_optional_int(
            params.get("min_successful_panels"), preset.min_successful_panels
        )
        or preset.min_successful_panels,
        timeout_seconds=_optional_float(
            params.get("timeout_seconds"), preset.timeout_seconds
        )
        or preset.timeout_seconds,
        tools_mode=tools_mode,
        pipeline_mode=settings.pipeline_mode,
        max_tool_calls=max_tool_calls,
        raw_parameters=dict(params),
    )
    _validate_resolved_request(resolved, settings)
    return resolved


def _validate_resolved_request(
    config: FusionRequestConfig,
    settings: FusionSettings,
) -> None:
    if config.pipeline_mode != "compact":
        raise FusionConfigurationError(
            "Fusion pipeline_mode='strict' is reserved; current implementation "
            "supports only compact panel -> judge/finalizer pipeline."
        )
    aliases = {_normalize_model_id(alias) for alias in settings.aliases}
    concrete_models = [
        *config.analysis_models,
        config.judge_model,
        *(model for model in [config.final_model] if model),
    ]
    for model in concrete_models:
        if _normalize_model_id(model) in aliases:
            raise FusionConfigurationError(
                f"Fusion cannot use Fusion alias {model!r} as an internal model"
            )
    if len(config.analysis_models) > settings.max_panel_models:
        raise FusionConfigurationError(
            "Fusion analysis_models exceeds GPT2GIGA_FUSION_MAX_PANEL_MODELS"
        )
    if config.min_successful_panels > len(config.analysis_models):
        raise FusionConfigurationError(
            "Fusion min_successful_panels cannot exceed analysis_models length"
        )


def _required_model(params: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _string_or_none(params.get(key))
        if value:
            return value
    raise FusionConfigurationError("Fusion request requires model or judge_model")


def _string_list(value: Any, fallback: list[str] | None = None) -> list[str]:
    if value is None:
        return list(fallback or [])
    if isinstance(value, str):
        if value.strip().startswith("["):
            import json

            parsed = json.loads(value)
            return _string_list(parsed, fallback=fallback)
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(fallback or [])


def _optional_mapping(
    value: Any,
    fallback: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return fallback
    if isinstance(value, Mapping):
        return dict(value)
    return fallback


def _optional_float(value: Any, fallback: float | None) -> float | None:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _optional_int(value: Any, fallback: int | None) -> int | None:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_model_id(model: str) -> str:
    return model.strip().removeprefix("models/")


def _is_explicitly_disabled(params: Mapping[str, Any]) -> bool:
    enabled = params.get("enabled")
    if isinstance(enabled, bool):
        return not enabled
    if isinstance(enabled, str):
        return enabled.strip().lower() in {"0", "false", "no", "off"}
    return False
