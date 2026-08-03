import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import pytest

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedTokenLimits,
    NormalizedTool,
    NormalizedToolCall,
    UnsupportedSemanticLossError,
)
from gpt2giga.providers.anthropic import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_IMPLEMENTED_FEATURES_V1,
    AnthropicProviderAdapter,
    AnthropicUnsupportedSemanticError,
    AnthropicUpstreamError,
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

    return app


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


async def test_profile_and_adapter_reject_unreviewed_authority():
    with pytest.raises(ValueError, match="credential"):
        AnthropicProviderAdapter(
            _profile(),
            credential=None,
            authorize_network=_NetworkAuthorizer(),
        )
    with pytest.raises(ValueError, match="unsupported features"):
        _profile(features={BridgeFeature.IMAGE_REFERENCES})
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
