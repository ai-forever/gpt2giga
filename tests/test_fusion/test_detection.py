import pytest

from gpt2giga.models.config import FusionSettings
from gpt2giga.providers.fusion.detection import (
    extract_fusion_request,
    is_fusion_model,
)
from gpt2giga.providers.fusion.errors import FusionConfigurationError


def _settings(**overrides) -> FusionSettings:
    values = {
        "enabled": True,
        "aliases": ["gpt2giga/fusion-code", "GigaChat-Fusion-Code"],
        "default_preset": "code-budget",
        "max_panel_models": 4,
    }
    values.update(overrides)
    return FusionSettings(**values)


def test_is_fusion_model_requires_enabled_flag():
    assert is_fusion_model("gpt2giga/fusion-code", _settings())
    assert not is_fusion_model(
        "gpt2giga/fusion-code",
        _settings(enabled=False),
    )
    assert is_fusion_model("models/gpt2giga/fusion-code", _settings())
    assert not is_fusion_model("GigaChat", _settings())


def test_extract_fusion_code_alias_uses_verified_tool_loop_preset():
    config = extract_fusion_request(
        {"model": "gpt2giga/fusion-code"},
        _settings(),
    )

    assert config is not None
    assert config.source == "model"
    assert config.preset == "verified-tool-loop-ultra"
    assert config.analysis_models == ["GigaChat-3-Ultra"]
    assert config.judge_model == "GigaChat-3-Ultra"
    assert config.invocation_mode == "force"
    assert config.decision_mode == "action"
    assert config.candidate_stage_order == "direct_then_verify"
    assert config.direct_tool_call_policy == "verify_before_return"
    assert config.post_tool_mode == "verified_continuation"


def test_extract_fusion_plugin_overrides_model_alias():
    config = extract_fusion_request(
        {
            "model": "gpt2giga/fusion-code",
            "plugins": [{"id": "fusion", "preset": "general"}],
        },
        _settings(),
    )

    assert config is not None
    assert config.source == "plugin"
    assert config.preset == "general"
    assert config.tools_mode == "off"


def test_extract_fusion_tool_has_highest_priority():
    config = extract_fusion_request(
        {
            "model": "gpt2giga/fusion-code",
            "plugins": [{"id": "fusion", "preset": "general"}],
            "tools": [
                {
                    "type": "openrouter:fusion",
                    "parameters": {
                        "analysis_models": ["A", "B"],
                        "model": "Judge",
                        "max_tool_calls": 1,
                    },
                }
            ],
        },
        _settings(),
    )

    assert config is not None
    assert config.source == "tool"
    assert config.analysis_models == ["A", "B"]
    assert config.judge_model == "Judge"
    assert config.max_server_tool_calls == 1
    assert config.max_client_final_tool_calls == 1


def test_extract_fusion_metadata_config():
    config = extract_fusion_request(
        {
            "model": "GigaChat",
            "extra_body": {
                "gpt2giga_fusion": {
                    "analysis_models": ["A"],
                    "judge_model": "Judge",
                }
            },
        },
        _settings(),
    )

    assert config is not None
    assert config.source == "metadata"
    assert config.analysis_models == ["A"]
    assert config.judge_model == "Judge"


def test_extract_fusion_explicit_disabled_plugin_falls_through():
    config = extract_fusion_request(
        {
            "model": "gpt2giga/fusion-code",
            "plugins": [{"id": "fusion", "enabled": False}],
        },
        _settings(),
    )

    assert config is None


def test_extract_fusion_ignores_non_fusion_payload():
    assert extract_fusion_request({"model": "GigaChat"}, _settings()) is None


def test_extract_fusion_rejects_recursive_internal_model():
    with pytest.raises(FusionConfigurationError):
        extract_fusion_request(
            {
                "tools": [
                    {
                        "type": "openrouter:fusion",
                        "parameters": {
                            "analysis_models": ["gpt2giga/fusion-code"],
                            "judge_model": "Judge",
                        },
                    }
                ]
            },
            _settings(),
        )


def test_extract_fusion_rejects_too_many_panel_models():
    with pytest.raises(FusionConfigurationError):
        extract_fusion_request(
            {
                "tools": [
                    {
                        "type": "openrouter:fusion",
                        "parameters": {
                            "analysis_models": ["A", "B", "C"],
                            "judge_model": "Judge",
                        },
                    }
                ]
            },
            _settings(max_panel_models=2),
        )


def test_extract_fusion_rejects_upstream_call_budget_exceeded():
    with pytest.raises(FusionConfigurationError):
        extract_fusion_request(
            {
                "tools": [
                    {
                        "type": "openrouter:fusion",
                        "parameters": {
                            "analysis_models": ["A", "B", "C"],
                            "judge_model": "Judge",
                        },
                    }
                ]
            },
            _settings(max_total_upstream_calls_per_request=3),
        )


def test_extract_fusion_accepts_selector_final_model_and_direct_candidate_options():
    config = extract_fusion_request(
        {
            "tools": [
                {
                    "type": "openrouter:fusion",
                    "parameters": {
                        "analysis_models": ["A"],
                        "judge_model": "Judge",
                        "direct_model": "Direct",
                        "final_model": "Finalizer",
                        "include_direct_candidate": True,
                        "return_selected_candidate": False,
                        "decision_mode": "selector",
                        "prompt_mode": "minimal",
                        "max_panel_output_chars": 123,
                        "max_total_panel_output_chars": 456,
                    },
                }
            ]
        },
        _settings(max_total_upstream_calls_per_request=4),
    )

    assert config is not None
    assert config.direct_model == "Direct"
    assert config.final_model == "Finalizer"
    assert config.include_direct_candidate is True
    assert config.return_selected_candidate is False
    assert config.decision_mode == "selector"
    assert config.prompt_mode == "minimal"
    assert config.max_panel_output_chars == 123
    assert config.max_total_panel_output_chars == 456


