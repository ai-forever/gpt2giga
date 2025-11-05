from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.config import ProxyConfig
from gpt2giga.routers import system_router, logs_router


def make_app():
    app = FastAPI()
    app.include_router(system_router)
    app.state.config = ProxyConfig()
    return app


def test_logs_ok_reads_last_lines():
    app = make_app()
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


def test_logs_stream_file_missing_sends_error_event():
    app = make_app()
    app.state.config.proxy_settings.log_filename = "__no_such_file__.log"
    client = TestClient(app)

    with client.stream("GET", "/logs/stream") as r:
        # Найдём первую строку data: ... с сообщением об ошибке
        found = False
        for line in r.iter_lines():
            if not line:
                continue
            text = line.decode() if isinstance(line, (bytes, bytearray)) else line
            if text.startswith("data:") and "Log file not found" in text:
                found = True
                break
        assert found
