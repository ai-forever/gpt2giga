import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import pytest

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedTokenCountRequest,
    NormalizedTokenLimits,
    NormalizedTool,
    NormalizedToolCall,
    UnsupportedSemanticLossError,
)
from gpt2giga.providers.anthropic import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    ANTHROPIC_IMPLEMENTED_FEATURES_V1,
    AnthropicProviderAdapter,
    AnthropicProtocolError,
    AnthropicUnsupportedSemanticError,
    AnthropicUpstreamError,
    anthropic_capability_evidence,
    anthropic_profile,
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


def _profile(*, credential=True, features=ANTHROPIC_IMPLEMENTED_FEATURES_V1):
    return anthropic_profile(
        profile_id="anthropic-fixture",
        revision="fixture-r1",
        base_url="https://upstream.invalid",
        model="claude-fixture",
        features=features,
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
        credential_reference_id="a" * 64 if credential else None,
        network_policy_ref="egress:fixture",
        default_max_tokens=256,
        timeout_seconds=2.0,
    )


def _request():
    return NormalizedChatRequest(
        protocol="openai",
        model="claude-fixture",
        messages=[
            NormalizedMessage(role="system", content="Be concise."),
            NormalizedMessage(role="user", content="Look up ping."),
            NormalizedMessage(
                role="assistant",
                tool_calls=[
                    NormalizedToolCall(
                        id="toolu_prior",
                        name="lookup",
                        arguments={"q": "prior"},
                    )
                ],
            ),
            NormalizedMessage(
                role="tool",
                tool_call_id="toolu_prior",
                content="prior-result",
            ),
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
        parallel_tool_calls=False,
        generation_config=NormalizedGenerationConfig(
            temperature=0.2,
            max_tokens=128,
            stop=["done"],
        ),
        user="fixture-user",
    )


def _fake_app():
    app = FastAPI()
    app.state.requests = []

    @app.post("/v1/messages")
    async def messages(request: Request):
        payload = await request.json()
        app.state.requests.append(
            {
                "path": request.url.path,
                "api_key": request.headers.get("x-api-key"),
                "anthropic_version": request.headers.get("anthropic-version"),
                "payload": payload,
            }
        )
        return JSONResponse(
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-fixture",
                "content": [
                    {"type": "text", "text": "Calling lookup."},
                    {
                        "type": "tool_use",
                        "id": "toolu_new",
                        "name": "lookup",
                        "input": {"q": "ping"},
                    },
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 11, "output_tokens": 5},
            }
        )

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(request: Request):
        payload = await request.json()
        app.state.requests.append(
            {
                "path": request.url.path,
                "api_key": request.headers.get("x-api-key"),
                "anthropic_version": request.headers.get("anthropic-version"),
                "payload": payload,
            }
        )
        return {"input_tokens": 17}

    return app


def _sse(event):
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


def _streaming_app(events):
    app = FastAPI()
    app.state.requests = []

    @app.post("/v1/messages")
    async def messages(request: Request):
        app.state.requests.append(await request.json())

        async def stream():
            for event in events:
                yield _sse(event)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _stream_events():
    return [
        {
            "type": "message_start",
            "message": {
                "id": "msg_stream",
                "type": "message",
                "role": "assistant",
                "model": "claude-fixture",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 11, "output_tokens": 1},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Calling lookup."},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_stream",
                "name": "lookup",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '"ping"}'},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]


