import pytest

from gpt2giga.config import ProxySettings, ProxyConfig


def test_proxy_settings_defaults(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_HOST", raising=False)
    s = ProxySettings()
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)


def test_proxy_config_instantiation():
    c = ProxyConfig()
    assert isinstance(c.proxy_settings, ProxySettings)


def test_proxy_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HOST", "127.0.0.1")
    s = ProxySettings()
    assert s.host == "127.0.0.1"


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
