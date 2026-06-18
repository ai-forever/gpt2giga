import pytest

from gpt2giga.models.config import (
    DEFAULT_FUSION_ALIASES,
    FusionSettings,
    ProxySettings,
)


_FUSION_ENV_KEYS = [
    "GPT2GIGA_FUSION_ENABLED",
    "GPT2GIGA_FUSION_DEFAULT_PRESET",
    "GPT2GIGA_FUSION_ALIASES",
    "GPT2GIGA_FUSION_PRESETS",
    "GPT2GIGA_FUSION_MAX_PANEL_MODELS",
    "GPT2GIGA_FUSION_MAX_PANEL_CONCURRENCY",
    "GPT2GIGA_FUSION_MAX_CONCURRENT_REQUESTS",
    "GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST",
    "GPT2GIGA_FUSION_MAX_TOOL_CALLS",
    "GPT2GIGA_FUSION_STREAMING_MODE",
    "GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS",
    "GPT2GIGA_FUSION_PIPELINE_MODE",
    "GPT2GIGA_FUSION_EXPOSE_ANALYSIS_METADATA",
    "GPT2GIGA_FUSION_EXPOSE_PANEL_RESPONSES",
    "GPT2GIGA_FUSION_DEBUG_TRACE_ENABLED",
    "GPT2GIGA_FUSION_FAIL_ON_ALL_PANELS_FAILED",
]


def _clear_fusion_env(monkeypatch):
    for key in _FUSION_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_fusion_settings_defaults_are_disabled(monkeypatch):
    _clear_fusion_env(monkeypatch)

    settings = ProxySettings()

    assert settings.fusion_enabled is False
    assert settings.fusion.enabled is False
    assert settings.fusion.default_preset == "code-high"
    assert settings.fusion.aliases == DEFAULT_FUSION_ALIASES
    assert settings.fusion.presets == {}
    assert settings.fusion.streaming_mode == "buffered"
    assert settings.fusion.stream_heartbeat_seconds == 0.0
    assert settings.fusion.pipeline_mode == "compact"
    assert settings.fusion.max_concurrent_requests == 4
    assert settings.fusion.max_total_upstream_calls_per_request == 5
    assert settings.fusion.max_tool_calls == 1


def test_fusion_settings_parse_json_env(monkeypatch):
    _clear_fusion_env(monkeypatch)
    monkeypatch.setenv("GPT2GIGA_FUSION_ENABLED", "true")
    monkeypatch.setenv(
        "GPT2GIGA_FUSION_ALIASES",
        '["gpt2giga/fusion-code","GigaChat-Fusion-Code"]',
    )
    monkeypatch.setenv(
        "GPT2GIGA_FUSION_PRESETS",
        """
        {
          "code-high": {
            "analysis_models": ["GigaChat-3-Ultra", "GigaChat-2-Max"],
            "judge_model": "GigaChat-3-Ultra",
            "panel_roles": ["architect", "reviewer"],
            "temperature": 0.1,
            "max_completion_tokens": 2048,
            "min_successful_panels": 1,
            "timeout_seconds": 90,
            "tools_mode": "SCHEMA_ONLY"
          }
        }
        """,
    )
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_PANEL_MODELS", "3")
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_PANEL_CONCURRENCY", "2")
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_CONCURRENT_REQUESTS", "7")
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST", "6")
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_TOOL_CALLS", "1")
    monkeypatch.setenv("GPT2GIGA_FUSION_STREAMING_MODE", "BUFFERED")
    monkeypatch.setenv("GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS", "1.5")

    settings = ProxySettings()

    assert settings.fusion.enabled is True
    assert settings.fusion.aliases == [
        "gpt2giga/fusion-code",
        "GigaChat-Fusion-Code",
    ]
    assert settings.fusion.max_panel_models == 3
    assert settings.fusion.max_panel_concurrency == 2
    assert settings.fusion.max_concurrent_requests == 7
    assert settings.fusion.max_total_upstream_calls_per_request == 6
    assert settings.fusion.max_tool_calls == 1
    assert settings.fusion.stream_heartbeat_seconds == 1.5
    preset = settings.fusion.presets["code-high"]
    assert preset.analysis_models == ["GigaChat-3-Ultra", "GigaChat-2-Max"]
    assert preset.panel_roles == ["architect", "reviewer"]
    assert preset.tools_mode == "schema_only"