async def test_adapter_executes_messages_and_tools_through_fake_server():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    response = await adapter.complete(
        _request(),
        downstream=DownstreamProtocol.OPENAI,
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=11,
    )
    await client.aclose()

    assert response.id == "msg_fixture"
    assert response.model == "claude-fixture"
    assert response.provider == "anthropic-fixture"
    assert response.choices[0].stop_reason == "tool_calls"
    assert response.choices[0].message.content[0].text == "Calling lookup."
    assert response.choices[0].message.tool_calls[0] == NormalizedToolCall(
        id="toolu_new",
        name="lookup",
        arguments={"q": "ping"},
    )
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 16
    assert response.provider_metadata["anthropic"] == {
        "profile_id": "anthropic-fixture",
        "profile_revision": "fixture-r1",
        "dialect": "anthropic-messages-2023-06-01",
        "admission_schema_version": "gigaloom.protocol-bridge-admission.v1",
    }

    observed = app.state.requests[0]
    assert observed["path"] == "/v1/messages"
    assert observed["api_key"] == "secret-value-canary"
    assert observed["anthropic_version"] == ANTHROPIC_API_VERSION
    assert observed["payload"]["model"] == "claude-fixture"
    assert observed["payload"]["system"] == [{"type": "text", "text": "Be concise."}]
    assert observed["payload"]["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Look up ping."}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_prior",
                    "name": "lookup",
                    "input": {"q": "prior"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_prior",
                    "content": "prior-result",
                }
            ],
        },
    ]
    assert observed["payload"]["tools"][0]["input_schema"]["type"] == "object"
    assert observed["payload"]["tool_choice"] == {
        "type": "tool",
        "name": "lookup",
        "disable_parallel_tool_use": True,
    }
    assert observed["payload"]["metadata"] == {"user_id": "fixture-user"}
    assert observed["payload"]["max_tokens"] == 128
    assert observed["payload"]["stop_sequences"] == ["done"]
    assert [intent.purpose for intent in network.intents] == [
        "provider.anthropic.messages"
    ]
    assert "secret-value-canary" not in repr(network.intents[0])
    assert network.authorizations[0].request_validations
    assert network.authorizations[0].response_validations


async def test_count_tokens_uses_only_the_explicit_anthropic_operation():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )
    chat = _request()
    request = NormalizedTokenCountRequest(
        model="claude-fixture",
        input=chat,
    )

    response = await adapter.count_tokens(
        request,
        downstream=DownstreamProtocol.ANTHROPIC,
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=11,
    )
    await client.aclose()

    assert response.input_tokens == 17
    assert response.model == "claude-fixture"
    assert response.limits.max_input_tokens == 6144
    assert [intent.purpose for intent in network.intents] == [
        "provider.anthropic.count-tokens"
    ]
    observed = app.state.requests[0]
    assert observed["path"] == "/v1/messages/count_tokens"
    assert observed["payload"]["model"] == "claude-fixture"
    assert "max_tokens" not in observed["payload"]
    assert "stream" not in observed["payload"]
    assert observed["payload"]["tools"][0]["name"] == "lookup"


