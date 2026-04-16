import pytest

from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def test_proxy_settings_defaults(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_HOST", raising=False)
    monkeypatch.delenv("GPT2GIGA_ENABLE_REASONING", raising=False)
    monkeypatch.delenv("GPT2GIGA_ENABLED_PROVIDERS", raising=False)
    monkeypatch.delenv("GPT2GIGA_GIGACHAT_API_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_GIGACHAT_RESPONSES_API_MODE", raising=False)
    s = ProxySettings()
    assert s.mode == "DEV"
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)
    assert s.enable_reasoning is False
    assert s.enabled_providers == ["openai", "anthropic", "gemini"]
    assert s.gigachat_api_mode == "v1"
    assert s.gigachat_responses_api_mode is None
    assert s.runtime_store_backend == "memory"
    assert s.runtime_store_namespace == "gpt2giga"
    assert s.enable_telemetry is True
    assert s.observability_sinks == ["prometheus"]
    assert s.scoped_api_keys == []
    assert s.governance_limits == []
    assert s.recent_requests_max_items == 200
    assert s.recent_errors_max_items == 100
    assert s.chat_backend_mode == "v1"
    assert s.responses_backend_mode == "v1"
    assert s.max_audio_file_size_bytes == 35 * 1024 * 1024
    assert s.max_image_file_size_bytes == 15 * 1024 * 1024
    assert s.max_text_file_size_bytes == 40 * 1024 * 1024
    assert s.max_audio_image_total_size_bytes == 80 * 1024 * 1024


def test_proxy_config_instantiation():
    c = ProxyConfig()
    assert isinstance(c.proxy_settings, ProxySettings)


def test_proxy_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HOST", "127.0.0.1")
    s = ProxySettings()
    assert s.host == "127.0.0.1"


def test_proxy_settings_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_MODE", "prod")
    s = ProxySettings()
    assert s.mode == "PROD"


def test_proxy_settings_bool_cast_from_env(monkeypatch):
    # Проверяем, что строки из ENV приводятся к bool согласно pydantic
    monkeypatch.setenv("GPT2GIGA_USE_HTTPS", "true")
    s = ProxySettings()
    assert s.use_https is True


def test_proxy_settings_disable_ui_supports_prefixed_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_DISABLE_UI", "true")
    s = ProxySettings()
    assert s.disable_ui is True


def test_proxy_settings_disable_ui_supports_legacy_env(monkeypatch):
    monkeypatch.setenv("DISABLE_UI", "true")
    s = ProxySettings()
    assert s.disable_ui is True


