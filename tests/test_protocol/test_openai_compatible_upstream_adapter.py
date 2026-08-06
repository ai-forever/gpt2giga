import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import pytest
from pydantic import ValidationError

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTokenLimits,
    NormalizedTool,
    NormalizedToolCall,
    UnsupportedSemanticLossError,
)
from gpt2giga.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleUpstreamError,
    normalized_chat_to_openai_compatible_payload,
    openai_compatible_profile,
)


class _Authorization:
    def __init__(self, intent, *, peer_validation_required=False):
        self.intent = intent
        self.max_response_bytes = intent.max_response_bytes
        self.peer_validation_required = peer_validation_required
        self.request_validations = []
        self.response_validations = []

    def validate_request_body(self, *, body_bytes, body_sha256):
        assert body_bytes == self.intent.request_body_bytes
        assert body_sha256 == self.intent.request_body_sha256
        self.request_validations.append((body_bytes, body_sha256))

    def validate_connected_peer(self, address):
        raise AssertionError(f"unexpected peer validation: {address}")

    def validate_response_body(self, *, body_bytes):
        assert body_bytes <= self.max_response_bytes
        self.response_validations.append(body_bytes)


class _NetworkAuthorizer:
    def __init__(self, *, peer_validation_required=False):
        self.intents = []
        self.authorizations = []
        self.peer_validation_required = peer_validation_required

    def __call__(self, intent):
        self.intents.append(intent)
        authorization = _Authorization(
            intent,
            peer_validation_required=self.peer_validation_required,
        )
        self.authorizations.append(authorization)
        return authorization


def _profile(*, credential=True, features=frozenset(BridgeFeature)):
    return openai_compatible_profile(
        profile_id="vllm-fixture",
        revision="fixture-r1",
        config_revision=f"sha256:{'1' * 64}",
        public_alias="openai/fixture",
        base_url="https://upstream.invalid/v1",
        model="fixture-model",
        capability_profile="openai-fixture-v1",
        loss_matrix_revision=f"sha256:{'2' * 64}",
        features=features,
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
        credential_reference_id="a" * 64 if credential else None,
        network_policy_ref="egress:fixture",
        timeout_seconds=2.0,
    )


async def test_reviewed_profile_binds_exact_public_route_without_secret_material():
    profile = _profile()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
    adapter = OpenAICompatibleProviderAdapter(
        profile,
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    redacted = adapter.__gpt2giga_redacted__()

    assert profile.schema_version == "gpt2giga.openai-compatible-upstream.v1"
    assert redacted["route"] == {
        "schema_version": "gpt2giga.execution-context.v1",
        "config_revision": f"sha256:{'1' * 64}",
        "profile_id": "vllm-fixture",
        "profile_revision": "fixture-r1",
        "public_alias": "openai/fixture",
        "provider_kind": "openai_compatible",
        "upstream_model": "fixture-model",
        "capability_profile": "openai-fixture-v1",
        "loss_matrix_revision": f"sha256:{'2' * 64}",
    }
    assert "secret-value-canary" not in repr(adapter)
    assert "secret-value-canary" not in json.dumps(redacted)
    await client.aclose()


def test_reviewed_profile_rejects_noncanonical_revisions():
    with pytest.raises(ValidationError, match="config_revision"):
        openai_compatible_profile(
            profile_id="vllm-fixture",
            revision="fixture-r1",
            config_revision="fixture-config",
            public_alias="openai/fixture",
            base_url="https://upstream.invalid/v1",
            model="fixture-model",
            capability_profile="openai-fixture-v1",
            loss_matrix_revision=f"sha256:{'2' * 64}",
            features=frozenset(BridgeFeature),
            limits=NormalizedTokenLimits(context_window=8192),
            network_policy_ref="egress:fixture",
        )


def test_full_chat_completions_url_is_not_appended_twice():
    profile = _profile().model_copy(
        update={"base_url": "https://upstream.invalid/v1/chat/completions"}
    )

    assert profile.chat_completions_url == (
        "https://upstream.invalid/v1/chat/completions"
    )


def _request(*, stream=False):
    return NormalizedChatRequest(
        model="fixture-model",
        stream=stream,
        messages=[
            NormalizedMessage(role="system", content="Be concise."),
            NormalizedMessage(role="user", content="Look up ping."),
        ],
        tools=[
            NormalizedTool(
                name="lookup",
                description="Look up a value.",
                parameters={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            )
        ],
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        generation_config=NormalizedGenerationConfig(
            temperature=0.2,
            max_tokens=128,
        ),
    )


def test_payload_preserves_tool_results_parallel_control_and_json_schema():
    request = NormalizedChatRequest(
        model="fixture-model",
        messages=[
            NormalizedMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    NormalizedToolCall(
                        id="call-1",
                        name="lookup",
                        arguments='{"q":"ping"}',
                    )
                ],
            ),
            NormalizedMessage(
                role="tool",
                tool_call_id="call-1",
                content='{"value":"pong"}',
            ),
        ],
        parallel_tool_calls=False,
        response_format=NormalizedResponseFormat(
            type="json_schema",
            json_schema={
                "name": "answer",
                "strict": True,
                "schema": {"type": "object"},
            },
        ),
    )

    payload = normalized_chat_to_openai_compatible_payload(request)

    assert payload["messages"][0]["tool_calls"][0]["id"] == "call-1"
    assert payload["messages"][1]["tool_call_id"] == "call-1"
    assert payload["parallel_tool_calls"] is False
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "answer",
            "strict": True,
            "schema": {"type": "object"},
        },
    }


