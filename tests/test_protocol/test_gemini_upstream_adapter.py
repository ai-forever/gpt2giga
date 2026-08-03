import base64
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
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
    ProtocolBridgeAdmission,
    UnsupportedSemanticLossError,
)
from gpt2giga.providers.gemini import (
    GeminiProtocolError,
    GeminiProviderAdapter,
    GeminiUpstreamError,
    gemini_response_to_normalized,
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


def _streaming_app(chunks):
    app = FastAPI()
    app.state.requests = []

    @app.post("/v1beta/models/gemini-fixture:streamGenerateContent")
    async def stream(request: Request):
        app.state.requests.append(
            {
                "path": request.url.path,
                "query": str(request.url.query),
                "api_key": request.headers.get("x-goog-api-key"),
                "payload": await request.json(),
            }
        )

        async def events():
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

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


async def test_adapter_streams_text_function_usage_and_one_terminal_event():
    chunks = [
        {
            "responseId": "gemini-stream-1",
            "modelVersion": "gemini-fixture-001",
            "candidates": [
                {
                    "index": 0,
                    "content": {"role": "model", "parts": [{"text": "Hel"}]},
                }
            ],
        },
        {
            "responseId": "gemini-stream-1",
            "modelVersion": "gemini-fixture-001",
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "id": "call-stream",
                                    "name": "lookup",
                                    "args": {"q": "ping"},
                                }
                            }
                        ],
                    },
                }
            ],
        },
        {
            "responseId": "gemini-stream-1",
            "modelVersion": "gemini-fixture-001",
            "candidates": [
                {
                    "index": 0,
                    "content": {"role": "model", "parts": [{"text": "lo"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 7,
                "candidatesTokenCount": 4,
                "totalTokenCount": 11,
            },
        },
    ]
    app = _streaming_app(chunks)
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = GeminiProviderAdapter(
        _profile(),
        credential="secret-value-canary",
        authorize_network=network,
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == [
        "message_start",
        "content_delta",
        "tool_call_start",
        "content_delta",
        "message_end",
        "usage",
    ]
    assert events[1].content_delta == "Hel"
    assert events[2].tool_call.id == "call-stream"
    assert events[2].tool_call.arguments == {"q": "ping"}
    assert events[3].content_delta == "lo"
    assert events[4].stop_reason == "stop"
    assert events[5].usage.total_tokens == 11
    assert len([event for event in events if event.type == "message_end"]) == 1
    recorded = app.state.requests[0]
    assert recorded["query"] == "alt=sse"
    assert recorded["api_key"] == "secret-value-canary"
    assert network.authorizations[0].response_validations


async def test_stream_projects_prompt_safety_block_as_content_filter_terminal():
    chunks = [
        {
            "promptFeedback": {
                "blockReason": "SAFETY",
                "safetyRatings": [
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "probability": "HIGH",
                        "blocked": True,
                    }
                ],
            }
        }
    ]
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == ["message_start", "message_end"]
    assert events[-1].finish_reason == "SAFETY"
    assert events[-1].stop_reason == "content_filter"
    assert events[-1].provider_metadata["gemini"]["prompt_feedback"] == {
        "block_reason": "SAFETY",
        "safety_ratings": [
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "probability": "HIGH",
                "blocked": True,
            }
        ],
    }


@pytest.mark.parametrize(
    ("status_code", "provider_status", "error_class", "retryable"),
    [
        (400, "INVALID_ARGUMENT", "invalid_request", False),
        (401, "UNAUTHENTICATED", "authentication", False),
        (403, "PERMISSION_DENIED", "permission", False),
        (429, "RESOURCE_EXHAUSTED", "rate_limit", True),
        (503, "UNAVAILABLE", "upstream", True),
        (504, "DEADLINE_EXCEEDED", "timeout", True),
    ],
)
async def test_http_errors_use_stable_safe_taxonomy(
    status_code,
    provider_status,
    error_class,
    retryable,
):
    async def handler(_request):
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "code": status_code,
                    "status": provider_status,
                    "message": "secret provider prose must not escape",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(GeminiUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    error = exc_info.value.error
    assert exc_info.value.status_code == status_code
    assert error.code == provider_status
    assert error.error_class == error_class
    assert error.retryable is retryable
    assert "secret provider prose" not in error.message


async def test_timeout_is_normalized_without_retry_or_fallback():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(GeminiUpstreamError) as exc_info:
        await adapter.complete(
            _request(),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert calls == 1
    assert exc_info.value.error.code == "timeout"
    assert exc_info.value.error.error_class == "timeout"
    assert exc_info.value.error.retryable is True


async def test_provider_native_tools_and_files_fail_before_network():
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_fake_app()))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=network,
        http_client=client,
    )
    native_tool_request = _request().model_copy(
        update={"raw_extensions": {"googleSearch": {}}}
    )
    file_request = _request().model_copy(
        update={
            "messages": [
                NormalizedMessage(
                    role="user",
                    content=[
                        NormalizedContentPart(
                            type="file",
                            data={"file_uri": "files/provider-owned"},
                        )
                    ],
                )
            ]
        }
    )

    with pytest.raises(UnsupportedSemanticLossError, match="unmodeled semantics"):
        await adapter.complete(
            native_tool_request,
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    with pytest.raises(UnsupportedSemanticLossError, match="outside normalized v1"):
        await adapter.complete(
            file_request,
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert network.intents == []


async def test_late_system_instruction_fails_before_network():
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_fake_app()))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=network,
        http_client=client,
    )
    request = _request().model_copy(
        update={
            "messages": [
                NormalizedMessage(role="user", content="First."),
                NormalizedMessage(role="system", content="Too late."),
            ]
        }
    )

    with pytest.raises(ValueError, match="must precede"):
        await adapter.complete(
            request,
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert network.intents == []


@pytest.mark.parametrize(
    "reference",
    [
        NormalizedImageReference(
            source="url",
            uri="https://images.invalid/unreviewed.png",
            mime_type="image/png",
        ),
        NormalizedImageReference(
            source="data_url",
            uri=("data:image/png;base64," + base64.b64encode(b"x" * 65).decode()),
            mime_type="image/png",
        ),
        NormalizedImageReference(
            source="data_url",
            uri="data:image/svg+xml;base64,PHN2Zy8+",
            mime_type="image/svg+xml",
        ),
    ],
)
async def test_unreviewed_image_sources_types_and_sizes_fail_before_network(reference):
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_fake_app()))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=network,
        http_client=client,
    )
    request = _request().model_copy(
        update={
            "messages": [
                NormalizedMessage(
                    role="user",
                    content=[
                        NormalizedContentPart(
                            type="image_reference",
                            image_reference=reference,
                        )
                    ],
                )
            ]
        }
    )

    with pytest.raises(ValueError):
        await adapter.complete(
            request,
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await client.aclose()

    assert network.intents == []


@pytest.mark.parametrize(
    ("chunks", "error_code"),
    [
        (
            [
                {
                    "candidates": [
                        {
                            "index": 0,
                            "content": {"parts": []},
                            "finishReason": "STOP",
                        }
                    ]
                },
                {
                    "candidates": [
                        {"index": 0, "content": {"parts": [{"text": "late"}]}}
                    ]
                },
            ],
            "stream_data_after_terminal",
        ),
        (
            [
                {
                    "usageMetadata": {
                        "promptTokenCount": 1,
                        "totalTokenCount": 1,
                    }
                }
            ],
            "usage_before_stream_terminal",
        ),
        (
            [
                {
                    "candidates": [
                        {
                            "index": 0,
                            "content": {"parts": [{"unknown": {}}]},
                        }
                    ]
                }
            ],
            "unsupported_stream_part",
        ),
    ],
)
async def test_reordered_and_unsupported_streams_end_in_protocol_error(
    chunks,
    error_code,
):
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.GEMINI,
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
    assert terminals[0].error.retryable is False


async def test_malformed_stream_json_ends_in_protocol_error():
    async def handler(_request):
        return httpx.Response(
            200,
            text="data: {not-json}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    assert events[-1].type == "error"
    assert events[-1].error.code == "invalid_stream_json"


async def test_client_loss_after_terminal_is_one_error_without_hidden_retry():
    calls = 0
    terminal = json.dumps(
        {
            "candidates": [
                {
                    "index": 0,
                    "content": {"parts": []},
                    "finishReason": "STOP",
                }
            ]
        }
    ).encode()

    class LostStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: " + terminal + b"\n\n"
            raise httpx.ReadError("fixture provider process loss")

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=LostStream(),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    ]
    await client.aclose()

    terminals = [
        event for event in events if event.type in {"message_end", "cancelled", "error"}
    ]
    assert [event.type for event in terminals] == ["error"]
    assert terminals[0].error.code == "connection_error"
    assert calls == 1


async def test_disconnect_projects_cancellation_and_stops_stream():
    chunks = [
        {"candidates": [{"index": 0, "content": {"parts": [{"text": "unobserved"}]}}]}
    ]
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_streaming_app(chunks))
    )
    network = _NetworkAuthorizer()
    adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=network,
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _request(stream=True),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
            is_disconnected=lambda: True,
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == ["message_start", "cancelled"]
    assert events[-1].stop_reason == "cancelled"
    assert network.intents == []