def test_fusion_aliases_parse_comma_env(monkeypatch):
    _clear_fusion_env(monkeypatch)
    monkeypatch.setenv("GPT2GIGA_FUSION_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_FUSION_ALIASES", "a, b, c")

    settings = ProxySettings()

    assert settings.fusion.aliases == ["a", "b", "c"]


def test_fusion_preset_rejects_too_many_analysis_models():
    with pytest.raises(Exception):
        FusionSettings(
            presets={
                "too-large": {
                    "analysis_models": [f"model-{index}" for index in range(9)],
                    "judge_model": "judge",
                }
            }
        )


def test_fusion_preset_rejects_recursive_alias(monkeypatch):
    _clear_fusion_env(monkeypatch)
    monkeypatch.setenv("GPT2GIGA_FUSION_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_FUSION_ALIASES", '["gpt2giga/fusion-code"]')
    monkeypatch.setenv(
        "GPT2GIGA_FUSION_PRESETS",
        """
        {
          "bad": {
            "analysis_models": ["gpt2giga/fusion-code"],
            "judge_model": "GigaChat"
          }
        }
        """,
    )

    with pytest.raises(Exception):
        ProxySettings()


def test_fusion_preset_rejects_unreachable_success_threshold():
    with pytest.raises(Exception):
        FusionSettings(
            presets={
                "bad": {
                    "analysis_models": ["GigaChat"],
                    "judge_model": "GigaChat",
                    "min_successful_panels": 2,
                }
            }
        )


def test_fusion_preset_rejects_zero_timeout():
    with pytest.raises(Exception):
        FusionSettings(
            presets={
                "bad": {
                    "analysis_models": ["GigaChat"],
                    "judge_model": "GigaChat",
                    "timeout_seconds": 0,
                }
            }
        )


def test_fusion_settings_loads_reserved_strict_pipeline(monkeypatch):
    _clear_fusion_env(monkeypatch)
    monkeypatch.setenv("GPT2GIGA_FUSION_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_FUSION_PIPELINE_MODE", "strict")

    settings = ProxySettings()

    assert settings.fusion.pipeline_mode == "strict"


def test_fusion_settings_loads_parallel_max_tool_calls(monkeypatch):
    _clear_fusion_env(monkeypatch)
    monkeypatch.setenv("GPT2GIGA_FUSION_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_TOOL_CALLS", "2")

    settings = ProxySettings()

    assert settings.fusion.max_tool_calls == 2


def test_fusion_settings_loads_reserved_final_model():
    settings = FusionSettings(
        presets={
            "bad": {
                "analysis_models": ["GigaChat"],
                "judge_model": "GigaChat",
                "final_model": "GigaChat-Pro",
            }
        }
    )

    assert settings.presets["bad"].final_model == "GigaChat-Pro"


def test_disabled_fusion_ignores_stale_reserved_env(monkeypatch):
    _clear_fusion_env(monkeypatch)
    monkeypatch.setenv("GPT2GIGA_FUSION_ENABLED", "false")
    monkeypatch.setenv("GPT2GIGA_FUSION_MAX_TOOL_CALLS", "16")
    monkeypatch.setenv(
        "GPT2GIGA_FUSION_PRESETS",
        """
        {
          "stale": {
            "analysis_models": ["GigaChat"],
            "judge_model": "GigaChat",
            "final_model": "GigaChat-Pro"
          }
        }
        """,
    )

    settings = ProxySettings()

    assert settings.fusion.enabled is False
