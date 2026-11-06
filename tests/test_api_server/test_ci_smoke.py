from types import SimpleNamespace

from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class FakeModel:
    def model_dump(self, by_alias=True):
        return {
            "id": "GigaChat",
            "object": "model",
            "owned_by": "gigachat",
        }


class FakeAChatResource:
    async def __call__(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Hello!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )

    async def create(self, chat):
        if hasattr(chat, "model_dump"):
            chat = chat.model_dump(exclude_none=True)
        return MockResponse(
            {
                "model": chat.get("model", "GigaChat"),
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "Hello!"}],
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )


class FakeGigaChat:
    def __init__(self, **kwargs):
        self.achat = FakeAChatResource()

    async def aget_models(self):
        return SimpleNamespace(data=[FakeModel()], object_="list")

    async def aget_model(self, model: str):
        return SimpleNamespace(id_=model)

    async def aclose(self):
        return None


def make_app(monkeypatch):
    config = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            log_filename="/tmp/gpt2giga-ci-smoke.log",
            gigachat_api_mode="v1",
        )
    )
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )
    return create_app(config=config)


def install_fake_transformer(app):
    app.state.request_transformer = RequestTransformer(
        app.state.config, app.state.logger
    )


def test_ci_smoke_health(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_ci_smoke_v1_models(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "GigaChat"
    assert body["data"][0]["metadata"] == {"type": "chat"}


def test_ci_smoke_v2_models(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/v2/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "GigaChat"
    assert body["data"][0]["metadata"] == {"type": "chat"}


def test_ci_smoke_litellm_model_info(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/v1/model/info")

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["model_name"] == "GigaChat"


def test_ci_smoke_openai_chat(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello!"


def test_ci_smoke_anthropic_messages(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        response = client.post(
            "/v1/messages",
            json={
                "model": "claude-test",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["content"][0]["text"] == "Hello!"


def test_ci_smoke_anthropic_messages_duplicate_v1_prefix(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        response = client.post(
            "/v1/v1/messages",
            json={
                "model": "claude-test",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"


def test_ci_smoke_anthropic_messages_gateway_v2_api_v1_prefix(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        response = client.post(
            "/v2/v1/messages",
            json={
                "model": "claude-test",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"


def test_ci_smoke_gemini_v1beta_under_v2_prefix(monkeypatch):
    app = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        response = client.post(
            "/v2/v1beta/models/GigaChat-2-Max:generateContent",
            json={
                "contents": [{"parts": [{"text": "Hello"}]}],
                "generationConfig": {"maxOutputTokens": 64},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["content"]["parts"] == [{"text": "Hello!"}]
