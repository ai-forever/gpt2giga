import json

from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedProtocolCapabilities,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedTokenLimits,
    NormalizedToolCall,
    NormalizedUsage,
    admit_protocol_bridge_request,
)


def test_anthropic_adapter_maps_messages_tools_and_controls_to_normalized():
    normalized = AnthropicProtocolAdapter().messages_to_normalized(
        {
            "model": "claude-x",
            "system": [{"type": "text", "text": "Be concise."}],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Inspect this."},
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.test/image.png",
                            },
                        },
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "lookup",
                            "input": {"q": "ping"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu-1",
                            "content": [{"type": "text", "text": "pong"}],
                        },
                        {"type": "text", "text": "Continue."},
                    ],
                },
            ],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Lookup data",
                    "input_schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                }
            ],
            "tool_choice": {
                "type": "tool",
                "name": "lookup",
                "disable_parallel_tool_use": True,
            },
            "max_tokens": 128,
            "temperature": 0.2,
            "stop_sequences": ["DONE"],
            "metadata": {"user_id": "opaque"},
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "name": "answer",
                    "schema": {"type": "object"},
                    "strict": True,
                }
            },
            "extra_body": {"profanity_check": False},
        }
    )

    assert normalized.protocol == "anthropic"
    assert normalized.model == "claude-x"
    assert [message.role for message in normalized.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "user",
    ]
    image = normalized.messages[1].content[1].image_reference
    assert image is not None
    assert image.uri == "https://example.test/image.png"
    assert normalized.messages[2].tool_calls[0].arguments == {"q": "ping"}
    assert normalized.messages[3].tool_call_id == "toolu-1"
    assert json.loads(normalized.messages[3].content) == {"result": "pong"}
    assert normalized.tools[0].name == "lookup"
    assert normalized.tool_choice == {
        "type": "function",
        "function": {"name": "lookup"},
    }
    assert normalized.parallel_tool_calls is False
    assert normalized.generation_config.max_tokens == 128
    assert normalized.generation_config.stop == ["DONE"]
    assert normalized.response_format.json_schema["name"] == "answer"
    assert normalized.metadata == {"user_id": "opaque"}
    assert normalized.provider_metadata == {
        "gigachat": {"additional_fields": {"profanity_check": False}}
    }


def test_anthropic_adapter_maps_provider_tools_only_when_enabled():
    payload = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "search"}],
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }
        ],
        "tool_choice": {"type": "tool", "name": "web_search"},
    }
    adapter = AnthropicProtocolAdapter()

    enabled = adapter.messages_to_normalized(payload)
    disabled = adapter.messages_to_normalized(
        payload,
        builtin_tool_mapping_enabled=False,
    )

    assert [(tool.type, tool.name) for tool in enabled.tools] == [
        ("web_search", "web_search")
    ]
    assert enabled.tool_choice == {"type": "web_search"}
    assert disabled.tools == []
    assert disabled.tool_choice == {
        "type": "function",
        "function": {"name": "web_search"},
    }


def test_anthropic_adapter_builds_normalized_count_tokens_request():
    normalized = AnthropicProtocolAdapter().count_tokens_to_normalized(
        {
            "model": "claude-x",
            "messages": [{"role": "user", "content": "count me"}],
        }
    )

    assert normalized.protocol == "anthropic"
    assert normalized.operation == "count_tokens"
    assert normalized.model == "claude-x"
    assert normalized.input.stream is False
    assert normalized.input.messages[0].content == "count me"


def test_anthropic_adapter_output_is_admissible_for_reviewed_bridge_subset():
    normalized = AnthropicProtocolAdapter().messages_to_normalized(
        {
            "model": "local-model",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "name": "lookup",
                    "input_schema": {"type": "object"},
                }
            ],
            "tool_choice": {"type": "tool", "name": "lookup"},
        }
    )

    admission = admit_protocol_bridge_request(
        normalized,
        downstream=DownstreamProtocol.ANTHROPIC,
        upstream=NormalizedProtocolCapabilities(
            profile="local-openai-compatible",
            features=frozenset(BridgeFeature),
            limits=NormalizedTokenLimits(
                context_window=8192,
                max_input_tokens=6144,
                max_output_tokens=2048,
            ),
        ),
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=8,
    )

    assert admission.downstream is DownstreamProtocol.ANTHROPIC
    assert BridgeFeature.FUNCTION_TOOLS in admission.required_features
    assert BridgeFeature.TOOL_CHOICE in admission.required_features


