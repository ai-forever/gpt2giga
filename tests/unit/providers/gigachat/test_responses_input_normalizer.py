import pytest
from loguru import logger

from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.providers.gigachat.request_mapping_base import (
    RequestTransformerBaseMixin,
)
from gpt2giga.providers.gigachat.responses.input_normalizer import (
    ResponsesV2InputNormalizerMixin,
)


class DummyResponsesInputNormalizer(
    ResponsesV2InputNormalizerMixin,
    RequestTransformerBaseMixin,
):
    def __init__(self) -> None:
        self.config = ProxyConfig()
        self.logger = logger
        self.attachment_processor = None


def test_repair_response_v2_input_history_backfills_matching_tool_result_metadata():
    normalizer = DummyResponsesInputNormalizer()

    repaired = normalizer._repair_response_v2_input_history(
        [
            {
                "role": "assistant",
                "content": "",
                "function_call": {
                    "name": "sum",
                    "arguments": '{"a": 1}',
                },
                "tool_call_id": "call-1",
            },
            {
                "role": "tool",
                "content": '{"ok": true}',
            },
        ]
    )

    assert repaired[1]["name"] == "sum"
    assert repaired[1]["tool_call_id"] == "call-1"


def test_repair_response_v2_input_history_inserts_synthetic_tool_result_midstream():
    normalizer = DummyResponsesInputNormalizer()

    repaired = normalizer._repair_response_v2_input_history(
        [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd": "pwd"}',
                "call_id": "call-1",
            },
            {
                "role": "user",
                "content": "continue",
            },
        ]
    )

    assert repaired[1] == {
        "role": "tool",
        "name": "exec_command",
        "content": {
            "status": "interrupted",
            "error": {
                "type": "missing_tool_result",
                "message": "Tool result missing from client-supplied history.",
            },
        },
        "tool_call_id": "call-1",
    }
    assert repaired[2] == {"role": "user", "content": "continue"}


@pytest.mark.asyncio
async def test_build_response_v2_content_parts_keeps_multimodal_parts_and_fallback_tool():
    normalizer = DummyResponsesInputNormalizer()

    parts = await normalizer._build_response_v2_content_parts(
        [
            {"type": "input_text", "text": "hello"},
            {"type": "input_file", "file_id": "file-1"},
            {"type": "input_image", "file_id": "img-1"},
            {"type": "function_call_output", "output": "done"},
            {"type": "refusal", "refusal": "denied"},
        ],
        fallback_function_name="run_shell_command",
    )

    assert parts == [
        {
            "text": "hello",
            "files": [{"id": "file-1"}, {"id": "img-1"}],
        },
        {
            "function_result": {
                "name": "run_shell_command",
                "result": {"output": "done"},
            }
        },
        {"text": "denied"},
    ]


@pytest.mark.asyncio
async def test_build_response_v2_messages_collects_reasoning_chunks():
    normalizer = DummyResponsesInputNormalizer()

    messages = await normalizer._build_response_v2_messages(
        {
            "input": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "step one"}],
                    "content": [{"text": "step two"}],
                }
            ]
        }
    )

    assert messages == [
        {
            "role": "assistant",
            "content": [{"text": "step one\nstep two"}],
        }
    ]
