import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import admin_api_router, admin_router
from gpt2giga.api.system import system_router
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.core.config.control_plane import load_control_plane_overrides
from gpt2giga.core.config._control_plane.paths import (
    ensure_control_plane_revisions_dir,
)
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
    client = TestClient(make_app(), client=("127.0.0.1", 50000))

    response = client.get("/admin/setup")
    assert response.status_code == 200
    assert "/admin/assets/admin/console.css" in response.text
    assert "/admin/assets/admin/index.js" in response.text

    assert client.get("/admin/settings").status_code == 200
    assert client.get("/admin/setup-claim").status_code == 200
    assert client.get("/admin/setup-application").status_code == 200
    assert client.get("/admin/setup-gigachat").status_code == 200
    assert client.get("/admin/setup-security").status_code == 200
    assert client.get("/admin/settings-application").status_code == 200
    assert client.get("/admin/settings-observability").status_code == 200
    assert client.get("/admin/settings-gigachat").status_code == 200
    assert client.get("/admin/settings-security").status_code == 200
    assert client.get("/admin/settings-history").status_code == 200
    assert client.get("/admin/keys").status_code == 200
    assert client.get("/admin/logs").status_code == 200
    assert client.get("/admin/playground").status_code == 200
    assert client.get("/admin/traffic").status_code == 200
    assert client.get("/admin/traffic-requests").status_code == 200
    assert client.get("/admin/traffic-errors").status_code == 200
    assert client.get("/admin/traffic-usage").status_code == 200
    assert client.get("/admin/files-batches").status_code == 200
    assert client.get("/admin/files").status_code == 200
    assert client.get("/admin/batches").status_code == 200


