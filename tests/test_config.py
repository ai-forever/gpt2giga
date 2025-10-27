from gpt2giga.config import ProxySettings, ProxyConfig


def test_proxy_settings_defaults():
    s = ProxySettings()
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)


def test_proxy_config_instantiation():
    c = ProxyConfig()
    assert isinstance(c.proxy_settings, ProxySettings)
