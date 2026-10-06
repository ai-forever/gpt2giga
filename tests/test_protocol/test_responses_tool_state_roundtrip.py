"""Replay native Responses tool output through OpenAI SDK response models."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models import ChatCompletionResponse
from gigachat.models.chat_completions import ChatCompletionChunk
from loguru import logger
from openai.types.responses import Response, ResponseCompletedEvent

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.routers.openai.responses import router


MODEL = "GigaChat-2-Max"
STATE_ID = "fc_state-original"
TOOLS = [
    {
        "type": "function",
        "name": "lookup",
        "parameters": {
            "type": "object",
            "properties": {"i": {"type": "integer"}},
            "required": ["i"],
        },
    }
]


class _ChatResource:
    def __init__(self, call_count, *, state_timing="inline"):
        self.call_count = call_count
        self.state_timing = state_timing
        self.requests = []

    def _tool_payload(self):
        return {
            "model": MODEL,
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": STATE_ID,
                    "content": [
                        {
                            "function_call": {
                                "id": f"call-{index}",
                                "name": "lookup",
                                "arguments": {"i": index},
                            }
                        }
                        for index in range(self.call_count)
                    ],
                }
            ],
            "finish_reason": "function_call",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }

    async def create(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatCompletionResponse.model_validate(self._tool_payload())
        return ChatCompletionResponse.model_validate(
            {
                "model": MODEL,
                "messages": [{"role": "assistant", "content": [{"text": "done"}]}],
                "finish_reason": "stop",
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            }
        )

    def stream(self, request):
        self.requests.append(request)

        async def events():
            payload = self._tool_payload()
            if self.state_timing != "inline":
                payload["messages"][0].pop("tools_state_id")
            if self.state_timing == "initial":
                yield ChatCompletionChunk.model_validate(
                    {
                        "model": MODEL,
                        "messages": [{"role": "assistant", "tools_state_id": STATE_ID}],
                    }
                )
            if self.state_timing == "terminal":
                payload.pop("finish_reason")
                payload.pop("usage")
            yield ChatCompletionChunk.model_validate(payload)
            if self.state_timing == "terminal":
                yield ChatCompletionChunk.model_validate(
                    {
                        "model": MODEL,
                        "messages": [{"role": "assistant", "tools_state_id": STATE_ID}],
                        "finish_reason": "function_call",
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 2,
                            "total_tokens": 3,
                        },
                    }
                )

        return events()


class _GigaChat:
    def __init__(self, call_count, *, state_timing="inline"):
        self.achat = _ChatResource(call_count, state_timing=state_timing)


def _app(call_count, *, state_timing="inline"):
    app = FastAPI()
    app.include_router(router)
    config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v2"),
        gigachat={"model": MODEL},
    )
    app.state.config = config
    app.state.logger = logger
    app.state.request_transformer = RequestTransformer(config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    app.state.gigachat_client = _GigaChat(call_count, state_timing=state_timing)
    return app


@pytest.mark.parametrize("call_count", [1, 2])
@pytest.mark.parametrize(
    ("stream", "state_timing"),
    [(False, "inline"), (True, "inline"), (True, "terminal"), (True, "initial")],
    ids=[
        "json",
        "stream-state-with-calls",
        "stream-state-at-terminal",
        "stream-state-before-calls",
    ],
)
def test_native_responses_tool_state_survives_sdk_and_reversed_results(
    call_count, stream, state_timing
):
    app = _app(call_count, state_timing=state_timing)
    with TestClient(app) as client:
        response = client.post(
            "/responses",
            json={
                "model": MODEL,
                "input": "lookup",
                "tools": TOOLS,
                "parallel_tool_calls": True,
                "stream": stream,
            },
        )
        assert response.status_code == 200, response.text
        if stream:
            events = [
                json.loads(line.removeprefix("data: "))
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            completed = [
                event for event in events if event["type"] == "response.completed"
            ]
            assert len(completed) == 1
            parsed = ResponseCompletedEvent.model_validate(completed[0]).response
            done_calls = [
                event["item"]
                for event in events
                if event["type"] == "response.output_item.done"
                and event["item"]["type"] == "function_call"
            ]
            assert [item.get("tools_state_id") for item in done_calls] == [
                STATE_ID
            ] * call_count
        else:
            parsed = Response.model_validate(response.json())

        calls = [item.model_dump(exclude_none=True) for item in parsed.output]
        assert [call["type"] for call in calls] == ["function_call"] * call_count
        assert [call["call_id"] for call in calls] == [
            f"call-{index}" for index in range(call_count)
        ]
        assert [call["name"] for call in calls] == ["lookup"] * call_count
        assert [call.get("tools_state_id") for call in calls] == [STATE_ID] * call_count
        assert len({call["id"] for call in calls}) == call_count

        follow_up = client.post(
            "/responses",
            json={
                "model": MODEL,
                "tools": TOOLS,
                "parallel_tool_calls": True,
                "input": [
                    {"role": "user", "content": "lookup"},
                    *calls,
                    *[
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": call["arguments"],
                        }
                        for call in reversed(calls)
                    ],
                ],
            },
        )

    assert follow_up.status_code == 200, follow_up.text
    assert follow_up.json()["output"][0]["content"][0]["text"] == "done"
    messages = app.state.gigachat_client.achat.requests[-1].model_dump(
        by_alias=True, exclude_none=True
    )["messages"]
    assistant_messages = [
        message for message in messages if message["role"] == "assistant"
    ]
    results = [message for message in messages if message["role"] == "tool"]
    assert assistant_messages
    assert all(
        message.get("tools_state_id") == STATE_ID for message in assistant_messages
    )
    assert [
        part["function_call"]
        for message in assistant_messages
        for part in message["content"]
        if "function_call" in part
    ] == [
        {"id": f"call-{index}", "name": "lookup", "arguments": {"i": index}}
        for index in range(call_count)
    ]
    assert [message.get("tools_state_id") for message in results] == [
        STATE_ID
    ] * call_count
    assert [message["content"][0]["function_result"] for message in results] == [
        {"id": f"call-{index}", "name": "lookup", "result": {"i": index}}
        for index in reversed(range(call_count))
    ]


async def test_native_responses_stream_idless_fragments_keep_one_sdk_call(monkeypatch):
    app = _app(1)
    resource = app.state.gigachat_client.achat

    async def chunks(request):
        resource.requests.append(request)
        for index, fragment in enumerate(['{"i":', "0}"]):
            payload = resource._tool_payload()
            message = payload["messages"][0]
            function_call = message["content"][0]["function_call"]
            function_call.pop("id")
            function_call["arguments"] = fragment
            if index == 0:
                message.pop("tools_state_id")
                payload.pop("finish_reason")
                payload.pop("usage")
            yield ChatCompletionChunk.model_validate(payload)

    monkeypatch.setattr(resource, "stream", chunks)
    with TestClient(app) as client:
        response = client.post(
            "/responses",
            json={"model": MODEL, "input": "lookup", "tools": TOOLS, "stream": True},
        )
    assert response.status_code == 200, response.text
    completed = [
        event
        for line in response.text.splitlines()
        if line.startswith("data: ")
        and (event := json.loads(line.removeprefix("data: ")))["type"]
        == "response.completed"
    ]
    assert len(completed) == 1
    parsed = ResponseCompletedEvent.model_validate(completed[0]).response
    assert len(parsed.output) == 1
    call = parsed.output[0].model_dump(exclude_none=True)
    assert call["type"] == "function_call"
    assert call["call_id"]
    assert call["tools_state_id"] == STATE_ID
    assert json.loads(call["arguments"]) == {"i": 0}

    request = await app.state.request_transformer.prepare_response_chat_completion(
        {
            "model": MODEL,
            "tools": TOOLS,
            "input": [
                {"role": "user", "content": "lookup"},
                call,
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": call["arguments"],
                },
            ],
        }
    )
    messages = request.model_dump(by_alias=True, exclude_none=True)["messages"]
    assert [message.get("tools_state_id") for message in messages[1:]] == [STATE_ID] * 2
    assert messages[1]["content"][0]["function_call"] == {
        "id": call["call_id"],
        "name": "lookup",
        "arguments": {"i": 0},
    }
    assert messages[2]["content"][0]["function_result"] == {
        "id": call["call_id"],
        "name": "lookup",
        "result": {"i": 0},
    }
