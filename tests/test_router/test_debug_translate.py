import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.api.admin import router as debug_router
from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocols.openai import OpenAIProtocolAdapter

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "debug_translate"


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {"prepared": "v1", "payload": data}

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        return {"prepared": "v2", "payload": data}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def make_debug_app(*, admin_key: str | None = "secret", mode: str = "v1"):
    app = FastAPI()
    app.include_router(debug_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            debug_translate_enabled=True,
            admin_api_key=admin_key,
            gigachat_api_mode=mode,
        )
    )
    app.state.logger = logger
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.gigachat_client = object()
    return app


def _headers(key: str = "secret") -> dict[str, str]:
    return {"x-admin-api-key": key}


def test_debug_translate_endpoints_are_unmounted_by_default():
    app = create_app(ProxyConfig(proxy=ProxySettings()))
    client = TestClient(app)

    response = client.post(
        "/_debug/translate/openai-to-normalized",
        json=_fixture("openai_simple_chat.json"),
        headers=_headers(),
    )

    assert response.status_code == 404


def test_debug_translate_prod_default_is_unmounted():
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
        "/_debug/translate/openai-to-normalized",
        json=_fixture("openai_simple_chat.json"),
        headers=_headers(),
    )

    assert response.status_code == 404


def test_debug_translate_requires_admin_key():
    client = TestClient(make_debug_app(admin_key="secret"))

    missing = client.post(
        "/_debug/translate/openai-to-normalized",
        json=_fixture("openai_simple_chat.json"),
    )
    wrong = client.post(
        "/_debug/translate/openai-to-normalized",
        json=_fixture("openai_simple_chat.json"),
        headers=_headers("wrong"),
    )
    bearer = client.post(
        "/_debug/translate/openai-to-normalized",
        json=_fixture("openai_simple_chat.json"),
        headers={"authorization": "Bearer secret"},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert bearer.status_code == 200


def test_debug_translate_enabled_without_admin_key_returns_403():
    client = TestClient(make_debug_app(admin_key=None))

    response = client.post(
        "/_debug/translate/openai-to-normalized",
        json=_fixture("openai_simple_chat.json"),
        headers=_headers(),
    )

    assert response.status_code == 403


def test_debug_translate_generic_openai_to_anthropic():
    client = TestClient(make_debug_app())

    response = client.post(
        "/_debug/translate",
        json={
            "from": "openai",
            "to": "anthropic",
            "payload": _fixture("openai_tools.json"),
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    payload = body["payload"]
    assert body["from"] == "openai"
    assert body["to"] == "anthropic"
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"][0]["text"] == "lookup weather"
    assert payload["tools"][0]["name"] == "lookup_weather"
    assert payload["tool_choice"] == {
        "type": "tool",
        "name": "lookup_weather",
    }
    assert body["intermediate"]["normalized"]["tools"][0]["name"] == "lookup_weather"


def test_debug_translate_generic_returns_400_for_unsupported_pair():
    client = TestClient(make_debug_app())

    response = client.post(
        "/_debug/translate",
        json={"from": "gigachat", "to": "anthropic", "payload": {}},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Unsupported translation pair: gigachat -> anthropic"
    )


@pytest.mark.parametrize(
    ("fixture_name", "assertion_key"),
    [
        ("openai_simple_chat.json", "simple"),
        ("openai_tools.json", "tools"),
        ("openai_structured_output.json", "structured"),
        ("openai_multimodal.json", "multimodal"),
    ],
)
def test_debug_translate_openai_to_normalized_fixtures(
    fixture_name,
    assertion_key,
):
    client = TestClient(make_debug_app())

    response = client.post(
        "/_debug/translate/openai-to-normalized",
        json=_fixture(fixture_name),
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    normalized = body["normalized"]
    assert body["source"] == "openai"
    assert body["target"] == "normalized"
    assert normalized["model"] == "GigaChat"
    if assertion_key == "tools":
        assert normalized["tools"][0]["name"] == "lookup_weather"
        assert normalized["tool_choice"]["function"]["name"] == "lookup_weather"
    elif assertion_key == "structured":
        assert normalized["response_format"]["json_schema"]["name"] == "answer"
    elif assertion_key == "multimodal":
        content = normalized["messages"][0]["content"]
        assert content[1]["type"] == "image_url"
        assert content[1]["detail"] == "low"
    else:
        assert normalized["messages"][0]["content"] == "hello"


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("anthropic_simple_chat.json", "Be concise."),
        ("anthropic_tools.json", "lookup_weather"),
    ],
)
def test_debug_translate_anthropic_to_normalized_fixtures(fixture_name, expected):
    client = TestClient(make_debug_app())

    response = client.post(
        "/_debug/translate/anthropic-to-normalized",
        json=_fixture(fixture_name),
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "anthropic"
    assert body["target"] == "normalized"
    assert expected in json.dumps(body, ensure_ascii=False)


def test_debug_translate_normalized_to_gigachat():
    client = TestClient(make_debug_app())

    response = client.post(
        "/_debug/translate/normalized-to-gigachat",
        json={
            "model": "GigaChat",
            "messages": [{"role": "user", "content": "hello"}],
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "normalized"
    assert body["target"] == "gigachat"
    assert body["openai_payload"]["messages"][0]["content"] == "hello"
    assert body["gigachat_payload"]["prepared"] == "v1"


def test_debug_translate_gigachat_to_openai():
    client = TestClient(make_debug_app())

    response = client.post(
        "/_debug/translate/gigachat-to-openai",
        json={
            "requested_model": "gpt-x",
            "response": {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            },
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "gigachat"
    assert body["target"] == "openai"
    assert body["normalized"]["choices"][0]["message"]["content"] == "ok"
    assert body["openai"]["choices"][0]["message"]["content"] == "ok"
    assert body["openai"]["usage"]["total_tokens"] == 3
