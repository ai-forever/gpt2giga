import json
from pathlib import Path

import pytest

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.protocols.normalized.models import NormalizedToolKind
from gpt2giga.protocols.openai import OpenAIProtocolAdapter


CORPUS_ROOT = Path(__file__).parents[1] / "corpora" / "bridge" / "v1"


def _corpus_request(name: str) -> dict:
    fixture = json.loads(CORPUS_ROOT.joinpath(name).read_text(encoding="utf-8"))
    return fixture["request"]["body"]


def test_responses_adapter_decodes_pinned_codex_request() -> None:
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        _corpus_request("codex_responses_sequence.json")
    )

    assert normalized.protocol == "openai"
    assert normalized.operation == "responses"
    assert normalized.model == "bridge/codex-test"
    assert normalized.stream is True
    assert normalized.messages[0].role == "system"
    assert normalized.messages[0].content == "Be concise."
    assert normalized.messages[1].role == "user"
    assert normalized.messages[1].to_json_dict()["content"] == [
        {
            "type": "text",
            "text": "Reply with one short sentence.",
            "raw_extensions": {},
            "provider_metadata": {},
        }
    ]
    assert normalized.tools[0].name == "weather"
    assert normalized.tools[0].parameters["required"] == ["city"]
    assert normalized.tools[0].raw_extensions == {"function": {"strict": True}}
    assert normalized.raw_extensions == {}
    assert normalized.provider_metadata == {}


def test_responses_adapter_preserves_ordered_messages_calls_and_results() -> None:
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        {
            "model": "bridge/codex-test",
            "instructions": "Follow policy.",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Weather?"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_fixture_1",
                    "name": "weather",
                    "arguments": '{"city":"Moscow"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_fixture_1",
                    "output": '{"temperature":20}',
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "20 C"}],
                },
            ],
        }
    )

    assert [message.role for message in normalized.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert normalized.messages[2].tool_calls[0].model_dump(
        exclude={"raw_extensions", "provider_metadata"}
    ) == {
        "id": "call_fixture_1",
        "type": "function",
        "name": "weather",
        "arguments": '{"city":"Moscow"}',
    }
    assert normalized.messages[3].tool_call_id == "call_fixture_1"
    assert normalized.messages[3].content == '{"temperature":20}'


def test_responses_adapter_decodes_json_schema_and_named_tool_choice() -> None:
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        {
            "model": "bridge/codex-test",
            "input": "Return JSON.",
            "tool_choice": {"type": "function", "name": "answer"},
            "tools": [
                {
                    "type": "function",
                    "name": "answer",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "answer",
                    "schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                    "strict": True,
                }
            },
        }
    )

    assert normalized.tool_choice == {
        "type": "function",
        "function": {"name": "answer"},
    }
    assert normalized.response_format is not None
    assert normalized.response_format.type == "json_schema"
    assert normalized.response_format.json_schema == {
        "name": "answer",
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        "strict": True,
    }


@pytest.mark.parametrize(
    ("tool", "expected_configuration"),
    [
        (
            {
                "type": "web_search_preview",
                "search_context_size": "high",
                "user_location": {"type": "approximate", "country": "RU"},
            },
            {
                "search_context_size": "high",
                "user_location": {"type": "approximate", "country": "RU"},
            },
        ),
        (
            {
                "type": "code_interpreter",
                "container": {"type": "auto", "file_ids": ["file-1"]},
            },
            {"container": {"type": "auto", "file_ids": ["file-1"]}},
        ),
        (
            {
                "type": "image_generation",
                "output_format": "png",
                "quality": "high",
                "size": "1024x1024",
            },
            {
                "output_format": "png",
                "quality": "high",
                "size": "1024x1024",
            },
        ),
        (
            {
                "type": "computer_use_preview",
                "display_height": 768,
                "display_width": 1024,
                "environment": "browser",
            },
            {
                "display_height": 768,
                "display_width": 1024,
                "environment": "browser",
            },
        ),
        (
            {
                "type": "file_search",
                "vector_store_ids": ["vs-1"],
                "max_num_results": 10,
            },
            {"vector_store_ids": ["vs-1"], "max_num_results": 10},
        ),
    ],
)
def test_responses_adapter_decodes_known_hosted_tools_before_admission(
    tool: dict,
    expected_configuration: dict,
) -> None:
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        {
            "model": "bridge/codex-test",
            "input": "Use the tool.",
            "tools": [tool],
        }
    )

    assert len(normalized.tools) == 1
    assert normalized.tools[0].kind is NormalizedToolKind.HOSTED
    assert normalized.tools[0].type == tool["type"]
    assert normalized.tools[0].name is None
    assert normalized.tools[0].configuration == expected_configuration


