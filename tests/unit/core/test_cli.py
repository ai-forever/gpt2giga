import os

from loguru import logger as loguru_logger

from gpt2giga.app.cli import load_config
from gpt2giga.core.config.control_plane import persist_control_plane_config
from gpt2giga.core.app_meta import warn_sensitive_cli_args
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


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


def test_load_config_env_path_does_not_leak_dotenv_into_process_env(
    monkeypatch, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GIGACHAT_CREDENTIALS=foobar\nGPT2GIGA_OBSERVABILITY_SINKS=phoenix\n"
    )
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_SINKS", raising=False)
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path / "control-plane"))
    monkeypatch.setattr("sys.argv", ["prog", "--env-path", str(env_file)])

    config = load_config()

    assert config.gigachat_settings.credentials.get_secret_value() == "foobar"
    assert config.proxy_settings.observability_sinks == ["phoenix"]
    assert os.environ.get("GIGACHAT_CREDENTIALS") is None
    assert os.environ.get("GPT2GIGA_OBSERVABILITY_SINKS") is None


def test_load_config_ignores_control_plane_when_disable_persist_is_enabled(
    monkeypatch, tmp_path
):
    control_plane_dir = tmp_path / "control-plane"
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(control_plane_dir))
    persist_control_plane_config(
        ProxyConfig(
            proxy=ProxySettings(api_key="persisted-secret"),
            gigachat={"credentials": "persisted-creds"},
        )
    )

    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPT2GIGA_DISABLE_PERSIST=true\n"
        "GPT2GIGA_API_KEY=env-secret\n"
        "GIGACHAT_CREDENTIALS=env-creds\n"
    )
    monkeypatch.setattr("sys.argv", ["prog", "--env-path", str(env_file)])

    config = load_config()

    assert config.proxy_settings.disable_persist is True
    assert config.proxy_settings.api_key == "env-secret"
    assert config.gigachat_settings.credentials.get_secret_value() == "env-creds"


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
