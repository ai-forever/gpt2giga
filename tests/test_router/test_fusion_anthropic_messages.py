import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.routers.anthropic import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FusionRequestTransformer:
    def __init__(self):
        self.chat_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        return data


class FusionGigachat:
    def __init__(self, judge_payload=None, panel_content=None, selector_payload=None):
        self.chat_calls = []
        self.panel_content = panel_content
        self.selector_payload = selector_payload
        self.judge_payload = judge_payload or {
            "consensus": ["Panels agree."],
            "contradictions": [],
            "partial_coverage": [],
            "unique_insights": [],
            "blind_spots": [],
            "risk_flags": [],
            "selected_strategy": "Use the merged answer.",
            "final_answer": "fused anthropic answer",
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
        if "<candidate_outputs" in joined_content and self.selector_payload:
            content = json.dumps(self.selector_payload)
        elif "judge/finalizer" in joined_content:
            content = json.dumps(self.judge_payload)
        else:
            content = self.panel_content or f"panel answer from {chat.get('model')}"
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
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            fusion_enabled=True,
            fusion_default_preset="code-budget",
            fusion_aliases=[
                "gpt2giga/fusion-code",
                "gpt2giga/fusion-code-budget",
                "gpt2giga/fusion-force-synthesize",
                "gpt2giga/fusion-force-selector",
            ],
            gigachat_api_mode="v1",
            structured_output_mode="function_call",
        )
    )
    app.state.logger = logger
    return app


def test_anthropic_messages_fusion_model_alias_returns_non_stream_message():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/messages",
        json={
            "model": "gpt2giga/fusion-code-budget",
            "system": "Be direct.",
            "messages": [{"role": "user", "content": "hello from claude"}],
            "max_tokens": 128,
            "metadata": {"tenant": "test"},
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["model"] == "gpt2giga/fusion-code-budget"
    assert body["content"] == [
        {"type": "text", "text": "panel answer from GigaChat-2-Max"}
    ]
    assert body["stop_reason"] == "end_turn"
    assert body["usage"] == {"input_tokens": 1, "output_tokens": 1}
    assert [call["model"] for call in app.state.gigachat_client.chat_calls] == [
        "GigaChat-2-Max",
    ]
    sent_payloads = [call[0] for call in app.state.request_transformer.chat_calls]
    assert len(sent_payloads) == 1
    assert "gpt2giga_fusion_runtime" not in sent_payloads[0]["messages"][0]["content"]


def test_anthropic_messages_fusion_model_alias_returns_buffered_stream():
    app = make_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/messages",
        json={
            "model": "gpt2giga/fusion-code-budget",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: message_start" in body
    assert "event: content_block_delta" in body
    assert "panel answer from GigaChat-2-Max" in body
    assert "event: message_stop" in body
    message_delta = _last_sse_payload(body, "message_delta")
    assert message_delta["delta"]["stop_reason"] == "end_turn"
    assert message_delta["usage"]["output_tokens"] == 1


def test_anthropic_messages_fusion_returns_final_tool_use_and_strips_artifacts():
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
        "/messages",
        json={
            "model": "gpt2giga/fusion-force-synthesize",
            "messages": [{"role": "user", "content": "lookup hello"}],
            "max_tokens": 128,
            "metadata": {
                "tenant": "test",
                "gpt2giga_fusion": {"preset": "force-synthesize"},
            },
            "extra_body": {
                "safe": "kept",
                "gpt2giga_fusion": {"preset": "force-synthesize"},
            },
            "tools": [
                {
                    "name": "lookup",
                    "description": "Lookup data",
                    "input_schema": {"type": "object"},
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["stop_reason"] == "tool_use"
    assert body["content"] == [
        {
            "type": "tool_use",
            "id": "call_lookup",
            "name": "lookup",
            "input": {"q": "hello"},
        }
    ]

    sent_payloads = [call[0] for call in app.state.request_transformer.chat_calls]
    assert [payload["model"] for payload in sent_payloads] == [
        "GigaChat-3-Ultra",
        "GigaChat-2-Max",
        "GigaChat-3-Ultra",
    ]
    for payload in sent_payloads:
        assert payload.get("metadata", {}).get("tenant") == "test"
        assert "gpt2giga_fusion" not in payload.get("metadata", {})
        assert payload.get("additional_fields") == {"safe": "kept"}
    assert "tools" not in sent_payloads[0]
    assert "tools" not in sent_payloads[1]
    assert sent_payloads[-1]["tools"][0]["function"]["name"] == "lookup"


def test_anthropic_messages_fusion_selector_panel_json_returns_tool_use():
    gigachat = FusionGigachat(
        panel_content=(
            '{"name":"write_file","parameters":'
            '{"file_path":"hello.py","content":"print(1)"}}'
        ),
        selector_payload={
            "schema_version": "gpt2giga.fusion.selection.v1",
            "selected_candidate_id": "panel_1",
            "confidence": 1.0,
            "reason_brief": "Use the write_file action.",
        },
    )
    app = make_app(gigachat=gigachat)
    client = TestClient(app)

    response = client.post(
        "/messages",
        json={
            "model": "gpt2giga/fusion-force-selector",
            "messages": [{"role": "user", "content": "write hello.py"}],
            "max_tokens": 128,
            "metadata": {
                "gpt2giga_fusion": {
                    "preset": "force-selector",
                    "tools_mode": "schema_only",
                }
            },
            "tools": [
                {
                    "name": "write_file",
                    "description": "Write a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["file_path", "content"],
                    },
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["stop_reason"] == "tool_use"
    assert body["content"] == [
        {
            "type": "tool_use",
            "id": body["content"][0]["id"],
            "name": "write_file",
            "input": {
                "file_path": "hello.py",
                "content": "print(1)",
            },
        }
    ]


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
