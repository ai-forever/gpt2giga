import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import admin_api_router, admin_router, legacy_logs_router
from gpt2giga.api.system import system_router
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


@pytest.fixture
def temp_log_file(tmp_path):
    log_file = tmp_path / "gpt2giga.log"
    log_file.write_text("INFO: this is a test log line\n")
    return log_file


def make_app(logs_ip_allowlist=None, config=None):
    app = FastAPI()
    app.include_router(system_router)
    app.include_router(admin_api_router)
    app.include_router(admin_router)
    app.include_router(legacy_logs_router)
    config = config or ProxyConfig(proxy=ProxySettings())
    if logs_ip_allowlist is not None:
        config.proxy_settings.logs_ip_allowlist = logs_ip_allowlist
    ensure_runtime_dependencies(app.state, config=config)
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


def test_admin_ui_ok():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()
    assert "Admin Surface" in resp.text
    assert "Capability Matrix" in resp.text
    assert "Clear filters" in resp.text


def test_legacy_logs_html_redirects_to_admin():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/logs/html", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/admin?tab=logs"
    assert resp.headers["deprecation"] == "true"


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


def test_logs_html_ip_allowlist_blocks():
    """IP allowlist also applies to /admin."""
    app = make_app(logs_ip_allowlist=["192.168.1.100"])
    client = TestClient(app)
    resp = client.get("/admin")
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


def test_admin_ui_warning_banner():
    """Verify the warning banner is present in the admin UI."""
    app = make_app()
    client = TestClient(app)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Warning" in resp.text
    assert "sensitive details" in resp.text


def test_admin_runtime_endpoint():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/admin/api/runtime")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["mode"] == "DEV"
    assert payload["admin_enabled"] is True
    assert payload["telemetry_enabled"] is True
    assert payload["runtime_store_backend"] == "memory"
    assert payload["state"]["stores"]["backend"] == "memory"
    assert payload["state"]["stores"]["usage_by_api_key"] == 0
    assert payload["state"]["stores"]["usage_by_provider"] == 0


def test_admin_capabilities_reflect_enabled_providers():
    app = make_app()
    app.state.config.proxy_settings.enabled_providers = ["openai", "gemini"]
    client = TestClient(app)
    resp = client.get("/admin/api/capabilities")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["providers"]["openai"]["enabled"] is True
    assert payload["providers"]["anthropic"]["enabled"] is False
    assert payload["providers"]["gemini"]["enabled"] is True
    matrix_names = {row["name"] for row in payload["matrix"]["rows"]}
    assert {"openai", "anthropic", "gemini", "system", "admin"} <= matrix_names


def test_admin_config_exposes_grouped_safe_summary():
    app = make_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                host="localhost",
                port=8090,
                gigachat_api_mode="v1",
                runtime_store_backend="memory",
                enable_telemetry=True,
            )
        )
    )
    client = TestClient(app)

    resp = client.get("/admin/api/config")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"]["network"]["bind"] == "localhost:8090"
    assert payload["summary"]["providers"]["gigachat_api_mode"] == "v1"
    assert payload["summary"]["providers"]["telemetry_enabled"] is True
    assert payload["summary"]["limits"]["max_request_body_bytes"] > 0
    assert payload["summary"]["logging"]["log_filename"] == "gpt2giga.log"


def test_admin_runtime_reflects_disabled_telemetry():
    app = make_app(config=ProxyConfig(proxy=ProxySettings(enable_telemetry=False)))
    client = TestClient(app)

    resp = client.get("/admin/api/runtime")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["telemetry_enabled"] is False
    assert payload["metrics_enabled"] is False


