import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.models.config import ProxyConfig
from gpt2giga.routers import logs_api_router, logs_router, system_router


@pytest.fixture
def temp_log_file(tmp_path):
    log_file = tmp_path / "gpt2giga.log"
    log_file.write_text("INFO: this is a test log line\n")
    return log_file


def make_app(logs_ip_allowlist=None):
    app = FastAPI()
    app.include_router(system_router)
    app.include_router(logs_api_router)
    app.include_router(logs_router)
    config = ProxyConfig()
    if logs_ip_allowlist is not None:
        config.proxy_settings.logs_ip_allowlist = logs_ip_allowlist
    app.state.config = config
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


# --- IP allowlist tests ---


def test_logs_ip_allowlist_empty_allows_all(temp_log_file):
    """Empty allowlist means no restriction."""
    app = make_app(logs_ip_allowlist=[])
    app.state.config.proxy_settings.log_filename = temp_log_file
    client = TestClient(app)
    resp = client.get("/logs", params={"lines": 1})
    assert resp.status_code == 200


def test_logs_ip_allowlist_blocks_unknown_ip(temp_log_file):
    """If allowlist is set and client IP is not in it, access is denied."""
    app = make_app(logs_ip_allowlist=["192.168.1.100"])
    app.state.config.proxy_settings.log_filename = temp_log_file
    client = TestClient(app)
    resp = client.get("/logs", params={"lines": 1})
    assert resp.status_code == 403
    assert "IP not in logs allowlist" in resp.json()["detail"]


def test_logs_ip_allowlist_allows_matching_ip(temp_log_file):
    """If client IP matches the allowlist, access is granted."""
    app = make_app(logs_ip_allowlist=["testclient", "127.0.0.1"])
    app.state.config.proxy_settings.log_filename = temp_log_file
    client = TestClient(app)
    resp = client.get("/logs", params={"lines": 1})
    assert resp.status_code == 200


def test_logs_html_ip_allowlist_blocks(temp_log_file):
    """IP allowlist also applies to /logs/html."""
    app = make_app(logs_ip_allowlist=["192.168.1.100"])
    client = TestClient(app)
    resp = client.get("/logs/html")
    assert resp.status_code == 403


def test_logs_stream_ip_allowlist_blocks(temp_log_file):
    """IP allowlist also applies to /logs/stream."""
    app = make_app(logs_ip_allowlist=["192.168.1.100"])
    app.state.config.proxy_settings.log_filename = temp_log_file
    client = TestClient(app)
    resp = client.get("/logs/stream")
    assert resp.status_code == 403


def test_logs_ip_allowlist_xforwardedfor(temp_log_file):
    """X-Forwarded-For header is used for IP detection."""
    app = make_app(logs_ip_allowlist=["10.0.0.5"])
    app.state.config.proxy_settings.log_filename = temp_log_file
    client = TestClient(app)
    resp = client.get(
        "/logs",
        params={"lines": 1},
        headers={"X-Forwarded-For": "10.0.0.5, 172.16.0.1"},
    )
    assert resp.status_code == 200


def test_logs_html_warning_banner():
    """Verify the warning banner is present in the log viewer HTML."""
    app = make_app()
    client = TestClient(app)
    resp = client.get("/logs/html")
    assert resp.status_code == 200
    assert "WARNING" in resp.text
    assert "sensitive information" in resp.text
