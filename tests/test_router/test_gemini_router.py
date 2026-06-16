import json
from types import SimpleNamespace

import pytest
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
from gpt2giga.routers.gemini.models import build_gemini_model


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
                        "content": [{"text": "ini"}],
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
        self.token_count_calls = []

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
        self.token_count_calls.append({"texts": texts, "model": model})
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


class EmptyStreamGigaChat(FakeGigaChat):
    def astream(self, payload):
        async def gen():
            if False:
                yield payload

        return gen()


class PartialFailingStreamGigaChat(FakeGigaChat):
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
            raise RuntimeError("upstream stream exploded")

        return gen()


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


class FailingPrepareRequestTransformer(FakeRequestTransformer):
    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        raise RuntimeError("prepare stream payload failed")


class RecordingObservabilitySink:
    def __init__(self):
        self.events = []

    async def emit(self, name, attributes=None, *, context=None, events=None):
        self.events.append((name, attributes or {}, context, list(events or [])))

    async def flush(self):
        return None


def make_app(
    *,
    include_prepared_files_batches=False,
    mode="v1",
    giga_client=None,
    request_transformer=None,
):
    app = FastAPI()
    app.include_router(gemini_router)
    if include_prepared_files_batches:
        app.include_router(gemini_files_router)
        app.include_router(gemini_batches_router)
    app.state.gigachat_client = giga_client or FakeGigaChat()
    app.state.request_transformer = request_transformer or FakeRequestTransformer()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.gemini_protocol_adapter = GeminiProtocolAdapter()
    app.state.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode=mode))
    return app


def _gemini_sse_chunks(body: str):
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


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


def test_gemini_generate_content_emits_phoenix_span_name():
    app = make_app()
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:generateContent",
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
    )

    assert response.status_code == 200
    name, attributes, _context, events = app.state.observability_sink.events[0]
    assert name == "Gemini-Content"
    assert attributes["gpt2giga.api_format"] == "generate_content"
    assert events == []


def test_gemini_generate_content_preserves_multi_function_response_payload():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:generateContent",
        json={
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "first",
                                "args": {"value": 1},
                            }
                        },
                        {
                            "functionCall": {
                                "name": "second",
                                "args": {"value": 2},
                            }
                        },
                    ],
                },
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "first",
                                "response": {"result": "one"},
                            }
                        },
                        {"text": "kept"},
                        {
                            "functionResponse": {
                                "name": "second",
                                "response": {"result": "two"},
                            }
                        },
                    ],
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = app.state.request_transformer.chat_calls[0][0]
    assert payload["messages"] == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "first",
                        "arguments": {"value": 1},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "second",
                        "arguments": {"value": 2},
                    },
                },
            ],
        },
        {
            "role": "tool",
            "content": '{"result": "one"}',
            "name": "first",
            "tool_call_id": "first",
            "gemini_role": "function",
            "functionResponse": {
                "name": "first",
                "response": {"result": "one"},
            },
        },
        {
            "role": "tool",
            "content": "kept",
        },
        {
            "role": "tool",
            "content": '{"result": "two"}',
            "name": "second",
            "tool_call_id": "second",
            "gemini_role": "function",
            "functionResponse": {
                "name": "second",
                "response": {"result": "two"},
            },
        },
    ]


def test_gemini_generate_content_rejects_malformed_function_response():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:generateContent",
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "functionResponse": "not an object",
                        }
                    ]
                }
            ]
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["param"] == (
        "contents[0].parts[0].functionResponse"
    )
    assert app.state.request_transformer.chat_calls == []


