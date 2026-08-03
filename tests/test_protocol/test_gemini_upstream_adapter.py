import base64
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import pytest

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedImageReference,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTokenLimits,
    NormalizedTool,
    NormalizedToolCall,
    UnsupportedSemanticLossError,
)
from gpt2giga.providers.gemini import (
    GeminiProviderAdapter,
    gemini_upstream_profile,
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
    return gemini_upstream_profile(
        profile_id="gemini-fixture",
        revision="fixture-r1",
        base_url="https://upstream.invalid/v1beta",
        model="gemini-fixture",
        features=features,
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
        credential_reference_id="a" * 64 if credential else None,
        network_policy_ref="egress:fixture",
        timeout_seconds=2.0,
        max_inline_image_bytes=64,
    )


def _request(*, stream=False):
    image = base64.b64encode(b"fixture-image").decode()
    return NormalizedChatRequest(
        protocol="gemini",
        model="gemini-fixture",
        stream=stream,
        messages=[
            NormalizedMessage(role="system", content="Be concise."),
            NormalizedMessage(
                role="user",
                content=[
                    NormalizedContentPart(type="text", text="Inspect this."),
                    NormalizedContentPart(
                        type="image_reference",
                        image_reference=NormalizedImageReference(
                            source="data_url",
                            uri=f"data:image/png;base64,{image}",
                            mime_type="image/png",
                        ),
                    ),
                ],
            ),
            NormalizedMessage(
                role="assistant",
                tool_calls=[
                    NormalizedToolCall(
                        id="call-1",
                        name="lookup",
                        arguments={"q": "ping"},
                    )
                ],
            ),
            NormalizedMessage(
                role="tool",
                name="lookup",
                tool_call_id="call-1",
                content=json.dumps({"value": "pong"}),
            ),
        ],
        tools=[
            NormalizedTool(
                name="lookup",
                description="Look up a value.",
                parameters={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            )
        ],
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        response_format=NormalizedResponseFormat(
            type="json_schema",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        ),
        generation_config=NormalizedGenerationConfig(
            temperature=0.2,
            top_p=0.8,
            max_tokens=128,
            stop=["END"],
            seed=7,
        ),
    )


def _all_downstream_capabilities():
    return frozenset(BridgeFeature)


def _fake_app():
    app = FastAPI()
    app.state.requests = []

    @app.post("/v1beta/models/gemini-fixture:generateContent")
    async def generate(request: Request):
        payload = await request.json()
        app.state.requests.append(
            {
                "path": request.url.path,
                "api_key": request.headers.get("x-goog-api-key"),
                "payload": payload,
            }
        )
        return JSONResponse(
            {
                "responseId": "gemini-response-1",
                "modelVersion": "gemini-fixture-001",
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "Checking."},
                                {
                                    "functionCall": {
                                        "id": "call-2",
                                        "name": "lookup",
                                        "args": {"q": "next"},
                                    }
                                },
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 10,
                },
            }
        )

    return app


async def test_adapter_executes_text_image_tools_and_json_schema_through_fake_server():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = GeminiProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    response = await adapter.complete(
        _request(),
        downstream=DownstreamProtocol.GEMINI,
        downstream_capabilities=_all_downstream_capabilities(),
        input_token_count=7,
    )
    await client.aclose()

    assert response.id == "gemini-response-1"
    assert response.model == "gemini-fixture-001"
    assert response.provider == "gemini-fixture"
    assert response.choices[0].message.content == "Checking."
    assert response.choices[0].message.tool_calls[0].model_dump(
        exclude={"raw_extensions", "provider_metadata"}
    ) == {
        "id": "call-2",
        "type": "function",
        "name": "lookup",
        "arguments": {"q": "next"},
    }
    assert response.choices[0].stop_reason == "stop"
    assert response.usage.model_dump(
        exclude={"raw_extensions", "provider_metadata"}
    ) == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    assert response.provider_metadata["gemini"] == {
        "profile_id": "gemini-fixture",
        "profile_revision": "fixture-r1",
        "dialect": "gemini-generate-content-v1beta",
        "admission_schema_version": "gigaloom.protocol-bridge-admission.v1",
    }

    recorded = app.state.requests[0]
    assert recorded["path"] == "/v1beta/models/gemini-fixture:generateContent"
    assert recorded["api_key"] == "secret-value-canary"
    payload = recorded["payload"]
    assert payload["systemInstruction"] == {"parts": [{"text": "Be concise."}]}
    assert payload["contents"][0]["parts"][1] == {
        "inlineData": {
            "mimeType": "image/png",
            "data": base64.b64encode(b"fixture-image").decode(),
        }
    }
    assert payload["contents"][1]["parts"][0]["functionCall"] == {
        "id": "call-1",
        "name": "lookup",
        "args": {"q": "ping"},
    }
    assert payload["contents"][2]["parts"][0]["functionResponse"] == {
        "id": "call-1",
        "name": "lookup",
        "response": {"value": "pong"},
    }
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "lookup"
    assert payload["toolConfig"] == {
        "functionCallingConfig": {
            "mode": "ANY",
            "allowedFunctionNames": ["lookup"],
        }
    }
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseJsonSchema"]["required"] == ["answer"]
    assert payload["generationConfig"]["maxOutputTokens"] == 128
    assert [intent.purpose for intent in network.intents] == [
        "provider.gemini.generate-content"
    ]
    assert "secret-value-canary" not in repr(adapter)
    assert "secret-value-canary" not in repr(network.intents[0])
    assert network.authorizations[0].request_validations
    assert network.authorizations[0].response_validations


async def test_semantic_and_model_admission_reject_before_network():
    app = _fake_app()
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = GeminiProviderAdapter(
        _profile(features={BridgeFeature.TEXT}),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    with pytest.raises(UnsupportedSemanticLossError, match="lacks"):
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    with pytest.raises(ValueError, match="model does not match"):
        await adapter.complete(
            _request().model_copy(update={"model": "unreviewed-model"}),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert network.intents == []
    assert app.state.requests == []


def test_profile_requires_exact_credential_and_reviewed_client_policies():
    profile = _profile()
    network = _NetworkAuthorizer()

    with pytest.raises(ValueError, match="credential is unresolved"):
        GeminiProviderAdapter(
            profile,
            credential=None,
            authorize_network=network,
        )
    with pytest.raises(ValueError, match="unreferenced.*credential"):
        GeminiProviderAdapter(
            _profile(credential=False),
            credential="not-referenced",
            authorize_network=network,
        )
    with pytest.raises(ValueError, match="injected HTTP client"):
        GeminiProviderAdapter(
            _profile(credential=False).model_copy(
                update={"tls_policy_ref": "tls:custom"}
            ),
            credential=None,
            authorize_network=network,
        )