def _all_downstream_capabilities():
    return frozenset(BridgeFeature)


def _fake_app():
    app = FastAPI()
    app.state.requests = []

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        payload = await request.json()
        app.state.requests.append(
            {
                "path": request.url.path,
                "authorization": request.headers.get("authorization"),
                "payload": payload,
            }
        )
        if payload["stream"]:
            chunks = [
                {
                    "id": "chatcmpl-stream",
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "lookup",
                                            "arguments": '{"q":',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-stream",
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '"ping"}'},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
                {
                    "id": "chatcmpl-stream",
                    "model": "fixture-model",
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 7,
                        "completion_tokens": 4,
                        "total_tokens": 11,
                    },
                },
            ]

            async def events():
                for chunk in chunks:
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        return JSONResponse(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "fixture-model",
                "system_fingerprint": "fixture-fingerprint",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"q":"ping"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            }
        )

    @app.get("/v1/models")
    async def models(request: Request):
        app.state.requests.append(
            {
                "path": request.url.path,
                "authorization": request.headers.get("authorization"),
            }
        )
        return {
            "object": "list",
            "data": [
                {"id": "fixture-model-b", "object": "model"},
                {"id": "fixture-model", "object": "model"},
                {"id": "fixture-model", "object": "model"},
            ],
        }

    return app


def _streaming_app(chunks):
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def stream():
        async def events():
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


async def test_adapter_executes_chat_tools_and_model_discovery_through_fake_server():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        timeout=2.0,
    )
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    response = await adapter.complete(
        _request(),
        downstream=DownstreamProtocol.OPENAI,
        downstream_capabilities=_all_downstream_capabilities(),
        input_token_count=7,
    )
    models = await adapter.discover_models()
    await client.aclose()

    assert response.id == "chatcmpl-1"
    assert response.model == "fixture-model"
    assert response.provider == "vllm-fixture"
    assert response.choices[0].stop_reason == "tool_calls"
    assert response.choices[0].message.tool_calls[0].name == "lookup"
    assert response.usage.input_tokens == 7
    assert response.usage.output_tokens == 3
    assert response.provider_metadata["openai_compatible"] == {
        "profile_id": "vllm-fixture",
        "profile_revision": "fixture-r1",
        "dialect": "openai-chat-completions-v1",
        "admission_schema_version": "gigaloom.protocol-bridge-admission.v1",
        "route": {
            "schema_version": "gpt2giga.execution-context.v1",
            "config_revision": f"sha256:{'1' * 64}",
            "profile_id": "vllm-fixture",
            "profile_revision": "fixture-r1",
            "public_alias": "openai/fixture",
            "provider_kind": "openai_compatible",
            "upstream_model": "fixture-model",
            "capability_profile": "openai-fixture-v1",
            "loss_matrix_revision": f"sha256:{'2' * 64}",
        },
        "system_fingerprint": "fixture-fingerprint",
    }
    assert models == ("fixture-model", "fixture-model-b")

    chat_request = app.state.requests[0]
    assert chat_request["authorization"] == "Bearer secret-value-canary"
    assert chat_request["payload"]["tools"][0]["function"]["name"] == "lookup"
    assert chat_request["payload"]["tool_choice"]["function"]["name"] == "lookup"
    assert chat_request["payload"]["temperature"] == 0.2
    assert chat_request["payload"]["max_tokens"] == 128
    assert [intent.purpose for intent in network.intents] == [
        "provider.openai-compatible.chat",
        "provider.openai-compatible.models",
    ]
    assert all("secret-value-canary" not in repr(intent) for intent in network.intents)
    assert all(
        authorization.request_validations for authorization in network.authorizations
    )
    assert all(
        authorization.response_validations for authorization in network.authorizations
    )