def test_setup_endpoint_reports_persisted_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.get("/admin/api/setup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["persisted"] is False
    assert payload["gigachat_ready"] is False
    assert payload["gigachat_auth_methods"] == []
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
            "user": "service-account",
            "password": "super-secret-password",
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
            "model": "GigaChat-Max",
            "ca_bundle_file": "/certs/company-root.pem",
            "verify_ssl_certs": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"] == "gigachat"
    assert payload["values"]["user"] == "service-account"
    assert payload["values"]["password_configured"] is True
    assert payload["values"]["password_preview"] != "super-secret-password"
    assert payload["values"]["credentials_configured"] is True
    assert payload["values"]["model"] == "GigaChat-Max"
    assert payload["values"]["ca_bundle_file"] == "/certs/company-root.pem"

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
            "user": "service-account",
            "password": "super-secret-password",
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
    assert second_payload["values"]["user"] == "service-account"
    assert second_payload["values"]["password_configured"] is True
    assert second_payload["values"]["credentials_configured"] is True

    get_response = client.get("/admin/api/settings/gigachat")
    assert get_response.status_code == 200
    values = get_response.json()["values"]
    assert values["credentials_configured"] is True
    assert values["password_configured"] is True
    assert values["user"] == "service-account"


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


def test_application_settings_update_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.put(
        "/admin/api/settings/application",
        json={
            "runtime_store_backend": "memory",
            "runtime_store_namespace": "tenant-a",
            "gigachat_responses_api_mode": "v2",
            "enable_reasoning": True,
            "recent_requests_max_items": 321,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"] == "application"
    assert payload["values"]["runtime_store_backend"] == "memory"
    assert payload["values"]["runtime_store_active_backend"] == "memory"
    assert payload["values"]["runtime_store_namespace"] == "tenant-a"
    assert payload["values"]["gigachat_responses_api_mode"] == "v2"
    assert payload["values"]["enable_reasoning"] is True
    assert payload["values"]["recent_requests_max_items"] == 321

    get_response = client.get("/admin/api/settings/application")
    assert get_response.status_code == 200
    values = get_response.json()["values"]
    assert values["runtime_store_namespace"] == "tenant-a"
    assert values["gigachat_responses_api_mode"] == "v2"
    assert values["enable_reasoning"] is True


def test_security_settings_update_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app(), client=("127.0.0.1", 50000))

    response = client.put(
        "/admin/api/settings/security",
        json={
            "logs_ip_allowlist": ["127.0.0.1", "10.0.0.8"],
            "trusted_proxy_cidrs": ["10.0.0.0/24"],
            "scoped_api_keys": [
                {
                    "name": "sdk-openai",
                    "key": "sdk-openai-secret",
                    "providers": ["openai"],
                    "endpoints": ["chat/completions"],
                }
            ],
            "governance_limits": [
                {
                    "name": "openai-chat-limit",
                    "scope": "provider",
                    "providers": ["openai"],
                    "endpoints": ["chat/completions"],
                    "window_seconds": 60,
                    "max_requests": 10,
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"] == "security"
    assert payload["values"]["logs_ip_allowlist"] == ["127.0.0.1", "10.0.0.8"]
    assert payload["values"]["trusted_proxy_cidrs"] == ["10.0.0.0/24"]
    assert payload["values"]["scoped_api_keys_configured"] == 1
    assert payload["values"]["governance_limits"][0]["name"] == "openai-chat-limit"

    get_response = client.get("/admin/api/settings/security")
    assert get_response.status_code == 200
    values = get_response.json()["values"]
    assert values["logs_ip_allowlist"] == ["127.0.0.1", "10.0.0.8"]
    assert values["trusted_proxy_cidrs"] == ["10.0.0.0/24"]
    assert values["scoped_api_keys_configured"] == 1
    assert values["governance_limits"][0]["providers"] == ["openai"]


def test_gigachat_settings_update_rejects_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.put(
        "/admin/api/settings/gigachat",
        json={"model": "GigaChat-Max", "unexpected_field": True},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["type"] == "extra_forbidden"
    assert detail[0]["loc"] == ["body", "unexpected_field"]


def test_observability_settings_endpoint_returns_grouped_sink_cards():
    client = TestClient(
        make_app(
            config=ProxyConfig(
                proxy=ProxySettings(
                    observability_sinks=["prometheus", "phoenix"],
                    phoenix_base_url="http://phoenix:6006",
                    phoenix_project_name="dev",
                )
            )
        )
    )

    response = client.get("/admin/api/settings/observability")

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"] == "observability"
    assert payload["values"]["enable_telemetry"] is True
    assert payload["values"]["metrics_enabled"] is True
    sink_by_id = {sink["id"]: sink for sink in payload["values"]["sinks"]}
    assert sink_by_id["prometheus"]["enabled"] is True
    assert sink_by_id["phoenix"]["enabled"] is True
    assert sink_by_id["phoenix"]["configured"] is True
    assert sink_by_id["phoenix"]["settings"]["base_url"] == "http://phoenix:6006"
    assert sink_by_id["phoenix"]["settings"]["project_name"] == "dev"
    assert sink_by_id["langfuse"]["missing_fields"] == [
        "base_url",
        "public_key",
        "secret_key",
    ]


def test_observability_settings_update_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    response = client.put(
        "/admin/api/settings/observability",
        json={
            "enable_telemetry": True,
            "active_sinks": ["prometheus", "otlp", "phoenix"],
            "otlp": {
                "traces_endpoint": "http://otel-collector:4318/v1/traces",
                "headers": {"x-tenant": "demo"},
                "service_name": "gpt2giga-dev",
            },
            "phoenix": {
                "base_url": "http://phoenix:6006",
                "project_name": "gpt2giga-local",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"] == "observability"
    assert payload["restart_required"] is False
    assert payload["applied_runtime"] is True
    assert payload["values"]["active_sinks"] == ["prometheus", "otlp", "phoenix"]

    sink_by_id = {sink["id"]: sink for sink in payload["values"]["sinks"]}
    assert sink_by_id["otlp"]["enabled"] is True
    assert sink_by_id["otlp"]["configured"] is True
    assert sink_by_id["otlp"]["settings"]["traces_endpoint"] == (
        "http://otel-collector:4318/v1/traces"
    )
    assert sink_by_id["otlp"]["settings"]["headers_configured"] is True
    assert sink_by_id["otlp"]["settings"]["header_names"] == ["x-tenant"]
    assert sink_by_id["phoenix"]["settings"]["base_url"] == "http://phoenix:6006"

    get_response = client.get("/admin/api/settings/observability")
    assert get_response.status_code == 200
    assert get_response.json()["values"]["active_sinks"] == [
        "prometheus",
        "otlp",
        "phoenix",
    ]


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
            "ca_bundle_file": "/certs/company-root.pem",
            "verify_ssl_certs": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_count"] == 2
    assert "GigaChat-Max" in payload["sample_models"]


def test_setup_endpoint_reports_env_only_mode_without_bootstrap():
    client = TestClient(
        make_app(
            config=ProxyConfig(
                proxy=ProxySettings(
                    mode="PROD",
                    disable_persist=True,
                    enable_api_key_auth=True,
                    api_key="env-admin-key",
                ),
                gigachat={"credentials": "env-creds", "scope": "GIGACHAT_API_PERS"},
            )
        )
    )

    response = client.get("/admin/api/setup", headers={"x-api-key": "env-admin-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["disable_persist"] is True
    assert payload["persistence_enabled"] is False
    assert payload["persisted"] is False
    assert payload["gigachat_auth_methods"] == ["credentials"]
    assert payload["setup_complete"] is True
    assert payload["bootstrap"]["required"] is False
    assert payload["claim"]["required"] is False


def test_setup_endpoint_treats_user_password_auth_as_runtime_ready():
    client = TestClient(
        make_app(
            config=ProxyConfig(
                proxy=ProxySettings(
                    mode="PROD",
                    disable_persist=True,
                    enable_api_key_auth=True,
                    api_key="env-admin-key",
                ),
                gigachat={
                    "user": "env-user",
                    "password": "env-password",
                    "scope": "GIGACHAT_API_PERS",
                },
            )
        )
    )

    response = client.get("/admin/api/setup", headers={"x-api-key": "env-admin-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["gigachat_ready"] is True
    assert payload["gigachat_auth_methods"] == ["user_password"]
    assert payload["setup_complete"] is True


def test_settings_mutation_is_rejected_when_persist_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(
        make_app(
            config=ProxyConfig(
                proxy=ProxySettings(mode="DEV", disable_persist=True),
                gigachat={"credentials": "env-creds"},
            )
        )
    )

    response = client.put(
        "/admin/api/settings/gigachat",
        json={"model": "GigaChat-Max"},
    )

    assert response.status_code == 409
    assert "Control-plane persistence is disabled" in response.json()["detail"]
    assert (tmp_path / "control-plane.json").exists() is False


def test_gigachat_settings_test_endpoint_passes_ca_bundle_to_factory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    app = make_app()

    captured_kwargs = {}

    class FakeModel:
        def __init__(self, model_id):
            self.id = model_id

    class FakeGigaChat:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def aget_models(self):
            return type("Result", (), {"data": [FakeModel("GigaChat-Max")]})()

        async def aclose(self):
            return None

    app.state.providers.gigachat_factory = FakeGigaChat
    client = TestClient(app)

    response = client.post(
        "/admin/api/settings/gigachat/test",
        json={
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
            "ca_bundle_file": "/certs/company-root.pem",
            "verify_ssl_certs": True,
        },
    )

    assert response.status_code == 200
    assert captured_kwargs["ca_bundle_file"] == "/certs/company-root.pem"


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


def test_gigachat_settings_rollback_restores_secret_for_follow_up_partial_apply(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    first_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": "first-gigachat-secret",
            "password": "first-gigachat-password",
            "scope": "GIGACHAT_API_PERS",
            "model": "GigaChat-Max",
            "user": "service-account",
        },
    )
    assert first_response.status_code == 200

    second_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": "second-gigachat-secret",
            "password": "second-gigachat-password",
            "model": "GigaChat-Pro",
        },
    )
    assert second_response.status_code == 200

    revisions_response = client.get("/admin/api/settings/revisions?limit=5")
    assert revisions_response.status_code == 200
    revisions_payload = revisions_response.json()
    first_revision = revisions_payload["revisions"][1]
    assert first_revision["changed_fields"] == [
        "credentials",
        "model",
        "password",
        "scope",
        "user",
    ]

    rollback_response = client.post(
        f"/admin/api/settings/revisions/{first_revision['revision_id']}/rollback"
    )
    assert rollback_response.status_code == 200
    rollback_payload = rollback_response.json()
    assert rollback_payload["rolled_back_revision_id"] == first_revision["revision_id"]
    assert (
        rollback_payload["values"]["gigachat"]["credentials_preview"]
        != "first-gigachat-secret"
    )
    assert (
        rollback_payload["values"]["gigachat"]["password_preview"]
        != "first-gigachat-password"
    )

    apply_response = client.put(
        "/admin/api/settings/gigachat",
        json={"model": "GigaChat-Ultra"},
    )
    assert apply_response.status_code == 200
    apply_payload = apply_response.json()
    assert apply_payload["values"]["model"] == "GigaChat-Ultra"
    assert apply_payload["values"]["credentials_configured"] is True
    assert apply_payload["values"]["password_configured"] is True
    assert apply_payload["values"]["credentials_preview"] != "first-gigachat-secret"

    _, gigachat_overrides = load_control_plane_overrides()
    assert gigachat_overrides["credentials"] == "first-gigachat-secret"
    assert gigachat_overrides["password"] == "first-gigachat-password"
    assert gigachat_overrides["model"] == "GigaChat-Ultra"


def test_settings_revisions_snapshots_keep_secret_previews_masked(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    client = TestClient(make_app())

    gigachat_response = client.put(
        "/admin/api/settings/gigachat",
        json={
            "credentials": "gigachat-secret-value",
            "password": "gigachat-password-value",
            "scope": "GIGACHAT_API_PERS",
            "model": "GigaChat-Max",
        },
    )
    assert gigachat_response.status_code == 200

    security_response = client.put(
        "/admin/api/settings/security",
        json={
            "api_key": "global-admin-secret",
            "scoped_api_keys": [
                {
                    "name": "sdk-openai",
                    "key": "sdk-openai-secret",
                    "providers": ["openai"],
                    "endpoints": ["chat/completions"],
                }
            ],
        },
    )
    assert security_response.status_code == 200

    revisions_response = client.get("/admin/api/settings/revisions?limit=5")
    assert revisions_response.status_code == 200
    revisions = revisions_response.json()["revisions"]
    security_revision = revisions[0]
    gigachat_revision = revisions[1]

    assert (
        security_revision["snapshot"]["security"]["global_api_key_preview"]
        != "global-admin-secret"
    )
    assert security_revision["snapshot"]["security"]["scoped_api_keys_configured"] == 1
    assert (
        gigachat_revision["snapshot"]["gigachat"]["credentials_preview"]
        != "gigachat-secret-value"
    )
    assert (
        gigachat_revision["snapshot"]["gigachat"]["password_preview"]
        != "gigachat-password-value"
    )


def test_settings_revisions_endpoint_ignores_legacy_unknown_fields(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    revisions_dir = ensure_control_plane_revisions_dir()
    revision_id = "20260422T120000000000Z-legacy"
    (revisions_dir / f"{revision_id}.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision_id": revision_id,
                "updated_at": "2026-04-22T12:00:00Z",
                "proxy": {
                    "mode": "DEV",
                    "enable_reasoning": True,
                    "enable_images": True,
                },
                "gigachat": {},
                "secrets": {"proxy": {}, "gigachat": {}},
                "managed": {"proxy": ["mode", "enable_reasoning"], "gigachat": []},
                "change": {"changed_fields": ["enable_reasoning", "enable_images"]},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(make_app())

    response = client.get("/admin/api/settings/revisions?limit=6")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revisions"][0]["revision_id"] == revision_id
    assert (
        payload["revisions"][0]["snapshot"]["application"]["enable_reasoning"] is True
    )
