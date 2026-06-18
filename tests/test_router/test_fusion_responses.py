import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.openai import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FusionRequestTransformer:
    def __init__(self):
        self.chat_calls = []
        self.response_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        return data

    async def prepare_response_chat(self, data, giga_client=None):
        self.response_calls.append((data, giga_client))
        return {"model": data.get("model", "giga")}


class FusionGigachat:
    def __init__(self, judge_payload=None):
        self.chat_calls = []
        self.judge_payload = judge_payload or {
            "consensus": ["Panels agree."],
            "contradictions": [],
            "partial_coverage": [],
            "unique_insights": [],
            "blind_spots": [],
            "risk_flags": [],
            "selected_strategy": "Use the merged answer.",
            "final_answer": "fused response answer",
            "final_tool_call": None,
        }

    async def achat(self, chat):
        self.chat_calls.append(chat)
        messages = chat.get("messages") or []
        joined_content = "\n".join(
            message.get("content", "")
            for message in messages
            if isinstance(message, dict)
        )
        if "judge/finalizer" in joined_content:
            content = json.dumps(self.judge_payload)
        else:
            content = f"panel answer from {chat.get('model')}"
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
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


def make_app(*, gigachat=None):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = gigachat or FusionGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FusionRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            fusion_enabled=True,
            fusion_default_preset="code-budget",
            fusion_aliases=["gpt2giga/fusion-code"],
            gigachat_api_mode="v1",
        )
    )
    return app


def test_responses_fusion_model_alias_returns_non_stream_response():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt2giga/fusion-code",
            "instructions": "Be direct.",
            "input": "hello from codex",
            "metadata": {"tenant": "test"},
            "max_output_tokens": 128,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["model"] == "gpt2giga/fusion-code"
    assert body["output"][0]["content"][0]["text"] == "fused response answer"
    assert body["output_text"] == "fused response answer"
    assert body["metadata"]["tenant"] == "test"
    assert body["metadata"]["gpt2giga_fusion_preset"] == "code-budget"
    assert body["usage"]["total_tokens"] == 6
    assert [call["model"] for call in app.state.gigachat_client.chat_calls] == [
        "GigaChat-2-Pro",
        "GigaChat-2-Max",
        "GigaChat-2-Max",
    ]
    assert not app.state.request_transformer.response_calls


def test_responses_fusion_model_alias_returns_buffered_stream():
    app = make_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={
            "model": "gpt2giga/fusion-code",
            "input": "hello",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert "fused response answer" in body
    assert "event: response.completed" in body
    completed = _last_sse_payload(body, "response.completed")
    assert completed["response"]["output_text"] == "fused response answer"
    assert completed["response"]["metadata"]["gpt2giga_fusion"] == "true"


def test_responses_fusion_openrouter_tool_strips_artifacts_and_returns_tool_call():
    gigachat = FusionGigachat(
        judge_payload={
            "consensus": ["Use lookup."],
            "contradictions": [],
            "partial_coverage": [],
            "unique_insights": [],
            "blind_spots": [],
            "risk_flags": [],
            "selected_strategy": "Call lookup once.",
            "final_answer": None,
            "final_tool_call": {
                "id": "call_lookup",
                "type": "function",
                "name": "lookup",
                "arguments": {"q": "hello"},
            },
        }
    )
    app = make_app(gigachat=gigachat)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "GigaChat",
            "input": "lookup hello",
            "metadata": {
                "tenant": "test",
                "gpt2giga_fusion": {"preset": "general"},
            },
            "extra_body": {
                "safe": "kept",
                "gpt2giga_fusion": {"preset": "general"},
            },
            "plugins": [{"id": "fusion", "preset": "general"}],
            "tools": [
                {
                    "type": "openrouter:fusion",
                    "parameters": {
                        "analysis_models": ["PanelA"],
                        "model": "Judge",
                    },
                },
                {
                    "type": "function",
                    "name": "lookup",
                    "description": "Lookup data",
                    "parameters": {"type": "object"},
                },
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["output"] == [
        {
            "id": "fc_call_lookup",
            "type": "function_call",
            "status": "completed",
            "call_id": "call_lookup",
            "name": "lookup",
            "arguments": '{"q": "hello"}',
        }
    ]

    sent_payloads = [call[0] for call in app.state.request_transformer.chat_calls]
    assert [payload["model"] for payload in sent_payloads] == ["PanelA", "Judge"]
    for payload in sent_payloads:
        assert "plugins" not in payload
        assert payload.get("metadata", {}).get("tenant") == "test"
        assert "gpt2giga_fusion" not in payload.get("metadata", {})
        assert payload.get("additional_fields") == {"safe": "kept"}
    assert "tools" not in sent_payloads[0]
    assert sent_payloads[-1]["tools"][0]["function"]["name"] == "lookup"


def _last_sse_payload(body: str, event_type: str):
    payloads = []
    for block in body.split("\n\n"):
        if f"event: {event_type}" not in block:
            continue
        data = next(
            line for line in block.splitlines() if line.startswith("data: ")
        ).removeprefix("data: ")
        payloads.append(json.loads(data))
    return payloads[-1]
