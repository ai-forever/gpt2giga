import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.config import ProxyConfig
from gpt2giga.routers import system_router, logs_router


@pytest.fixture
def temp_log_file(tmp_path):
    log_file = tmp_path / "gpt2giga.log"
    log_file.write_text("INFO: this is a test log line\n")
    return log_file


def make_app():
    app = FastAPI()
    app.include_router(system_router)
    app.include_router(logs_router)
    app.state.config = ProxyConfig()
    return app


def test_logs_ok_reads_last_lines(temp_log_file):
    app = make_app()
    app.state.config.proxy_settings.log_filename = temp_log_file
    client = TestClient(app)
    # по умолчанию log_filename = gpt2giga.log, файл присутствует в репо
    resp = client.get("/logs", params={"lines": 1})
    assert resp.status_code == 200


def test_logs_not_found():
    app = make_app()
    app.state.config.proxy_settings.log_filename = "__no_such_file__.log"
    client = TestClient(app)
    resp = client.get("/logs")
    assert resp.status_code == 404
    assert "Log file not found" in resp.text


def test_logs_html_ok():
    app = make_app()
    app.include_router(logs_router)
    client = TestClient(app)
    resp = client.get("/logs/html")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_logs_read_exception(temp_log_file, monkeypatch):
    app = make_app()
    app.state.config.proxy_settings.log_filename = temp_log_file

    # Mock open to raise exception
    def broken_open(*args, **kwargs):
        raise IOError("Disk error")

    monkeypatch.setattr("builtins.open", broken_open)

    # Need to mock logger because exception handler uses it
    from unittest.mock import MagicMock

    app.state.logger = MagicMock()

    client = TestClient(app)
    resp = client.get("/logs")
    assert resp.status_code == 500
    assert "Error: Disk error" in resp.text


def test_logs_stream_init_error(temp_log_file, monkeypatch):
    app = make_app()
    app.state.config.proxy_settings.log_filename = temp_log_file

    # Mock open to raise exception ONLY on first call inside stream logic?
    # Actually easier to mock open globally but we need it to work for other things?
    # The stream_logs function opens file inside the generator.

    def broken_open(*args, **kwargs):
        raise OSError("Can't open")

    monkeypatch.setattr("builtins.open", broken_open)

    client = TestClient(app)
    with client.stream("GET", "/logs/stream") as r:
        found_error = False
        for line in r.iter_lines():
            if not line:
                continue
            text = line if isinstance(line, str) else line.decode()
            if "Error accessing log file" in text:
                found_error = True
                break
        assert found_error
