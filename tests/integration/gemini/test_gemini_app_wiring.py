from types import SimpleNamespace

from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, **kwargs):
        return self.data


class FakeModel:
    def __init__(self, model_id="GigaChat"):
        self.model_id = model_id

    def model_dump(self, by_alias=True):
        return {
            "id": self.model_id,
            "object": "model",
            "owned_by": "gigachat",
        }


class FakeAChat:
    def __init__(self, owner):
        self.owner = owner

    async def __call__(self, chat):
        self.owner.chat_calls.append({"mode": "v1", "payload": chat})
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Gemini ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            }
        )

    async def create(self, chat):
        self.owner.chat_calls.append({"mode": "v2", "payload": chat})
        return MockResponse(
            {
                "messages": [{"role": "assistant", "content": "Gemini ok"}],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            }
        )

    def stream(self, chat):
        self.owner.chat_calls.append({"mode": "v2-stream", "payload": chat})

        async def gen():
            yield MockResponse({"messages": [{"role": "assistant", "content": "Gem"}]})
            yield MockResponse(
                {
                    "messages": [{"role": "assistant", "content": "ini"}],
                    "finish_reason": "stop",
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )

        return gen()


class FakeGigaChat:
    def __init__(self):
        self.achat = FakeAChat(self)
        self.chat_calls = []
        self.embedding_calls = []

    async def aget_models(self):
        return SimpleNamespace(data=[FakeModel()], object_="list")

    async def aget_model(self, model: str):
        return FakeModel(model)

    def astream(self, chat):
        self.chat_calls.append({"mode": "v1-stream", "payload": chat})

        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "Gem"},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"content": "ini"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )

        return gen()

    async def atokens_count(self, texts, model):
        return [SimpleNamespace(tokens=len(text.split()) or 1) for text in texts]

    async def aembeddings(self, texts, model):
        self.embedding_calls.append({"texts": texts, "model": model})
        return {
            "data": [
                {"embedding": [float(index)], "index": index}
                for index, _text in enumerate(texts)
            ],
            "model": model,
            "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
        }

    async def aclose(self):
        return None


class FakeRequestTransformer:
    async def prepare_chat(self, data, giga_client=None):
        return {
            "model": data.get("model", "GigaChat"),
            "messages": data.get("messages", []),
            "tools": data.get("tools"),
            "tool_choice": data.get("tool_choice"),
            "max_tokens": data.get("max_tokens"),
        }

    async def prepare_chat_completion(self, data, giga_client=None):
        return await self.prepare_chat(data, giga_client)


def make_app(monkeypatch):
    fake_client = FakeGigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: fake_client,
    )
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                mode="DEV",
                log_filename="/tmp/gpt2giga-gemini-integration.log",
                gigachat_api_mode="v1",
            )
        )
    )
    return app, fake_client


def install_fake_transformer(app):
    app.state.request_transformer = FakeRequestTransformer()


def test_gemini_v1beta_generate_count_embed_and_models(monkeypatch):
    app, fake_client = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        models = client.get("/v1beta/models")
        generated = client.post(
            "/v1beta/models/GigaChat:generateContent",
            json={
                "contents": [{"parts": [{"text": "hello"}]}],
                "generationConfig": {"maxOutputTokens": 64},
            },
        )
        tokens = client.post(
            "/v1beta/models/GigaChat:countTokens",
            json={"contents": [{"parts": [{"text": "hello world"}]}]},
        )
        embedding = client.post(
            "/v1beta/models/Embeddings:embedContent",
            json={"content": {"parts": [{"text": "embed me"}]}},
        )

    assert models.status_code == 200
    assert models.json()["models"][0]["name"] == "models/GigaChat"
    assert generated.status_code == 200
    assert generated.json()["candidates"][0]["content"]["parts"] == [
        {"text": "Gemini ok"}
    ]
    assert fake_client.chat_calls[0]["payload"]["max_tokens"] == 64
    assert tokens.status_code == 200
    assert tokens.json() == {"totalTokens": 2}
    assert embedding.status_code == 200
    assert embedding.json()["embedding"]["values"] == [0.0]
    assert fake_client.embedding_calls == [
        {"texts": ["embed me"], "model": "Embeddings"}
    ]


def test_gemini_stream_and_prefixed_v1beta_path(monkeypatch):
    app, _fake_client = make_app(monkeypatch)

    with TestClient(app) as client:
        install_fake_transformer(app)
        with client.stream(
            "POST",
            "/proxy/v1beta/models/GigaChat:streamGenerateContent?alt=sse",
            json={"contents": [{"parts": [{"text": "hello"}]}]},
        ) as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"text": "Gem"' in body
    assert '"finishReason": "STOP"' in body
    assert "[DONE]" not in body


def test_gemini_generate_is_mounted_on_shared_prefixes(monkeypatch):
    app, fake_client = make_app(monkeypatch)
    paths = app.openapi()["paths"]

    assert "/models/{model}:generateContent" in paths
    assert "/v1/models/{model}:generateContent" in paths
    assert "/v2/models/{model}:generateContent" in paths
    assert "/v1beta/models/{model}:generateContent" in paths

    with TestClient(app) as client:
        install_fake_transformer(app)
        responses = [
            client.post(
                "/models/GigaChat:generateContent",
                json={"contents": [{"parts": [{"text": "root"}]}]},
            ),
            client.post(
                "/v1/models/GigaChat:generateContent",
                json={"contents": [{"parts": [{"text": "v1"}]}]},
            ),
            client.post(
                "/v2/models/GigaChat:generateContent",
                json={"contents": [{"parts": [{"text": "v2"}]}]},
            ),
            client.post(
                "/v1beta/models/GigaChat:generateContent",
                json={"contents": [{"parts": [{"text": "v1beta"}]}]},
            ),
        ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert [call["mode"] for call in fake_client.chat_calls] == [
        "v1",
        "v1",
        "v2",
        "v1",
    ]


def test_gemini_prepared_files_and_batches_are_not_publicly_mounted(monkeypatch):
    app, _fake_client = make_app(monkeypatch)
    paths = app.openapi()["paths"]

    assert "/v1beta/files" not in paths
    assert "/v1beta/batches" not in paths
    assert "/v1beta/models/{model}:batchGenerateContent" not in paths
    assert "/v1/files" not in paths
    assert "/v1/batches" not in paths
    assert "/v1/models/{model}:batchGenerateContent" not in paths
    assert "/v2/files" not in paths
    assert "/v2/batches" not in paths
    assert "/v2/models/{model}:batchGenerateContent" not in paths

    with TestClient(app) as client:
        install_fake_transformer(app)
        files = client.get("/v1beta/files")
        batch = client.post(
            "/v1beta/models/GigaChat:batchGenerateContent",
            json={"batch": {"displayName": "demo"}},
        )
        v1_batch = client.post(
            "/v1/models/GigaChat:batchGenerateContent",
            json={"batch": {"displayName": "demo"}},
        )

    assert files.status_code == 404
    assert batch.status_code in {404, 405}
    assert v1_batch.status_code in {404, 405}
