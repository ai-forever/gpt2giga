import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.admin import compat_router
from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings


class FailingUpstreamClient:
    def __getattribute__(self, name):
        raise AssertionError(f"unexpected upstream access: {name}")


def make_compat_app(*, admin_key: str | None = "secret", mode: str = "v1"):
    app = FastAPI()
    app.include_router(compat_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            admin_api_enabled=True,
            admin_api_key=admin_key,
            gigachat_api_mode=mode,
        )
    )
    app.state.gigachat_client = FailingUpstreamClient()
    return app


def _headers(key: str = "secret") -> dict[str, str]:
    return {"x-admin-api-key": key}


def test_admin_compat_unmounted_by_default():
    app = create_app(ProxyConfig(proxy=ProxySettings()))
    client = TestClient(app)

    response = client.post(
        "/_admin/compat/analyze",
        json={"route": "/chat/completions", "body": {"messages": []}},
        headers=_headers(),
    )

    assert response.status_code == 404


def test_admin_compat_prod_default_is_unmounted():
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                mode="PROD",
                enable_api_key_auth=True,
                api_key="client-secret",
            )
        )
    )
    client = TestClient(app)

    response = client.post(
        "/_admin/compat/analyze",
        json={"route": "/chat/completions", "body": {"messages": []}},
        headers=_headers(),
    )

    assert response.status_code == 404


def test_admin_compat_requires_admin_key():
    client = TestClient(make_compat_app())
    payload = {"route": "/models"}

    missing = client.post("/_admin/compat/analyze", json=payload)
    wrong = client.post(
        "/_admin/compat/analyze",
        json=payload,
        headers=_headers("wrong"),
    )
    bearer = client.post(
        "/_admin/compat/analyze",
        json=payload,
        headers={"authorization": "Bearer secret"},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert bearer.status_code == 200


def test_admin_compat_enabled_without_admin_key_returns_403():
    client = TestClient(make_compat_app(admin_key=None))

    response = client.post(
        "/_admin/compat/analyze",
        json={"route": "/models"},
        headers=_headers(),
    )

    assert response.status_code == 403


def test_admin_compat_create_app_mounts_when_admin_api_enabled():
    app = create_app(
        ProxyConfig(proxy=ProxySettings(admin_api_enabled=True, admin_api_key="secret"))
    )
    client = TestClient(app)

    response = client.post(
        "/_admin/compat/analyze",
        json={"route": "/model/info"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["operation"] == "model_info"


def test_admin_compat_returns_redacted_diagnostics_without_raw_content():
    client = TestClient(make_compat_app(mode="v2"))

    response = client.post(
        "/_admin/compat/analyze",
        json={
            "protocol": "openai",
            "route": "/v2/chat/completions",
            "headers": {
                "Authorization": "Bearer upstream-secret",
                "x-request-id": "req-1",
            },
            "query": {"key": "query-secret"},
            "body": {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "raw prompt secret"}],
                "tools": [{"type": "web_search_preview"}],
                "metadata": {"session_token": "body-secret"},
            },
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["protocol"] == "openai"
    assert body["route"] == "/v2/chat/completions"
    assert body["operation"] == "chat_completions"
    assert body["backend_mode"] == "gigachat_v2"
    assert body["security"] == {
        "headers_redacted": ["authorization"],
        "query_redacted": ["key"],
        "body_fields_redacted": ["metadata.session_token"],
    }
    assert body["tools"]["mapped_builtin_tools"] == [
        {
            "from": "web_search_preview",
            "to": "web_search",
            "reason": "provider_alias",
        }
    ]
    serialized = json.dumps(body, ensure_ascii=False)
    assert "raw prompt secret" not in serialized
    assert "upstream-secret" not in serialized
    assert "query-secret" not in serialized
    assert "body-secret" not in serialized


def test_admin_compat_rejects_invalid_envelope_without_echoing_values():
    client = TestClient(make_compat_app())

    response = client.post(
        "/_admin/compat/analyze",
        json={"route": "/models", "headers": "Authorization: secret"},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Expected headers to be an object"}