async def test_redirect_peer_evidence_and_response_limit_fail_closed():
    async def redirect_handler(_request):
        return httpx.Response(307, headers={"location": "https://other.invalid"})

    redirect_client = httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler))
    redirect_adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=redirect_client,
    )
    with pytest.raises(GeminiUpstreamError) as exc_info:
        await redirect_adapter.complete(
            _request(),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await redirect_client.aclose()
    assert exc_info.value.error.code == "destination_mismatch"

    peer_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_fake_app()))
    peer_adapter = GeminiProviderAdapter(
        _profile(credential=False),
        credential=None,
        authorize_network=_NetworkAuthorizer(peer_validation_required=True),
        http_client=peer_client,
    )
    with pytest.raises(GeminiUpstreamError) as exc_info:
        await peer_adapter.complete(
            _request(),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await peer_client.aclose()
    assert exc_info.value.error.code == "peer_evidence_unavailable"

    async def oversized_handler(_request):
        return httpx.Response(200, content=b"x" * 65)

    limit_profile = _profile(credential=False).model_copy(
        update={"max_response_bytes": 64}
    )
    limit_client = httpx.AsyncClient(transport=httpx.MockTransport(oversized_handler))
    limit_adapter = GeminiProviderAdapter(
        limit_profile,
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=limit_client,
    )
    with pytest.raises(GeminiUpstreamError) as exc_info:
        await limit_adapter.complete(
            _request(),
            downstream=DownstreamProtocol.GEMINI,
            downstream_capabilities=_all_downstream_capabilities(),
            input_token_count=7,
        )
    await limit_client.aclose()
    assert exc_info.value.error.code == "response_too_large"


def test_malformed_non_stream_response_raises_protocol_error():
    with pytest.raises(GeminiProtocolError) as exc_info:
        gemini_response_to_normalized(
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {"parts": [{"unknown": "shape"}]},
                        "finishReason": "STOP",
                    }
                ]
            },
            profile=_profile(credential=False),
            admission=ProtocolBridgeAdmission(
                downstream=DownstreamProtocol.GEMINI,
                upstream_profile="gemini-fixture@fixture-r1",
                required_features=(),
            ),
        )

    assert exc_info.value.error.code == "unsupported_candidate_part"


def test_non_stream_safety_candidate_without_content_is_a_filtered_choice():
    response = gemini_response_to_normalized(
        {
            "candidates": [
                {
                    "index": 0,
                    "finishReason": "SAFETY",
                    "safetyRatings": [
                        {
                            "category": "HARM_CATEGORY_HARASSMENT",
                            "probability": "HIGH",
                            "blocked": True,
                        }
                    ],
                }
            ]
        },
        profile=_profile(credential=False),
        admission=ProtocolBridgeAdmission(
            downstream=DownstreamProtocol.GEMINI,
            upstream_profile="gemini-fixture@fixture-r1",
            required_features=(),
        ),
    )

    assert response.choices[0].stop_reason == "content_filter"
    assert response.choices[0].message.content is None
    assert response.choices[0].provider_metadata["gemini"]["safety_ratings"] == [
        {
            "category": "HARM_CATEGORY_HARASSMENT",
            "probability": "HIGH",
            "blocked": True,
        }
    ]
