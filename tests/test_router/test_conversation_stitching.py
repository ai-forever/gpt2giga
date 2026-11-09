from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.routers.anthropic import router as anthropic_router
from gpt2giga.routers.openai import router as openai_router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeAChatResource:
    def __init__(self):
        self.chat_calls = []
        self.chat_completion_calls = []

    async def __call__(self, payload):
        self.chat_calls.append(deepcopy(payload))
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"ok-{len(self.chat_calls)}",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )

    async def create(self, payload):
        self.chat_completion_calls.append(deepcopy(payload))
        return ChatCompletionResponse.model_validate(
            {
                "model": "GigaChat-2-Max",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "ok-v2"}],
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


class FakeGigachat:
    def __init__(self):
        self.achat = FakeAChatResource()
        self.stream_calls = []

    def astream(self, payload):
        self.stream_calls.append(deepcopy(payload))

        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "stream-"},
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )

        return gen()


class FakeRequestTransformer:
    async def prepare_normalized(
        self, request, giga_client=None, *, api_mode, forced_model=None
    ):
        from gpt2giga.providers.gigachat.adapter import (
            normalized_chat_to_openai_payload,
        )

        payload = normalized_chat_to_openai_payload(request)
        if api_mode == "v2":
            return await self.prepare_chat_completion(payload, giga_client)
        return await self.prepare_chat(payload, giga_client)

    def __init__(self):
        self.chat_calls = []
        self.response_chat_calls = []
        self.response_chat_completion_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append(deepcopy(data))
        return {
            "model": data.get("model", "giga"),
            "messages": deepcopy(data.get("messages", [])),
        }

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_calls.append(deepcopy(data))
        return {"contract": "chat-v2"}

    async def prepare_response_chat(self, data, giga_client=None):
        self.response_chat_calls.append(deepcopy(data))
        return {"model": data.get("model", "giga"), "messages": []}

    async def prepare_response_chat_completion(self, data, giga_client=None):
        self.response_chat_completion_calls.append(deepcopy(data))
        return {"contract": "responses-v2"}


def make_openai_app(**settings):
    app = FastAPI()
    app.include_router(openai_router)
    app.state.gigachat_client = FakeGigachat()
    app.state.logger = logger
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            conversation_stitching_enabled=True,
            **settings,
        ),
        gigachat={"model": "GigaChat"},
    )
    return app


def make_anthropic_app(**settings):
    app = FastAPI()
    app.include_router(anthropic_router)
    app.state.gigachat_client = FakeGigachat()
    app.state.logger = logger
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            conversation_stitching_enabled=True,
            **settings,
        )
    )
    return app


def test_chat_completions_stitches_second_turn_by_conversation_id():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    first = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    second = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "again"}],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "again"},
    ]


def test_chat_completions_full_history_is_not_duplicated():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "ok-1"},
                {"role": "user", "content": "again"},
            ],
        },
    )

    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "again"},
    ]


def test_chat_completions_namespaces_conversations_by_api_key():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    client.post(
        "/chat/completions",
        headers={"authorization": "Bearer key-a"},
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "from-a"}],
        },
    )
    client.post(
        "/chat/completions",
        headers={"authorization": "Bearer key-b"},
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "from-b"}],
        },
    )

    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "from-b"}
    ]


def test_chat_completions_session_id_is_opt_in_conversation_key():
    default_app = make_openai_app(gigachat_api_mode="v1")
    default_client = TestClient(default_app)
    for content in ("one", "two"):
        default_client.post(
            "/chat/completions",
            headers={"x-session-id": "session-1"},
            json={
                "model": "gpt-x",
                "messages": [{"role": "user", "content": content}],
            },
        )

    enabled_app = make_openai_app(
        gigachat_api_mode="v1",
        conversation_use_session_id=True,
    )
    enabled_client = TestClient(enabled_app)
    for content in ("one", "two"):
        enabled_client.post(
            "/chat/completions",
            headers={"x-session-id": "session-1"},
            json={
                "model": "gpt-x",
                "messages": [{"role": "user", "content": content}],
            },
        )

    assert default_app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "two"}
    ]
    assert enabled_app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "two"},
    ]


