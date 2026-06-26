import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from gpt2giga.api.admin import playground_router
from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.openapi_tags import OPENAPI_TAG_ADMIN_PLAYGROUND


def make_playground_app(*, admin_key: str | None = "secret") -> FastAPI:
    app = FastAPI()

    @app.post("/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        return JSONResponse(
            {
                "ok": True,
                "authorization_seen": request.headers.get("authorization"),
                "admin_key_seen": request.headers.get("x-admin-api-key"),
                "request_marker": request.headers.get("x-gpt2giga-playground"),
                "body": payload,
                "secret": "response-secret",
            },
            headers={
                "x-request-id": "req-playground",
                "x-secret-token": "response-secret",
            },
        )

    @app.get("/models")
    async def models(request: Request):
        return {
            "object": "list",
            "query": dict(request.query_params),
            "authorization_seen": request.headers.get("authorization"),
        }

    app.include_router(playground_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            admin_api_enabled=True,
            ui_enabled=True,
            admin_api_key=admin_key,
            enable_api_key_auth=True,
            api_key="proxy-secret",
            gigachat_api_mode="v2",
        )
    )
    return app


def _headers(key: str = "secret") -> dict[str, str]:
    return {"x-admin-api-key": key}


def test_admin_playground_unmounted_by_default():
    app = create_app(ProxyConfig(proxy=ProxySettings()))
    client = TestClient(app)

    response = client.get("/_admin/playground/examples", headers=_headers())

    assert response.status_code == 404


def test_admin_playground_requires_ui_and_admin_api_enabled():
    app = create_app(
        ProxyConfig(proxy=ProxySettings(admin_api_enabled=True, admin_api_key="secret"))
    )
    client = TestClient(app)

    response = client.get("/_admin/playground/examples", headers=_headers())

    assert response.status_code == 404


def test_admin_playground_create_app_mounts_with_ui_and_admin_api():
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                admin_api_enabled=True,
                ui_enabled=True,
                admin_api_key="secret",
            )
        )
    )
    client = TestClient(app)

    missing = client.get("/_admin/playground/examples")
    response = client.get("/_admin/playground/examples", headers=_headers())

    assert missing.status_code == 403
    assert response.status_code == 200
    assert response.json()["examples"][0]["id"] == "openai_chat"


def test_admin_playground_openapi_tags_when_mounted():
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                admin_api_enabled=True,
                ui_enabled=True,
                admin_api_key="secret",
            )
        )
    )

    schema = app.openapi()

    assert schema["paths"]["/_admin/playground/send"]["post"]["tags"] == [
        OPENAPI_TAG_ADMIN_PLAYGROUND
    ]
    assert schema["paths"]["/_admin/playground/analyze"]["post"]["tags"] == [
        OPENAPI_TAG_ADMIN_PLAYGROUND
    ]
    assert schema["paths"]["/_admin/playground/examples"]["get"]["tags"] == [
        OPENAPI_TAG_ADMIN_PLAYGROUND
    ]
    assert OPENAPI_TAG_ADMIN_PLAYGROUND in {tag["name"] for tag in schema["tags"]}


def test_admin_playground_requires_admin_key():
    client = TestClient(make_playground_app())
    payload = {"route": "/models", "method": "GET"}

    missing = client.post("/_admin/playground/analyze", json=payload)
    wrong = client.post(
        "/_admin/playground/analyze",
        json=payload,
        headers=_headers("wrong"),
    )
    bearer = client.post(
        "/_admin/playground/analyze",
        json=payload,
        headers={"authorization": "Bearer secret"},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert bearer.status_code == 200


def test_admin_playground_examples_are_safe_starters():
    client = TestClient(make_playground_app())

    response = client.get("/_admin/playground/examples", headers=_headers())

    assert response.status_code == 200
    examples = response.json()["examples"]
    assert {item["id"] for item in examples} == {
        "anthropic_messages",
        "gemini_generate_content",
        "openai_chat",
    }
    serialized = json.dumps(examples, ensure_ascii=False)
    assert "api_key" not in serialized
    assert "Bearer" not in serialized


def test_admin_playground_analyze_reuses_compatibility_doctor():
    client = TestClient(make_playground_app())

    response = client.post(
        "/_admin/playground/analyze",
        headers=_headers(),
        json={
            "protocol": "openai",
            "method": "POST",
            "route": "/v2/chat/completions",
            "headers": {"authorization": "Bearer user-secret"},
            "query": {"key": "query-secret"},
            "body": {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {"access_token": "body-secret"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "chat_completions"
    assert body["backend_mode"] == "gigachat_v2"
    assert body["security"]["headers_redacted"] == ["authorization"]
    assert body["security"]["query_redacted"] == ["key"]
    assert body["security"]["body_fields_redacted"] == ["metadata.access_token"]
    serialized = json.dumps(body, ensure_ascii=False)
    assert "user-secret" not in serialized
    assert "query-secret" not in serialized
    assert "body-secret" not in serialized


def test_admin_playground_send_dispatches_public_route_with_redaction():
    client = TestClient(make_playground_app())

    response = client.post(
        "/_admin/playground/send",
        headers=_headers(),
        json={
            "protocol": "openai",
            "method": "POST",
            "route": "/chat/completions",
            "headers": {
                "authorization": "Bearer user-secret",
                "x-request-id": "safe-request-header",
            },
            "body": {
                "model": "GigaChat-2-Max",
                "messages": [{"role": "user", "content": "hello"}],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is True
    assert body["request_id"] == "req-playground"
    assert body["response"]["status_code"] == 200
    assert body["response"]["body"]["request_marker"] == "true"
    assert body["response"]["body"]["admin_key_seen"] is None
    assert body["response"]["body"]["secret"] == "***"
    assert body["analysis"]["operation"] == "chat_completions"
    serialized = json.dumps(body, ensure_ascii=False)
    assert "user-secret" not in serialized
    assert "proxy-secret" not in serialized
    assert "response-secret" not in serialized
    assert "x-secret-token" in body["response"]["headers"]
    assert body["response"]["headers"]["x-secret-token"] == "***"


def test_admin_playground_send_supports_get_with_safe_query():
    client = TestClient(make_playground_app())

    response = client.post(
        "/_admin/playground/send",
        headers=_headers(),
        json={
            "protocol": "openai",
            "method": "GET",
            "route": "/models?after_id=model-a&key=query-secret",
            "headers": {"authorization": "Bearer user-secret"},
            "query": {"limit": 2, "x-api-key": "query-secret"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response"]["body"]["query"] == {
        "after_id": "model-a",
        "limit": "2",
    }
    serialized = json.dumps(body, ensure_ascii=False)
    assert "user-secret" not in serialized
    assert "query-secret" not in serialized
    assert "proxy-secret" not in serialized


def test_admin_playground_send_blocks_service_routes():
    client = TestClient(make_playground_app())

    response = client.post(
        "/_admin/playground/send",
        headers=_headers(),
        json={
            "protocol": "openai",
            "method": "POST",
            "route": "/_admin/compat/analyze",
            "body": {"route": "/models"},
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Admin, debug, log, and UI routes cannot be sent from playground"
    }
