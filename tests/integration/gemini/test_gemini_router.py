"""Tests for Gemini Developer API compatible routes."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.gemini import router
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.providers.gigachat import ResponseProcessor


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class FakeTokensCount:
    def __init__(self, tokens):
        self.tokens = tokens


class FakeGigaChat:
    def __init__(self):
        self.last_method = None
        self.last_embedding_texts = None
        self.last_embedding_model = None
        self.last_token_texts = None
        self._response_v2 = None
        self._response = {
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

    async def achat(self, chat):
        self.last_method = "v1"
        return MockResponse(self._response)

    async def achat_v2(self, chat):
        self.last_method = "v2"
        response = self._response_v2
        if response is None:
            return MockResponse(
                {
                    "model": "gemini-test",
                    "created_at": 123,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "Hello from v2!"}],
                        }
                    ],
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )
        if "messages" in response:
            return MockResponse(response)

        choice = response["choices"][0]
        message = choice.get("message", {})
        content = []
        if message.get("content"):
            content.append({"text": message["content"]})
        if isinstance(message.get("function_call"), dict):
            content.append({"function_call": message["function_call"]})

        usage = response.get("usage") or {}
        return MockResponse(
            {
                "model": "gemini-test",
                "created_at": 123,
                "messages": [
                    {
                        "message_id": "msg-1",
                        "role": "assistant",
                        "content": content or [{"text": "Hello from v2!"}],
                    }
                ],
                "finish_reason": choice.get("finish_reason", "stop"),
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 10),
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": usage.get("completion_tokens", 5),
                    "total_tokens": usage.get("total_tokens", 15),
                },
            }
        )

    def astream(self, chat):
        async def gen():
            self.last_method = "v1"
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "Hel"}}],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()

    def astream_v2(self, chat):
        async def gen():
            self.last_method = "v2"
            yield MockResponse(
                {
                    "model": "gemini-test",
                    "created_at": 123,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "Hel"}],
                        }
                    ],
                }
            )
            yield MockResponse(
                {
                    "model": "gemini-test",
                    "created_at": 123,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "lo"}],
                        }
                    ],
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()

    async def atokens_count(self, input_, model=None):
        self.last_token_texts = list(input_)
        return [FakeTokensCount(tokens=len(text.split())) for text in input_]

    async def aembeddings(self, texts, model):
        self.last_embedding_texts = list(texts)
        self.last_embedding_model = model
        return {
            "data": [
                {"embedding": [float(index), float(index) + 0.5], "index": index}
                for index, _ in enumerate(texts)
            ]
        }

    async def aget_models(self):
        return SimpleNamespace(
            data=[
                SimpleNamespace(id_="GigaChat-2-Max"),
                SimpleNamespace(id_="GigaChat-2-Pro"),
            ]
        )

    async def aget_model(self, model: str):
        return SimpleNamespace(id_=model)


class FakeRequestTransformer:
    def __init__(self):
        self.last_data = None
        self.last_mode = None

    async def prepare_chat_completion(self, data, giga_client=None):
        payload = to_backend_payload(data)
        self.last_mode = "v1"
        self.last_data = payload
        return {
            "model": payload.get("model", "giga"),
            "messages": payload.get("messages", []),
            "functions": payload.get("functions"),
            "function_call": payload.get("function_call"),
            "response_format": payload.get("response_format"),
            "reasoning_effort": payload.get("reasoning_effort"),
        }

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        payload = to_backend_payload(data)
        self.last_mode = "v2"
        self.last_data = payload
        return {
            "model": payload.get("model", "giga"),
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": str(payload.get("messages", []))}],
                }
            ],
            "functions": payload.get("functions"),
            "function_call": payload.get("function_call"),
            "response_format": payload.get("response_format"),
            "reasoning_effort": payload.get("reasoning_effort"),
        }


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigaChat()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.response_processor = ResponseProcessor()
    app.state.config = ProxyConfig.model_validate(
        {"proxy": {"gigachat_api_mode": "v1"}}
    )
    app.state.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    return app


def test_generate_content_text():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["content"]["parts"][0]["text"] == "Hello!"
    assert body["usageMetadata"]["totalTokenCount"] == 15
    assert app.state.request_transformer.last_data["messages"] == [
        {"role": "user", "content": "Hello"}
    ]


def test_generate_content_v2_mode_uses_chat_v2_backend():
    app = make_app()
    app.state.config = ProxyConfig.model_validate(
        {"proxy": {"gigachat_api_mode": "v2"}}
    )
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["content"]["parts"][0]["text"] == "Hello from v2!"
    assert app.state.gigachat_client.last_method == "v2"
    assert app.state.request_transformer.last_mode == "v2"


def test_generate_content_v2_mode_preserves_function_calls():
    app = make_app()
    app.state.config = ProxyConfig.model_validate(
        {"proxy": {"gigachat_api_mode": "v2"}}
    )
    app.state.gigachat_client._response_v2 = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": "get_weather",
                        "arguments": {"city": "Moscow"},
                    },
                },
                "finish_reason": "function_call",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "Weather?"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get weather by city.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"city": {"type": "STRING"}},
                            },
                        }
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["get_weather"],
                }
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["content"]["parts"][0]["functionCall"]["name"] == (
        "get_weather"
    )
    assert app.state.gigachat_client.last_method == "v2"
    assert app.state.request_transformer.last_mode == "v2"


def test_generate_content_with_function_call_and_tools():
    app = make_app()
    app.state.gigachat_client._response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": "get_weather",
                        "arguments": {"city": "Moscow"},
                    },
                },
                "finish_reason": "function_call",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "Weather?"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get weather by city.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"city": {"type": "STRING"}},
                                "required": ["city"],
                            },
                        }
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["get_weather"],
                }
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    part = body["candidates"][0]["content"]["parts"][0]["functionCall"]
    assert part["name"] == "get_weather"
    assert part["args"] == {"city": "Moscow"}
    assert app.state.request_transformer.last_data["function_call"] == {
        "name": "get_weather"
    }
    assert (
        app.state.request_transformer.last_data["tools"][0]["function"]["parameters"][
            "type"
        ]
        == "object"
    )


def test_generate_content_preserves_parameters_json_schema():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "Read a file"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "read_file",
                            "description": "Read the content of a file.",
                            "parameters": {"type": "OBJECT", "properties": {}},
                            "parametersJsonSchema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "start_line": {"type": "integer"},
                                },
                                "required": ["path"],
                            },
                        }
                    ]
                }
            ],
        },
    )

    assert response.status_code == 200
    tool_parameters = app.state.request_transformer.last_data["tools"][0]["function"][
        "parameters"
    ]
    assert tool_parameters["properties"]["path"]["type"] == "string"
    assert tool_parameters["properties"]["start_line"]["type"] == "integer"

    function_parameters = app.state.request_transformer.last_data["functions"][
        0
    ].parameters
    params = (
        function_parameters.model_dump()
        if hasattr(function_parameters, "model_dump")
        else dict(function_parameters)
    )
    assert "path" in params["properties"]
    assert "start_line" in params["properties"]
    assert params["required"] == ["path"]


def test_generate_content_structured_output_returns_json_text():
    app = make_app()
    app.state.gigachat_client._response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "function_call": {
                        "name": "gemini_structured_output",
                        "arguments": {"answer": "ok"},
                    },
                },
                "finish_reason": "function_call",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "Return JSON"}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
            },
        },
    )

    assert response.status_code == 200
    part = response.json()["candidates"][0]["content"]["parts"][0]
    assert part["text"] == '{"answer": "ok"}'
    assert app.state.request_transformer.last_data["response_format"]["type"] == (
        "json_schema"
    )


def test_stream_generate_content_returns_sse():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:streamGenerateContent?alt=sse",
        json={"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]},
    )

    assert response.status_code == 200
    assert "data: " in response.text
    assert '"text": "Hel"' in response.text
    assert '"finishReason": "STOP"' in response.text


def test_stream_generate_content_v2_mode_uses_chat_v2_backend():
    app = make_app()
    app.state.config = ProxyConfig.model_validate(
        {"proxy": {"gigachat_api_mode": "v2"}}
    )
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:streamGenerateContent?alt=sse",
        json={"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]},
    )

    assert response.status_code == 200
    assert '"text": "Hel"' in response.text
    assert '"finishReason": "STOP"' in response.text
    assert app.state.gigachat_client.last_method == "v2"
    assert app.state.request_transformer.last_mode == "v2"


def test_count_tokens_with_generate_content_request_and_tools():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:countTokens",
        json={
            "generateContentRequest": {
                "systemInstruction": {"parts": [{"text": "Be brief"}]},
                "contents": [{"role": "user", "parts": [{"text": "How are you?"}]}],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "get_weather",
                                "description": "Get weather by city.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                },
                            }
                        ]
                    }
                ],
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["totalTokens"] > 0
    assert any(
        "Be brief" in text for text in app.state.gigachat_client.last_token_texts
    )
    assert any(
        "get_weather" in text for text in app.state.gigachat_client.last_token_texts
    )


def test_generate_content_rejects_unsupported_builtin_tool():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
            "tools": [{"googleSearch": {}}],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["status"] == "INVALID_ARGUMENT"
    assert "googleSearch" in body["error"]["message"]


def test_generate_content_rejects_inline_data():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-test:generateContent",
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": "aGVsbG8=",
                            }
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_batch_embed_contents():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-embedding-001:batchEmbedContents",
        json={
            "requests": [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"role": "user", "parts": [{"text": "hello"}]},
                },
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"role": "user", "parts": [{"text": "world"}]},
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["embeddings"][0]["values"] == [0.0, 0.5]
    assert app.state.gigachat_client.last_embedding_texts == ["hello", "world"]
    assert (
        app.state.gigachat_client.last_embedding_model
        == app.state.config.proxy_settings.embeddings
    )


def test_embed_content_alias():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gemini-embedding-001:embedContent",
        json={"content": {"role": "user", "parts": [{"text": "hello"}]}},
    )

    assert response.status_code == 200
    assert response.json()["embedding"]["values"] == [0.0, 0.5]


def test_models_list_and_get():
    app = make_app()
    client = TestClient(app)

    list_response = client.get("/models")
    get_response = client.get("/models/GigaChat-2-Max")
    embedding_response = client.get(
        f"/models/{app.state.config.proxy_settings.embeddings}"
    )

    assert list_response.status_code == 200
    models = list_response.json()["models"]
    assert any(model["name"] == "models/GigaChat-2-Max" for model in models)
    assert any(
        model["name"] == f"models/{app.state.config.proxy_settings.embeddings}"
        for model in models
    )
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "models/GigaChat-2-Max"
    assert embedding_response.json()["supportedGenerationMethods"] == ["embedContent"]
