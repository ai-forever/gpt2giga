"""Fusion request detection and per-request config extraction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gpt2giga.models.config import (
    FusionCandidateStageOrder,
    FusionDecisionMode,
    FusionDirectToolCallPolicy,
    FusionInvocationMode,
    FusionPanelOutputTruncation,
    FusionPipelineMode,
    FusionPostToolMode,
    FusionPresetSettings,
    FusionPromptMode,
    FusionRequiredToolPolicy,
    FusionSettings,
    FusionToolsMode,
)
from gpt2giga.providers.fusion.errors import FusionConfigurationError
from gpt2giga.providers.fusion.presets import get_fusion_presets

FusionSource = Literal["tool", "plugin", "metadata", "model"]


class FusionStopServerToolsWhen(BaseModel):
    """OpenRouter-compatible server-tool stop policy."""

    max_steps: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_cost: float | None = Field(default=None, ge=0)
    max_time_ms: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="ignore")


class FusionRequestConfig(BaseModel):
    """Resolved Fusion options for one public request."""

    source: FusionSource
    requested_model: Optional[str] = None
    preset: str
    analysis_models: list[str] = Field(min_length=1, max_length=8)
    judge_model: str
    final_model: Optional[str] = None
    direct_model: Optional[str] = None
    panel_roles: list[str] = Field(default_factory=list)
    temperature: Optional[float] = None
    max_completion_tokens: Optional[int] = None
    reasoning: Optional[dict[str, Any]] = None
    include_direct_candidate: bool = False
    return_selected_candidate: bool = True
    invocation_mode: FusionInvocationMode = "outer_auto"
    decision_mode: FusionDecisionMode = "tool_result"
    prompt_mode: FusionPromptMode = "minimal"
    max_panel_output_chars: int = Field(default=6000, ge=0)
    max_total_panel_output_chars: int = Field(default=16000, ge=0)
    panel_output_truncation: FusionPanelOutputTruncation = "head_tail"
    min_successful_panels: int = 1
    timeout_seconds: float = 120.0
    tools_mode: FusionToolsMode = "schema_only"
    pipeline_mode: FusionPipelineMode = "compact"
    max_server_tool_calls: int = Field(default=16, ge=0, le=16)
    max_client_final_tool_calls: int = Field(default=1, ge=0, le=1)
    max_tool_calls: int = Field(default=1, ge=0, le=1)
    max_client_tool_rounds: int = Field(default=8, ge=0, le=64)
    post_tool_mode: FusionPostToolMode = "direct_continuation"
    direct_tool_call_policy: FusionDirectToolCallPolicy = "return_immediately"
    candidate_stage_order: FusionCandidateStageOrder = "parallel"
    required_tool_policy: FusionRequiredToolPolicy = "model_inferred"
    stop_server_tools_when: FusionStopServerToolsWhen | None = None
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
        config = _build_request_config(
            source="tool",
            params=_with_top_level_server_tool_params(tool_config, payload),
            requested_model=requested_model,
            settings=settings,
        )
        _reject_tools_mode_off_with_client_tools(payload, config)
        return config

    plugin_config = _extract_plugin_config(payload)
    if plugin_config is not None:
        if _is_explicitly_disabled(plugin_config):
            return None
        config = _build_request_config(
            source="plugin",
            params=_with_top_level_server_tool_params(plugin_config, payload),
            requested_model=requested_model,
            settings=settings,
        )
        _reject_tools_mode_off_with_client_tools(payload, config)
        return config

    metadata_config = _extract_metadata_config(payload)
    if metadata_config is not None:
        if _is_explicitly_disabled(metadata_config):
            return None
        config = _build_request_config(
            source="metadata",
            params=_with_top_level_server_tool_params(metadata_config, payload),
            requested_model=requested_model,
            settings=settings,
        )
        _reject_tools_mode_off_with_client_tools(payload, config)
        return config

    if is_fusion_model(requested_model, settings):
        config = _build_request_config(
            source="model",
            params=_with_top_level_server_tool_params({}, payload),
            requested_model=requested_model,
            settings=settings,
        )
        _reject_tools_mode_off_with_client_tools(payload, config)
        return config

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


def _with_top_level_server_tool_params(
    params: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(params)
    for key in ("max_tool_calls", "stop_server_tools_when"):
        if key in payload and key not in merged:
            merged[key] = payload[key]
    return merged


def _reject_tools_mode_off_with_client_tools(
    payload: Mapping[str, Any],
    config: FusionRequestConfig,
) -> None:
    if config.tools_mode != "off" or not _payload_has_client_tools(payload):
        return
    if config.source == "model":
        requested = config.requested_model or "this Fusion alias"
    else:
        requested = "this Fusion request"
    raise FusionConfigurationError(
        f"Fusion preset {config.preset} has tools_mode=off but the request "
        "includes client tools. Use gpt2giga/fusion-benchmark-tools or "
        f"gpt2giga/fusion-code instead of {requested}."
    )


def _payload_has_client_tools(payload: Mapping[str, Any]) -> bool:
    tools = payload.get("tools")
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        return False
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        tool_type = str(tool.get("type", "")).strip().lower()
        tool_name = str(tool.get("name", "")).strip().lower()
        function = tool.get("function")
        function_name = (
            str(function.get("name", "")).strip().lower()
            if isinstance(function, Mapping)
            else ""
        )
        if tool_type == "openrouter:fusion":
            continue
        if tool_type == "function" or tool_name or function_name:
            return True
        if tool_type and not tool_type.startswith("openrouter:"):
            return True
    return False


def _build_request_config(
    *,
    source: FusionSource,
    params: Mapping[str, Any],
    requested_model: str | None,
    settings: FusionSettings,
) -> FusionRequestConfig:
    preset_name = (
        _string_or_none(params.get("preset"))
        or preset_from_model_alias(requested_model)
        or settings.default_preset
    )
    presets = get_fusion_presets(settings.presets)
    preset = presets.get(preset_name)
    if preset is None:
        if not {"analysis_models", "model", "judge_model"} & set(params):
            raise FusionConfigurationError(f"Unknown Fusion preset: {preset_name}")
        preset = FusionPresetSettings(
            analysis_models=_string_list(params.get("analysis_models")),
            judge_model=_required_model(params, "model", "judge_model"),
            final_model=_string_or_none(params.get("final_model")),
            direct_model=_string_or_none(params.get("direct_model")),
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
    direct_model = (
        _string_or_none(params.get("direct_model"))
        if "direct_model" in params
        else preset.direct_model
    )
    panel_roles = _string_list(params.get("panel_roles"), fallback=preset.panel_roles)
    tools_mode = _string_or_none(params.get("tools_mode")) or preset.tools_mode
    max_server_tool_calls = _optional_int(
        params.get("max_tool_calls"), settings.max_server_tool_calls
    )
    stop_server_tools_when = parse_stop_server_tools_when(
        params.get("stop_server_tools_when")
    )
    max_server_tool_calls = _apply_stop_policy_to_server_tool_limit(
        max_server_tool_calls,
        stop_server_tools_when,
    )
    max_client_final_tool_calls = _optional_int(
        params.get("max_client_final_tool_calls"),
        settings.max_client_final_tool_calls,
    )
    max_client_tool_rounds = _optional_int(
        params.get("max_client_tool_rounds"),
        (
            preset.max_client_tool_rounds
            if preset.max_client_tool_rounds is not None
            else settings.max_client_tool_rounds
        ),
    )
    post_tool_mode = _optional_mode(
        params.get("post_tool_mode"),
        preset.post_tool_mode or settings.post_tool_mode,
    )
    direct_tool_call_policy = _optional_mode(
        params.get("direct_tool_call_policy"),
        preset.direct_tool_call_policy or settings.direct_tool_call_policy,
    )
    candidate_stage_order = _optional_mode(
        params.get("candidate_stage_order"),
        preset.candidate_stage_order,
    )
    required_tool_policy = _optional_mode(
        params.get("required_tool_policy"),
        preset.required_tool_policy,
    )

    resolved = FusionRequestConfig(
        source=source,
        requested_model=requested_model,
        preset=preset_name,
        analysis_models=analysis_models,
        judge_model=judge_model,
        final_model=final_model,
        direct_model=direct_model,
        panel_roles=panel_roles,
        temperature=_optional_float(params.get("temperature"), preset.temperature),
        max_completion_tokens=_optional_int(
            params.get("max_completion_tokens", params.get("max_tokens")),
            preset.max_completion_tokens,
        ),
        reasoning=_optional_mapping(params.get("reasoning"), preset.reasoning),
        include_direct_candidate=_optional_bool(
            params.get("include_direct_candidate"),
            preset.include_direct_candidate,
        ),
        return_selected_candidate=_optional_bool(
            params.get("return_selected_candidate"),
            preset.return_selected_candidate,
        ),
        invocation_mode=_optional_mode(
            params.get("invocation_mode"),
            preset.invocation_mode,
        ),
        decision_mode=_optional_mode(
            params.get("decision_mode"),
            preset.decision_mode,
        ),
        prompt_mode=_optional_mode(params.get("prompt_mode"), preset.prompt_mode),
        max_panel_output_chars=_optional_int(
            params.get("max_panel_output_chars"),
            preset.max_panel_output_chars,
        ),
        max_total_panel_output_chars=_optional_int(
            params.get("max_total_panel_output_chars"),
            preset.max_total_panel_output_chars,
        ),
        panel_output_truncation=_optional_mode(
            params.get("panel_output_truncation"),
            preset.panel_output_truncation,
        ),
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
        max_server_tool_calls=max_server_tool_calls
        if max_server_tool_calls is not None
        else settings.max_server_tool_calls,
        max_client_final_tool_calls=max_client_final_tool_calls
        if max_client_final_tool_calls is not None
        else settings.max_client_final_tool_calls,
        max_tool_calls=max_client_final_tool_calls
        if max_client_final_tool_calls is not None
        else settings.max_client_final_tool_calls,
        max_client_tool_rounds=max_client_tool_rounds
        if max_client_tool_rounds is not None
        else settings.max_client_tool_rounds,
        post_tool_mode=post_tool_mode,
        direct_tool_call_policy=direct_tool_call_policy,
        candidate_stage_order=candidate_stage_order,
        required_tool_policy=required_tool_policy,
        stop_server_tools_when=stop_server_tools_when,
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
        *(model for model in [config.final_model, config.direct_model] if model),
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
    if (
        settings.max_total_upstream_calls_per_request > 0
        and _planned_upstream_calls(config)
        > settings.max_total_upstream_calls_per_request
    ):
        raise FusionConfigurationError(
            "Fusion planned upstream calls exceed "
            "GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST"
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


def parse_stop_server_tools_when(value: Any) -> FusionStopServerToolsWhen | None:
    """Safely parse OpenRouter SDK-compatible server-tool stop policies."""
    if value in (None, "", False):
        return None
    raw_items: list[Any]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raw_items = list(value)
    else:
        raw_items = [value]

    merged: dict[str, Any] = {}
    for item in raw_items:
        data = _mapping_from_stop_policy(item)
        if data is None:
            continue
        for key in ("max_steps", "max_tool_calls", "max_cost", "max_time_ms"):
            if key in data and data[key] is not None:
                merged[key] = data[key]
    if not merged:
        return None
    try:
        return FusionStopServerToolsWhen.model_validate(merged)
    except ValidationError:
        return None


def _mapping_from_stop_policy(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        dumped = dict_method()
        if isinstance(dumped, Mapping):
            return dumped
    data = {
        key: getattr(value, key)
        for key in ("max_steps", "max_tool_calls", "max_cost", "max_time_ms")
        if hasattr(value, key)
    }
    return data or None


def _apply_stop_policy_to_server_tool_limit(
    max_server_tool_calls: int | None,
    stop_policy: FusionStopServerToolsWhen | None,
) -> int | None:
    limit = max_server_tool_calls
    if stop_policy is None:
        return limit
    for value in (stop_policy.max_tool_calls, stop_policy.max_steps):
        if value is None:
            continue
        limit = value if limit is None else min(limit, value)
    return limit


def _optional_bool(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return fallback


def _optional_mode(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    text = _string_or_none(value)
    return text.lower() if text else fallback


def preset_from_model_alias(model: str | None) -> str | None:
    """Return the built-in Fusion preset implied by a virtual model alias."""
    if model is None:
        return None
    normalized = _normalize_model_id(model).lower()
    if normalized.endswith("fusion-force-selector"):
        return "force-selector"
    if normalized.endswith("fusion-force-synthesize"):
        return "force-synthesize"
    if normalized.endswith("fusion-code-budget"):
        return "code-budget"
    if normalized.endswith("fusion-code-high"):
        return "code-high"
    if normalized.endswith("fusion-general"):
        return "general"
    if normalized.endswith("fusion-benchmark-text"):
        return "force-benchmark-selector"
    if normalized.endswith("fusion-benchmark-tools"):
        return "force-benchmark-selector-tools"
    if normalized.endswith("fusion-benchmark"):
        return "force-benchmark-selector-tools"
    if normalized.endswith("fusion-code"):
        return "verified-tool-loop-ultra"
    if normalized.endswith("fusion-accuracy"):
        return "accuracy-ultra-selector"
    if normalized.endswith("fusion-accuracy-verifier"):
        return "accuracy-ultra-verifier"
    if normalized.endswith("fusion-code-agent-safe"):
        return "code-agent-safe"
    return None


def _planned_upstream_calls(config: FusionRequestConfig) -> int:
    if config.decision_mode == "action":
        return 3
    calls = len(config.analysis_models) + 1
    if config.include_direct_candidate:
        calls += 1
    if config.decision_mode == "selector":
        calls += 1
    return calls


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
