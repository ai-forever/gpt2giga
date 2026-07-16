from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.ui.app import create_app


def test_settings_read_model_is_bounded_and_never_exposes_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "provider-secret")
    client = _client(
        tmp_path,
        api_key="provider-secret",
        proxy_url="http://operator:proxy-secret@127.0.0.1:8090/?token=hidden",
    )

    response = client.get("/api/settings", params={"workspace": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["proxy_url"] == "http://127.0.0.1:8090/"
    assert body["provider"] == {
        "configured": True,
        "source": "environment",
        "health": "not_checked",
        "secret_readable": False,
        "change_effect": "restart_required",
    }
    assert body["workspace"]["name"] == tmp_path.name
    assert body["routes"]["default_api_mode_source"] == "built_in"
    assert body["routes"]["default_model_source"] == "built_in"
    assert "root" not in body["workspace"]
    assert body["diagnostics"]["content_free"] is True
    serialized = str(body)
    assert "provider-secret" not in serialized
    assert "proxy-secret" not in serialized
    assert "token=hidden" not in serialized


def test_settings_defaults_persist_read_back_and_seed_new_sessions(tmp_path):
    client = _client(tmp_path)
    revision = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()[
        "revision"
    ]

    saved = client.patch(
        "/api/settings/defaults",
        json={
            "expected_revision": revision,
            "defaults": {
                "default_harness_id": "direct-chat",
                "default_model": "GigaChat",
                "default_api_mode": "v2",
                "mode": "act",
                "invocation_mode": "headless",
                "workspace_policy": "current",
                "permission_profile": "review_every_action",
                "stream": False,
            },
        },
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["saved"] is True
    assert body["defaults"]["default_harness_id"] == "direct-chat"
    assert body["sources"]["default_harness_id"] == "harness_settings"
    assert body["change_effect"] == "new_runs"
    stored = tmp_path / "data" / "settings" / "defaults.json"
    assert stored.is_file()
    assert "api_key" not in stored.read_text(encoding="utf-8")

    read_back = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()
    assert read_back["harness_defaults"]["permission_profile"] == (
        "review_every_action"
    )
    assert read_back["routes"]["default_model"] == "GigaChat"

    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session = created.json()["session"]
    assert session["default_harness_id"] == "direct-chat"
    assert session["default_model"] == "GigaChat"
    assert session["default_api_mode"] == "v2"
    assert session["default_mode"] == "act"


def test_settings_reject_invalid_harness_invocation_before_persistence(tmp_path):
    client = _client(tmp_path)

    response = client.patch(
        "/api/settings/defaults",
        json={
            "defaults": {
                "default_harness_id": "direct-chat",
                "invocation_mode": "native",
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"] == {
        "invocation_mode": "selected harness does not support native sessions"
    }
    assert not (tmp_path / "data" / "settings" / "defaults.json").exists()


def test_settings_do_not_persist_environment_owned_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DEFAULT_MODEL", "EnvironmentModel")
    client = _client(tmp_path, default_model="EnvironmentModel")

    response = client.patch(
        "/api/settings/defaults",
        json={"defaults": {"default_model": "StoredModel"}},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "environment_owned"
    assert "default_model" in detail["field_errors"]
    assert "EnvironmentModel" not in str(detail)
    assert not (tmp_path / "data" / "settings" / "defaults.json").exists()


def test_settings_reject_stale_revision_without_overwriting(tmp_path):
    client = _client(tmp_path)
    original = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()[
        "revision"
    ]
    first = client.patch(
        "/api/settings/defaults",
        json={
            "expected_revision": original,
            "defaults": {"workspace_policy": "current"},
        },
    )
    assert first.status_code == 200

    stale = client.patch(
        "/api/settings/defaults",
        json={
            "expected_revision": original,
            "defaults": {"workspace_policy": "worktree"},
        },
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    read_back = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()
    assert read_back["harness_defaults"]["workspace_policy"] == "current"


def _client(data_dir, **overrides) -> TestClient:
    config = HarnessConfig(data_dir=str(data_dir / "data"), **overrides)
    app = create_app(
        config,
        registry=create_default_registry(include_entry_points=False),
        store=InMemoryHarnessSessionStore(),
    )
    return TestClient(app)
