from fastapi import FastAPI
from starlette.requests import Request

from gpt2giga.api.admin import admin_api_router
from gpt2giga.api.system import system_router
from gpt2giga.app.admin_runtime import AdminRuntimeSnapshotService, AdminUsageReporter
from gpt2giga.app.dependencies import ensure_runtime_dependencies
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
            "path": "/admin/api/runtime",
            "headers": [],
        }
    )


def test_admin_runtime_snapshot_service_reports_runtime_state():
    request = _build_request(
        ProxyConfig(
            proxy=ProxySettings(
                enable_telemetry=False,
                enabled_providers=["openai", "gemini"],
            )
        )
    )

    payload = AdminRuntimeSnapshotService(request).build_runtime_payload()

    assert payload["mode"] == "DEV"
    assert payload["telemetry_enabled"] is False
    assert payload["metrics_enabled"] is False
    assert payload["enabled_providers"] == ["openai", "gemini"]
    assert payload["state"]["stores"]["backend"] == "memory"
    assert payload["state"]["stores"]["usage_by_api_key"] == 0


def test_admin_runtime_snapshot_service_reports_config_summary():
    request = _build_request(
        ProxyConfig(
            proxy=ProxySettings(
                host="localhost",
                port=8090,
                gigachat_api_mode="v1",
                gigachat_responses_api_mode="v2",
                enable_telemetry=True,
            )
        )
    )

    payload = AdminRuntimeSnapshotService(request).build_config_payload()

    assert payload["mode"] == "DEV"
    assert payload["summary"]["network"]["bind"] == "localhost:8090"
    assert payload["summary"]["providers"]["gigachat_api_mode"] == "v1"
    assert payload["summary"]["providers"]["gigachat_responses_api_mode"] == "v2"
    assert payload["summary"]["providers"]["chat_backend_mode"] == "v1"
    assert payload["summary"]["providers"]["responses_backend_mode"] == "v2"
    assert payload["summary"]["providers"]["telemetry_enabled"] is True


def test_admin_usage_reporter_filters_and_summarizes_entries():
    request = _build_request()
    request.app.state.stores.usage_by_api_key["sdk-openai"] = {
        "name": "sdk-openai",
        "source": "scoped",
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
                "total_tokens": 12,
            }
        },
        "providers": {
            "openai": {
                "request_count": 2,
                "total_tokens": 12,
            }
        },
        "api_keys": {},
    }

    payload = AdminUsageReporter(request).build_payload(
        kind="keys",
        limit=50,
        provider="openai",
        model="GigaChat-2-Max",
        source="scoped",
    )

    assert payload["count"] == 1
    assert payload["entries"][0]["name"] == "sdk-openai"
    assert payload["filters"] == {
        "provider": "openai",
        "model": "GigaChat-2-Max",
        "api_key_name": None,
        "source": "scoped",
    }
    assert payload["available_filters"] == {
        "provider": ["openai"],
        "model": ["GigaChat-2-Max"],
        "api_key_name": [],
        "source": ["scoped"],
    }
    assert payload["summary"]["total_tokens"] == 12
