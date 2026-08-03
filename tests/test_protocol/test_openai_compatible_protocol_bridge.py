import json

import httpx
import pytest

from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.gemini import (
    GeminiProtocolAdapter,
    normalized_chat_response_to_gemini,
    normalized_stream_event_to_gemini_sse,
)
from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedTokenLimits,
    UnsupportedSemanticLossError,
)
from gpt2giga.protocols.openai import (
    OpenAIProtocolAdapter,
    normalized_chat_response_to_openai,
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_sse,
)
from gpt2giga.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    openai_compatible_profile,
)


class _Authorization:
    def __init__(self, intent):
        self.max_response_bytes = intent.max_response_bytes
        self.peer_validation_required = False

    def validate_request_body(self, *, body_bytes, body_sha256):
        assert body_bytes > 0
        assert body_sha256

    def validate_connected_peer(self, address):
        raise AssertionError(f"unexpected peer validation: {address}")

    def validate_response_body(self, *, body_bytes):
        assert body_bytes <= self.max_response_bytes


class _NetworkAuthorizer:
    def __init__(self):
        self.intents = []

    def __call__(self, intent):
        self.intents.append(intent)
        return _Authorization(intent)


def _profile():
    return openai_compatible_profile(
        profile_id="hermetic-vllm",
        revision="closure-r1",
        config_revision=f"sha256:{'3' * 64}",
        public_alias="openai/hermetic-vllm",
        base_url="https://upstream.invalid/v1",
        model="fixture-model",
        capability_profile="openai-hermetic-v1",
        loss_matrix_revision=f"sha256:{'4' * 64}",
        features=frozenset(BridgeFeature),
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
        network_policy_ref="egress:hermetic-closure",
        timeout_seconds=2.0,
    )


def _request_payload(downstream, *, stream=False):
    tool = {
        "name": "lookup",
        "description": "Look up a value.",
        "schema": {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        },
    }
    if downstream is DownstreamProtocol.OPENAI:
        return {
            "model": "fixture-model",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Look up ping."},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["schema"],
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": tool["name"]},
            },
            "max_tokens": 64,
            "stream": stream,
        }
    if downstream is DownstreamProtocol.ANTHROPIC:
        return {
            "model": "fixture-model",
            "system": "Be concise.",
            "messages": [{"role": "user", "content": "Look up ping."}],
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["schema"],
                }
            ],
            "tool_choice": {"type": "tool", "name": tool["name"]},
            "max_tokens": 64,
            "stream": stream,
        }
    return {
        "systemInstruction": {"parts": [{"text": "Be concise."}]},
        "contents": [{"role": "user", "parts": [{"text": "Look up ping."}]}],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["schema"],
                    }
                ]
            }
        ],
        "toolConfig": {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": [tool["name"]],
            }
        },
        "generationConfig": {"maxOutputTokens": 64},
    }


def _to_normalized(downstream, *, stream=False):
    payload = _request_payload(downstream, stream=stream)
    if downstream is DownstreamProtocol.OPENAI:
        return OpenAIProtocolAdapter().chat_to_normalized(payload)
    if downstream is DownstreamProtocol.ANTHROPIC:
        return AnthropicProtocolAdapter().messages_to_normalized(payload)
    return GeminiProtocolAdapter().generate_content_to_normalized(
        payload,
        model="fixture-model",
        stream=stream,
    )


def _project_response(downstream, response):
    if downstream is DownstreamProtocol.OPENAI:
        return normalized_chat_response_to_openai(
            response,
            requested_model="fixture-model",
        )
    if downstream is DownstreamProtocol.ANTHROPIC:
        return normalized_chat_response_to_anthropic(
            response,
            requested_model="fixture-model",
        )
    return normalized_chat_response_to_gemini(
        response,
        requested_model="fixture-model",
    )


def _assert_tool_response(downstream, payload):
    if downstream is DownstreamProtocol.OPENAI:
        call = payload["choices"][0]["message"]["tool_calls"][0]
        assert call["function"]["name"] == "lookup"
        assert payload["usage"]["total_tokens"] == 10
    elif downstream is DownstreamProtocol.ANTHROPIC:
        call = payload["content"][0]
        assert call["type"] == "tool_use"
        assert call["name"] == "lookup"
        assert payload["usage"]["input_tokens"] == 7
    else:
        call = payload["candidates"][0]["content"]["parts"][0]["functionCall"]
        assert call["name"] == "lookup"
        assert payload["usageMetadata"]["totalTokenCount"] == 10


