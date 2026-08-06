"""Hermetic public-facade E2E for a Chat Completions-only upstream."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import httpx

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocols.normalized import BridgeFeature


MODEL_ALIAS = "bridge/chat-only"
UPSTREAM_MODEL = "fixture-upstream-model"


class _Authorization:
    def __init__(self, intent: Any) -> None:
        self.max_response_bytes = intent.max_response_bytes
        self.peer_validation_required = False

    def validate_request_body(
        self,
        *,
        body_bytes: int,
        body_sha256: str | None,
    ) -> None:
        assert body_bytes > 0
        assert body_sha256 is not None

    def validate_connected_peer(self, _address: str) -> None:
        raise AssertionError("mock transport must not require peer evidence")

    def validate_response_body(self, *, body_bytes: int) -> None:
        assert body_bytes <= self.max_response_bytes


class _NetworkAuthorizer:
    def __call__(self, intent: Any) -> _Authorization:
        return _Authorization(intent)


def _write_profile(
    path: Path,
    *,
    features: list[str] | None = None,
) -> Path:
    payload = {
        "schema_version": "gpt2giga.provider-profiles.v3",
        "profiles": [
            {
                "profile_id": "chat-only-upstream",
                "provider_kind": "openai_compatible",
                "base_url": "https://upstream.invalid/v1/chat/completions",
                "network_policy_ref": "public-openai",
                "tls_policy_ref": "system-default",
                "models": [
                    {
                        "public_alias": MODEL_ALIAS,
                        "upstream_model": UPSTREAM_MODEL,
                        "capability_profile": "chat-only-fixture-v1",
                        "capabilities": {
                            "features": features
                            or [
                                feature.value
                                for feature in BridgeFeature
                                if feature is not BridgeFeature.COUNT_TOKENS
                            ],
                            "limits": {
                                "context_window": 8192,
                                "max_input_tokens": 4096,
                                "max_output_tokens": 4096,
                            },
                        },
                        "support_status": "technical_preview",
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _app(
    tmp_path: Path,
    handler: Any,
    *,
    features: list[str] | None = None,
):
    profile_path = _write_profile(
        tmp_path / "providers.json",
        features=features,
    )
    app = create_app(ProxyConfig(config=str(profile_path)))
    app.state.openai_compatible_network_authorizer_factory = lambda _profile: (
        _NetworkAuthorizer()
    )
    app.state.openai_compatible_http_client_factory = lambda _profile: (
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return app


def _chat_response(*, tool_call: bool = False) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "facade-ok"}
    finish_reason = "stop"
    if tool_call:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_fixture",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"q":"ping"}',
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    return {
        "id": "chatcmpl-facade",
        "object": "chat.completion",
        "created": 1_786_000_000,
        "model": UPSTREAM_MODEL,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "total_tokens": 3,
        },
    }


def _stream_body() -> str:
    chunks = [
        {
            "id": "chatcmpl-facade-stream",
            "model": UPSTREAM_MODEL,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "facade-"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-facade-stream",
            "model": UPSTREAM_MODEL,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "stream"},
                    "finish_reason": "stop",
                }
            ],
        },
        {
            "id": "chatcmpl-facade-stream",
            "model": UPSTREAM_MODEL,
            "choices": [],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 1,
                "total_tokens": 3,
            },
        },
    ]
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + (
        "data: [DONE]\n\n"
    )


def test_responses_anthropic_and_gemini_share_one_chat_upstream(
    tmp_path: Path,
) -> None:
    observed: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=_chat_response())

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        responses = client.post(
            "/v1/responses",
            json={"model": MODEL_ALIAS, "input": "hello"},
        )
        anthropic = client.post(
            "/v1/messages",
            json={
                "model": MODEL_ALIAS,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        gemini = client.post(
            f"/v1beta/models/{MODEL_ALIAS}:generateContent",
            json={"contents": [{"parts": [{"text": "hello"}], "role": "user"}]},
        )

    assert responses.status_code == 200, responses.text
    assert anthropic.status_code == 200, anthropic.text
    assert gemini.status_code == 200, gemini.text
    assert responses.json()["output"][0]["content"][0]["text"] == "facade-ok"
    assert anthropic.json()["content"][0]["text"] == "facade-ok"
    assert gemini.json()["candidates"][0]["content"]["parts"][0]["text"] == (
        "facade-ok"
    )
    assert [path for path, _payload in observed] == [
        "/v1/chat/completions",
        "/v1/chat/completions",
        "/v1/chat/completions",
    ]
    assert all(payload["model"] == UPSTREAM_MODEL for _path, payload in observed)


def test_static_profile_inventory_is_exposed_without_provider_io(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("model discovery must not contact the chat upstream")

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        openai_models = client.get("/v1/models")
        anthropic_models = client.get(
            "/v1/models",
            headers={"anthropic-version": "2023-06-01"},
        )
        gemini_models = client.get("/v1beta/models")
        bridge_models = client.get("/bridge/models")
        readiness = client.get("/ready")

    assert openai_models.status_code == 200, openai_models.text
    assert [item["id"] for item in openai_models.json()["data"]] == [MODEL_ALIAS]
    assert anthropic_models.status_code == 200, anthropic_models.text
    assert [item["id"] for item in anthropic_models.json()["data"]] == [MODEL_ALIAS]
    assert gemini_models.status_code == 200, gemini_models.text
    gemini_model = gemini_models.json()["models"][0]
    assert gemini_model["name"] == f"models/{MODEL_ALIAS}"
    assert gemini_model["inputTokenLimit"] == 4096
    assert gemini_model["outputTokenLimit"] == 4096
    assert gemini_model["supportedGenerationMethods"] == [
        "generateContent",
        "streamGenerateContent",
    ]
    assert bridge_models.status_code == 200, bridge_models.text
    assert [item["id"] for item in bridge_models.json()["models"]] == [MODEL_ALIAS]
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["ready"] is True


def test_three_facades_project_function_calls(tmp_path: Path) -> None:
    observed: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        assert payload["tools"][0]["function"]["name"] == "lookup"
        return httpx.Response(200, json=_chat_response(tool_call=True))

    tool_schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        responses = client.post(
            "/v1/responses",
            json={
                "model": MODEL_ALIAS,
                "input": "lookup",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "description": "Lookup a value.",
                        "parameters": tool_schema,
                    }
                ],
            },
        )
        anthropic = client.post(
            "/v1/messages",
            json={
                "model": MODEL_ALIAS,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "lookup"}],
                "tools": [
                    {
                        "name": "lookup",
                        "description": "Lookup a value.",
                        "input_schema": tool_schema,
                    }
                ],
            },
        )
        gemini = client.post(
            f"/v1beta/models/{MODEL_ALIAS}:generateContent",
            json={
                "contents": [{"parts": [{"text": "lookup"}], "role": "user"}],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "lookup",
                                "description": "Lookup a value.",
                                "parameters": tool_schema,
                            }
                        ]
                    }
                ],
            },
        )

    assert responses.status_code == 200, responses.text
    assert anthropic.status_code == 200, anthropic.text
    assert gemini.status_code == 200, gemini.text
    assert [item["type"] for item in responses.json()["output"]] == ["function_call"]
    assert anthropic.json()["content"][0]["type"] == "tool_use"
    assert (
        gemini.json()["candidates"][0]["content"]["parts"][0]["functionCall"]["name"]
        == "lookup"
    )
    assert len(observed) == 3


def test_three_facades_project_streaming_text(tmp_path: Path) -> None:
    observed: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            text=_stream_body(),
            headers={"content-type": "text/event-stream"},
        )

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        responses = client.post(
            "/v1/responses",
            json={"model": MODEL_ALIAS, "input": "hello", "stream": True},
        )
        anthropic = client.post(
            "/v1/messages",
            json={
                "model": MODEL_ALIAS,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )
        gemini = client.post(
            f"/v1beta/models/{MODEL_ALIAS}:streamGenerateContent",
            json={"contents": [{"parts": [{"text": "hello"}], "role": "user"}]},
        )

    assert responses.status_code == 200, responses.text
    assert anthropic.status_code == 200, anthropic.text
    assert gemini.status_code == 200, gemini.text
    assert "response.output_text.delta" in responses.text
    assert "facade-" in responses.text and "stream" in responses.text
    assert "event: content_block_delta" in anthropic.text
    assert "facade-" in anthropic.text and "stream" in anthropic.text
    assert '"text": "facade-"' in gemini.text
    assert '"text": "stream"' in gemini.text
    assert len(observed) == 3


def test_three_facades_keep_protocol_native_upstream_errors(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "fixture rate limit",
                    "type": "rate_limit_error",
                    "code": "rate_limited",
                }
            },
        )

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        responses = client.post(
            "/v1/responses",
            json={"model": MODEL_ALIAS, "input": "hello"},
        )
        anthropic = client.post(
            "/v1/messages",
            json={
                "model": MODEL_ALIAS,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        gemini = client.post(
            f"/v1beta/models/{MODEL_ALIAS}:generateContent",
            json={"contents": [{"parts": [{"text": "hello"}], "role": "user"}]},
        )

    assert responses.status_code == 429
    assert responses.json()["error"] == {
        "message": "fixture rate limit",
        "type": "rate_limit_error",
        "param": None,
        "code": "rate_limited",
    }
    assert anthropic.status_code == 429
    assert anthropic.json()["error"]["type"] == "rate_limit_error"
    assert anthropic.json()["error"]["message"] == "fixture rate limit"
    assert gemini.status_code == 429
    assert gemini.json()["error"] == {
        "code": 429,
        "message": "fixture rate limit",
        "status": "RESOURCE_EXHAUSTED",
    }


def test_unreviewed_tool_support_is_rejected_before_upstream_io(
    tmp_path: Path,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("unreviewed tool request reached the upstream")

    features = [
        feature.value
        for feature in BridgeFeature
        if feature
        not in {
            BridgeFeature.COUNT_TOKENS,
            BridgeFeature.FUNCTION_TOOLS,
            BridgeFeature.TOOL_CHOICE,
            BridgeFeature.TOOL_RESULTS,
            BridgeFeature.PARALLEL_TOOL_CALLS,
        }
    ]
    app = _app(tmp_path, handler, features=features)
    with TestClient(app) as client:
        response = client.post(
            "/v1/responses",
            json={
                "model": MODEL_ALIAS,
                "input": "lookup",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {"type": "object"},
                    }
                ],
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_semantic"
    assert calls == 0


def test_codex_runtime_envelope_reaches_chat_and_restores_namespace(
    tmp_path: Path,
) -> None:
    observed: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        assert [message["role"] for message in payload["messages"]] == [
            "system",
            "user",
        ]
        assert [tool["function"]["name"] for tool in payload["tools"]] == [
            "exec_command",
            "multi_agent_v1__spawn_agent",
        ]
        assert all("strict" not in tool["function"] for tool in payload["tools"])
        assert payload["parallel_tool_calls"] is False
        return httpx.Response(
            200,
            json={
                **_chat_response(tool_call=True),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_namespace",
                                    "type": "function",
                                    "function": {
                                        "name": "multi_agent_v1__spawn_agent",
                                        "arguments": '{"task":"inspect"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        response = client.post(
            "/v1/responses",
            json={
                "model": MODEL_ALIAS,
                "input": [
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [
                            {"type": "input_text", "text": "Use tools carefully."}
                        ],
                    },
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Inspect."}],
                    },
                ],
                "tools": [
                    {
                        "type": "function",
                        "name": "exec_command",
                        "description": "Run a command.",
                        "parameters": {"type": "object"},
                        "strict": False,
                    },
                    {
                        "type": "namespace",
                        "name": "multi_agent_v1",
                        "description": "Agent tools.",
                        "tools": [
                            {
                                "type": "function",
                                "name": "spawn_agent",
                                "description": "Spawn one agent.",
                                "parameters": {"type": "object"},
                                "strict": False,
                            }
                        ],
                    },
                ],
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "reasoning": {},
                "store": False,
                "include": ["reasoning.encrypted_content"],
                "prompt_cache_key": "session-1",
                "client_metadata": {"session_id": "session-1"},
            },
        )

    assert response.status_code == 200, response.text
    function_call = response.json()["output"][0]
    assert function_call["type"] == "function_call"
    assert function_call["name"] == "spawn_agent"
    assert function_call["namespace"] == "multi_agent_v1"
    assert len(observed) == 1


def test_claude_code_runtime_envelope_reaches_chat(tmp_path: Path) -> None:
    observed: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        assert [message["role"] for message in payload["messages"]] == [
            "system",
            "user",
        ]
        assert payload["messages"][0]["content"] == [
            {"type": "text", "text": "Use tools carefully."}
        ]
        assert payload["max_tokens"] == 4096
        assert payload["stream"] is True
        assert payload["tools"][0]["function"]["name"] == "lookup"
        return httpx.Response(
            200,
            text=_stream_body(),
            headers={"content-type": "text/event-stream"},
        )

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        response = client.post(
            "/v1/messages?beta=true",
            headers={
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "claude-code-20250219",
            },
            json={
                "model": MODEL_ALIAS,
                "max_tokens": 4096,
                "system": [{"type": "text", "text": "Use tools carefully."}],
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Inspect."}],
                    }
                ],
                "tools": [
                    {
                        "name": "lookup",
                        "description": "Lookup a value.",
                        "input_schema": {"type": "object"},
                    }
                ],
                "output_config": {"effort": "high"},
                "stream": True,
            },
        )

    assert response.status_code == 200, response.text
    assert "event: content_block_delta" in response.text
    assert "facade-" in response.text and "stream" in response.text
    assert len(observed) == 1


def test_gemini_cli_runtime_envelope_reaches_chat(tmp_path: Path) -> None:
    observed: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        assert [message["role"] for message in payload["messages"]] == [
            "system",
            "user",
        ]
        assert payload["messages"][0]["content"] == "Use tools carefully."
        assert payload["temperature"] == 1
        assert payload["top_p"] == 0.95
        assert payload["max_tokens"] == 4096
        assert payload["stream"] is True
        assert payload["tools"][0]["function"]["name"] == "lookup"
        return httpx.Response(
            200,
            text=_stream_body(),
            headers={"content-type": "text/event-stream"},
        )

    app = _app(tmp_path, handler)
    with TestClient(app) as client:
        response = client.post(
            f"/v1beta/models/{MODEL_ALIAS}:streamGenerateContent?alt=sse",
            json={
                "systemInstruction": {"parts": [{"text": "Use tools carefully."}]},
                "contents": [{"role": "user", "parts": [{"text": "Inspect."}]}],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "lookup",
                                "description": "Lookup a value.",
                                "parameters": {"type": "object"},
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 1,
                    "topP": 0.95,
                    "maxOutputTokens": 4096,
                },
            },
        )

    assert response.status_code == 200, response.text
    assert '"text": "facade-"' in response.text
    assert '"text": "stream"' in response.text
    assert len(observed) == 1