async def test_cache_usage_and_refusal_facts_are_normalized_without_explanation():
    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "id": "msg_refusal",
                "type": "message",
                "role": "assistant",
                "model": "claude-fixture",
                "content": [{"type": "text", "text": "I cannot help."}],
                "stop_reason": "refusal",
                "stop_sequence": None,
                "stop_details": {
                    "type": "refusal",
                    "category": "general_harms",
                    "explanation": "sensitive-explanation-canary",
                },
                "usage": {
                    "input_tokens": 3,
                    "cache_creation_input_tokens": 2,
                    "cache_read_input_tokens": 5,
                    "output_tokens": 4,
                    "service_tier": "priority",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    response = await adapter.complete(
        _request(),
        downstream=DownstreamProtocol.OPENAI,
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=10,
    )
    await client.aclose()

    assert response.choices[0].stop_reason == "content_filter"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 4
    assert response.usage.total_tokens == 14
    assert response.usage.provider_metadata["anthropic"] == {
        "input_tokens": 3,
        "output_tokens": 4,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 5,
        "service_tier": "priority",
    }
    assert response.provider_metadata["anthropic"]["refusal_category"] == (
        "general_harms"
    )
    assert "sensitive-explanation-canary" not in response.model_dump_json()


async def test_adapter_streams_content_tools_usage_and_one_terminal_state():
    app = _streaming_app(_stream_events())
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )
    request = _request()
    request.stream = True

    events = [
        event
        async for event in adapter.stream_chat(
            request,
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == [
        "message_start",
        "content_delta",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_delta",
        "usage",
        "message_end",
    ]
    assert [event.sequence for event in events] == list(range(len(events)))
    assert events[0].id == "msg_stream"
    assert events[1].content_delta == "Calling lookup."
    assert events[2].tool_call == NormalizedToolCall(
        id="toolu_stream",
        name="lookup",
        raw_extensions={"index": 1},
    )
    assert events[3].tool_call.arguments == '{"q":'
    assert events[4].tool_call.arguments == '"ping"}'
    assert events[5].usage.input_tokens == 11
    assert events[5].usage.output_tokens == 5
    assert events[5].usage.total_tokens == 16
    assert events[6].stop_reason == "tool_calls"
    assert events[6].finish_reason == "tool_calls"
    assert events[6].metadata == {"anthropic_stop_reason": "tool_use"}
    assert app.state.requests[0]["stream"] is True
    assert network.authorizations[0].response_validations


async def test_stream_preserves_cache_usage_and_refusal_category():
    raw_events = _stream_events()
    raw_events[0]["message"]["usage"] = {
        "input_tokens": 3,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 5,
        "output_tokens": 1,
        "service_tier": "standard",
    }
    raw_events = raw_events[:4] + [
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": "refusal",
                "stop_sequence": None,
                "stop_details": {
                    "type": "refusal",
                    "category": "cyber",
                    "explanation": "stream-explanation-canary",
                },
            },
            "usage": {
                "cache_read_input_tokens": 6,
                "output_tokens": 4,
            },
        },
        {"type": "message_stop"},
    ]
    app = _streaming_app(raw_events)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )
    request = _request()
    request.stream = True

    events = [
        event
        async for event in adapter.stream_chat(
            request,
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    ]
    await client.aclose()

    usage = next(event.usage for event in events if event.type == "usage")
    terminal = events[-1]
    assert usage.input_tokens == 11
    assert usage.output_tokens == 4
    assert usage.total_tokens == 15
    assert usage.provider_metadata["anthropic"]["cache_read_input_tokens"] == 6
    assert terminal.stop_reason == "content_filter"
    assert terminal.metadata == {
        "anthropic_stop_reason": "refusal",
        "anthropic_refusal_category": "cyber",
    }
    assert "stream-explanation-canary" not in "".join(
        event.model_dump_json() for event in events
    )


async def test_stream_disconnect_emits_cancellation_and_closes_upstream():
    app = _streaming_app(_stream_events())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )
    request = _request()
    request.stream = True

    events = [
        event
        async for event in adapter.stream_chat(
            request,
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
            is_disconnected=lambda: True,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == ["message_start", "cancelled"]
    assert events[-1].stop_reason == "cancelled"


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (
            lambda events: events.__setitem__(
                2,
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": "{}",
                    },
                },
            ),
            "content_delta_type_mismatch",
        ),
        (
            lambda events: events[6]["delta"].__setitem__("partial_json", '"ping"'),
            "invalid_stream_tool_input",
        ),
        (lambda events: events.pop(), "incomplete_stream"),
    ],
)
async def test_malformed_or_incomplete_stream_ends_in_one_error(mutate, error_code):
    raw_events = _stream_events()
    mutate(raw_events)
    app = _streaming_app(raw_events)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )
    request = _request()
    request.stream = True

    events = [
        event
        async for event in adapter.stream_chat(
            request,
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    ]
    await client.aclose()

    assert events[-1].type == "error"
    assert events[-1].error.code == error_code
    assert [event.type for event in events].count("error") == 1
    assert "message_end" not in [event.type for event in events]


async def test_stream_data_after_message_stop_raises_without_second_terminal():
    raw_events = _stream_events()
    raw_events.append({"type": "ping"})
    app = _streaming_app(raw_events)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )
    request = _request()
    request.stream = True
    events = []

    with pytest.raises(AnthropicProtocolError) as exc_info:
        async for event in adapter.stream_chat(
            request,
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        ):
            events.append(event)
    await client.aclose()

    assert exc_info.value.error.code == "stream_data_after_terminal"
    assert [event.type for event in events].count("message_end") == 1
    assert "error" not in [event.type for event in events]