def test_responses_adapter_preserves_versioned_hosted_tool_alias_and_choice() -> None:
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        {
            "model": "bridge/codex-test",
            "input": "Search.",
            "tools": [{"type": "web_search_preview_2025_03_11"}],
            "tool_choice": {"type": "web_search_preview_2025_03_11"},
        }
    )

    assert normalized.tools[0].kind is NormalizedToolKind.HOSTED
    assert normalized.tools[0].type == "web_search_preview_2025_03_11"
    assert normalized.tool_choice == {"type": "web_search_preview_2025_03_11"}


def test_responses_adapter_preserves_namespace_and_nested_function_tools() -> None:
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        {
            "model": "bridge/codex-test",
            "input": "Open the page.",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__playwright",
                    "description": "Browser tools.",
                    "tools": [
                        {
                            "type": "function",
                            "name": "browser_navigate",
                            "description": "Navigate to a URL.",
                            "parameters": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                            },
                            "strict": True,
                        }
                    ],
                }
            ],
        }
    )

    namespace = normalized.tools[0]
    nested = namespace.configuration["tools"][0]
    assert namespace.kind is NormalizedToolKind.NAMESPACE
    assert namespace.name == "mcp__playwright"
    assert namespace.description == "Browser tools."
    assert nested["kind"] == "function"
    assert nested["name"] == "browser_navigate"
    assert nested["raw_extensions"] == {"function": {"strict": True}}


@pytest.mark.parametrize(
    "field",
    [
        "api_key",
        "base_url",
        "background",
        "conversation",
        "include",
        "parallel_tool_calls",
        "previous_response_id",
        "provider",
        "reasoning",
        "reasoning_effort",
        "store",
        "web_search_options",
    ],
)
def test_responses_adapter_rejects_unsupported_semantics(field: str) -> None:
    payload = {
        "model": "bridge/codex-test",
        "input": "hello",
        field: True
        if field in {"background", "parallel_tool_calls", "store"}
        else "fixture",
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        OpenAIProtocolAdapter().responses_to_normalized(payload)

    assert exc_info.value.code == "unsupported_semantic"
    assert exc_info.value.param == field
    assert exc_info.value.message == (
        "The selected bridge route cannot preserve this semantic."
    )


@pytest.mark.parametrize(
    ("payload", "param"),
    [
        ({"input": "hello"}, "model"),
        ({"model": "bridge/codex-test"}, "input"),
        (
            {"model": "bridge/codex-test", "input": 42},
            "input",
        ),
        (
            {
                "model": "bridge/codex-test",
                "input": "hello",
                "tools": [{"type": "unknown_hosted_tool"}],
            },
            "tools[0].type",
        ),
        (
            {
                "model": "bridge/codex-test",
                "input": "hello",
                "tools": [{"type": "code_interpreter"}],
            },
            "tools[0].container",
        ),
        (
            {
                "model": "bridge/codex-test",
                "input": "hello",
                "text": {"format": {"type": "json_object"}},
            },
            "text.format.type",
        ),
    ],
)
def test_responses_adapter_rejects_malformed_or_unadmitted_shapes(
    payload: dict,
    param: str,
) -> None:
    with pytest.raises(ClientCompatibilityError) as exc_info:
        OpenAIProtocolAdapter().responses_to_normalized(payload)

    assert exc_info.value.param == param
    assert exc_info.value.code in {"invalid_request", "unsupported_semantic"}


async def test_responses_adapter_async_entrypoint_is_explicit() -> None:
    adapter = OpenAIProtocolAdapter()
    payload = {"model": "bridge/codex-test", "input": "hello"}

    normalized = await adapter.responses_to_normalized_async(payload)

    assert normalized.operation == "responses"
    assert normalized.messages[0].content == "hello"
