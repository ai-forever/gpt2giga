import pytest

from gpt2giga.models.config import ProxySettings, ProxyConfig


def test_proxy_settings_defaults(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_HOST", raising=False)
    s = ProxySettings()
    assert s.mode == "DEV"
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)
    assert s.enable_reasoning is False
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
