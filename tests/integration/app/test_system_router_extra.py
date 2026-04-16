import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import admin_api_router, admin_router, legacy_logs_router
from gpt2giga.api.system import system_router
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.app.factory import create_app
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
    assert "gpt2giga Console" in resp.text
    assert "Gateway Console" in resp.text
    assert "Start" in resp.text
    assert "Configure" in resp.text
    assert "Observe" in resp.text
    assert "Diagnose" in resp.text
    assert "Playground" in resp.text
    assert "Files &amp; Batches" in resp.text
    assert 'class="skip-link"' in resp.text
    assert 'href="#page-title"' in resp.text
    assert 'aria-label="Primary console navigation"' in resp.text
    assert 'id="page-title" tabindex="-1"' in resp.text
    assert 'data-workflow="start"' in resp.text
    assert 'data-workflow="configure"' in resp.text
    assert 'data-workflow="observe"' in resp.text
    assert 'data-workflow="diagnose"' in resp.text
    assert 'id="workflow-chip"' in resp.text
    assert 'id="surface-chip"' in resp.text
    assert 'id="page-context"' in resp.text


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
    """Verify the admin UI shell loads the modular frontend assets."""
    app = make_app()
    client = TestClient(app)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert 'id="alerts"' in resp.text
    assert "/admin/assets/admin/console.css" in resp.text
    assert "/admin/assets/admin/index.js" in resp.text

    asset_client = TestClient(create_app(config=ProxyConfig(proxy=ProxySettings())))
    index_asset = asset_client.get("/admin/assets/admin/index.js")
    app_asset = asset_client.get("/admin/assets/admin/app.js")
    stylesheet = asset_client.get("/admin/assets/admin/console.css")

    assert index_asset.status_code == 200
    assert app_asset.status_code == 200
    assert stylesheet.status_code == 200
    assert "AdminApp" in index_asset.text
    assert "navigateToLocation" in app_asset.text
    assert "url.search" in app_asset.text
    assert "url.pathname === window.location.pathname" in app_asset.text
    assert "url.hash" in app_asset.text
    assert "pageTitle.focus()" in app_asset.text
    assert ".hero-context" in stylesheet.text
    assert ".nav-group--active" in stylesheet.text
    assert ".skip-link" in stylesheet.text
    assert ".subpage-nav" in stylesheet.text


def test_admin_ui_assets_include_observability_presets():
    client = TestClient(create_app(config=ProxyConfig(proxy=ProxySettings())))

    response = client.get("/admin/assets/admin/pages/control-plane-sections.js")

    assert response.status_code == 200
    assert "Local Prometheus" in response.text
    assert "Local OTLP collector" in response.text
    assert "Local Langfuse" in response.text
    assert "Local Phoenix" in response.text
    assert "deploy/compose/observability-otlp.yaml" in response.text
    assert 'pathForPage("settings-observability")' in response.text
    assert "settings?section=observability" not in response.text


