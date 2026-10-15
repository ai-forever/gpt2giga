import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **_kwargs):
        return self.payload


class _Upstream:
    def __init__(self, *, mode, outcome):
        self.mode = mode
        self.outcome = outcome
        self.payloads = []
        self.achat = self
        self.waiting = asyncio.Event()
        self.cancelled = False

    def _record(self, payload):
        self.payloads.append(
            payload if isinstance(payload, dict) else payload.model_dump(mode="json")
        )

    async def __call__(self, payload):
        self._record(payload)
        return _Response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    async def create(self, payload):
        self._record(payload)
        return _Response(
            {
                "messages": [{"role": "assistant", "content": [{"text": "ok"}]}],
                "finish_reason": "stop",
            }
        )

    async def astream(self, payload):
        self._record(payload)
        if self.outcome == "empty":
            return
        if self.outcome in {"tool", "truncated_tool", "mixed_tool"}:
            delta = {
                "function_call": {
                    "name": "get_weather",
                    "arguments": '{"city":'
                    if self.outcome == "truncated_tool"
                    else {"city": "Paris"},
                }
            }
            finish_reason = "function_call" if self.outcome == "tool" else None
            if self.outcome == "mixed_tool":
                delta["content"] = "Before tool."
        else:
            delta = {"content": "Partial answer"}
            finish_reason = None
        yield _Response({"choices": [{"delta": delta, "finish_reason": finish_reason}]})
        if self.outcome == "mixed_tool":
            yield _Response(
                {"choices": [{"delta": {}, "finish_reason": "function_call"}]}
            )
        if self.outcome == "error":
            raise RuntimeError("synthetic upstream failure")
        if self.outcome == "cancel":
            await self._wait_for_cancellation()

    async def stream(self, payload):
        self._record(payload)
        if self.outcome == "empty":
            return
        if self.outcome in {"tool", "truncated_tool", "mixed_tool"}:
            content = [
                {
                    "function_call": {
                        "name": "get_weather",
                        "arguments": '{"city":'
                        if self.outcome == "truncated_tool"
                        else {"city": "Paris"},
                    }
                }
            ]
            finish_reason = "function_call" if self.outcome == "tool" else None
            if self.outcome == "mixed_tool":
                content.insert(0, {"text": "Before tool."})
        else:
            content = [{"text": "Partial answer"}]
            finish_reason = None
        yield _Response(
            {
                "messages": [{"role": "assistant", "content": content}],
                "finish_reason": finish_reason,
            }
        )
        if self.outcome == "mixed_tool":
            yield _Response({"messages": [], "finish_reason": "function_call"})
        if self.outcome == "error":
            raise RuntimeError("synthetic upstream failure")
        if self.outcome == "cancel":
            await self._wait_for_cancellation()

    async def _wait_for_cancellation(self):
        self.waiting.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _app(*, mode, outcome):
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                mode="DEV", gigachat_api_mode=mode, conversation_stitching_enabled=True
            ),
            gigachat={"model": "GigaChat-2-Max"},
        )
    )
    upstream = _Upstream(mode=mode, outcome=outcome)
    app.state.gigachat_client = upstream
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.logger = logger
    return app, upstream


def _payload(text):
    return {"contents": [{"parts": [{"text": text}]}]}


def _chunks(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.parametrize("mode", ["v1", "v2"])
def test_terminal_function_call_is_emitted_and_retained_for_next_turn(mode):
    app, upstream = _app(mode=mode, outcome="tool")
    client = TestClient(app)
    headers = {"x-gpt2giga-conversation-id": "terminal-tool"}
    response = client.post(
        f"/{mode}/v1beta/models/GigaChat-2-Max:streamGenerateContent",
        json={
            **_payload("Weather?"),
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                            },
                        }
                    ]
                }
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200
    parts = [
        part
        for chunk in _chunks(response)
        for candidate in chunk.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    ]
    function_call = next(
        (part["functionCall"] for part in parts if "functionCall" in part), None
    )
    assert function_call is not None
    assert function_call["name"] == "get_weather"
    assert function_call["args"] == {"city": "Paris"}

    followup = client.post(
        f"/{mode}/v1beta/models/GigaChat-2-Max:generateContent",
        json=_payload("Next question"),
        headers=headers,
    )

    assert followup.status_code == 200, followup.text
    assistant = upstream.payloads[-1]["messages"][1]
    if mode == "v1":
        assert assistant["function_call"]["name"] == "get_weather"
    else:
        assert assistant["content"][0]["function_call"]["name"] == "get_weather"


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("outcome", ["error", "truncated", "truncated_tool", "empty"])
def test_failed_or_unfinished_stream_does_not_commit_conversation(mode, outcome):
    app, upstream = _app(mode=mode, outcome=outcome)
    client = TestClient(app)
    headers = {"x-gpt2giga-conversation-id": "failed-turn"}
    response = client.post(
        f"/{mode}/v1beta/models/GigaChat-2-Max:streamGenerateContent",
        json=_payload("Failed question"),
        headers=headers,
    )
    assert response.status_code == 200
    if outcome in {"error", "truncated"}:
        assert "Partial answer" in response.text
    if outcome == "error":
        assert "error" in _chunks(response)[-1]

    followup = client.post(
        f"/{mode}/v1beta/models/GigaChat-2-Max:generateContent",
        json=_payload("Next question"),
        headers=headers,
    )

    assert followup.status_code == 200, followup.text
    assert len(upstream.payloads[-1]["messages"]) == 1


@pytest.mark.parametrize("mode", ["v1", "v2"])
async def test_cancelled_stream_does_not_commit_partial_conversation(mode):
    app, upstream = _app(mode=mode, outcome="cancel")
    headers = {"x-gpt2giga-conversation-id": "cancelled-turn"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        task = asyncio.create_task(
            client.post(
                f"/{mode}/v1beta/models/GigaChat-2-Max:streamGenerateContent",
                json=_payload("Cancelled question"),
                headers=headers,
            )
        )
        await asyncio.wait_for(upstream.waiting.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert upstream.cancelled

        followup = await client.post(
            f"/{mode}/v1beta/models/GigaChat-2-Max:generateContent",
            json=_payload("Next question"),
            headers=headers,
        )

    assert followup.status_code == 200, followup.text
    assert len(upstream.payloads[-1]["messages"]) == 1


@pytest.mark.parametrize("mode", ["v1", "v2"])
def test_nonterminal_tool_event_preserves_accompanying_text(mode):
    app, _ = _app(mode=mode, outcome="mixed_tool")
    response = TestClient(app).post(
        f"/{mode}/v1beta/models/GigaChat-2-Max:streamGenerateContent",
        json=_payload("Weather?"),
    )
    assert response.status_code == 200, response.text
    parts = [
        part
        for chunk in _chunks(response)
        for candidate in chunk.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    ]
    assert "".join(part.get("text", "") for part in parts) == "Before tool."
    assert [
        part["functionCall"]["name"] for part in parts if "functionCall" in part
    ] == ["get_weather"]