def test_proxy_settings_enabled_providers_from_env_csv(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_ENABLED_PROVIDERS", "openai, gemini")
    s = ProxySettings()
    assert s.enabled_providers == ["openai", "gemini"]


def test_proxy_settings_enabled_providers_supports_all(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_ENABLED_PROVIDERS", "all")
    s = ProxySettings()
    assert s.enabled_providers == ["openai", "anthropic", "gemini"]


def test_proxy_settings_enabled_providers_invalid_value(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_ENABLED_PROVIDERS", "openai,unknown")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_gigachat_api_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", " V1 ")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v1"
    assert s.chat_backend_mode == "v1"
    assert s.responses_backend_mode == "v1"


def test_proxy_settings_gigachat_api_mode_v2(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", "v2")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v2"
    assert s.chat_backend_mode == "v2"
    assert s.responses_backend_mode == "v2"


def test_proxy_settings_gigachat_responses_api_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_RESPONSES_API_MODE", " V2 ")
    s = ProxySettings()
    assert s.gigachat_responses_api_mode == "v2"
    assert s.responses_backend_mode == "v2"


def test_proxy_settings_gigachat_responses_api_mode_overrides_base_mode(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", "v1")
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_RESPONSES_API_MODE", "v2")
    s = ProxySettings()
    assert s.chat_backend_mode == "v1"
    assert s.responses_backend_mode == "v2"


def test_proxy_settings_runtime_store_backend_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_RUNTIME_STORE_BACKEND", " MEMORY ")
    s = ProxySettings()
    assert s.runtime_store_backend == "memory"


def test_proxy_settings_runtime_store_dsn_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_RUNTIME_STORE_DSN", " sqlite:///tmp/runtime.db ")
    s = ProxySettings()
    assert s.runtime_store_dsn == "sqlite:///tmp/runtime.db"


def test_proxy_settings_runtime_store_grouped_view():
    s = ProxySettings(
        runtime_store_backend="sqlite",
        runtime_store_dsn="sqlite:///tmp/runtime.db",
        runtime_store_namespace="tests",
    )
    assert s.runtime_store.backend == "sqlite"
    assert s.runtime_store.dsn == "sqlite:///tmp/runtime.db"
    assert s.runtime_store.namespace == "tests"
    assert s.runtime_store.dsn_configured is True
    assert s.runtime_store.durable is True


def test_proxy_settings_enable_telemetry_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_ENABLE_TELEMETRY", "false")
    s = ProxySettings()
    assert s.enable_telemetry is False
    assert s.metrics_enabled is False


def test_proxy_settings_observability_sinks_from_env_csv(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SINKS", "prometheus, otlp")
    s = ProxySettings()
    assert s.observability_sinks == ["prometheus", "otlp"]


def test_proxy_settings_observability_sinks_supports_phoenix(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SINKS", "prometheus, phoenix")
    s = ProxySettings()
    assert s.observability_sinks == ["prometheus", "phoenix"]


def test_proxy_settings_observability_grouped_view():
    s = ProxySettings(
        enable_telemetry=True,
        observability_sinks=["prometheus", "phoenix"],
        phoenix_base_url="http://phoenix:6006",
        phoenix_project_name="local",
    )
    assert s.observability.enable_telemetry is True
    assert s.observability.active_sinks == ["prometheus", "phoenix"]
    assert s.observability.metrics_enabled is True
    assert s.observability.phoenix.base_url == "http://phoenix:6006"
    assert s.observability.phoenix.project_name == "local"


def test_proxy_settings_observability_sinks_can_be_disabled(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SINKS", " none ")
    s = ProxySettings()
    assert s.observability_sinks == []


def test_proxy_settings_phoenix_fields_normalize_blank_values():
    s = ProxySettings(
        phoenix_base_url="  ",
        phoenix_api_key="",
        phoenix_project_name="   ",
    )
    assert s.phoenix_base_url is None
    assert s.phoenix_api_key is None
    assert s.phoenix_project_name is None


def test_proxy_settings_otlp_headers_from_env_json(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_OTLP_HEADERS",
        '{"Authorization":"Bearer token","X-Scope-OrgID":"tenant-a"}',
    )
    s = ProxySettings()
    assert s.otlp_headers == {
        "Authorization": "Bearer token",
        "X-Scope-OrgID": "tenant-a",
    }


def test_proxy_settings_otlp_headers_from_env_csv(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_OTLP_HEADERS",
        "Authorization=Bearer token,X-Scope-OrgID=tenant-a",
    )
    s = ProxySettings()
    assert s.otlp_headers == {
        "Authorization": "Bearer token",
        "X-Scope-OrgID": "tenant-a",
    }


def test_proxy_settings_scoped_api_keys_from_env_json(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_SCOPED_API_KEYS",
        (
            '[{"name":"sdk","key":"secret","providers":["openai"],'
            '"endpoints":["chat/completions"],"models":["GigaChat-2-Max"]}]'
        ),
    )
    s = ProxySettings()
    assert len(s.scoped_api_keys) == 1
    assert s.scoped_api_keys[0].name == "sdk"
    assert s.scoped_api_keys[0].providers == ["openai"]
    assert s.scoped_api_keys[0].endpoints == ["chat/completions"]
    assert s.scoped_api_keys[0].models == ["GigaChat-2-Max"]


def test_proxy_settings_scoped_api_keys_invalid_json(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_SCOPED_API_KEYS", "not-json")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_governance_limits_from_env_json(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_GOVERNANCE_LIMITS",
        (
            '[{"name":"openai-burst","scope":"api_key","providers":["openai"],'
            '"endpoints":["chat/completions"],"models":["GigaChat-2-Max"],'
            '"window_seconds":60,"max_requests":3,"max_total_tokens":500}]'
        ),
    )
    s = ProxySettings()
    assert len(s.governance_limits) == 1
    rule = s.governance_limits[0]
    assert rule.name == "openai-burst"
    assert rule.scope == "api_key"
    assert rule.providers == ["openai"]
    assert rule.endpoints == ["chat/completions"]
    assert rule.models == ["GigaChat-2-Max"]
    assert rule.window_seconds == 60
    assert rule.max_requests == 3
    assert rule.max_total_tokens == 500


def test_proxy_settings_governance_limits_invalid_json(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GOVERNANCE_LIMITS", "not-json")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_governance_limits_require_threshold():
    with pytest.raises(Exception):
        ProxySettings(
            governance_limits=[
                {
                    "scope": "provider",
                    "providers": ["openai"],
                    "window_seconds": 60,
                }
            ]
        )


def test_proxy_settings_invalid_port(monkeypatch):
    # Невалидный порт должен вызвать ошибку парсинга pydantic
    monkeypatch.setenv("GPT2GIGA_PORT", "not_an_int")
    with pytest.raises(Exception):
        ProxySettings()


def test_api_key_hidden_from_repr():
    """api_key value must not appear in ProxySettings repr (visible in logs)."""
    s = ProxySettings(api_key="super-secret-key-12345")
    text = repr(s)
    assert "super-secret-key-12345" not in text
    assert "api_key=" not in text


def test_api_key_hidden_from_model_dump_exclude():
    """model_dump(exclude={'api_key'}) must not contain the key."""
    s = ProxySettings(api_key="super-secret-key-12345")
    dumped = s.model_dump(exclude={"api_key"})
    assert "api_key" not in dumped
    assert "super-secret-key-12345" not in str(dumped)


def test_scoped_api_key_hidden_from_repr():
    """Scoped API key values must not appear in ProxySettings repr."""
    s = ProxySettings(
        scoped_api_keys=[
            {"name": "sdk", "key": "scoped-secret", "providers": ["openai"]}
        ]
    )
    text = repr(s)
    assert "scoped-secret" not in text
