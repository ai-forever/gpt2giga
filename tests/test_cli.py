from gpt2giga.cli import load_config
from gpt2giga.config import ProxyConfig


def test_load_config_basic(monkeypatch):
    # Патчим аргументы командной строки и переменные окружения
    monkeypatch.setattr("sys.argv", ["prog"])
    config = load_config()
    assert isinstance(config, ProxyConfig)
