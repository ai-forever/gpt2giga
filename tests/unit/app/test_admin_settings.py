import pytest
from fastapi import FastAPI
from starlette.requests import Request

from gpt2giga.api.admin import admin_api_router
from gpt2giga.api.system import system_router
from gpt2giga.app.admin_settings import (
    AdminControlPlaneSettingsService,
    AdminKeyManagementService,
)
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.core.config.observability import ObservabilitySettingsUpdate
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def _build_request(config: ProxyConfig | None = None) -> Request:
    app = FastAPI()
    app.include_router(system_router)
    app.include_router(admin_api_router)
    ensure_runtime_dependencies(
        app.state,
        config=config or ProxyConfig(proxy=ProxySettings()),
    )
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/admin/api/settings/application",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_admin_control_plane_settings_service_updates_observability(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    request = _build_request()

    payload = ObservabilitySettingsUpdate(
        enable_telemetry=True,
        active_sinks=["prometheus", "otlp"],
        otlp={
            "traces_endpoint": "http://otel-collector:4318/v1/traces",
            "service_name": "gpt2giga-dev",
        },
    )

    result = await AdminControlPlaneSettingsService(
        request
    ).update_observability_settings(payload)

    assert result["section"] == "observability"
    assert result["restart_required"] is False
    assert result["applied_runtime"] is True
    assert result["values"]["active_sinks"] == ["prometheus", "otlp"]
    sink_by_id = {sink["id"]: sink for sink in result["values"]["sinks"]}
    assert sink_by_id["otlp"]["configured"] is True
    assert sink_by_id["otlp"]["settings"]["service_name"] == "gpt2giga-dev"


@pytest.mark.asyncio
async def test_admin_control_plane_settings_service_builds_masked_revision_diffs(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    request = _build_request()
    keys = AdminKeyManagementService(request)

    await keys.rotate_global_key(value="first-global-key")
    await keys.rotate_global_key(value="second-global-key")

    payload = AdminControlPlaneSettingsService(request).build_revisions_payload(limit=5)

    previous_revision = payload["revisions"][1]
    assert previous_revision["changed_fields"] == ["api_key"]
    security_diff = previous_revision["diff"]["security"][0]
    assert security_diff["field"] == "api_key"
    assert security_diff["current"]["configured"] is True
    assert security_diff["target"]["configured"] is True
    assert security_diff["current"]["preview"] != "second-global-key"
    assert security_diff["target"]["preview"] != "first-global-key"


@pytest.mark.asyncio
async def test_admin_control_plane_settings_service_tests_gigachat_factory():
    request = _build_request()
    captured_kwargs = {}

    class FakeModel:
        def __init__(self, model_id: str):
            self.id = model_id

    class FakeGigaChat:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def aget_models(self):
            return type("Result", (), {"data": [FakeModel("GigaChat-Max")]})()

        async def aclose(self):
            return None

    request.app.state.providers.gigachat_factory = FakeGigaChat

    payload = await AdminControlPlaneSettingsService(request).test_gigachat_settings(
        {
            "credentials": "gigachat-secret",
            "scope": "GIGACHAT_API_PERS",
            "ca_bundle_file": "/certs/company-root.pem",
            "verify_ssl_certs": True,
        }
    )

    assert payload["ok"] is True
    assert payload["sample_models"] == ["GigaChat-Max"]
    assert captured_kwargs["ca_bundle_file"] == "/certs/company-root.pem"


@pytest.mark.asyncio
async def test_admin_key_management_service_manages_scoped_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_CONTROL_PLANE_DIR", str(tmp_path))
    request = _build_request()
    service = AdminKeyManagementService(request)

    created = await service.create_scoped_key(
        name="sdk-openai",
        key="created-key",
        providers=["openai"],
        endpoints=["chat/completions"],
        models=None,
    )
    rotated = await service.rotate_scoped_key(
        name="sdk-openai",
        key="rotated-key",
    )
    deleted = await service.delete_scoped_key(name="sdk-openai")

    assert created["scoped_key"]["value"] == "created-key"
    assert created["keys"]["scoped"][0]["name"] == "sdk-openai"
    assert rotated["scoped_key"]["value"] == "rotated-key"
    assert rotated["keys"]["scoped"][0]["key_preview"] != "rotated-key"
    assert deleted["deleted"] == "sdk-openai"
    assert deleted["keys"]["scoped"] == []
