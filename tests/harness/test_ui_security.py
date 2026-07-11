from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions.store import InMemoryHarnessSessionStore
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.static import INDEX_HTML, load_text_asset


def test_local_shell_issues_strict_httponly_session_cookie():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    denied = client.get("/api/defaults")
    response = client.get("/")

    assert denied.status_code == 401
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "gpt2giga_harness_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" not in cookie
    assert client.get("/api/defaults").status_code == 200


def test_ui_assets_include_url_authoritative_routes_and_bootstrap_form():
    script = load_text_asset("app.js")

    for fragment in (
        'id="work-nav-link"',
        'id="runs-nav-link"',
        'id="tools-nav-link"',
        'id="agents-nav-link"',
        'id="approvals-nav-link"',
        'id="evaluate-nav-link"',
        'id="scheduled-nav-link"',
        'id="auth-form"',
        'id="auth-token-input" type="password"',
    ):
        assert fragment in INDEX_HTML
    for fragment in (
        "function currentRoute()",
        "function syncBrowserRoute",
        "function applyCurrentRoute",
        "function loadApprovals",
        "function loadScheduledCenter",
        "function notifyAttentionItems",
        'window.addEventListener("popstate"',
        "`/work/${encodeURIComponent(session.id)}`",
        "`/runs/${encodeURIComponent(run.id)}`",
        "headers: { Authorization: `Bearer ${token}` }",
    ):
        assert fragment in script
    assert "localStorage" not in script


def test_ui_security_config_loads_token_and_host_allowlist_without_api_exposure(
    monkeypatch,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN", "secret-token")
    monkeypatch.setenv(
        "GPT2GIGA_HARNESS_UI_ALLOWED_HOSTS",
        " harness.example, 10.0.0.7 ",
    )
    config = HarnessConfig.from_env()
    client = _client(config)

    assert config.ui_bootstrap_token == "secret-token"
    assert config.ui_allowed_hosts == ("harness.example", "10.0.0.7")
    assert "secret-token" not in repr(config)
    assert "secret-token" not in client.get("/api/defaults").text


def test_remote_shell_requires_bootstrap_exchange_for_api_and_sse_cookie():
    config = HarnessConfig(
        ui_host="0.0.0.0",
        ui_bootstrap_token="bootstrap-secret",
    )
    client = _client(config, base_url="https://192.168.1.50")

    shell = client.get("/work")
    denied = client.get("/api/defaults")
    invalid = client.post(
        "/auth/session",
        headers={"Authorization": "Bearer wrong"},
    )
    accepted = client.post(
        "/auth/session",
        headers={"Authorization": "Bearer bootstrap-secret"},
    )

    assert shell.status_code == 200
    assert "set-cookie" not in shell.headers
    assert denied.status_code == 401
    assert invalid.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"authenticated": True}
    cookie = accepted.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" in cookie
    assert client.get("/api/defaults").status_code == 200
    assert client.get("/api/runs/missing/events/stream").status_code == 404


def test_remote_mutations_fail_closed_without_auth_configuration():
    config = HarnessConfig(ui_host="0.0.0.0")
    client = _client(config, base_url="http://192.168.1.50")

    response = client.post("/api/sessions", json={})

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_host_and_origin_validation_reject_untrusted_requests():
    client = _client()

    bad_host = client.get("/healthz", headers={"Host": "attacker.example"})
    bad_origin = client.post(
        "/api/sessions",
        headers={"Origin": "https://attacker.example"},
        json={},
    )

    assert bad_host.status_code == 400
    assert bad_origin.status_code == 403


def test_shell_deep_links_and_unknown_paths_fail_closed():
    client = _client()

    for path in (
        "/",
        "/work",
        "/work/sess_123",
        "/runs",
        "/runs/run_123",
        "/approvals",
        "/tools",
        "/agents",
        "/workflows",
        "/workflows/review-team",
        "/evaluate",
        "/scheduled",
        "/scheduled/daily-echo",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    unknown_api = client.get("/api/not-a-route")
    unknown_asset = client.get("/assets/nested/app.js")
    unknown_page = client.get("/unknown-product-area")
    assert unknown_api.status_code == 404
    assert not unknown_api.headers["content-type"].startswith("text/html")
    assert unknown_asset.status_code == 404
    assert not unknown_asset.headers["content-type"].startswith("text/html")
    assert unknown_page.status_code == 404


def test_run_deep_link_api_returns_selected_session_bundle():
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Deep link")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
    )
    client = _client(store=store)

    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["selected_run_id"] == run.id
    assert body["session"]["id"] == session.id
    assert body["runs"][0]["id"] == run.id
    assert client.get("/api/runs/run_missing").status_code == 404


def _client(
    config: HarnessConfig | None = None,
    *,
    base_url: str = "http://testserver",
    store: InMemoryHarnessSessionStore | None = None,
) -> TestClient:
    app = create_app(
        config or HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
        store=store,
    )
    return TestClient(app, base_url=base_url)
