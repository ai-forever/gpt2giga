import json
from datetime import datetime, timezone

import pytest

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.openai import OpenAIProtocolAdapter


def test_openai_adapter_maps_chat_payload_to_normalized_request():
    adapter = OpenAIProtocolAdapter()
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )

    normalized = adapter.chat_to_normalized(
        {
            "model": "GigaChat-2-Max",
            "stream": True,
            "messages": [
                {"role": "system", "content": "Be concise."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,AA==",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
            "temperature": 0.3,
            "top_p": 0.8,
            "max_completion_tokens": 128,
            "stop": ["</done>"],
            "metadata": {"scenario": "test"},
            "extra_body": {"profanity_check": False},
        },
        context=context,
    )

    payload = normalized.to_json_dict()

    assert payload["id"] == "req-1"
    assert payload["model"] == "GigaChat-2-Max"
    assert payload["stream"] is True
    assert payload["messages"][1]["content"][1]["type"] == "image_url"
    assert payload["messages"][1]["content"][1]["detail"] == "low"
    assert payload["generation_config"] == {
        "temperature": 0.3,
        "top_p": 0.8,
        "max_tokens": 128,
        "stop": ["</done>"],
        "raw_extensions": {},
        "provider_metadata": {},
    }
    assert payload["metadata"] == {"scenario": "test"}
    assert payload["provider_metadata"] == {
        "gigachat": {"additional_fields": {"profanity_check": False}}
    }
    json.dumps(payload)


def test_openai_adapter_maps_tools_tool_choice_and_response_format():
    adapter = OpenAIProtocolAdapter()

    normalized = adapter.chat_to_normalized(
        {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": "lookup"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Lookup data.",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "lookup"}},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "answer",
                    "schema": {"type": "object", "properties": {}},
                    "strict": True,
                },
            },
        }
    )

    payload = normalized.to_json_dict()

    assert payload["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup data.",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            "raw_extensions": {},
            "provider_metadata": {},
        }
    ]
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "lookup"},
    }
    assert payload["response_format"]["json_schema"]["name"] == "answer"


def test_openai_adapter_preserves_message_tool_calls_and_unknown_extensions():
    adapter = OpenAIProtocolAdapter()

    normalized = adapter.chat_to_normalized(
        {
            "model": "GigaChat",
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"q":"ping"}',
                                "extra": "kept",
                            },
                        }
                    ],
                    "functions_state_id": "state-1",
                }
            ],
            "custom_flag": "on",
            "additional_fields": {"storage": {"mode": "session"}},
        }
    )

    payload = normalized.to_json_dict()

    assert payload["messages"][0]["tool_calls"][0]["name"] == "lookup"
    assert payload["messages"][0]["tool_calls"][0]["raw_extensions"] == {
        "function": {"extra": "kept"}
    }
    assert payload["messages"][0]["raw_extensions"] == {"functions_state_id": "state-1"}
    assert payload["provider_metadata"] == {
        "gigachat": {
            "additional_fields": {
                "custom_flag": "on",
                "storage": {"mode": "session"},
            }
        }
    }


@pytest.mark.asyncio
async def test_openai_adapter_async_entrypoint_matches_chat_converter():
    adapter = OpenAIProtocolAdapter()
    payload = {
        "model": "GigaChat",
        "messages": [{"role": "user", "content": "hello"}],
        "user": "user-1",
    }

    normalized = await adapter.to_normalized(payload)

    assert normalized.operation == "chat"
    assert normalized.user == "user-1"


def test_openai_adapter_reuses_chat_compatibility_policy():
    adapter = OpenAIProtocolAdapter()

    with pytest.raises(ClientCompatibilityError) as exc_info:
        adapter.chat_to_normalized(
            {
                "model": "GigaChat",
                "messages": [{"role": "user", "content": "hello"}],
                "n": 2,
            }
        )

    assert exc_info.value.param == "n"
