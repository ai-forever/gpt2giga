import pytest

from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def test_proxy_settings_defaults(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_HOST", raising=False)
    monkeypatch.delenv("GPT2GIGA_ENABLE_REASONING", raising=False)
    monkeypatch.delenv("GPT2GIGA_ENABLED_PROVIDERS", raising=False)
    monkeypatch.delenv("GPT2GIGA_GIGACHAT_API_MODE", raising=False)
    s = ProxySettings()
    assert s.mode == "DEV"
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)
    assert s.enable_reasoning is False
    assert s.enabled_providers == ["openai", "anthropic", "gemini"]
    assert s.gigachat_api_mode == "v1"
    assert s.runtime_store_backend == "memory"
    assert s.runtime_store_namespace == "gpt2giga"
    assert s.observability_sinks == ["prometheus"]
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
    assert s.responses_backend_mode == "v1"


def test_proxy_settings_gigachat_api_mode_v2(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", "v2")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v2"
    assert s.chat_backend_mode == "v2"
    assert s.responses_backend_mode == "v2"


def test_proxy_settings_runtime_store_backend_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_RUNTIME_STORE_BACKEND", " MEMORY ")
    s = ProxySettings()
    assert s.runtime_store_backend == "memory"


def test_proxy_settings_observability_sinks_from_env_csv(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SINKS", "prometheus, otlp")
    s = ProxySettings()
    assert s.observability_sinks == ["prometheus", "otlp"]


def test_proxy_settings_observability_sinks_can_be_disabled(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SINKS", " none ")
    s = ProxySettings()
    assert s.observability_sinks == []


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
