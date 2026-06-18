import json

from fastapi.testclient import TestClient

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings


def _app(
    *,
    ui_enabled: bool = True,
    admin_key: str | None = "admin",
    api_key: str | None = None,
):
    return create_app(
        ProxyConfig(
            proxy=ProxySettings(
                ui_enabled=ui_enabled,
                admin_api_key=admin_key,
                enable_api_key_auth=api_key is not None,
                api_key=api_key,
            )
        )
    )


def _headers(key: str = "admin") -> dict[str, str]:
    return {"x-admin-api-key": key}


def test_playground_helpers_are_unmounted_by_default():
    client = TestClient(_app(ui_enabled=False))

    response = client.get("/_admin/playground/examples", headers=_headers())

    assert response.status_code == 404


def test_playground_helpers_require_admin_key():
    client = TestClient(_app())

    missing = client.get("/_admin/playground/examples")
    wrong = client.get("/_admin/playground/examples", headers=_headers("wrong"))
    bearer = client.get(
        "/_admin/playground/examples",
        headers={"authorization": "Bearer admin"},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert bearer.status_code == 200


def test_playground_examples_return_builtin_protocol_cases():
    client = TestClient(_app())

    response = client.get("/_admin/playground/examples", headers=_headers())

    assert response.status_code == 200
    examples = {item["id"]: item["request"] for item in response.json()["data"]}
    assert examples["openai-chat"]["protocol"] == "openai"
    assert examples["anthropic-messages"]["protocol"] == "anthropic"
    assert examples["gemini-generate"]["operation"] == "generateContent"
    assert examples["gemini-stream"]["stream"] is True
    assert examples["structured-output"]["protocol"] == "gemini"


def test_playground_translate_reuses_debug_translation_adapters():
    client = TestClient(_app())

    response = client.post(
        "/_admin/playground/translate",
        json={
            "from": "openai",
            "to": "normalized",
            "payload": {
                "model": "GigaChat",
                "messages": [{"role": "user", "content": "hello"}],
            },
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["from"] == "openai"
    assert body["to"] == "normalized"
    assert body["payload"]["model"] == "GigaChat"
    assert body["payload"]["messages"][0]["content"] == "hello"


def test_playground_send_preserves_public_auth_semantics_and_redacts_query_key():
    client = TestClient(_app(api_key="client-secret"))

    response = client.post(
        "/_admin/playground/send",
        json={
            "method": "POST",
            "path": "/v1/chat/completions?key=gemini-secret&model=GigaChat",
            "headers": {},
            "body": {
                "model": "GigaChat",
                "messages": [{"role": "user", "content": "hello"}],
            },
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["request"]["path"] == "/v1/chat/completions?key=***&model=GigaChat"
    assert body["response"]["status_code"] == 401
    assert body["response"]["body"]["detail"] == "Invalid API key"
    assert "gemini-secret" not in json.dumps(body)


def test_playground_send_redacts_headers_and_body_without_forwarding_admin_key():
    client = TestClient(_app())

    response = client.post(
        "/_admin/playground/send",
        json={
            "method": "POST",
            "path": "/ping",
            "headers": {
                "Authorization": "Bearer proxy-secret",
                "x-admin-api-key": "admin",
            },
            "body": {"api_key": "body-secret", "prompt": "hello"},
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response"]["status_code"] == 200
    assert body["request"]["headers"] == {"Authorization": "***"}
    assert body["request"]["body"]["api_key"] == "***"
    serialized = json.dumps(body)
    assert "proxy-secret" not in serialized
    assert "body-secret" not in serialized
    assert "x-admin-api-key" not in serialized


def test_playground_send_blocks_admin_and_debug_paths():
    client = TestClient(_app())

    response = client.post(
        "/_admin/playground/send",
        json={"method": "POST", "path": "/_admin/logs", "headers": {}, "body": {}},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert "cannot be sent" in response.json()["detail"]
