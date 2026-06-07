import pytest

from gpt2giga.models.config import ProxyConfig, ProxySettings


def test_proxy_settings_defaults(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_HOST", raising=False)
    monkeypatch.delenv("GPT2GIGA_PASS_MODEL", raising=False)
    monkeypatch.delenv("GPT2GIGA_ENABLE_REASONING", raising=False)
    monkeypatch.delenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_GIGACHAT_API_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_RESPONSES_API_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER", raising=False)
    monkeypatch.delenv("GPT2GIGA_NORMALIZATION_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_LEGACY_CHAT_FALLBACK", raising=False)
    monkeypatch.delenv("GPT2GIGA_TRAFFIC_LOG_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_UI_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_DEBUG_TRANSLATE_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("GPT2GIGA_DEFAULT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODEL_MAX_CONNECTIONS", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", raising=False)
    s = ProxySettings()
    assert s.mode == "DEV"
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)
    assert s.pass_model is True
    assert s.enable_reasoning is False
    assert s.structured_output_mode == "function_call"
    assert s.gigachat_api_mode == "v1"
    assert s.responses_api_mode == "inherit"
    assert s.resolve_responses_api_mode() == "v1"
    assert s.experimental_normalized_layer is False
    assert s.normalization_mode == "off"
    assert s.legacy_chat_fallback is True
    assert s.traffic_log_enabled is False
    assert s.observability_enabled is False
    assert s.ui_enabled is False
    assert s.debug_translate_enabled is False
    assert s.admin_api_key is None
    assert s.max_audio_file_size_bytes == 35 * 1024 * 1024
    assert s.max_image_file_size_bytes == 15 * 1024 * 1024
    assert s.max_text_file_size_bytes == 40 * 1024 * 1024
    assert s.max_audio_image_total_size_bytes == 80 * 1024 * 1024
    assert s.default_max_tokens is None
    assert s.model_max_connections == {}
    assert s.model_max_connections_default is None
    assert s.model_max_connections_acquire_timeout is None


def test_proxy_config_instantiation():
    c = ProxyConfig()
    assert isinstance(c.proxy_settings, ProxySettings)


def test_proxy_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HOST", "127.0.0.1")
    s = ProxySettings()
    assert s.host == "127.0.0.1"


def test_proxy_settings_default_max_tokens_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_DEFAULT_MAX_TOKENS", "128000")

    s = ProxySettings()

    assert s.default_max_tokens == 128000


@pytest.mark.parametrize("env_value", ["0", "-1"])
def test_proxy_settings_default_max_tokens_must_be_positive(monkeypatch, env_value):
    monkeypatch.setenv("GPT2GIGA_DEFAULT_MAX_TOKENS", env_value)

    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_model_max_connections_from_env(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_MODEL_MAX_CONNECTIONS",
        '{"GigaChat":1,"GigaChat-Pro":2,"GigaChat-Max":5}',
    )
    monkeypatch.setenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", "3")
    monkeypatch.setenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", "30")

    s = ProxySettings()

    assert s.model_max_connections == {
        "GigaChat": 1,
        "GigaChat-Pro": 2,
        "GigaChat-Max": 5,
    }
    assert s.model_max_connections_default == 3
    assert s.model_max_connections_acquire_timeout == 30


def test_proxy_settings_model_max_connections_timeout_zero_is_valid(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", "0")

    s = ProxySettings()

    assert s.model_max_connections_acquire_timeout == 0


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS", '{"GigaChat":0}'),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS", '{"GigaChat":-1}'),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", "0"),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", "-1"),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", "-1"),
    ],
)
def test_proxy_settings_invalid_model_max_connections(monkeypatch, env_name, env_value):
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_MODE", "prod")
    s = ProxySettings()
    assert s.mode == "PROD"


def test_proxy_settings_bool_cast_from_env(monkeypatch):
    # Проверяем, что строки из ENV приводятся к bool согласно pydantic
    monkeypatch.setenv("GPT2GIGA_USE_HTTPS", "true")
    s = ProxySettings()
    assert s.use_https is True


def test_proxy_settings_structured_output_mode_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", "native")
    s = ProxySettings()
    assert s.structured_output_mode == "native"


def test_proxy_settings_structured_output_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", " NATIVE ")
    s = ProxySettings()
    assert s.structured_output_mode == "native"


def test_proxy_settings_invalid_structured_output_mode(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", "unsupported")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_gigachat_api_mode_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", "v2")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v2"
    assert s.resolve_responses_api_mode() == "v2"


@pytest.mark.parametrize("mode", ["v1", "v2", "inherit"])
def test_proxy_settings_responses_api_mode_from_env(monkeypatch, mode):
    monkeypatch.setenv("GPT2GIGA_RESPONSES_API_MODE", mode)
    s = ProxySettings()
    assert s.responses_api_mode == mode


def test_proxy_settings_responses_api_mode_empty_env_inherits(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_GIGACHAT_API_MODE", raising=False)
    monkeypatch.setenv("GPT2GIGA_RESPONSES_API_MODE", "")
    s = ProxySettings()
    assert s.responses_api_mode == "inherit"
    assert s.resolve_responses_api_mode() == "v1"


def test_proxy_settings_modular_feature_flags_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER", "true")
    monkeypatch.setenv("GPT2GIGA_NORMALIZATION_MODE", " SHADOW ")
    monkeypatch.setenv("GPT2GIGA_LEGACY_CHAT_FALLBACK", "false")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINK", " JSONL ")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_JSONL_PATH", "/tmp/gpt2giga-traffic.jsonl")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_UI_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_DEBUG_TRANSLATE_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_ADMIN_API_KEY", "admin-secret")

    s = ProxySettings()

    assert s.experimental_normalized_layer is True
    assert s.normalization_mode == "shadow"
    assert s.legacy_chat_fallback is False
    assert s.traffic_log_enabled is True
    assert s.traffic_log_sink == "jsonl"
    assert s.traffic_log_jsonl_path == "/tmp/gpt2giga-traffic.jsonl"
    assert s.observability_enabled is True
    assert s.ui_enabled is True
    assert s.debug_translate_enabled is True
    assert s.admin_api_key == "admin-secret"


def test_proxy_settings_invalid_traffic_log_sink(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINK", "postgres")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_invalid_normalization_mode(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_NORMALIZATION_MODE", "unsupported")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_api_modes_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", " V2 ")
    monkeypatch.setenv("GPT2GIGA_RESPONSES_API_MODE", " V1 ")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v2"
    assert s.responses_api_mode == "v1"
    assert s.resolve_responses_api_mode() == "v1"


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("GPT2GIGA_GIGACHAT_API_MODE", "inherit"),
        ("GPT2GIGA_GIGACHAT_API_MODE", "unsupported"),
        ("GPT2GIGA_RESPONSES_API_MODE", "unsupported"),
    ],
)
def test_proxy_settings_invalid_api_modes(monkeypatch, env_name, env_value):
    monkeypatch.setenv(env_name, env_value)
    with pytest.raises(Exception):
        ProxySettings()


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


def test_admin_api_key_hidden_from_repr():
    """admin_api_key value must not appear in ProxySettings repr."""
    s = ProxySettings(admin_api_key="admin-secret-12345")
    text = repr(s)
    assert "admin-secret-12345" not in text
    assert "admin_api_key=" not in text
