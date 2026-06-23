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


class VerifiedLoopGigachat:
    def __init__(self):
        self.chat_calls = []

    async def achat(self, chat):
        self.chat_calls.append(chat)
        stage = chat.get("metadata", {}).get("gpt2giga_fusion_stage")
        if stage == "direct_candidate":
            content = None
            message = {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": "call-weather",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps(
                                {
                                    "city": "Saint Petersburg",
                                    "date": "tomorrow",
                                }
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif stage == "verifier_panel":
            message = {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "schema_version": "gpt2giga.fusion.verification.v1",
                        "checked_candidate_id": "direct",
                        "verdict": "approve",
                        "concrete_issues": [],
                        "corrected_tool_call": None,
                        "missing_requirements_after_action": ["hotel", "currency"],
                        "all_required_data_present": False,
                        "reason_brief": "direct tool call is valid",
                    }
                ),
            }
            finish_reason = "stop"
        elif stage == "action_judge":
            message = {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "schema_version": "gpt2giga.fusion.action_decision.v1",
                        "task_status": "needs_tool",
                        "action_type": "tool_call",
                        "selected_candidate_id": "direct",
                        "tool_call": {
                            "id": "call-weather",
                            "type": "function",
                            "name": "get_weather",
                            "arguments": {
                                "city": "Saint Petersburg",
                                "date": "tomorrow",
                            },
                        },
                        "final_answer": None,
                        "missing_requirements": ["hotel", "currency"],
                        "verifier_findings": [],
                        "direct_candidate_errors": [],
                        "confidence": 1.0,
                        "reason_brief": "call weather first",
                    }
                ),
            }
            finish_reason = "stop"
        else:
            message = {"role": "assistant", "content": "unexpected stage"}
            finish_reason = "stop"
        return MockResponse(
            {
                "choices": [{"message": message, "finish_reason": finish_reason}],
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
            fusion_aliases=[
                "gpt2giga/fusion-code",
                "gpt2giga/fusion-code-budget",
                "gpt2giga/fusion-benchmark-text",
                "gpt2giga/fusion-benchmark-tools",
                "gpt2giga/fusion-force-synthesize",
                "gpt2giga/fusion-force-selector",
            ],
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
            "model": "gpt2giga/fusion-code-budget",
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
    assert body["model"] == "gpt2giga/fusion-code-budget"
    assert body["output"][0]["content"][0]["text"] == (
        "panel answer from GigaChat-2-Max"
    )
    assert body["output_text"] == "panel answer from GigaChat-2-Max"
    assert body["metadata"]["tenant"] == "test"
    assert "gpt2giga_fusion_preset" not in body["metadata"]
    assert body["usage"]["total_tokens"] == 2
    assert [call["model"] for call in app.state.gigachat_client.chat_calls] == [
        "GigaChat-2-Max",
    ]
    sent_payloads = [call[0] for call in app.state.request_transformer.chat_calls]
    assert len(sent_payloads) == 1
    assert "gpt2giga_fusion_runtime" not in sent_payloads[0]["messages"][0]["content"]
    assert not app.state.request_transformer.response_calls


def test_responses_fusion_model_alias_returns_buffered_stream():
    app = make_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={
            "model": "gpt2giga/fusion-code-budget",
            "input": "hello",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert "panel answer from GigaChat-2-Max" in body
    assert "event: response.completed" in body
    completed = _last_sse_payload(body, "response.completed")
    assert completed["response"]["output_text"] == "panel answer from GigaChat-2-Max"
    assert "gpt2giga_fusion" not in completed["response"]["metadata"]


def test_responses_fusion_error_returns_http_502():
    class FailingFusionGigachat:
        def __init__(self):
            self.chat_calls = []

        async def achat(self, chat):
            self.chat_calls.append(chat)
            raise RuntimeError("upstream unavailable")

    app = make_app(gigachat=FailingFusionGigachat())
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt2giga/fusion-code-budget",
            "input": "hello",
        },
    )

    body = response.json()
    assert response.status_code == 502
    assert body["status"] == "failed"
    assert body["error"]["code"] == "outer_model_failed"
    assert [call["model"] for call in app.state.gigachat_client.chat_calls] == [
        "GigaChat-2-Max",
    ]


def test_responses_fusion_code_verified_loop_returns_function_call():
    gigachat = VerifiedLoopGigachat()
    app = make_app(gigachat=gigachat)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt2giga/fusion-code",
            "input": "Check weather before planning the trip.",
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "date": {"type": "string"},
                        },
                        "required": ["city", "date"],
                    },
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["output"] == [
        {
            "id": "fc_call-weather",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-weather",
            "name": "get_weather",
            "arguments": '{"city": "Saint Petersburg", "date": "tomorrow"}',
        }
    ]
    assert [
        call["metadata"]["gpt2giga_fusion_stage"] for call in gigachat.chat_calls
    ] == ["direct_candidate", "verifier_panel", "action_judge"]


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
            "model": "gpt2giga/fusion-force-synthesize",
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


def test_responses_fusion_selector_panel_json_returns_function_call():
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
        "/responses",
        json={
            "model": "gpt2giga/fusion-force-selector",
            "input": "write hello.py",
            "metadata": {
                "gpt2giga_fusion": {
                    "preset": "force-selector",
                    "tools_mode": "schema_only",
                }
            },
            "tools": [
                {
                    "type": "function",
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
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["output"][0]["type"] == "function_call"
    assert body["output"][0]["name"] == "write_file"
    assert json.loads(body["output"][0]["arguments"]) == {
        "file_path": "hello.py",
        "content": "print(1)",
    }


def test_responses_fusion_benchmark_text_rejects_client_tools():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt2giga/fusion-benchmark-text",
            "input": "Check weather.",
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object"},
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 400
    assert body["error"]["type"] == "invalid_fusion_configuration"
    assert body["error"]["code"] == "invalid_fusion_configuration"
    assert "tools_mode=off" in body["error"]["message"]
    assert app.state.gigachat_client.chat_calls == []


def test_responses_fusion_benchmark_tools_exposes_resolved_metadata():
    gigachat = FusionGigachat(
        panel_content="Plain panel answer.",
        selector_payload={
            "schema_version": "gpt2giga.fusion.selection.v1",
            "selected_candidate_id": "panel_1",
            "confidence": 1.0,
            "reason_brief": "Use panel.",
        },
    )
    app = make_app(gigachat=gigachat)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt2giga/fusion-benchmark-tools",
            "input": "Answer directly.",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["metadata"]["gpt2giga_fusion_requested_model"] == (
        "gpt2giga/fusion-benchmark-tools"
    )
    assert body["metadata"]["gpt2giga_fusion_preset"] == (
        "force-benchmark-selector-tools"
    )
    assert body["metadata"]["gpt2giga_fusion_invocation_mode"] == "force"
    assert body["metadata"]["gpt2giga_fusion_decision_mode"] == "selector"
    assert body["metadata"]["gpt2giga_fusion_tools_mode"] == "schema_only"
    assert body["metadata"]["gpt2giga_fusion_direct_tool_call_policy"] == "selector"
    assert body["metadata"]["gpt2giga_fusion_post_tool_mode"] == ("fusion_continuation")


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
