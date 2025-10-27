from gpt2giga.cli import load_config
from gpt2giga.config import ProxyConfig


def test_load_config_basic(monkeypatch):
    # Патчим аргументы командной строки и переменные окружения
    monkeypatch.setattr("sys.argv", ["prog"])
    config = load_config()
    assert isinstance(config, ProxyConfig)


def test_load_config_env_path(monkeypatch, tmp_path):
    # Создадим временный .env
    env_file = tmp_path / ".env"
    env_file.write_text("GIGACHAT_CREDENTIALS=foobar\n")
    monkeypatch.setattr("sys.argv", ["prog", "--env-path", str(env_file)])
    config = load_config()
    assert isinstance(config, ProxyConfig)


def test_load_config_boolean_flags(monkeypatch):
    # Булевы флаги должны выставляться как True
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--proxy-use-https",
            "--gigachat-verify-prompt-limit",
        ],
    )
    config = load_config()
    assert config.proxy_settings.use_https is True
    assert getattr(config.gigachat_settings, "verify_prompt_limit", False) is False