def test_admin_ui_assets_include_observe_diagnose_handoff_copy():
    client = TestClient(create_app(config=ProxyConfig(proxy=ProxySettings())))

    traffic_asset = client.get("/admin/assets/admin/pages/traffic/view.js")
    traffic_bindings_asset = client.get("/admin/assets/admin/pages/traffic/bindings.js")
    logs_asset = client.get("/admin/assets/admin/pages/logs/view.js")
    logs_bindings_asset = client.get("/admin/assets/admin/pages/logs/bindings.js")
    docs_links_asset = client.get("/admin/assets/admin/docs-links.js")

    assert traffic_asset.status_code == 200
    assert traffic_bindings_asset.status_code == 200
    assert "Traffic navigation" in traffic_asset.text
    assert "Traffic pages" in traffic_asset.text
    assert "Open requests" in traffic_asset.text
    assert "Open errors" in traffic_asset.text
    assert "Open usage" in traffic_asset.text
    assert "Current posture" in traffic_asset.text
    assert "Selection and handoff" in traffic_asset.text
    assert "Request inspector and handoff" in traffic_asset.text
    assert "Error inspector and handoff" in traffic_asset.text
    assert "Usage inspector and handoff" in traffic_asset.text
    assert "Current scope snapshot" in traffic_asset.text
    assert "Selected request snapshot" in traffic_bindings_asset.text
    assert "Traffic workflow guide" in traffic_asset.text
    assert "Troubleshooting handoff map" in traffic_asset.text

    assert logs_asset.status_code == 200
    assert logs_bindings_asset.status_code == 200
    assert "Open traffic summary" in logs_asset.text
    assert "Current posture and handoff" in logs_asset.text
    assert "Rendered log tail" in logs_asset.text
    assert "Live stream diagnostics" in logs_asset.text
    assert "Current scope snapshot" in logs_asset.text
    assert "Logs deep-dive guide" in logs_asset.text
    assert "Keep Logs narrower than the broad traffic workflow." in logs_asset.text
    assert "Tail-derived request context" in logs_asset.text
    assert "Return to the broad traffic summary" in logs_asset.text
    assert "Selected request snapshot" in logs_bindings_asset.text
    assert "Selected error snapshot" in logs_bindings_asset.text
    assert "Selected tail context snapshot" in logs_bindings_asset.text

    assert docs_links_asset.status_code == 200
    assert "operator-guide.md" in docs_links_asset.text
    assert "traffic-summary-to-request-scope" in docs_links_asset.text
    assert "logs-deep-dive-and-live-tail" in docs_links_asset.text


def test_admin_ui_assets_include_summary_first_system_and_provider_copy():
    client = TestClient(create_app(config=ProxyConfig(proxy=ProxySettings())))

    overview_asset = client.get("/admin/assets/admin/pages/render-overview.js")
    system_asset = client.get("/admin/assets/admin/pages/render-system.js")
    providers_asset = client.get("/admin/assets/admin/pages/render-providers.js")
    docs_links_asset = client.get("/admin/assets/admin/docs-links.js")

    assert overview_asset.status_code == 200
    assert "Workflow handoff" in overview_asset.text
    assert "Recent error handoff" in overview_asset.text
    assert "Overview workflow guide" in overview_asset.text
    assert "Overview stays summary-first" in overview_asset.text

    assert system_asset.status_code == 200
    assert "Confirm live request behavior before deep forensics" in system_asset.text
    assert (
        "Detailed diagnostics stay staged until the executive summary, readiness"
        in system_asset.text
    )
    assert "Use staged diagnostics when the summary is not enough" in system_asset.text
    assert "Copy system snapshot" in system_asset.text
    assert "Current system snapshot" in system_asset.text
    assert "System stays staged." in system_asset.text

    assert providers_asset.status_code == 200
    assert "Keep this page summary-first" in providers_asset.text
    assert "Smoke the mounted provider surface" in providers_asset.text
    assert "Route-family detail stays secondary" in providers_asset.text
    assert "Provider surface diagnostics" in providers_asset.text
    assert "Provider workflow handoff" in providers_asset.text
    assert "Current route-family snapshot" in providers_asset.text
    assert "Full provider surface matrix" in providers_asset.text
    assert docs_links_asset.status_code == 200
    assert "provider-surface-diagnostics" in docs_links_asset.text


def test_admin_ui_assets_include_polished_keys_and_playground_copy():
    client = TestClient(create_app(config=ProxyConfig(proxy=ProxySettings())))

    keys_asset = client.get("/admin/assets/admin/pages/render-keys.js")
    playground_asset = client.get("/admin/assets/admin/pages/playground/view.js")
    docs_links_asset = client.get("/admin/assets/admin/docs-links.js")

    assert keys_asset.status_code == 200
    assert "Key workflows" in keys_asset.text
    assert "Create scoped key" in keys_asset.text
    assert "Scoped key inventory" in keys_asset.text
    assert "Current key snapshot" in keys_asset.text
    assert "Open usage traffic" in keys_asset.text
    assert "Keys stay narrow on purpose." in keys_asset.text

    assert playground_asset.status_code == 200
    assert "Smoke workflow handoff" in playground_asset.text
    assert "Current request posture" in playground_asset.text
    assert "Current request payload" in playground_asset.text
    assert "Current transport snapshot" in playground_asset.text
    assert "Playground stays narrow." in playground_asset.text
    assert "Current bootstrap posture" in playground_asset.text

    assert docs_links_asset.status_code == 200
    assert "troubleshooting-handoff-map" in docs_links_asset.text
    assert "rollout-backend-v2" in docs_links_asset.text


