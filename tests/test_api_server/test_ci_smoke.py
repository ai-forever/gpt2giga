from types import SimpleNamespace

from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeModel:
    def model_dump(self, by_alias=True):
        return {
            "id": "GigaChat",
            "object": "model",
            "owned_by": "gigachat",
        }


class FakeGigaChat:
    def __init__(self, **kwargs):
        pass

    async def aget_models(self):
        return SimpleNamespace(data=[FakeModel()], object_="list")

    async def aget_model(self, model: str):
        return SimpleNamespace(id_=model)

    async def achat(self, chat):
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

    async def aclose(self):
        return None


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {
            "model": data.get("model", "giga"),
            "messages": data.get("messages", []),
            "tools": data.get("tools"),
            "function_call": data.get("function_call"),
            "functions": data.get("functions"),
            "reasoning_effort": data.get("reasoning_effort"),
        }


def make_app(monkeypatch):
    config = ProxyConfig(
        proxy=ProxySettings(mode="DEV", log_filename="/tmp/gpt2giga-ci-smoke.log")
    )
    monkeypatch.setattr("gpt2giga.api_server.GigaChat", lambda **kw: FakeGigaChat())
    return create_app(config=config)


def install_fake_transformer(app):
    app.state.request_transformer = FakeRequestTransformer()


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
