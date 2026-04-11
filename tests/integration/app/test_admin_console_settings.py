from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import admin_api_router, admin_router
from gpt2giga.api.system import system_router
from gpt2giga.app.dependencies import ensure_runtime_dependencies
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

    assert client.get("/admin/settings").status_code == 200
    assert client.get("/admin/keys").status_code == 200
    assert client.get("/admin/logs").status_code == 200
    assert client.get("/admin/playground").status_code == 200


def test_setup_endpoint_reports_persisted_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.get("/admin/api/setup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["persisted"] is False
    assert payload["gigachat_ready"] is False


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
