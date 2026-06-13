import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
from pydantic import BaseModel, Field

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.routers.gemini import router as gemini_router
from gpt2giga.routers.gemini.batches import router as gemini_batches_router
from gpt2giga.routers.gemini.files import router as gemini_files_router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, **_kwargs):
        return self.data


class FakeAChat:
    def __init__(self):
        self.calls = []
        self.create_calls = []
        self.stream_calls = []

    async def __call__(self, payload):
        self.calls.append(payload)
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
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

    async def create(self, payload):
        self.create_calls.append(payload)
        return MockResponse(
            {
                "model": "GigaChat-2-Max",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "Gemini ok"}],
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 3,
                    "total_tokens": 5,
                },
            }
        )

    def stream(self, payload):
        self.stream_calls.append(payload)

        async def gen():
            yield MockResponse(
                {
                    "model": "GigaChat-2-Max",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [{"text": "Gem"}],
                        }
                    ],
                }
            )
            done_payload = {
                "event": "response.message.done",
                "model": "GigaChat-2-Max",
                "created_at": 1781352508,
                "messages": [
                    {
                        "role": "assistant",
                        "tool_state_id": "new-state",
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 3,
                    "total_tokens": 5,
                },
            }
            yield (
                "event: response.message.done\n"
                f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
            )

        return gen()


class FakeModels(BaseModel):
    data: list
    object_: str = "list"


class FakeModel(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(alias="object")
    owned_by: str


class FakeUploadedFile(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(alias="object")
    bytes_: int = Field(alias="bytes")
    created_at: int
    filename: str
    purpose: str


class FakeGigaChat:
    def __init__(self):
        self.achat = FakeAChat()
        self.embedding_calls = []

    def astream(self, payload):
        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "Hel"},
                            "finish_reason": None,
                        }
                    ]
                }
            )
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"content": "lo"},
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

    async def aget_models(self):
        return FakeModels(
            data=[FakeModel(id="GigaChat", object="model", owned_by="Sber")]
        )

    async def aget_model(self, model):
        return FakeModel(id=model, object="model", owned_by="Sber")

    async def aupload_file(self, file, purpose):
        filename, content, _content_type = file
        return FakeUploadedFile(
            id="file-1",
            object="file",
            bytes=len(content),
            created_at=123,
            filename=filename,
            purpose=purpose,
        )


class FakeRequestTransformer:
    def __init__(self):
        self.chat_calls = []
        self.chat_completion_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        return {"model": data["model"], "messages": data["messages"]}

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_completion_calls.append((data, giga_client))
        return {"model": data["model"], "messages": data["messages"]}


def make_app(*, include_prepared_files_batches=False, mode="v1"):
    app = FastAPI()
    app.include_router(gemini_router)
    if include_prepared_files_batches:
        app.include_router(gemini_files_router)
        app.include_router(gemini_batches_router)
    app.state.gigachat_client = FakeGigaChat()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.gemini_protocol_adapter = GeminiProtocolAdapter()
    app.state.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode=mode))
    return app


def test_gemini_generate_content_roundtrips_through_gigachat_provider():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:generateContent",
        json={
            "systemInstruction": {"parts": [{"text": "Be concise."}]},
            "contents": [{"parts": [{"text": "Hello"}]}],
            "generationConfig": {"maxOutputTokens": 64},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["content"]["parts"] == [{"text": "ok"}]
    assert body["usageMetadata"]["totalTokenCount"] == 5
    payload = app.state.request_transformer.chat_calls[0][0]
    assert payload["messages"][0] == {"role": "system", "content": "Be concise."}
    assert payload["messages"][1] == {"role": "user", "content": "Hello"}
    assert payload["max_tokens"] == 64


def test_gemini_stream_generate_content_returns_sse_without_openai_done_marker():
    app = make_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/models/gemini-pro:streamGenerateContent?alt=sse",
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "data: " in body
    assert '"text": "Hel"' in body
    assert '"finishReason": "STOP"' in body
    assert "[DONE]" not in body


def test_gemini_v2_stream_generate_content_handles_named_done_event():
    app = make_app(mode="v2")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/models/gemini-pro:streamGenerateContent?alt=sse",
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert chunks[0]["candidates"][0]["content"]["parts"] == [{"text": "Gem"}]
    assert chunks[-1]["candidates"][0]["finishReason"] == "STOP"
    assert chunks[-1]["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 3,
        "totalTokenCount": 5,
    }
    assert "[DONE]" not in body
    assert not app.state.request_transformer.chat_calls
    assert app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.stream_calls == [
        {"model": "gemini-pro", "messages": [{"role": "user", "content": "Hello"}]}
    ]


def test_gemini_count_tokens_and_embeddings():
    app = make_app()
    client = TestClient(app)

    token_response = client.post(
        "/models/gemini-pro:countTokens",
        json={"contents": [{"parts": [{"text": "hello world"}]}]},
    )
    embedding_response = client.post(
        "/models/gemini-embedding:embedContent",
        json={"content": {"parts": [{"text": "embed me"}]}},
    )

    assert token_response.status_code == 200
    assert token_response.json() == {"totalTokens": 2}
    assert embedding_response.status_code == 200
    assert embedding_response.json()["embedding"]["values"] == [0.0]
    assert app.state.gigachat_client.embedding_calls == [
        {"texts": ["embed me"], "model": "gemini-embedding"}
    ]


def test_gemini_models_use_gemini_resource_shape():
    client = TestClient(make_app())

    listed = client.get("/models")
    retrieved = client.get("/models/GigaChat")

    assert listed.status_code == 200
    assert listed.json()["models"][0]["name"] == "models/GigaChat"
    assert retrieved.status_code == 200
    assert retrieved.json()["supportedGenerationMethods"] == [
        "generateContent",
        "streamGenerateContent",
        "countTokens",
    ]


def test_gemini_files_and_batches_are_not_mounted_in_public_router():
    client = TestClient(make_app())

    assert client.post("/files", json={"file": {"displayName": "x"}}).status_code == 404
    assert client.get("/files").status_code == 404
    assert client.get("/batches").status_code == 404
    assert "/models/{model}:batchGenerateContent" not in make_app().openapi()["paths"]
    assert (
        client.post(
            "/models/gemini-pro:batchGenerateContent",
            json={"batch": {"displayName": "batch"}},
        ).status_code
        != 200
    )


def test_gemini_prepared_files_and_batches_work_when_mounted_directly():
    app = make_app(include_prepared_files_batches=True)
    client = TestClient(app)

    file_response = client.post(
        "/files",
        files={"file": ("input.jsonl", b'{"contents":[]}\n', "application/json")},
    )
    batch_response = client.post(
        "/models/gemini-pro:batchGenerateContent",
        json={
            "batch": {
                "displayName": "batch",
                "inputConfig": {"fileName": file_response.json()["file"]["name"]},
            }
        },
    )

    assert file_response.status_code == 200
    assert file_response.json()["file"]["name"] == "files/file-1"
    assert batch_response.status_code == 200
    operation = batch_response.json()
    assert operation["metadata"]["batch"]["model"] == "models/gemini-pro"
    assert client.get("/batches").json()["batches"][0]["name"] == "batches/1"
    assert json.dumps(operation)