async def test_semantic_admission_rejects_before_network_or_fake_server():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = AnthropicProviderAdapter(
        _profile(features={BridgeFeature.TEXT}),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    with pytest.raises(UnsupportedSemanticLossError, match="lacks"):
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    await client.aclose()

    assert network.intents == []
    assert app.state.requests == []


async def test_anthropic_only_unsupported_controls_fail_before_network():
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )
    request = _request()
    request.generation_config.seed = 7

    with pytest.raises(AnthropicUnsupportedSemanticError) as exc_info:
        await adapter.complete(
            request,
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    await client.aclose()

    assert exc_info.value.param == "generation_config.seed"
    assert network.intents == []


async def test_timeout_is_normalized_and_task_cancellation_propagates():
    async def timeout_handler(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    timeout_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=timeout_client,
    )
    with pytest.raises(AnthropicUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    await timeout_client.aclose()

    assert exc_info.value.error.error_class == "timeout"
    assert exc_info.value.error.retryable is True

    async def cancel_handler(_request):
        raise asyncio.CancelledError

    cancel_client = httpx.AsyncClient(transport=httpx.MockTransport(cancel_handler))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=cancel_client,
    )
    with pytest.raises(asyncio.CancelledError):
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    await cancel_client.aclose()


@pytest.mark.parametrize(
    ("status", "error_type", "error_class", "retryable"),
    [
        (401, "authentication_error", "authentication", False),
        (429, "rate_limit_error", "rate_limit", True),
        (529, "overloaded_error", "upstream", True),
    ],
)
async def test_http_status_errors_preserve_bounded_provider_facts(
    status,
    error_type,
    error_class,
    retryable,
):
    async def handler(_request):
        return httpx.Response(
            status,
            json={
                "type": "error",
                "error": {
                    "type": error_type,
                    "message": "secret-provider-error-canary",
                },
                "request_id": "req_fixture",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(AnthropicUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=11,
        )
    await client.aclose()

    error = exc_info.value.error
    assert exc_info.value.status_code == status
    assert error.type == error_type
    assert error.code == error_type
    assert error.error_class == error_class
    assert error.retryable is retryable
    assert error.provider_metadata == {
        "anthropic": {"http_status": status, "request_id": "req_fixture"}
    }
    assert "secret-provider-error-canary" not in str(exc_info.value)


async def test_profile_and_adapter_reject_unreviewed_authority():
    with pytest.raises(ValueError, match="credential"):
        AnthropicProviderAdapter(
            _profile(),
            credential=None,
            authorize_network=_NetworkAuthorizer(),
        )
    with pytest.raises(ValueError, match="unsupported features"):
        _profile(features={BridgeFeature.IMAGE_REFERENCES})
    with pytest.raises(ValueError, match="enabled together"):
        _profile(features={BridgeFeature.STREAM_DELTAS})
    with pytest.raises(ValueError, match="absolute"):
        anthropic_profile(
            profile_id="anthropic-fixture",
            revision="fixture-r1",
            base_url="relative",
            model="claude-fixture",
            features=ANTHROPIC_IMPLEMENTED_FEATURES_V1,
            limits=NormalizedTokenLimits(context_window=8192),
            network_policy_ref="egress:fixture",
        )

    profile = _profile()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        follow_redirects=True,
    )
    with pytest.raises(ValueError, match="redirects"):
        AnthropicProviderAdapter(
            profile,
            credential="secret-value-canary",
            authorize_network=_NetworkAuthorizer(),
            http_client=client,
        )
    await client.aclose()


async def test_redacted_runtime_projection_never_contains_credential():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"unused": True})
        )
    )
    adapter = AnthropicProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    assert "secret-value-canary" not in repr(adapter)
    assert "secret-value-canary" not in json.dumps(adapter.__gpt2giga_redacted__())
    await client.aclose()


def test_capability_evidence_is_complete_content_free_and_deterministic():
    evidence = anthropic_capability_evidence()

    assert evidence["schema_version"] == (ANTHROPIC_CAPABILITY_EVIDENCE_SCHEMA_VERSION)
    assert evidence["provider_kind"] == "anthropic"
    assert evidence["support_status"] == "technical_preview"
    assert "count_tokens" in evidence["exact_normalized_features"]
    blocked = {
        row["semantic"]: row["reason_id"] for row in evidence["blocked_semantics"]
    }
    assert blocked["hosted_provider_tools"] == (
        "anthropic_hosted_tools_not_admitted_v1"
    )
    assert blocked["reasoning_controls_and_summaries"] == (
        "anthropic_reasoning_not_admitted_v1"
    )
    assert blocked["structured_output"] == (
        "anthropic_structured_output_not_admitted_v1"
    )
    serialized = json.dumps(evidence, sort_keys=True)
    assert serialized == json.dumps(anthropic_capability_evidence(), sort_keys=True)
    assert "credential" not in serialized
    assert "prompt" not in serialized