def test_extract_fusion_model_alias_can_select_accuracy_preset():
    config = extract_fusion_request(
        {"model": "gpt2giga/fusion-accuracy"},
        _settings(aliases=["gpt2giga/fusion-accuracy"]),
    )

    assert config is not None
    assert config.preset == "accuracy-ultra-selector"
    assert config.include_direct_candidate is True
    assert config.invocation_mode == "outer_auto"
    assert config.decision_mode == "tool_result"
    assert config.prompt_mode == "minimal"


def test_extract_fusion_benchmark_alias_uses_tool_aware_forced_selector_preset():
    config = extract_fusion_request(
        {"model": "gpt2giga/fusion-benchmark"},
        _settings(aliases=["gpt2giga/fusion-benchmark"]),
    )

    assert config is not None
    assert config.preset == "force-benchmark-selector-tools"
    assert config.include_direct_candidate is True
    assert config.return_selected_candidate is True
    assert config.invocation_mode == "force"
    assert config.decision_mode == "selector"
    assert config.tools_mode == "schema_only"
    assert config.direct_tool_call_policy == "selector"
    assert config.post_tool_mode == "fusion_continuation"


def test_extract_fusion_benchmark_text_alias_uses_text_only_preset():
    config = extract_fusion_request(
        {"model": "gpt2giga/fusion-benchmark-text"},
        _settings(aliases=["gpt2giga/fusion-benchmark-text"]),
    )

    assert config is not None
    assert config.preset == "force-benchmark-selector"
    assert config.tools_mode == "off"


def test_extract_fusion_benchmark_tools_alias_uses_tool_aware_preset():
    config = extract_fusion_request(
        {"model": "gpt2giga/fusion-benchmark-tools"},
        _settings(aliases=["gpt2giga/fusion-benchmark-tools"]),
    )

    assert config is not None
    assert config.preset == "force-benchmark-selector-tools"
    assert config.tools_mode == "schema_only"


def test_extract_fusion_text_only_preset_rejects_client_tools():
    with pytest.raises(FusionConfigurationError, match="tools_mode=off"):
        extract_fusion_request(
            {
                "model": "gpt2giga/fusion-benchmark-text",
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "get_weather"},
                    }
                ],
            },
            _settings(aliases=["gpt2giga/fusion-benchmark-text"]),
        )


def test_extract_fusion_openrouter_tool_config_is_not_client_tool():
    config = extract_fusion_request(
        {
            "tools": [
                {
                    "type": "openrouter:fusion",
                    "parameters": {"preset": "force-benchmark-selector"},
                }
            ],
        },
        _settings(),
    )

    assert config is not None
    assert config.tools_mode == "off"


def test_extract_fusion_rejects_recursive_direct_model():
    with pytest.raises(FusionConfigurationError):
        extract_fusion_request(
            {
                "tools": [
                    {
                        "type": "openrouter:fusion",
                        "parameters": {
                            "analysis_models": ["A"],
                            "judge_model": "Judge",
                            "direct_model": "gpt2giga/fusion-code",
                        },
                    }
                ]
            },
            _settings(),
        )


def test_extract_fusion_accepts_parallel_server_tool_budget():
    config = extract_fusion_request(
        {
            "tools": [
                {
                    "type": "openrouter:fusion",
                    "parameters": {
                        "analysis_models": ["A"],
                        "judge_model": "Judge",
                        "max_tool_calls": 8,
                    },
                }
            ]
        },
        _settings(),
    )

    assert config is not None
    assert config.max_server_tool_calls == 8
    assert config.max_client_final_tool_calls == 1


def test_extract_fusion_maps_settings_max_tool_calls_to_server_tools():
    config = extract_fusion_request(
        {"model": "gpt2giga/fusion-code"},
        _settings(max_tool_calls=2),
    )

    assert config is not None
    assert config.max_server_tool_calls == 2
    assert config.max_client_final_tool_calls == 1


def test_extract_fusion_applies_stop_server_tools_when_to_server_tools_only():
    config = extract_fusion_request(
        {
            "model": "gpt2giga/fusion-code",
            "stop_server_tools_when": {"max_tool_calls": 0},
        },
        _settings(max_server_tool_calls=8),
    )

    assert config is not None
    assert config.max_server_tool_calls == 0
    assert config.max_client_final_tool_calls == 1


def test_extract_fusion_forced_aliases_use_force_mode():
    selector = extract_fusion_request(
        {"model": "gpt2giga/fusion-force-selector"},
        _settings(aliases=["gpt2giga/fusion-force-selector"]),
    )
    synthesize = extract_fusion_request(
        {"model": "gpt2giga/fusion-force-synthesize"},
        _settings(aliases=["gpt2giga/fusion-force-synthesize"]),
    )

    assert selector is not None
    assert selector.invocation_mode == "force"
    assert selector.decision_mode == "selector"
    assert synthesize is not None
    assert synthesize.invocation_mode == "force"
    assert synthesize.decision_mode == "synthesize"


def test_extract_fusion_rejects_reserved_strict_pipeline():
    with pytest.raises(FusionConfigurationError):
        extract_fusion_request(
            {"model": "gpt2giga/fusion-code"},
            _settings(pipeline_mode="strict"),
        )
