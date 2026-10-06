"""Regression coverage for the SDK's v2 request contract."""

import pytest
from loguru import logger

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)
from gpt2giga.protocols.anthropic.adapter import AnthropicProtocolAdapter
from gpt2giga.providers.gigachat.adapter import normalized_chat_to_openai_payload


def transformer():
    return RequestTransformer(
        ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2")), logger=logger
    )


@pytest.mark.parametrize("responses", [False, True])
async def test_required_tool_choice_maps_to_v2_any_and_errors_in_v1(responses):
    payload = {
        "model": "GigaChat-3-Ultra",
        "tools": [
            {"type": "function", "function": {"name": "lookup", "parameters": {}}}
        ],
        "tool_choice": "required",
    }
    rt = transformer()
    if responses:
        payload["input"] = "Look up a room"
        request = await rt.prepare_response_chat_completion(payload)
        legacy = rt.prepare_response_chat
    else:
        payload["messages"] = [{"role": "user", "content": "Look up a room"}]
        request = await rt.prepare_chat_completion(payload)
        legacy = rt.prepare_chat
    assert request.tool_config.mode == "any"
    with pytest.raises(ClientCompatibilityError, match="v2"):
        await legacy(payload)


@pytest.mark.parametrize("normalized", [False, True])
async def test_anthropic_any_and_reasoning_budget_reach_v2(normalized):
    payload = {
        "model": "GigaChat-3-Ultra",
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": "Look up a room"}],
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        "tools": [{"name": "lookup", "input_schema": {"type": "object"}}],
    }
    if normalized:
        request = AnthropicProtocolAdapter().messages_to_normalized(payload)
        openai_payload = normalized_chat_to_openai_payload(request)
    else:
        openai_payload = _build_openai_data_from_anthropic_request(payload, logger)
    request = await transformer().prepare_chat_completion(openai_payload)
    assert request.tool_config.mode == "any"
    assert request.model_options.parallel_tool_calls is False
    assert request.model_options.max_tokens == 3000
    assert request.model_options.reasoning.max_tokens == 1024
    assert request.model_options.reasoning.effort == "low"


async def test_nested_model_options_merge_without_losing_sdk_options():
    request = await transformer().prepare_chat_completion(
        {
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.4,
            "reasoning": {"effort": "high", "max_tokens": 512},
            "additional_fields": {
                "model_options": {
                    "temperature": 0.8,
                    "max_tokens": 1024,
                    "reasoning": {"max_tokens": 256},
                    "future_option": True,
                },
                "future_request_option": "kept",
            },
        }
    )
    payload = request.model_dump(exclude_none=True, by_alias=True)
    assert payload["model_options"] == {
        "temperature": 0.4,
        "max_tokens": 1024,
        "reasoning": {"effort": "high", "max_tokens": 512},
        "future_option": True,
    }
    assert payload["future_request_option"] == "kept"


@pytest.mark.parametrize("responses", [False, True])
async def test_parallel_repeated_names_keep_result_ids_and_shared_state(responses):
    calls = [
        {
            "id": f"call_room-{i}",
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": {"room": i},
            },
        }
        for i in range(2)
    ]
    if responses:
        payload = {
            "input": [
                *[
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "tools_state_id": "call_shared-state",
                        **call["function"],
                    }
                    for call in calls
                ],
                *[
                    {
                        "type": "function_call_output",
                        "call_id": call["id"],
                        "output": "ok",
                    }
                    for call in reversed(calls)
                ],
            ]
        }
        request = await transformer().prepare_response_chat_completion(payload)
    else:
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": calls,
                    "tools_state_id": "call_shared-state",
                },
                *[
                    {"role": "tool", "tool_call_id": call["id"], "content": "ok"}
                    for call in reversed(calls)
                ],
            ]
        }
        request = await transformer().prepare_chat_completion(payload)
    function_calls = [
        part.function_call
        for msg in request.messages
        for part in msg.content
        if part.function_call
    ]
    results = [
        part.function_result
        for msg in request.messages
        for part in msg.content
        if part.function_result
    ]
    assert [call.id_ for call in function_calls] == ["call_room-0", "call_room-1"]
    assert [result.id_ for result in results] == ["call_room-1", "call_room-0"]
    assert all(
        message.tools_state_id == "call_shared-state" for message in request.messages
    )


@pytest.mark.parametrize("parallel", [True, False])
async def test_responses_v2_preserves_parallel_tool_call_setting(parallel):
    request = await transformer().prepare_response_chat_completion(
        {"input": "hello", "parallel_tool_calls": parallel}
    )
    assert request.model_options.parallel_tool_calls is parallel


@pytest.mark.parametrize("choice", ["none", "auto"])
async def test_legacy_function_choice_strings_map_to_v2_tool_config(choice):
    request = await transformer().prepare_chat_completion(
        {"messages": [{"role": "user", "content": "hello"}], "function_call": choice}
    )
    assert request.tool_config.mode == choice


@pytest.mark.parametrize("responses", [False, True])
async def test_reasoning_budget_reaches_v1_sdk(responses):
    payload = {"reasoning": {"effort": "high", "max_tokens": 512}}
    rt = transformer()
    if responses:
        payload["input"] = "hello"
        request = await rt.prepare_response_chat(payload)
    else:
        payload["messages"] = [{"role": "user", "content": "hello"}]
        request = await rt.prepare_chat(payload)
    assert request["reasoning_max_tokens"] == 512
    assert request["reasoning_effort"] == "high"


async def test_disabled_reasoning_removes_v1_extra_budget():
    request = await transformer().prepare_chat(
        {
            "messages": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "none", "max_tokens": 512},
            "extra_body": {"reasoning_max_tokens": 256},
        }
    )
    assert "reasoning_max_tokens" not in request
    assert "reasoning_max_tokens" not in (request.get("additional_fields") or {})