@pytest.mark.parametrize("downstream", list(DownstreamProtocol))
async def test_three_wire_protocols_execute_the_same_hermetic_upstream_workload(
    downstream,
):
    observed = []

    async def handler(request):
        observed.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-closure",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "fixture-model",
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
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    network = _NetworkAuthorizer()
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential=None,
        authorize_network=network,
        http_client=client,
    )

    response = await adapter.complete(
        _to_normalized(downstream),
        downstream=downstream,
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=7,
    )
    projected = _project_response(downstream, response)
    await client.aclose()

    assert len(observed) == 1
    assert observed[0]["model"] == "fixture-model"
    assert observed[0]["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Look up ping."},
    ]
    assert observed[0]["tools"][0]["function"]["name"] == "lookup"
    assert observed[0]["tool_choice"]["function"]["name"] == "lookup"
    assert observed[0]["max_tokens"] == 64
    assert len(network.intents) == 1
    _assert_tool_response(downstream, projected)


def _stream_body():
    chunks = [
        {
            "id": "chatcmpl-stream",
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hel"},
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
                    "delta": {"content": "lo"},
                    "finish_reason": "stop",
                }
            ],
        },
        {
            "id": "chatcmpl-stream",
            "model": "fixture-model",
            "choices": [],
            "usage": {"prompt_tokens": 2},
        },
    ]
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + (
        "data: [DONE]\n\n"
    )


def _project_stream(downstream, events):
    if downstream is DownstreamProtocol.OPENAI:
        frames = [
            frame
            for event in events
            if (
                frame := normalized_stream_event_to_openai_sse(
                    event,
                    requested_model="fixture-model",
                    response_id="closure-stream",
                )
            )
            is not None
        ]
        frames.append(normalized_stream_done_sse())
        return "".join(frames)
    if downstream is DownstreamProtocol.ANTHROPIC:
        projector = AnthropicStreamProjector(
            requested_model="fixture-model",
            response_id="closure-stream",
        )
        return "".join(frame for event in events for frame in projector.project(event))
    return "".join(
        frame
        for event in events
        if (
            frame := normalized_stream_event_to_gemini_sse(
                event,
                requested_model="fixture-model",
                response_id="closure-stream",
            )
        )
        is not None
    )


@pytest.mark.parametrize("downstream", list(DownstreamProtocol))
async def test_three_wire_protocols_project_streaming_and_partial_usage_truthfully(
    downstream,
):
    async def handler(_request):
        return httpx.Response(
            200,
            text=_stream_body(),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    events = [
        event
        async for event in adapter.stream_chat(
            _to_normalized(downstream, stream=True),
            downstream=downstream,
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=2,
        )
    ]
    wire = _project_stream(downstream, events)
    await client.aclose()

    assert [event.type for event in events] == [
        "message_start",
        "content_delta",
        "content_delta",
        "message_end",
        "usage",
    ]
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 2
    assert events[-1].usage.output_tokens is None
    assert "Hel" in wire
    assert "lo" in wire
    if downstream is DownstreamProtocol.OPENAI:
        assert "data: [DONE]" in wire
        assert '"completion_tokens": null' in wire
    elif downstream is DownstreamProtocol.ANTHROPIC:
        assert "event: message_stop" in wire
    else:
        assert '"candidates": []' in wire
        assert '"promptTokenCount": 2' in wire


@pytest.mark.parametrize(
    ("feature", "normalized"),
    [
        (
            BridgeFeature.IMAGE_REFERENCES,
            OpenAIProtocolAdapter().chat_to_normalized(
                {
                    "model": "fixture-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Inspect."},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "data:image/png;base64,AA=="},
                                },
                            ],
                        }
                    ],
                }
            ),
        ),
        (
            BridgeFeature.JSON_SCHEMA_OUTPUT,
            GeminiProtocolAdapter().generate_content_to_normalized(
                {
                    "contents": [{"parts": [{"text": "Answer."}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": {"type": "object"},
                    },
                },
                model="fixture-model",
            ),
        ),
        (
            BridgeFeature.TOOL_CHOICE,
            GeminiProtocolAdapter().generate_content_to_normalized(
                _request_payload(DownstreamProtocol.GEMINI),
                model="fixture-model",
            ),
        ),
    ],
)
async def test_conditional_image_schema_and_tool_choice_loss_fails_before_io(
    feature,
    normalized,
):
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        raise AssertionError("semantic loss reached the transport")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    network = _NetworkAuthorizer()
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential=None,
        authorize_network=network,
        http_client=client,
    )
    downstream = (
        DownstreamProtocol.GEMINI
        if feature in {BridgeFeature.JSON_SCHEMA_OUTPUT, BridgeFeature.TOOL_CHOICE}
        else DownstreamProtocol.OPENAI
    )

    with pytest.raises(UnsupportedSemanticLossError, match=feature.value):
        await adapter.complete(
            normalized,
            downstream=downstream,
            downstream_capabilities=frozenset(BridgeFeature) - {feature},
            input_token_count=2,
        )
    await client.aclose()

    assert calls == 0
    assert network.intents == []
