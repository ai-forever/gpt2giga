import json
import os

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions.store import InMemoryHarnessSessionStore
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.local_access import (
    LocalUIAccessError,
    LocalUIAccessStore,
)
from gpt2giga_harness.ui.static import INDEX_HTML, load_text_asset


def test_local_shell_issues_strict_httponly_session_cookie(tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    denied = client.get("/api/defaults")
    automation_denied = client.get("/api/automation")
    response = client.get("/")

    assert denied.status_code == 401
    assert automation_denied.status_code == 401
    assert response.status_code == 200
    assert response.history[0].headers["location"] == "/cockpit-v2/work"
    cookie = response.history[0].headers["set-cookie"]
    assert "gpt2giga_harness_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" not in cookie
    assert client.get("/api/defaults").status_code == 200


def test_local_arena_deep_link_issues_browser_session_cookie(tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/arena")

    assert response.status_code == 200
    assert response.history[0].headers["location"] == "/cockpit-v2/evaluation/arena"
    assert "gpt2giga_harness_session=" in response.history[0].headers["set-cookie"]
    assert client.get("/api/defaults").status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/cockpit-v2/work", "/cockpit-v2/runs/run_123", "/legacy/runs/run_123"],
)
def test_local_selectable_shell_deep_links_issue_browser_session_cookie(path, tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    response = client.get(path)

    assert response.status_code == 200
    assert "gpt2giga_harness_session=" in response.headers["set-cookie"]
    assert client.get("/api/defaults").status_code == 200


def test_ui_assets_include_url_authoritative_routes_and_bootstrap_form():
    script = load_text_asset("app.js")

    for fragment in (
        'id="work-nav-link"',
        'id="arena-nav-link"',
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
        "function loadCurrentRoute",
        "function bindPrimaryNavigation",
        "function loadApprovals",
        "function loadScheduledCenter",
        "function notifyAttentionItems",
        'window.addEventListener("popstate"',
        'document.querySelectorAll(".primary-nav-link")',
        "event.preventDefault()",
        "`/work/${encodeURIComponent(session.id)}`",
        "`/runs/${encodeURIComponent(run.id)}`",
        "headers: { Authorization: `Bearer ${token}` }",
        '"X-GigaLoom-CSRF": "1"',
    ):
        assert fragment in script
    assert "const secondaryLoads = Promise.all([" in script
    assert "loadMemory(),\n        loadTools(),\n        loadEvals()," in script
    assert "state.routeLoadKey === routeKey && state.routeLoadPromise" in script
    assert "state.routeLoadedKey === routeKey" in script
    assert "localStorage" not in script


def test_local_access_persists_only_hashed_expiring_sessions(tmp_path):
    now = [1_000.0]
    store = LocalUIAccessStore(
        tmp_path,
        clock=lambda: now[0],
        session_ttl_seconds=60,
    )

    session = store.claim()

    assert session is not None
    state_path = tmp_path / "ui_access" / "state.json"
    state_text = state_path.read_text()
    state = json.loads(state_text)
    assert session.token not in state_text
    assert state["claimable"] is False
    assert len(state["sessions"][0]["digest"]) == 64
    if os.name != "nt":
        assert state_path.stat().st_mode & 0o777 == 0o600
    assert LocalUIAccessStore(
        tmp_path,
        clock=lambda: now[0],
        session_ttl_seconds=60,
    ).authenticate(session.token)

    now[0] = 1_061.0

    assert not store.authenticate(session.token)
    assert store.status(session.token).expires_at is None


def test_local_access_rejects_symlinked_private_state(tmp_path):
    access_root = tmp_path / "ui_access"
    access_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    try:
        (access_root / "state.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(LocalUIAccessError, match="regular file"):
        LocalUIAccessStore(tmp_path).claim()


def test_local_access_logout_rotate_recovery_and_csrf(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    app = create_app(
        config,
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    first = client.get("/")
    original_cookie = client.cookies.get("gpt2giga_harness_session")
    status = client.get("/auth/status")
    csrf_denied = client.post("/auth/local/rotate")
    rotated = client.post(
        "/auth/local/rotate",
        headers={"X-GigaLoom-CSRF": "1"},
    )
    rotated_cookie = client.cookies.get("gpt2giga_harness_session")

    assert first.status_code == 200
    assert original_cookie
    assert status.json()["authenticated"] is True
    assert status.json()["local"] is True
    assert status.json()["expires_at"]
    unclaimed = TestClient(
        create_app(
            config,
            registry=create_default_registry(include_entry_points=False),
        ),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50002),
    )
    unclaimed_shell = unclaimed.get("/", follow_redirects=False)
    assert unclaimed_shell.status_code == 303
    assert unclaimed_shell.headers["location"] == "/local-access"
    assert csrf_denied.status_code == 403
    assert rotated.status_code == 200
    assert rotated_cookie
    assert rotated_cookie != original_cookie

    stale = TestClient(
        create_app(
            config,
            registry=create_default_registry(include_entry_points=False),
        ),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50001),
        cookies={"gpt2giga_harness_session": original_cookie},
    )
    assert stale.get("/api/defaults").status_code == 401

    logout = client.post(
        "/auth/logout",
        headers={"X-GigaLoom-CSRF": "1"},
    )
    locked = client.get("/", follow_redirects=False)
    recovery_page = client.get("/local-access")
    cross_origin = client.post(
        "/auth/local/recover",
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )
    recovered = client.post(
        "/auth/local/recover",
        headers={
            "Origin": "null",
            "Sec-Fetch-Site": "same-origin",
        },
        follow_redirects=False,
    )

    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False}
    assert locked.status_code == 303
    assert locked.headers["location"] == "/local-access"
    assert recovery_page.status_code == 200
    assert "Recover local GigaLoom access" in recovery_page.text
    assert "token=" not in recovery_page.text
    assert cross_origin.status_code == 403
    assert recovered.status_code == 303
    assert recovered.headers["location"] == "/cockpit-v2/settings"
    assert client.get("/api/defaults").status_code == 200


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
        "/arena",
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