def test_responses_v2_with_previous_response_id_skips_local_stitching():
    app = make_openai_app(gigachat_api_mode="v2")
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "previous_response_id": "resp_previous",
            "input": "hello",
        },
    )

    assert response.status_code == 200
    assert (
        app.state.request_transformer.response_chat_completion_calls[0]["input"]
        == "hello"
    )


def test_chat_completions_stream_updates_conversation_after_completion():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    ) as response:
        body = "".join(response.iter_text())
    client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "again"}],
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in body
    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "stream-ok"},
        {"role": "user", "content": "again"},
    ]


def test_anthropic_messages_stitches_by_metadata_conversation_id():
    app = make_anthropic_app(gigachat_api_mode="v1")
    client = TestClient(app)

    client.post(
        "/messages",
        json={
            "model": "claude",
            "metadata": {"conversation_id": "conv-1"},
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    client.post(
        "/messages",
        json={
            "model": "claude",
            "metadata": {"conversation_id": "conv-1"},
            "messages": [{"role": "user", "content": "again"}],
        },
    )

    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "again"},
    ]


class MountedChatResource(FakeAChatResource):
    async def stream(self, payload):
        yield await self.create(payload)


class ToolCallingChatResource(MountedChatResource):
    async def create(self, payload):
        if self.chat_completion_calls:
            return await super().create(payload)
        self.chat_completion_calls.append(deepcopy(payload))
        return ChatCompletionResponse.model_validate(
            {
                "model": "GigaChat-2-Max",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_state_id": "synthetic-tools-state",
                        "content": [
                            {
                                "function_call": {
                                    "id": "call-lookup",
                                    "name": "lookup",
                                    "arguments": {"query": "example"},
                                }
                            }
                        ],
                    }
                ],
                "finish_reason": "function_call",
                "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            }
        )