def test_gemini_generate_content_rejects_undeclared_allowed_function_name():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:generateContent",
        json={
            "contents": [{"parts": [{"text": "Hello"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {"name": "declared", "parameters": {"type": "object"}}
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["missing"],
                }
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["param"] == (
        "toolConfig.functionCallingConfig.allowedFunctionNames"
    )
    assert app.state.request_transformer.chat_calls == []


@pytest.mark.parametrize(
    ("payload", "param"),
    [
        ({}, "contents"),
        ({"contents": "bad"}, "contents"),
        (
            {"contents": [{"parts": [{"unknown": {"value": 1}}]}]},
            "contents[0].parts[0]",
        ),
        (
            {
                "contents": [{"parts": [{"text": "Hello"}]}],
                "generationConfig": {"responseMimeType": "application/xml"},
            },
            "generationConfig.responseMimeType",
        ),
        (
            {
                "contents": [{"parts": [{"text": "Hello"}]}],
                "tools": [
                    {"functionDeclarations": [{"name": "lookup", "parameters": "bad"}]}
                ],
            },
            "tools[0].functionDeclarations[0].parameters",
        ),
        (
            {"contents": [{"parts": [{"text": "Hello"}]}], "toolConfig": "bad"},
            "toolConfig",
        ),
    ],
)
def test_gemini_generate_content_rejects_invalid_payload_without_upstream_call(
    payload,
    param,
):
    app = make_app()
    client = TestClient(app)

    response = client.post("/models/gemini-pro:generateContent", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["param"] == param
    assert app.state.request_transformer.chat_calls == []
    assert app.state.gigachat_client.achat.calls == []


def test_gemini_generate_content_ignores_unsupported_but_accepted_fields():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:generateContent",
        json={
            "contents": [{"parts": [{"text": "Hello"}]}],
            "generationConfig": {
                "candidateCount": 2,
                "topK": 40,
                "responseModalities": ["TEXT"],
                "responseMimeType": "text/plain",
            },
            "tools": [{"googleSearch": {}}],
            "safetySettings": [{"category": "HARM_CATEGORY_HARASSMENT"}],
            "cachedContent": "cachedContents/1",
        },
    )

    assert response.status_code == 200
    payload = app.state.request_transformer.chat_calls[0][0]
    assert payload == {
        "model": "gemini-pro",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
    }


def test_gemini_stream_generate_content_rejects_malformed_payload_before_upstream():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:streamGenerateContent?alt=sse",
        json={"contents": "bad"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["param"] == "contents"
    assert app.state.request_transformer.chat_calls == []
    assert app.state.gigachat_client.achat.stream_calls == []


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
    chunks = _gemini_sse_chunks(body)
    assert chunks[0]["candidates"][0]["content"]["parts"] == [{"text": "Gem"}]
    assert chunks[-1]["candidates"][0]["content"]["parts"] == [{"text": "ini"}]
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


def test_gemini_stream_generate_content_empty_stream_returns_final_chunk():
    app = make_app(giga_client=EmptyStreamGigaChat())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/models/gemini-pro:streamGenerateContent?alt=sse",
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
    ) as response:
        body = "".join(response.iter_text())

    chunks = _gemini_sse_chunks(body)

    assert response.status_code == 200
    assert chunks == [
        {
            "candidates": [{"index": 0, "finishReason": "STOP"}],
            "modelVersion": "gemini-pro",
            "responseId": chunks[0]["responseId"],
        }
    ]
    assert "[DONE]" not in body


def test_gemini_stream_generate_content_returns_error_chunk_before_first_delta():
    app = make_app(request_transformer=FailingPrepareRequestTransformer())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/models/gemini-pro:streamGenerateContent?alt=sse",
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
    ) as response:
        body = "".join(response.iter_text())

    chunks = _gemini_sse_chunks(body)

    assert response.status_code == 200
    assert chunks == [
        {
            "error": {
                "code": "internal_error",
                "message": "Stream interrupted",
                "status": "RuntimeError",
            }
        }
    ]
    assert "[DONE]" not in body


def test_gemini_stream_generate_content_returns_error_chunk_after_partial_delta():
    app = make_app(giga_client=PartialFailingStreamGigaChat())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/models/gemini-pro:streamGenerateContent?alt=sse",
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
    ) as response:
        body = "".join(response.iter_text())

    chunks = _gemini_sse_chunks(body)

    assert response.status_code == 200
    assert chunks[0]["candidates"][0]["content"]["parts"] == [{"text": "Hel"}]
    assert chunks[-1] == {
        "error": {
            "code": "internal_error",
            "message": "Stream interrupted",
            "status": "RuntimeError",
        }
    }
    assert "[DONE]" not in body


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


def test_gemini_count_tokens_includes_system_contents_and_tools():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-pro:countTokens",
        json={
            "systemInstruction": {"parts": [{"text": "system prompt"}]},
            "contents": [{"parts": [{"text": "hello world"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup",
                            "description": "Find fresh data",
                        }
                    ]
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"totalTokens": 8}
    assert app.state.gigachat_client.token_count_calls == [
        {
            "texts": ["system prompt", "hello world", "lookup", "Find fresh data"],
            "model": "gemini-pro",
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"contents": []},
        {"contents": [{"parts": []}]},
        {
            "cachedContent": "cachedContents/1",
            "contents": [
                {
                    "parts": [
                        {"fileData": {"fileUri": "files/1"}},
                        {"inlineData": {"mimeType": "image/png", "data": "AA=="}},
                    ]
                }
            ],
            "tools": [{"googleSearch": {}}],
        },
    ],
)
def test_gemini_count_tokens_ignores_non_text_shapes_without_upstream_call(payload):
    app = make_app()
    client = TestClient(app)

    response = client.post("/models/gemini-pro:countTokens", json=payload)

    assert response.status_code == 200
    assert response.json() == {"totalTokens": 0}
    assert app.state.gigachat_client.token_count_calls == []


def test_gemini_batch_embed_contents_and_output_dimensionality():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-embedding:batchEmbedContents",
        json={
            "requests": [
                {"content": {"parts": [{"text": "embed one"}]}},
                {"content": {"parts": [{"text": "embed two"}]}},
            ],
            "outputDimensionality": 128,
        },
    )

    assert response.status_code == 200
    assert response.json()["embeddings"] == [
        {"values": [0.0]},
        {"values": [1.0]},
    ]
    assert app.state.gigachat_client.embedding_calls == [
        {"texts": ["embed one", "embed two"], "model": "gemini-embedding"}
    ]


@pytest.mark.parametrize(
    ("payload", "param"),
    [
        ({}, "content"),
        ({"content": 123}, "content"),
        ({"content": {"parts": []}}, "content.parts"),
        (
            {"content": {"parts": [{"inlineData": {"data": "AA=="}}]}},
            "content.parts[0]",
        ),
        ({"content": {"parts": [{"text": ""}]}}, "content.parts[0].text"),
    ],
)
def test_gemini_embed_content_rejects_invalid_payload_without_upstream_call(
    payload,
    param,
):
    app = make_app()
    client = TestClient(app)

    response = client.post("/models/gemini-embedding:embedContent", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["param"] == param
    assert app.state.gigachat_client.embedding_calls == []


@pytest.mark.parametrize(
    ("payload", "param"),
    [
        ({}, "requests"),
        ({"requests": "bad"}, "requests"),
        ({"requests": []}, "requests"),
        ({"requests": [None]}, "requests[0]"),
        ({"requests": [{}]}, "requests[0].content"),
        (
            {"requests": [{"content": {"parts": [{"text": ""}]}}]},
            "requests[0].content.parts[0].text",
        ),
        (
            {"requests": [{"content": {"parts": [{"fileData": {"fileUri": "x"}}]}}]},
            "requests[0].content.parts[0]",
        ),
    ],
)
def test_gemini_batch_embed_contents_rejects_invalid_payload_without_upstream_call(
    payload,
    param,
):
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-embedding:batchEmbedContents",
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["param"] == param
    assert app.state.gigachat_client.embedding_calls == []


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


def test_gemini_model_capabilities_are_inferred_conservatively():
    assert build_gemini_model({"id": "GigaChat-2-Max"})[
        "supportedGenerationMethods"
    ] == [
        "generateContent",
        "streamGenerateContent",
        "countTokens",
    ]
    assert build_gemini_model({"id": "EmbeddingsGigaR"})[
        "supportedGenerationMethods"
    ] == [
        "embedContent",
        "batchEmbedContents",
    ]
    assert build_gemini_model({"id": "custom-model"})["supportedGenerationMethods"] == [
        "countTokens"
    ]
    assert build_gemini_model(
        {
            "id": "explicit",
            "supportedGenerationMethods": ["embedContent"],
        }
    )["supportedGenerationMethods"] == ["embedContent"]


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