async def test_adapter_streams_tool_events_usage_and_terminal_event():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == [
        "message_start",
        "tool_call_start",
        "tool_call_delta",
        "message_end",
        "usage",
    ]
    assert events[1].tool_call.name == "lookup"
    assert events[2].tool_call.arguments == '"ping"}'
    assert events[3].stop_reason == "tool_calls"
    assert events[4].usage.total_tokens == 11
    assert app.state.requests[0]["payload"]["stream_options"] == {"include_usage": True}


async def test_parallel_stream_tool_calls_preserve_indexes_and_identity():
    chunks = [
        {
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-0",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{"},
                            },
                            {
                                "index": 1,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{"},
                            },
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": "}"}},
                            {"index": 1, "function": {"arguments": "}"}},
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    ]
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    tool_events = [event for event in events if event.tool_call is not None]
    assert [event.type for event in tool_events] == [
        "tool_call_start",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_delta",
    ]
    assert [event.tool_call.raw_extensions["index"] for event in tool_events] == [
        0,
        1,
        0,
        1,
    ]
    assert [event.tool_call.id for event in tool_events[:2]] == ["call-0", "call-1"]
    assert [event.type for event in events if event.type == "message_end"] == [
        "message_end"
    ]


async def test_stream_rejects_changed_tool_identity_without_success_terminal():
    chunks = [
        {
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-0",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{"},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-changed",
                                "function": {"arguments": "}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    ]
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == [
        "message_start",
        "tool_call_start",
        "error",
    ]
    assert events[-1].error.code == "stream_tool_identity_changed"


@pytest.mark.parametrize(
    ("chunks", "error_code"),
    [
        (
            [
                {
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                },
                {
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "late"},
                            "finish_reason": None,
                        }
                    ],
                },
            ],
            "stream_data_after_terminal",
        ),
        (
            [
                {
                    "model": "fixture-model",
                    "choices": [],
                    "usage": {"prompt_tokens": 2},
                },
                {
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                },
            ],
            "usage_before_stream_terminal",
        ),
    ],
)
async def test_reordered_streams_fail_with_normalized_protocol_errors(
    chunks,
    error_code,
):
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert events[-1].type == "error"
    assert events[-1].error is not None
    assert events[-1].error.code == error_code
    assert events[-1].error.retryable is False


async def test_stream_accepts_partial_usage_after_terminal_without_inventing_counts():
    chunks = [
        {
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        },
        {
            "model": "fixture-model",
            "choices": [],
            "usage": {"prompt_tokens": 2},
        },
    ]
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == [
        "message_start",
        "content_delta",
        "message_end",
        "usage",
    ]
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 2
    assert events[-1].usage.output_tokens is None
    assert events[-1].usage.total_tokens is None


async def test_malformed_stream_fails_with_a_non_retryable_protocol_error():
    async def handler(_request):
        return httpx.Response(
            200,
            text="data: {not-json}\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert events[-1].type == "error"
    assert events[-1].error is not None
    assert events[-1].error.code == "invalid_stream_json"
    assert events[-1].error.retryable is False


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        (
            'data: {"model":"fixture-model","choices":[{"index":0,'
            '"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n',
            "incomplete_stream",
        ),
        (
            'data: {"model":"fixture-model","choices":[{"index":0,'
            '"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
            'data: {"model":"fixture-model","choices":[]}\n\n',
            "stream_data_after_done",
        ),
    ],
)
async def test_incomplete_or_post_done_stream_has_only_error_terminal(
    body,
    error_code,
):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                text=body,
                headers={"content-type": "text/event-stream"},
            )
        )
    )
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    terminals = [
        event for event in events if event.type in {"message_end", "cancelled", "error"}
    ]
    assert [event.type for event in terminals] == ["error"]
    assert terminals[0].error.code == error_code