def test_admin_ui_assets_include_staged_files_batches_copy():
    client = TestClient(create_app(config=ProxyConfig(proxy=ProxySettings())))

    files_batches_asset = client.get("/admin/assets/admin/pages/files-batches/view.js")
    files_batches_serializers_asset = client.get(
        "/admin/assets/admin/pages/files-batches/serializers.js"
    )
    docs_links_asset = client.get("/admin/assets/admin/docs-links.js")

    assert files_batches_asset.status_code == 200
    assert "Shared workbench hub" in files_batches_asset.text
    assert "Files workbench" in files_batches_asset.text
    assert "Batch jobs workbench" in files_batches_asset.text
    assert "Upload input" in files_batches_asset.text
    assert "Queue batch job" in files_batches_asset.text
    assert "Selection metadata snapshot" in files_batches_asset.text
    assert "Content preview stays secondary" in files_batches_asset.text
    assert "Open batches" in files_batches_asset.text
    assert "Files and batches lifecycle" in files_batches_asset.text
    assert files_batches_serializers_asset.status_code == 200
    assert "Open batch composer" in files_batches_serializers_asset.text
    assert (
        "Preview one output first to unlock request-scoped Traffic and Logs handoff."
        in (files_batches_serializers_asset.text)
    )
    assert (
        'scopedLabel = (selection.handoffRequestCount ?? 0) > 1 ? "sample result" : "request"'
        in files_batches_serializers_asset.text
    )
    assert (
        "Open traffic for ${escapeHtml(scopedLabel)}"
        in files_batches_serializers_asset.text
    )
    assert (
        "Open logs for ${escapeHtml(scopedLabel)}"
        in files_batches_serializers_asset.text
    )
    assert "Sample request scoped" in files_batches_serializers_asset.text
    assert docs_links_asset.status_code == 200
    assert "files-and-batches-lifecycle" in docs_links_asset.text


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
    assert payload["state"]["stores"]["governance_counters"] == 0
    assert payload["governance_enabled"] is False
    assert payload["governance_limits_configured"] == 0


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
    assert "/admin/files-batches" in payload["admin"]["routes"]
    assert "files_batches" in payload["admin"]["capabilities"]


def test_admin_config_exposes_grouped_safe_summary():
    app = make_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                host="localhost",
                port=8090,
                gigachat_api_mode="v1",
                gigachat_responses_api_mode="v2",
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
    assert payload["summary"]["network"]["governance_limits_configured"] == 0
    assert payload["summary"]["providers"]["gigachat_api_mode"] == "v1"
    assert payload["summary"]["providers"]["gigachat_responses_api_mode"] == "v2"
    assert payload["summary"]["providers"]["responses_backend_mode"] == "v2"
    assert payload["summary"]["providers"]["telemetry_enabled"] is True
    assert payload["summary"]["providers"]["governance_enabled"] is False
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
            "request_id": "req-gemini",
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
        "request_id": "req-gemini",
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
            "request_id": None,
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
            "request_id": None,
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
        params={
            "request_id": "req-gemini-1",
            "provider": "gemini",
            "status_code": 429,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["events"][0]["request_id"] == "req-gemini-1"
    assert payload["filters"]["request_id"] == "req-gemini-1"
    assert payload["available_filters"]["provider"] == ["gemini", "openai"]
