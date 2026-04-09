from loguru import logger as loguru_logger

from gpt2giga.cli import load_config
from gpt2giga.common.app_meta import warn_sensitive_cli_args
from gpt2giga.models.config import ProxyConfig


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
    # Булевы флаги должны выставляться как True/False
    # Используем новый формат аргументов pydantic-settings для вложенных моделей
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--proxy.use-https",
            "true",
            "--proxy.pass-model",
            "true",
            "--gigachat.verify-ssl-certs",
            "false",
        ],
    )
    config = load_config()
    assert config.proxy_settings.use_https is True
    assert config.proxy_settings.pass_model is True
    assert config.gigachat_settings.verify_ssl_certs is False


def test_warn_sensitive_cli_args_credentials(monkeypatch):
    """Log warning is emitted when --gigachat.credentials is passed via CLI."""
    monkeypatch.setattr("sys.argv", ["prog", "--gigachat.credentials", "secret123"])

    calls: list[str] = []

    def _spy_warning(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr(loguru_logger, "warning", _spy_warning)
    warn_sensitive_cli_args()

    assert len(calls) == 1
    assert "security warning" in calls[0].lower()
    assert "--gigachat.credentials" in calls[0]


def test_warn_sensitive_cli_args_multiple(monkeypatch):
    """Warning lists all sensitive arguments found."""
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--gigachat.credentials", "x", "--proxy.api-key", "y"],
    )
    calls: list[str] = []

    def _spy_warning(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr(loguru_logger, "warning", _spy_warning)
    warn_sensitive_cli_args()

    assert len(calls) == 1
    msg = calls[0]
    assert "--gigachat.credentials" in msg
    assert "--proxy.api-key" in msg


def test_warn_sensitive_cli_args_equals_form(monkeypatch):
    """Warning detects --gigachat.password=secret form."""
    monkeypatch.setattr("sys.argv", ["prog", "--gigachat.password=secret"])
    calls: list[str] = []

    def _spy_warning(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr(loguru_logger, "warning", _spy_warning)
    warn_sensitive_cli_args()

    assert len(calls) == 1
    assert "--gigachat.password=secret" in calls[0]


def test_no_warning_for_safe_args(monkeypatch):
    """No warning when only non-sensitive arguments are used."""
    monkeypatch.setattr(
        "sys.argv", ["prog", "--proxy.host", "0.0.0.0", "--proxy.port", "9000"]
    )
    calls: list[str] = []

    def _spy_warning(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr(loguru_logger, "warning", _spy_warning)
    warn_sensitive_cli_args()

    assert calls == []
