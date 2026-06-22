import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.routers.gemini import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FusionRequestTransformer:
    def __init__(self):
        self.chat_calls = []
        self.chat_completion_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        return data

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_completion_calls.append((data, giga_client))
        return data


class FusionAChat:
    def __init__(self, owner):
        self.owner = owner

    async def __call__(self, chat):
        return await self.owner._complete(chat)

    async def create(self, chat):
        return await self.owner._complete(chat)


class FusionGigachat:
    def __init__(self, judge_payload=None, panel_content=None, selector_payload=None):
        self.achat = FusionAChat(self)
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
            "final_answer": "fused gemini answer",
            "final_tool_call": None,
        }

    async def _complete(self, chat):
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
    app.state.gemini_protocol_adapter = GeminiProtocolAdapter()
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
        )
    )
    app.state.logger = logger
    return app


def test_gemini_generate_content_fusion_model_alias_returns_non_stream_response():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/models/gpt2giga/fusion-code-budget:generateContent",
        json={
            "systemInstruction": {"parts": [{"text": "Be direct."}]},
            "contents": [{"parts": [{"text": "hello from gemini"}]}],
            "metadata": {"tenant": "test"},
            "generationConfig": {"maxOutputTokens": 128},
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["modelVersion"] == "gpt2giga/fusion-code-budget"
    assert body["candidates"][0]["content"]["parts"] == [
        {"text": "panel answer from GigaChat-2-Max"}
    ]
    assert body["usageMetadata"]["totalTokenCount"] == 2
    assert "gpt2gigaMetadata" not in body
    assert [call["model"] for call in app.state.gigachat_client.chat_calls] == [
        "GigaChat-2-Max",
    ]
    sent_payloads = [call[0] for call in app.state.request_transformer.chat_calls]
    assert sent_payloads[0]["metadata"]["tenant"] == "test"
    assert "gpt2giga_fusion" not in sent_payloads[0]["metadata"]
    assert "gpt2giga_fusion_runtime" not in sent_payloads[0]["messages"][0]["content"]


def test_gemini_stream_generate_content_fusion_model_alias_returns_buffered_sse():
    app = make_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/models/gpt2giga/fusion-code-budget:streamGenerateContent?alt=sse",
        json={
            "contents": [{"parts": [{"text": "hello"}]}],
        },
    ) as response:
        body = "".join(response.iter_text())

    chunks = _gemini_sse_chunks(body)
    assert response.status_code == 200
    assert chunks[0]["candidates"][0]["content"]["parts"] == [
        {"text": "panel answer from GigaChat-2-Max"}
    ]
    assert chunks[-1]["candidates"][0]["finishReason"] == "STOP"
    assert chunks[-1]["usageMetadata"] == {
        "promptTokenCount": 1,
        "candidatesTokenCount": 1,
        "totalTokenCount": 2,
    }
    assert "[DONE]" not in body


def test_gemini_fusion_returns_final_function_call_and_strips_artifacts():
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
        "/models/gpt2giga/fusion-force-synthesize:generateContent",
        json={
            "contents": [{"parts": [{"text": "lookup hello"}]}],
            "metadata": {
                "tenant": "test",
                "gpt2giga_fusion": {"preset": "force-synthesize"},
            },
            "plugins": [{"id": "fusion", "preset": "force-synthesize"}],
            "tools": [
                {
                    "type": "openrouter:fusion",
                    "parameters": {"preset": "force-synthesize"},
                },
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup",
                            "description": "Lookup data",
                            "parameters": {"type": "object"},
                        }
                    ]
                },
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["candidates"][0]["content"]["parts"] == [
        {
            "functionCall": {
                "id": "call_lookup",
                "name": "lookup",
                "args": {"q": "hello"},
            }
        }
    ]

    sent_payloads = [call[0] for call in app.state.request_transformer.chat_calls]
    for payload in sent_payloads:
        assert payload.get("metadata", {}).get("tenant") == "test"
        assert "plugins" not in payload
        assert "gpt2giga_fusion" not in payload.get("metadata", {})
    assert "tools" not in sent_payloads[0]
    assert "tools" not in sent_payloads[1]
    assert sent_payloads[-1]["tools"][0]["function"]["name"] == "lookup"


def test_gemini_fusion_selector_panel_json_returns_function_call():
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
        "/models/gpt2giga/fusion-force-selector:generateContent",
        json={
            "contents": [{"parts": [{"text": "write hello.py"}]}],
            "metadata": {
                "gpt2giga_fusion": {
                    "preset": "force-selector",
                    "tools_mode": "schema_only",
                }
            },
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "write_file",
                            "description": "Write a file",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "file_path": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["file_path", "content"],
                            },
                        }
                    ]
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["candidates"][0]["content"]["parts"] == [
        {
            "functionCall": {
                "name": "write_file",
                "args": {
                    "file_path": "hello.py",
                    "content": "print(1)",
                },
            }
        }
    ]


def _gemini_sse_chunks(body: str):
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