def test_anthropic_response_adapter_preserves_text_tools_usage_and_stop_reason():
    payload = normalized_chat_response_to_anthropic(
        NormalizedResponse(
            id="response-1",
            model="GigaChat",
            choices=[
                NormalizedChoice(
                    message=NormalizedMessage(
                        role="assistant",
                        content="Checking.",
                        tool_calls=[
                            NormalizedToolCall(
                                id="toolu-1",
                                name="lookup",
                                arguments={"q": "ping"},
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=NormalizedUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            ),
        ),
        requested_model="claude-x",
    )

    assert payload == {
        "id": "msg_response-1",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Checking."},
            {
                "type": "tool_use",
                "id": "toolu-1",
                "name": "lookup",
                "input": {"q": "ping"},
            },
        ],
        "model": "claude-x",
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_anthropic_response_adapter_preserves_error_shape():
    payload = normalized_chat_response_to_anthropic(
        NormalizedResponse(
            id="request-1",
            error=NormalizedError(
                type="rate_limit_error",
                message="Slow down",
                code="rate_limit",
            ),
        ),
        requested_model="claude-x",
    )

    assert payload == {
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": "Slow down",
            "code": "rate_limit",
        },
        "request_id": "request-1",
    }


def test_anthropic_stream_projector_preserves_golden_event_order():
    projector = AnthropicStreamProjector(
        requested_model="claude-test",
        response_id="-",
    )
    events = [
        NormalizedStreamEvent(type="message_start"),
        NormalizedStreamEvent(type="content_delta", content_delta="Hel"),
        NormalizedStreamEvent(type="content_delta", content_delta="lo!"),
        NormalizedStreamEvent(
            type="message_end",
            finish_reason="stop",
            usage=NormalizedUsage(output_tokens=2),
        ),
    ]

    frames = [frame for event in events for frame in projector.project(event)]
    event_names = [frame.splitlines()[0] for frame in frames]

    assert event_names == [
        "event: message_start",
        "event: ping",
        "event: content_block_start",
        "event: content_block_delta",
        "event: content_block_delta",
        "event: content_block_stop",
        "event: message_delta",
        "event: message_stop",
    ]
    assert '"text": "Hel"' in frames[3]
    assert '"stop_reason": "end_turn"' in frames[6]
    assert '"output_tokens": 2' in frames[6]


def test_anthropic_stream_projector_maps_tool_and_error_events():
    projector = AnthropicStreamProjector(
        requested_model="claude-test",
        response_id="request-1",
    )

    tool_frames = projector.project(
        NormalizedStreamEvent(
            type="tool_call_start",
            tool_call=NormalizedToolCall(
                id="toolu-1",
                name="lookup",
                arguments='{"q":"ping"}',
            ),
        )
    )
    error_frames = projector.project(
        NormalizedStreamEvent(
            type="error",
            error=NormalizedError(
                type="rate_limit_error",
                message="Slow down",
                code="model_concurrency_limit",
            ),
        )
    )

    assert '"type": "tool_use"' in tool_frames[0]
    assert '"partial_json": "{\\"q\\":\\"ping\\"}"' in tool_frames[1]
    assert "event: error" in error_frames[0]
    assert '"type": "rate_limit_error"' in error_frames[0]


def test_anthropic_stream_projector_renders_structured_tool_as_text():
    projector = AnthropicStreamProjector(
        requested_model="claude-test",
        response_id="request-1",
        structured_output=True,
    )

    frames = projector.project(
        NormalizedStreamEvent(
            type="tool_call_start",
            tool_call=NormalizedToolCall(
                id="toolu-1",
                name="structured_output",
                arguments={"answer": 42},
            ),
        )
    )
    terminal = projector.project(
        NormalizedStreamEvent(type="message_end", finish_reason="tool_calls")
    )

    assert '"type": "text"' in frames[0]
    assert '"text": "{\\"answer\\": 42}"' in frames[1]
    assert '"stop_reason": "end_turn"' in terminal[-2]