async def test_stream_disconnect_projects_cooperative_cancellation():
    app = _streaming_app(
        [
            {
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "unobserved"},
                        "finish_reason": None,
                    }
                ],
            }
        ]
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    network = _NetworkAuthorizer()
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=network,
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
            is_disconnected=lambda: True,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == ["message_start", "cancelled"]
    assert events[-1].stop_reason == "cancelled"
    assert network.intents == []


async def test_semantic_admission_rejects_before_network_or_fake_server():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(features={BridgeFeature.TEXT}),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    with pytest.raises(UnsupportedSemanticLossError, match="lacks"):
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert network.intents == []
    assert app.state.requests == []


async def test_http_errors_preserve_provider_facts_and_normalize_retryability():
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def fail():
        return JSONResponse(
            {
                "error": {
                    "message": "fixture is busy",
                    "type": "server_error",
                    "code": "busy",
                }
            },
            status_code=503,
        )

    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=network,
        http_client=client,
    )

    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    error = exc_info.value.error
    assert exc_info.value.status_code == 503
    assert error.message == "fixture is busy"
    assert error.type == "server_error"
    assert error.code == "busy"
    assert error.error_class == "upstream"
    assert error.retryable is True


async def test_invalid_request_http_error_is_non_retryable():
    async def handler(_request):
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "fixture request is invalid",
                    "type": "invalid_request_error",
                    "code": "invalid_fixture",
                    "param": "tool_choice",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    error = exc_info.value.error
    assert exc_info.value.status_code == 400
    assert error.type == "invalid_request_error"
    assert error.code == "invalid_fixture"
    assert error.param == "tool_choice"
    assert error.error_class == "invalid_request"
    assert error.retryable is False


async def test_redirect_is_a_nonretryable_destination_mismatch():
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(307, headers={"location": "https://elsewhere.invalid"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert calls == 1
    assert exc_info.value.status_code == 307
    assert exc_info.value.error.code == "destination_mismatch"
    assert exc_info.value.error.retryable is False


async def test_route_model_and_peer_evidence_fail_closed_before_response_use():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    with pytest.raises(ValueError, match="model does not match"):
        await adapter.complete(
            _request().model_copy(update={"model": "unreviewed-model"}),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert network.intents == []
    assert app.state.requests == []

    peer_network = _NetworkAuthorizer(peer_validation_required=True)
    peer_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_fake_app()))
    peer_adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=peer_network,
        http_client=peer_client,
    )
    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await peer_adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await peer_client.aclose()

    assert exc_info.value.error.code == "peer_evidence_unavailable"


async def test_timeout_and_response_ceiling_are_normalized_without_retries():
    calls = 0

    async def timeout_handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    timeout_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    timeout_adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=timeout_client,
    )
    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await timeout_adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await timeout_client.aclose()

    assert calls == 1
    assert exc_info.value.error.code == "timeout"
    assert exc_info.value.error.retryable is True

    async def oversized_handler(_request):
        return httpx.Response(200, content=b"x" * 65)

    profile = _profile(credential=False).model_copy(update={"max_response_bytes": 64})
    oversized_client = httpx.AsyncClient(
        transport=httpx.MockTransport(oversized_handler)
    )
    oversized_adapter = OpenAICompatibleProviderAdapter(
        profile,
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=oversized_client,
    )
    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await oversized_adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await oversized_client.aclose()

    assert exc_info.value.error.code == "response_too_large"


def test_tls_and_proxy_refs_require_an_injected_policy_owned_client():
    profile = _profile(credential=False).model_copy(
        update={"tls_policy_ref": "tls:custom"}
    )

    with pytest.raises(ValueError, match="injected HTTP client"):
        OpenAICompatibleProviderAdapter(
            profile,
            credential=None,
            authorize_network=_NetworkAuthorizer(),
        )