def make_mounted_anthropic_app(*, normalization_mode):
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(
                mode="DEV",
                gigachat_api_mode="v1",
                conversation_stitching_enabled=True,
                normalization_mode=normalization_mode,
                legacy_chat_fallback=False,
            ),
            gigachat={"model": "GigaChat-2-Max"},
        )
    )
    app.state.gigachat_client = FakeGigachat()
    app.state.gigachat_client.achat = MountedChatResource()
    app.state.logger = logger
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    return app


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("normalization_mode", ["off", "on"])
def test_mounted_anthropic_preserves_stitched_history(mode, stream, normalization_mode):
    app = make_mounted_anthropic_app(normalization_mode=normalization_mode)
    client = TestClient(app)
    headers = {"x-gpt2giga-conversation-id": "synthetic-conversation"}

    first = client.post(
        f"/{mode}/messages",
        headers=headers,
        json={
            "model": "GigaChat-2-Max",
            "system": "Remember this rule.",
            "messages": [{"role": "user", "content": "First question."}],
            "max_tokens": 16,
            "stream": stream,
        },
    )
    second = client.post(
        f"/{mode}/messages",
        headers=headers,
        json={
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "Second question."}],
            "max_tokens": 16,
            "stream": stream,
        },
    )

    assert first.status_code == second.status_code == 200
    upstream = app.state.gigachat_client
    if mode == "v2":
        payload = upstream.achat.chat_completion_calls[1].model_dump(mode="json")
        expected_answer = "ok-v2"
    else:
        payload = (upstream.stream_calls if stream else upstream.achat.chat_calls)[1]
        expected_answer = "stream-ok" if stream else "ok-1"
    assert [message["role"] for message in payload["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [
        message["content"]
        if isinstance(message["content"], str)
        else "".join(part.get("text", "") for part in message["content"])
        for message in payload["messages"]
    ] == ["Remember this rule.", "First question.", expected_answer, "Second question."]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("normalization_mode", ["off", "on"])
@pytest.mark.parametrize("followup_text", [False, True])
def test_mounted_anthropic_stitching_preserves_tool_identity(
    stream, normalization_mode, followup_text
):
    app = make_mounted_anthropic_app(normalization_mode=normalization_mode)
    upstream = ToolCallingChatResource()
    app.state.gigachat_client.achat = upstream
    client = TestClient(app)
    headers = {"x-gpt2giga-conversation-id": "synthetic-tools-conversation"}
    common = {
        "model": "GigaChat-2-Max",
        "max_tokens": 16,
        "tools": [
            {
                "name": "lookup",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
    }
    first = client.post(
        "/v2/messages",
        headers=headers,
        json={
            **common,
            "stream": stream,
            "messages": [{"role": "user", "content": "Look it up."}],
        },
    )
    assert first.status_code == 200, first.text
    assert "call-lookup" in first.text
    results = [
        {
            "type": "tool_result",
            "tool_use_id": "call-lookup",
            "content": "Found it.",
        }
    ]
    if followup_text:
        results.append({"type": "text", "text": "Summarize."})
    second = client.post(
        "/v2/messages",
        headers=headers,
        json={
            **common,
            "messages": [
                {
                    "role": "user",
                    "content": results,
                }
            ],
        },
    )

    assert second.status_code == 200, second.text
    messages = upstream.chat_completion_calls[1].model_dump(mode="json", by_alias=True)[
        "messages"
    ]
    expected_roles = ["user", "assistant", "tool"]
    if followup_text:
        expected_roles.append("user")
    assert [message["role"] for message in messages] == expected_roles
    assert messages[1]["content"][0]["function_call"]["id"] == "call-lookup"
    assert messages[1]["tools_state_id"] == "synthetic-tools-state"
    assert messages[2]["content"][0]["function_result"]["id"] == "call-lookup"
    assert messages[2]["content"][0]["function_result"]["name"] == "lookup"
    assert messages[2]["tools_state_id"] == "synthetic-tools-state"


@pytest.mark.parametrize("stream", [False, True])
def test_mounted_normalized_anthropic_stitching_keeps_native_content(stream):
    app = make_mounted_anthropic_app(normalization_mode="on")
    client = TestClient(app)
    payload = {
        "model": "GigaChat-2-Max",
        "max_tokens": 16,
        "stream": stream,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "First block."},
                    {"type": "text", "text": "Second block."},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-lookup",
                        "name": "lookup",
                        "input": {"query": "example"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-lookup",
                        "tools_state_id": "explicit-tools-state",
                        "content": "Found it.",
                    }
                ],
            },
        ],
    }
    plain = client.post("/v2/messages", json=payload)
    first = client.post(
        "/v2/messages",
        headers={"x-gpt2giga-conversation-id": "synthetic-native-content"},
        json=payload,
    )
    followup = client.post(
        "/v2/messages",
        headers={"x-gpt2giga-conversation-id": "synthetic-native-content"},
        json={
            "model": "GigaChat-2-Max",
            "max_tokens": 16,
            "stream": stream,
            "messages": [{"role": "user", "content": "Next question."}],
        },
    )

    assert plain.status_code == first.status_code == followup.status_code == 200
    calls = app.state.gigachat_client.achat.chat_completion_calls
    original = calls[0].model_dump(mode="json", by_alias=True)["messages"]
    assert original[2]["tools_state_id"] == "explicit-tools-state"
    assert calls[1].model_dump(mode="json", by_alias=True)["messages"] == original
    assert calls[2].model_dump(mode="json", by_alias=True)["messages"][:3] == original


def test_anthropic_current_turn_uses_normalized_messages_without_second_decode(
    monkeypatch,
):
    app = make_mounted_anthropic_app(normalization_mode="on")

    def reject_redecode(*args, **kwargs):
        raise AssertionError("current normalized messages must not be decoded twice")

    monkeypatch.setattr(
        "gpt2giga.protocols.openai.OpenAIProtocolAdapter.chat_to_normalized",
        reject_redecode,
    )
    client = TestClient(app, raise_server_exceptions=True)
    response = client.post(
        "/v1/messages",
        headers={"x-gpt2giga-conversation-id": "fresh-conversation"},
        json={
            "model": "GigaChat-2-Max",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "Keep typed input."}],
        },
    )
    assert response.status_code == 200, response.text
