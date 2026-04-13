from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import admin_api_router, admin_router
from gpt2giga.api.system import system_router
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.core.config.control_plane import load_control_plane_overrides
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def make_app(config=None):
    app = FastAPI()
    app.include_router(system_router)
    app.include_router(admin_api_router)
    app.include_router(admin_router)
    ensure_runtime_dependencies(
        app.state,
        config=config or ProxyConfig(proxy=ProxySettings()),
    )
    return app


def test_console_routes_are_available():
    client = TestClient(make_app())

    response = client.get("/admin/setup")
    assert response.status_code == 200
    assert "/admin/assets/admin/console.css" in response.text
    assert "/admin/assets/admin/index.js" in response.text

    assert client.get("/admin/settings").status_code == 200
    assert client.get("/admin/keys").status_code == 200
    assert client.get("/admin/logs").status_code == 200
    assert client.get("/admin/playground").status_code == 200
    assert client.get("/admin/files-batches").status_code == 200


def test_setup_endpoint_reports_persisted_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.get("/admin/api/setup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["persisted"] is False
    assert payload["gigachat_ready"] is False
    assert payload["security_ready"] is False
    assert payload["setup_complete"] is False
    assert payload["claim"]["required"] is False
    assert payload["claim"]["claimed"] is False
    assert payload["wizard_steps"][0]["id"] == "claim"
    assert payload["warnings"]


def test_setup_claim_endpoint_records_operator_metadata_in_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD"))))

    response = client.post(
        "/admin/api/setup/claim",
        json={"operator_label": "Primary operator"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["claimed"] is True
    assert payload["claim"]["operator_label"] == "Primary operator"
    assert payload["control_plane"]["claim"]["claimed"] is True
    assert payload["control_plane"]["wizard_steps"][0]["ready"] is True


def test_gigachat_settings_update_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
            "model": "GigaChat-Max",
            "verify_ssl_certs": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"] == "gigachat"
    assert payload["values"]["credentials_configured"] is True
    assert payload["values"]["model"] == "GigaChat-Max"

    control_file = tmp_path / "control-plane.json"
    assert control_file.exists()
    raw = control_file.read_text(encoding="utf-8")
    assert "gigachat-secret" not in raw


def test_gigachat_settings_partial_update_preserves_existing_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    first_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
            "model": "GigaChat-Max",
            "verify_ssl_certs": True,
        },
    )
    assert first_response.status_code == 200

    second_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "model": "GigaChat-Pro",
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload["values"]["model"] == "GigaChat-Pro"
    assert second_payload["values"]["credentials_configured"] is True

    get_response = client.get("/admin/api/settings/gigachat")
    assert get_response.status_code == 200
    assert get_response.json()["values"]["credentials_configured"] is True


def test_gigachat_settings_null_secret_clears_existing_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    first_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
        },
    )
    assert first_response.status_code == 200

    clear_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": None,
        },
    )
    assert clear_response.status_code == 200
    clear_payload = clear_response.json()
    assert clear_payload["values"]["credentials_configured"] is False


def test_gigachat_settings_test_endpoint_reports_success(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    app = make_app()

    class FakeModel:
        def __init__(self, model_id):
            self.id = model_id

    class FakeGigaChat:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def aget_models(self):
            return type(
                "Result",
                (),
                {"data": [FakeModel("GigaChat"), FakeModel("GigaChat-Max")]},
            )()

        async def aclose(self):
            return None

    app.state.providers.gigachat_factory = FakeGigaChat
    client = TestClient(app)

    response = client.post(
        "/admin/api/settings/gigachat/test",
        json={
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
            "model": "GigaChat-Max",
            "verify_ssl_certs": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_count"] == 2
    assert "GigaChat-Max" in payload["sample_models"]


def test_gigachat_settings_test_endpoint_reports_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    app = make_app()

    class FakeBrokenGigaChat:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def aget_models(self):
            raise RuntimeError("upstream auth failed")

        async def aclose(self):
            return None

    app.state.providers.gigachat_factory = FakeBrokenGigaChat
    client = TestClient(app)

    response = client.post(
        "/admin/api/settings/gigachat/test",
        json={
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "upstream auth failed"


def test_scoped_key_create_rotate_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    create_response = client.post(
        "/admin/api/keys/scoped",
        json={
            "name": "sdk-openai",
            "providers": ["openai"],
            "endpoints": ["chat/completions"],
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["scoped_key"]["name"] == "sdk-openai"
    assert created["scoped_key"]["value"]

    rotate_response = client.post("/admin/api/keys/scoped/sdk-openai/rotate", json={})
    assert rotate_response.status_code == 200
    rotated = rotate_response.json()
    assert rotated["scoped_key"]["name"] == "sdk-openai"
    assert rotated["scoped_key"]["value"]

    list_response = client.get("/admin/api/keys")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["scoped"][0]["name"] == "sdk-openai"

    delete_response = client.delete("/admin/api/keys/scoped/sdk-openai")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] == "sdk-openai"


def test_settings_revisions_endpoint_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    first_rotate = client.post(
        "/admin/api/keys/global/rotate",
        json={"value": "first-global-key"},
    )
    assert first_rotate.status_code == 200

    second_rotate = client.post(
        "/admin/api/keys/global/rotate",
        json={"value": "second-global-key"},
    )
    assert second_rotate.status_code == 200

    revisions_response = client.get("/admin/api/settings/revisions?limit=5")
    assert revisions_response.status_code == 200
    revisions_payload = revisions_response.json()
    assert len(revisions_payload["revisions"]) >= 2

    previous_revision = revisions_payload["revisions"][1]
    assert previous_revision["changed_fields"] == ["api_key"]

    rollback_response = client.post(
        f"/admin/api/settings/revisions/{previous_revision['revision_id']}/rollback"
    )
    assert rollback_response.status_code == 200
    rollback_payload = rollback_response.json()
    assert (
        rollback_payload["rolled_back_revision_id"] == previous_revision["revision_id"]
    )

    proxy_overrides, _ = load_control_plane_overrides()
    assert proxy_overrides["api_key"] == "first-global-key"