def test_admin_recent_endpoints_support_extended_filters():
    app = make_app()
    app.state.stores.recent_requests.append(
        {
            "created_at": "2026-04-11T10:00:00Z",
            "request_id": "req-openai",
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "path": "/v1/chat/completions",
            "status_code": 200,
            "duration_ms": 41.0,
            "stream_duration_ms": None,
            "client_ip": "127.0.0.1",
            "model": "gpt-4.1-mini",
            "token_usage": {
                "prompt_tokens": 4,
                "completion_tokens": 6,
                "total_tokens": 10,
            },
            "error_type": None,
        }
    )
    app.state.stores.recent_requests.append(
        {
            "created_at": "2026-04-11T10:01:00Z",
            "request_id": "req-gemini",
            "provider": "gemini",
            "endpoint": "/v1beta/models/gemini:generateContent",
            "method": "POST",
            "path": "/v1beta/models/gemini:generateContent",
            "status_code": 429,
            "duration_ms": 63.0,
            "stream_duration_ms": 81.0,
            "client_ip": "127.0.0.1",
            "model": "gemini-2.5-pro",
            "token_usage": None,
            "error_type": "RateLimitError",
        }
    )
    app.state.stores.recent_errors.append(app.state.stores.recent_requests.recent()[-1])

    client = TestClient(app)
    resp = client.get(
        "/admin/api/errors/recent",
        params={
            "provider": "gemini",
            "method": "POST",
            "status_code": 429,
            "model": "gemini-2.5-pro",
            "error_type": "RateLimitError",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["events"][0]["request_id"] == "req-gemini"
    assert payload["filters"] == {
        "provider": "gemini",
        "endpoint": None,
        "method": "POST",
        "status_code": 429,
        "model": "gemini-2.5-pro",
        "error_type": "RateLimitError",
    }
    assert payload["available_filters"]["provider"] == ["gemini"]
    assert payload["available_filters"]["status_code"] == [429]


def test_admin_recent_endpoints_return_empty_payload_by_default():
    app = make_app()
    client = TestClient(app)

    recent_requests = client.get("/admin/api/requests/recent")
    recent_errors = client.get("/admin/api/errors/recent")

    assert recent_requests.status_code == 200
    assert recent_requests.json() == {
        "events": [],
        "count": 0,
        "kind": "requests",
        "limit": 50,
        "filters": {
            "provider": None,
            "endpoint": None,
            "method": None,
            "status_code": None,
            "model": None,
            "error_type": None,
        },
        "available_filters": {
            "provider": [],
            "endpoint": [],
            "method": [],
            "status_code": [],
            "model": [],
            "error_type": [],
        },
    }
    assert recent_errors.status_code == 200
    assert recent_errors.json() == {
        "events": [],
        "count": 0,
        "kind": "errors",
        "limit": 50,
        "filters": {
            "provider": None,
            "endpoint": None,
            "method": None,
            "status_code": None,
            "model": None,
            "error_type": None,
        },
        "available_filters": {
            "provider": [],
            "endpoint": [],
            "method": [],
            "status_code": [],
            "model": [],
            "error_type": [],
        },
    }


def test_admin_usage_endpoints_return_aggregated_payloads():
    app = make_app()
    app.state.stores.usage_by_api_key["sdk-openai"] = {
        "kind": "api_key",
        "name": "sdk-openai",
        "source": "scoped",
        "request_count": 2,
        "success_count": 2,
        "error_count": 0,
        "prompt_tokens": 7,
        "completion_tokens": 5,
        "total_tokens": 12,
        "models": {
            "GigaChat-2-Max": {
                "request_count": 2,
                "success_count": 2,
                "error_count": 0,
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
            }
        },
        "endpoints": {"/chat/completions": {"request_count": 2, "total_tokens": 12}},
        "providers": {"openai": {"request_count": 2, "total_tokens": 12}},
        "first_seen_at": "2026-04-11T10:00:00Z",
        "last_seen_at": "2026-04-11T10:01:00Z",
    }
    app.state.stores.usage_by_provider["openai"] = {
        "kind": "provider",
        "provider": "openai",
        "request_count": 2,
        "success_count": 2,
        "error_count": 0,
        "prompt_tokens": 7,
        "completion_tokens": 5,
        "total_tokens": 12,
        "models": {
            "GigaChat-2-Max": {
                "request_count": 2,
                "success_count": 2,
                "error_count": 0,
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
            }
        },
        "endpoints": {"/chat/completions": {"request_count": 2, "total_tokens": 12}},
        "api_keys": {"sdk-openai": {"request_count": 2, "total_tokens": 12}},
        "first_seen_at": "2026-04-11T10:00:00Z",
        "last_seen_at": "2026-04-11T10:01:00Z",
    }

    client = TestClient(app)
    by_key = client.get(
        "/admin/api/usage/keys",
        params={"provider": "openai", "model": "GigaChat-2-Max", "source": "scoped"},
    )
    by_provider = client.get(
        "/admin/api/usage/providers",
        params={"provider": "openai", "api_key_name": "sdk-openai"},
    )

    assert by_key.status_code == 200
    assert by_key.json() == {
        "entries": [app.state.stores.usage_by_api_key["sdk-openai"]],
        "count": 1,
        "kind": "keys",
        "limit": 50,
        "filters": {
            "provider": "openai",
            "model": "GigaChat-2-Max",
            "api_key_name": None,
            "source": "scoped",
        },
        "available_filters": {
            "provider": ["openai"],
            "model": ["GigaChat-2-Max"],
            "api_key_name": [],
            "source": ["scoped"],
        },
        "summary": {
            "request_count": 2,
            "success_count": 2,
            "error_count": 0,
            "prompt_tokens": 7,
            "completion_tokens": 5,
            "total_tokens": 12,
        },
    }
    assert by_provider.status_code == 200
    assert by_provider.json()["entries"][0]["provider"] == "openai"
    assert by_provider.json()["available_filters"]["api_key_name"] == ["sdk-openai"]
    assert by_provider.json()["summary"]["total_tokens"] == 12


def test_admin_recent_endpoints_support_sqlite_backend_queries(tmp_path):
    config = ProxyConfig(
        proxy=ProxySettings(
            runtime_store_backend="sqlite",
            runtime_store_dsn=str(tmp_path / "runtime.sqlite3"),
            runtime_store_namespace="admin-tests",
            recent_errors_max_items=5,
        )
    )
    app = make_app(config=config)
    app.state.stores.recent_errors.append(
        {
            "created_at": "2026-04-11T10:01:00Z",
            "request_id": "req-openai-1",
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "path": "/v1/chat/completions",
            "status_code": 500,
            "duration_ms": 63.0,
            "stream_duration_ms": None,
            "client_ip": "127.0.0.1",
            "model": "gpt-4.1-mini",
            "token_usage": None,
            "error_type": "InternalServerError",
        }
    )
    app.state.stores.recent_errors.append(
        {
            "created_at": "2026-04-11T10:02:00Z",
            "request_id": "req-gemini-1",
            "provider": "gemini",
            "endpoint": "/v1beta/models/gemini:generateContent",
            "method": "POST",
            "path": "/v1beta/models/gemini:generateContent",
            "status_code": 429,
            "duration_ms": 81.0,
            "stream_duration_ms": 93.0,
            "client_ip": "127.0.0.1",
            "model": "gemini-2.5-pro",
            "token_usage": None,
            "error_type": "RateLimitError",
        }
    )

    client = TestClient(app)
    resp = client.get(
        "/admin/api/errors/recent",
        params={"provider": "gemini", "status_code": 429},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["events"][0]["request_id"] == "req-gemini-1"
    assert payload["available_filters"]["provider"] == ["gemini", "openai"]
