"""Opt-in smoke tests for Gemini clients against a real gpt2giga server."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
import uvicorn
from dotenv import load_dotenv
from google import genai
from google.genai import types

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings

pytestmark = [pytest.mark.integration, pytest.mark.live_gigachat, pytest.mark.slow]

_TRUE_VALUES = {"1", "true", "yes", "on"}
_BASE_PATHS = ("", "/v1", "/v2", "/v1beta", "/v1/v1beta", "/v2/v1beta")


@dataclass(frozen=True)
class SmokeServer:
    """Represent one running smoke-test server."""

    base_url: str
    api_key: str
    auth_enabled: bool

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"


def _load_live_env_file() -> None:
    env_file = os.getenv("GPT2GIGA_LIVE_ENV_FILE", ".env.live").strip()
    if not env_file:
        return
    path = Path(env_file)
    if path.exists():
        load_dotenv(path, override=False)


_load_live_env_file()


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def _configured(value: str | None) -> bool:
    if value is None:
        return False
    value = value.strip()
    return bool(value) and "REPLACE_WITH" not in value and not value.startswith("<")


def _has_live_auth() -> bool:
    if _configured(os.getenv("GIGACHAT_ACCESS_TOKEN")):
        return True
    if _configured(os.getenv("GIGACHAT_CREDENTIALS")):
        return True
    return (
        _configured(os.getenv("GIGACHAT_USER"))
        and _configured(os.getenv("GIGACHAT_PASSWORD"))
        and _configured(os.getenv("GIGACHAT_BASE_URL"))
    )


def _skip_reason() -> str | None:
    if not _enabled(os.getenv("GPT2GIGA_RUN_GEMINI_SMOKE")):
        return "set GPT2GIGA_RUN_GEMINI_SMOKE=1 to run Gemini client smoke tests"
    if not _has_live_auth():
        return (
            "set GIGACHAT_ACCESS_TOKEN, GIGACHAT_CREDENTIALS, or "
            "GIGACHAT_USER+GIGACHAT_PASSWORD+GIGACHAT_BASE_URL"
        )
    return None


@pytest.fixture(scope="session", autouse=True)
def require_gemini_smoke_env() -> None:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)


@pytest.fixture(scope="session")
def smoke_model() -> str:
    return os.getenv("GPT2GIGA_GEMINI_SMOKE_MODEL") or os.getenv(
        "GPT2GIGA_LIVE_MODEL",
        os.getenv("GIGACHAT_MODEL", "GigaChat"),
    )


@pytest.fixture(scope="session", params=[False, True], ids=["auth-off", "auth-on"])
def smoke_server(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[SmokeServer]:
    auth_enabled = bool(request.param)
    api_key = os.getenv("GPT2GIGA_GEMINI_SMOKE_API_KEY", "gemini-smoke-key")
    log_path = tmp_path_factory.mktemp("gpt2giga-gemini-smoke") / (
        "auth-on.log" if auth_enabled else "auth-off.log"
    )
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                mode="DEV",
                enable_api_key_auth=auth_enabled,
                api_key=api_key,
                log_filename=str(log_path),
                default_max_tokens=32,
                gigachat_api_mode="v1",
            )
        )
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [sock]},
        daemon=True,
    )
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Timed out while starting gpt2giga smoke server")
    try:
        yield SmokeServer(
            base_url=f"http://127.0.0.1:{port}",
            api_key=api_key if auth_enabled else "0",
            auth_enabled=auth_enabled,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _genai_client(server: SmokeServer, base_path: str):
    return genai.Client(
        api_key=server.api_key,
        http_options=types.HttpOptions(
            base_url=server.url(base_path),
            api_version="",
            timeout=60_000,
        ),
    )


def _prompt(label: str) -> str:
    return f"Gemini smoke {label}. Reply with one short sentence."


@pytest.mark.parametrize("base_path", _BASE_PATHS)
def test_google_genai_generate_content_base_url_matrix(
    smoke_server: SmokeServer,
    smoke_model: str,
    base_path: str,
) -> None:
    client = _genai_client(smoke_server, base_path)

    response = client.models.generate_content(
        model=smoke_model,
        contents=_prompt(f"generate {base_path or 'root'}"),
        config=types.GenerateContentConfig(
            max_output_tokens=32,
            temperature=0,
        ),
    )

    assert response.text


def test_google_genai_stream_generate_content(
    smoke_server: SmokeServer,
    smoke_model: str,
) -> None:
    client = _genai_client(smoke_server, "")

    chunks = client.models.generate_content_stream(
        model=smoke_model,
        contents=_prompt("stream"),
        config=types.GenerateContentConfig(
            max_output_tokens=32,
            temperature=0,
        ),
    )
    text = "".join(chunk.text or "" for chunk in chunks)

    assert text


def _gemini_cli_command() -> list[str]:
    raw = os.getenv("GPT2GIGA_GEMINI_CLI_COMMAND", "gemini")
    command = shlex.split(raw)
    if not command:
        pytest.skip("set GPT2GIGA_GEMINI_CLI_COMMAND to run Gemini CLI smoke tests")
    if shutil.which(command[0]) is None:
        pytest.skip(f"Gemini CLI command not found: {command[0]}")
    return command


def _run_gemini_cli(
    smoke_server: SmokeServer,
    smoke_model: str,
    tmp_path: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GOOGLE_GEMINI_BASE_URL": smoke_server.base_url,
            "GEMINI_API_KEY": smoke_server.api_key,
            "GEMINI_MODEL": smoke_model,
            "GEMINI_CLI_HOME": str(tmp_path / "gemini-cli-home"),
            "GEMINI_CLI_TRUST_WORKSPACE": "true",
        }
    )
    timeout = int(os.getenv("GPT2GIGA_GEMINI_CLI_TIMEOUT", "120"))
    return subprocess.run(
        [
            *_gemini_cli_command(),
            "-m",
            smoke_model,
            "-p",
            _prompt("cli"),
            "--skip-trust",
            *extra_args,
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=timeout,
    )


def test_gemini_cli_basic_prompt(
    smoke_server: SmokeServer,
    smoke_model: str,
    tmp_path: Path,
) -> None:
    result = _run_gemini_cli(smoke_server, smoke_model, tmp_path)

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip()


def test_gemini_cli_json_output(
    smoke_server: SmokeServer,
    smoke_model: str,
    tmp_path: Path,
) -> None:
    result = _run_gemini_cli(
        smoke_server,
        smoke_model,
        tmp_path,
        "--output-format",
        "json",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert _parse_cli_json(result.stdout)


def _parse_cli_json(stdout: str) -> dict[str, object]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value

    for line in reversed([item for item in stdout.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"Gemini CLI did not produce JSON output: {stdout}")
