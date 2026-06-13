import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import gigachat.exceptions
import pytest
from gigachat.models.chat_completions import ChatCompletionChunk

from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_chat_generator,
    stream_responses_chat_completion_generator,
    stream_responses_generator,
)
from gpt2giga.protocol import ResponseProcessor


class FakeResponseProcessor:
    def process_stream_chunk(self, chunk, model, response_id: str, request_data=None):
        return {
            "id": response_id,
            "model": model,
            "delta": chunk.model_dump()["choices"][0]["delta"],
        }

    def process_stream_chunk_response(
        self, chunk, sequence_number: int, response_id: str
    ):
        return {
            "id": response_id,
            "sequence": sequence_number,
            "delta": chunk.model_dump()["choices"][0]["delta"],
        }

    @staticmethod
    def _build_response_usage(usage_data):
        return {
            "input_tokens": usage_data.get("prompt_tokens", 0),
            "output_tokens": usage_data.get("completion_tokens", 0),
            "total_tokens": usage_data.get("total_tokens", 0),
            "prompt_tokens_details": {
                "cached_tokens": usage_data.get("precached_prompt_tokens", 0)
            },
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }


class FakeClient:
    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [{"delta": {"content": "A"}}],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [{"delta": {"content": "B"}}],
                    "usage": None,
                    "model": "giga",
                }
            )

        return gen()


class FakeClientV1TerminalChunk:
    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                    "model": "giga",
                }
            )

        return gen()


class FakeClientThinkTags:
    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [{"delta": {"content": "<think>plan"}}],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [{"delta": {"content": "</think>Answer"}}],
                    "usage": None,
                    "model": "giga",
                }
            )

        return gen()


class FakeClientError:
    def astream(self, chat):
        async def gen():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        return gen()


class FakeClientGigaChatError:
    """Client that raises GigaChatException"""

    def astream(self, chat):
        async def gen():
            # Используем базовый GigaChatException который не требует дополнительных аргументов
            raise gigachat.exceptions.GigaChatException("GigaChat API error occurred")
            yield  # pragma: no cover

        return gen()


class FakeAChatStreamResource:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or []
        self.error = error

    def stream(self, chat_request):
        async def gen():
            if self.error:
                raise self.error
            for chunk in self.chunks:
                yield chunk

        return gen()


class FakeClientV2Stream:
    def __init__(self, chunks=None, error=None, images=None):
        self.achat = FakeAChatStreamResource(chunks=chunks, error=error)
        self.images = images or {}

    async def aget_image(self, file_id):
        return SimpleNamespace(
            model_dump=lambda **_kwargs: {"content": self.images[file_id]}
        )


class FakeClientCancelled:
    def astream(self, chat):
        async def gen():
            raise asyncio.CancelledError()
            yield  # pragma: no cover

        return gen()


class FakeAppState:
    def __init__(self, client, logger=None):
        self.gigachat_client = client
        self.response_processor = FakeResponseProcessor()
        self.rquid = "rquid-1"
        self.logger = logger


class FakeRequest:
    def __init__(self, client, disconnected: bool = False, logger=None):
        self.app = SimpleNamespace(state=FakeAppState(client, logger))
        self._disconnected = disconnected

    async def is_disconnected(self):
        return self._disconnected


async def test_stream_chat_generator_exception_path():
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_generator(req, "1", chat, response_id="1"):
        lines.append(line)
    assert len(lines) == 2
    assert "Stream interrupted" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_responses_generator_exception_path():
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="1"):
        lines.append(line)
    # Now we expect: response.created, response.in_progress, then error
    # (output_item.added and content_part.added are emitted lazily on first content)
    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "Stream interrupted" in lines[2]
    assert "event: error" in lines[2]


async def test_stream_chat_generator_gigachat_exception():
    """Тест обработки GigaChatException с правильным типом ошибки"""
    logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger=logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_generator(req, "1", chat, response_id="1"):
        lines.append(line)
    assert len(lines) == 2
    # Проверяем, что ошибка содержит тип и код
    assert "GigaChatException" in lines[0]
    assert "stream_error" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_chat_generator_preserves_input_called_tools():
    req = FakeRequest(FakeClientV1TerminalChunk())
    req.app.state.response_processor = ResponseProcessor(logger=MagicMock())
    chat = SimpleNamespace(model="giga")
    lines = []

    async for line in stream_chat_generator(
        req,
        "gpt-x",
        chat,
        response_id="v1",
        request_data={
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {"command": "make install"},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_result": {
                                "name": "run_shell_command",
                                "result": {"result": "ok"},
                            }
                        }
                    ],
                },
            ]
        },
    ):
        lines.append(line)

    payload = json.loads(lines[0].replace("data: ", ""))
    assert json.loads(payload["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 0,
            "name": "run_shell_command",
            "arguments": {"command": "make install"},
            "content_index": 0,
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_chat_completion_generator_text_chunks():
    chunks = [
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "assistant", "content": [{"text": "A"}]}]}
        ),
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "assistant", "content": [{"text": "B"}]}]}
        ),
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    lines = []

    async for line in stream_chat_completion_generator(
        req, "gpt-x", {"contract": "v2"}, response_id="v2"
    ):
        lines.append(line)

    assert len(lines) == 3
    assert '"content": "A"' in lines[0]
    assert '"content": "B"' in lines[1]
    assert lines[2].strip() == "data: [DONE]"


async def test_stream_chat_completion_generator_named_done_event_finishes_stream():
    done_payload = {
        "model": "GigaChat-3-Ultra:32.3.18.5",
        "created_at": 1781352508,
        "messages": [
            {
                "role": "assistant",
                "tool_state_id": "019ec0e2-2bc1-7cf4-86fb-0280fd4c7cb9",
            }
        ],
        "finish_reason": "stop",
        "usage": {
            "input_tokens": 27221,
            "input_tokens_details": {"prompt_tokens": 27221, "cached_tokens": 0},
            "output_tokens": 16,
            "total_tokens": 27237,
        },
    }
    chunks = [
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "assistant", "content": [{"text": "A"}]}]}
        ),
        (
            "event: response.message.done\n"
            f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        ),
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    req.app.state.response_processor = ResponseProcessor(logger=MagicMock())
    lines = []

    async for line in stream_chat_completion_generator(
        req, "gpt-x", {"contract": "v2"}, response_id="v2"
    ):
        lines.append(line)

    final_payload = json.loads(lines[1].removeprefix("data: "))
    assert len(lines) == 3
    assert final_payload["choices"][0]["finish_reason"] == "stop"
    assert final_payload["usage"]["prompt_tokens"] == 27221
    assert final_payload["metadata"]["gigachat_tool_state_id"] == (
        "019ec0e2-2bc1-7cf4-86fb-0280fd4c7cb9"
    )
    assert lines[2].strip() == "data: [DONE]"


async def test_stream_chat_completion_generator_reasoning_chunks():
    chunks = [
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "reasoning", "content": [{"text": "Plan"}]}]}
        ),
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "assistant", "content": [{"text": "Answer"}]}]}
        ),
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    lines = []

    async for line in stream_chat_completion_generator(
        req, "gpt-x", {"contract": "v2"}, response_id="v2"
    ):
        lines.append(line)

    assert len(lines) == 3
    assert '"content": ""' in lines[0]
    assert '"reasoning_content": "Plan"' in lines[0]
    assert '"content": "Answer"' in lines[1]
    assert lines[2].strip() == "data: [DONE]"


async def test_stream_chat_completion_generator_usage_only_chunk():
    chunks = [
        ChatCompletionChunk.model_validate(
            {
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                }
            }
        )
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    lines = []

    async for line in stream_chat_completion_generator(
        req, "gpt-x", {"contract": "v2"}, response_id="v2"
    ):
        lines.append(line)

    assert len(lines) == 2
    assert '"content": ""' in lines[0]
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_chat_completion_generator_preserves_input_called_tools():
    chunks = [
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "tools_state_id": "new-state",
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            }
        )
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    req.app.state.response_processor = ResponseProcessor(logger=MagicMock())
    lines = []

    async for line in stream_chat_completion_generator(
        req,
        "gpt-x",
        {"contract": "v2"},
        response_id="v2",
        request_data={
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {"command": "make install"},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_result": {
                                "name": "run_shell_command",
                                "result": {"result": "ok"},
                            }
                        }
                    ],
                },
            ]
        },
    ):
        lines.append(line)

    payload = json.loads(lines[0].replace("data: ", ""))
    metadata = payload["metadata"]
    assert metadata["gigachat_tool_state_id"] == "new-state"
    assert json.loads(metadata["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 0,
            "name": "run_shell_command",
            "arguments": {"command": "make install"},
            "content_index": 0,
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_chat_completion_generator_gigachat_exception():
    logger = MagicMock()
    req = FakeRequest(
        FakeClientV2Stream(
            error=gigachat.exceptions.GigaChatException("GigaChat API error occurred")
        ),
        logger=logger,
    )
    lines = []

    async for line in stream_chat_completion_generator(
        req, "gpt-x", {"contract": "v2"}, response_id="v2"
    ):
        lines.append(line)

    assert len(lines) == 2
    assert "GigaChatException" in lines[0]
    assert "stream_error" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_chat_generator_propagates_cancellation():
    req = FakeRequest(FakeClientCancelled())
    chat = SimpleNamespace(model="giga")
    gen = stream_chat_generator(req, "1", chat, response_id="1")

    with pytest.raises(asyncio.CancelledError):
        await anext(gen)


async def test_stream_responses_generator_gigachat_exception():
    """Тест обработки GigaChatException в responses generator"""
    logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger=logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="1"):
        lines.append(line)
    # Now we expect: response.created, response.in_progress, then error
    # (output_item.added and content_part.added are emitted lazily on first content)
    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "GigaChat" in lines[2]
    assert "stream_error" in lines[2]
    assert "event: error" in lines[2]


async def test_stream_responses_chat_completion_generator_text_and_usage():
    chunks = [
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "assistant", "content": [{"text": "Hi"}]}]}
        ),
        ChatCompletionChunk.model_validate(
            {
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                }
            }
        ),
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    lines = []

    async for line in stream_responses_chat_completion_generator(
        req,
        {"contract": "v2"},
        response_id="resp-v2",
        request_data={"model": "gpt-x"},
    ):
        lines.append(line)

    assert any("event: response.output_text.delta" in line for line in lines)
    assert any('"delta": "Hi"' in line for line in lines)
    completed = [line for line in lines if "event: response.completed" in line][-1]
    assert '"text": "Hi"' in completed
    assert '"input_tokens": 1' in completed
    assert '"output_tokens": 2' in completed


async def test_stream_responses_chat_completion_generator_builtin_tool_outputs():
    chunks = [
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"tool_execution": {"name": "image_generate"}},
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "files": [
                                    {
                                        "id": "image-file-1",
                                        "mime": "image/jpeg",
                                        "target": "image",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "text": "Done. [sources=[1]]",
                                "inline_data": {
                                    "sources": {
                                        "1": {
                                            "url": "https://example.test/source",
                                            "title": "Example Source",
                                        }
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        ),
    ]
    req = FakeRequest(
        FakeClientV2Stream(chunks=chunks, images={"image-file-1": "aW1n"})
    )
    lines = []

    async for line in stream_responses_chat_completion_generator(
        req,
        {"contract": "v2"},
        response_id="resp-v2",
        request_data={
            "model": "gpt-x",
            "input": "Draw and cite",
            "store": False,
            "tools": [{"type": "image_generation"}, {"type": "web_search"}],
        },
    ):
        lines.append(line)

    completed = [line for line in lines if "event: response.completed" in line][-1]
    payload = json.loads(completed.strip().split("\n")[1].replace("data: ", ""))
    response = payload["response"]
    output = response["output"]

    assert response["store"] is False
    assert response["tools"] == [{"type": "image_generation"}, {"type": "web_search"}]
    image_call = next(
        item for item in output if item["type"] == "image_generation_call"
    )
    web_call = next(item for item in output if item["type"] == "web_search_call")
    message = next(item for item in output if item["type"] == "message")
    assert image_call["result"] == "aW1n"
    assert image_call["file_id"] == "image-file-1"
    assert web_call["action"]["query"] == "Draw and cite"
    content = message["content"][0]
    assert content["inline_data"]["sources"]["1"]["title"] == "Example Source"
    assert content["annotations"][0]["type"] == "url_citation"
    assert content["annotations"][0]["url"] == "https://example.test/source"


async def test_stream_responses_chat_completion_generator_emits_source_annotation_event():
    chunks = [
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "inline_data": {
                                    "sources": {
                                        "1": {
                                            "url": "https://example.test/source",
                                            "title": "Example Source",
                                        }
                                    }
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "Answer. "}],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "[sources=[1]]"}],
                    }
                ]
            }
        ),
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    lines = []

    async for line in stream_responses_chat_completion_generator(
        req,
        {"contract": "v2"},
        response_id="resp-v2",
        request_data={
            "model": "gpt-x",
            "input": "Find and cite",
            "tools": [{"type": "web_search"}],
        },
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        return parts[0].replace("event: ", ""), json.loads(
            parts[1].replace("data: ", "")
        )

    events = [parse_sse(line) for line in lines]
    annotation_events = [
        data
        for event_type, data in events
        if event_type == "response.output_text.annotation.added"
    ]
    delta_text = "".join(
        data["delta"]
        for event_type, data in events
        if event_type == "response.output_text.delta"
    )
    text_done = [
        data for event_type, data in events if event_type == "response.output_text.done"
    ][-1]
    completed = [
        data for event_type, data in events if event_type == "response.completed"
    ][-1]
    message = next(
        item for item in completed["response"]["output"] if item["type"] == "message"
    )
    content = message["content"][0]

    assert len(annotation_events) == 1
    annotation = annotation_events[0]["annotation"]
    assert annotation_events[0]["annotation_index"] == 0
    assert annotation["type"] == "url_citation"
    assert annotation["start_index"] == len("Answer. ")
    assert annotation["url"] == "https://example.test/source"
    assert annotation["title"] == "Example Source"
    assert delta_text == (
        "Answer.\n\nSources:\n- [Example Source](https://example.test/source)"
    )
    assert "[sources=" not in delta_text
    assert text_done["text"] == delta_text
    assert content["text"] == delta_text
    assert content["annotations"] == [annotation]
    assert content["inline_data"]["sources"]["1"]["title"] == "Example Source"


async def test_stream_responses_chat_completion_generator_emits_builtin_tool_progress_events():
    chunks = [
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"tool_execution": {"name": "image_generate"}}],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "image_generate",
                                    "seconds_left": 12,
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "image_generate",
                                    "seconds_left": 6,
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "image_generate",
                                    "seconds_left": 3,
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "image_generate",
                                    "status": "success",
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "files": [
                                    {
                                        "id": "image-file-1",
                                        "mime": "image/jpeg",
                                        "target": "image",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "Done."}],
                    }
                ]
            }
        ),
    ]
    req = FakeRequest(
        FakeClientV2Stream(chunks=chunks, images={"image-file-1": "aW1n"})
    )
    lines = []

    async for line in stream_responses_chat_completion_generator(
        req,
        {"contract": "v2"},
        response_id="resp-v2",
        request_data={
            "model": "gpt-x",
            "input": "Draw space",
            "tools": [{"type": "image_generation"}],
        },
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        return parts[0].replace("event: ", ""), json.loads(
            parts[1].replace("data: ", "")
        )

    events = [parse_sse(line) for line in lines]
    image_added = next(
        data
        for event_type, data in events
        if event_type == "response.output_item.added"
        and data["item"]["type"] == "image_generation_call"
    )
    progress_events = [
        data
        for event_type, data in events
        if event_type == "response.image_generation_call.in_progress"
    ]
    image_completed = next(
        data
        for event_type, data in events
        if event_type == "response.image_generation_call.completed"
    )
    image_done = next(
        data
        for event_type, data in events
        if event_type == "response.output_item.done"
        and data["item"]["type"] == "image_generation_call"
    )
    completed = [
        data for event_type, data in events if event_type == "response.completed"
    ][-1]

    assert image_added["item"]["status"] == "in_progress"
    assert [event.get("seconds_left") for event in progress_events] == [
        None,
        12,
        6,
        3,
    ]
    assert image_completed["item_id"] == image_added["item"]["id"]
    assert image_done["item"]["id"] == image_added["item"]["id"]
    assert image_done["item"]["result"] == "aW1n"
    assert image_done["item"]["file_id"] == "image-file-1"
    image_call = next(
        item
        for item in completed["response"]["output"]
        if item["type"] == "image_generation_call"
    )
    assert image_call["result"] == "aW1n"


async def test_stream_responses_chat_completion_generator_maps_reasoning_role_to_output_item():
    chunks = [
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "reasoning",
                        "content": [{"text": "Use a known geography fact."}],
                    }
                ]
            }
        ),
        ChatCompletionChunk.model_validate(
            {"messages": [{"role": "assistant", "content": [{"text": "Paris"}]}]}
        ),
    ]
    req = FakeRequest(FakeClientV2Stream(chunks=chunks))
    lines = []

    async for line in stream_responses_chat_completion_generator(
        req,
        {"contract": "v2"},
        response_id="resp-v2",
        request_data={"model": "gpt-x"},
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    output_text_deltas = []
    for line in lines:
        event_type, data = parse_sse(line)
        if event_type == "response.output_text.delta":
            output_text_deltas.append(data["delta"])

    assert output_text_deltas == ["Paris"]

    event_type, data = parse_sse(lines[-1])
    assert event_type == "response.completed"
    output = data["response"]["output"]
    assert output[0]["type"] == "reasoning"
    assert output[0]["summary"][0]["text"] == "Use a known geography fact."
    assert output[1]["type"] == "message"
    assert output[1]["content"][0]["text"] == "Paris"


async def test_stream_responses_chat_completion_generator_gigachat_exception():
    logger = MagicMock()
    req = FakeRequest(
        FakeClientV2Stream(
            error=gigachat.exceptions.GigaChatException("GigaChat API error occurred")
        ),
        logger=logger,
    )
    lines = []

    async for line in stream_responses_chat_completion_generator(
        req,
        {"contract": "v2"},
        response_id="resp-v2",
        request_data={"model": "gpt-x"},
    ):
        lines.append(line)

    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "stream_error" in lines[2]
    assert "event: error" in lines[2]


async def test_stream_responses_generator_propagates_cancellation():
    req = FakeRequest(FakeClientCancelled())
    chat = SimpleNamespace(model="giga")
    gen = stream_responses_generator(req, chat, response_id="1")

    first = await anext(gen)
    second = await anext(gen)
    assert "event: response.created" in first
    assert "event: response.in_progress" in second

    with pytest.raises(asyncio.CancelledError):
        await anext(gen)


async def test_stream_chat_generator_success_with_disconnect():
    """Тест корректного завершения при отключении клиента"""

    class FakeClientWithChunks:
        def astream(self, chat):
            async def gen():
                yield SimpleNamespace(
                    model_dump=lambda: {
                        "choices": [{"delta": {"content": "A"}}],
                        "usage": None,
                        "model": "giga",
                    }
                )
                yield SimpleNamespace(
                    model_dump=lambda: {
                        "choices": [{"delta": {"content": "B"}}],
                        "usage": None,
                        "model": "giga",
                    }
                )

            return gen()

    # Клиент отключается после первого чанка
    class DisconnectAfterFirstRequest:
        def __init__(self, client):
            self.app = SimpleNamespace(state=FakeAppState(client, logger=MagicMock()))
            self._call_count = 0

        async def is_disconnected(self):
            self._call_count += 1
            return self._call_count > 1  # Disconnect after first call

    req = DisconnectAfterFirstRequest(FakeClientWithChunks())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_generator(req, "1", chat, response_id="1"):
        lines.append(line)
    # Должен быть только 1 чанк данных + DONE
    assert len(lines) == 2
    assert lines[1].strip() == "data: [DONE]"


async def test_stream_chat_completion_error_response_format():
    """Тест формата ответа об ошибке в стриминге"""
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_generator(req, "1", chat, response_id="1"):
        lines.append(line)

    # Парсим ошибку
    error_line = lines[0].replace("data: ", "").strip()
    error_data = json.loads(error_line)

    assert "error" in error_data
    assert "message" in error_data["error"]
    assert "type" in error_data["error"]
    assert "code" in error_data["error"]
    assert error_data["error"]["code"] == "internal_error"


async def test_stream_responses_generator_success():
    """Test successful streaming with all proper SSE events"""
    req = FakeRequest(FakeClient())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="test123"):
        lines.append(line)

    # Expected events:
    # 1. response.created
    # 2. response.in_progress
    # 3. response.output_item.added
    # 4. response.content_part.added
    # 5. response.output_text.delta (for "A")
    # 6. response.output_text.delta (for "B")
    # 7. response.output_text.done
    # 8. response.content_part.done
    # 9. response.output_item.done
    # 10. response.completed
    assert len(lines) == 10

    # Parse and verify each event
    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["type"] == "response.created"
    assert data["response"]["status"] == "in_progress"

    event_type, data = parse_sse(lines[1])
    assert event_type == "response.in_progress"
    assert data["type"] == "response.in_progress"

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["type"] == "response.output_item.added"
    assert data["item"]["role"] == "assistant"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.content_part.added"
    assert data["type"] == "response.content_part.added"
    assert data["part"]["type"] == "output_text"

    # Delta events for "A" and "B"
    event_type, data = parse_sse(lines[4])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "A"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "B"

    # Finalization events
    event_type, data = parse_sse(lines[6])
    assert event_type == "response.output_text.done"
    assert data["text"] == "AB"

    event_type, data = parse_sse(lines[7])
    assert event_type == "response.content_part.done"
    assert data["part"]["text"] == "AB"

    event_type, data = parse_sse(lines[8])
    assert event_type == "response.output_item.done"
    assert data["item"]["status"] == "completed"

    event_type, data = parse_sse(lines[9])
    assert event_type == "response.completed"
    assert data["response"]["status"] == "completed"
    assert data["response"]["output"][0]["content"][0]["text"] == "AB"


async def test_stream_responses_generator_preserves_reasoning_config():
    req = FakeRequest(FakeClient())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req,
        chat,
        response_id="reasoning123",
        request_data={
            "model": "gpt-x",
            "reasoning": {"effort": "high", "summary": "auto"},
        },
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["response"]["reasoning"] == {"effort": "high", "summary": "auto"}

    event_type, data = parse_sse(lines[-1])
    assert event_type == "response.completed"
    assert data["response"]["reasoning"] == {"effort": "high", "summary": "auto"}


async def test_stream_responses_generator_extracts_think_tags():
    req = FakeRequest(FakeClientThinkTags())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="think123"):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    output_text_deltas = []
    for line in lines:
        event_type, data = parse_sse(line)
        if event_type == "response.output_text.delta":
            output_text_deltas.append(data["delta"])

    assert output_text_deltas == ["Answer"]

    event_type, data = parse_sse(lines[-1])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["type"] == "reasoning"
    assert data["response"]["output"][0]["summary"][0]["text"] == "plan"
    assert data["response"]["output"][1]["content"][0]["text"] == "Answer"


class FakeClientFunctionCall:
    """Client that returns function call chunks"""

    def astream(self, chat):
        async def gen():
            # First chunk with function name
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "get_weather",
                                    "arguments": {"location": "Moscow"},
                                },
                                "functions_state_id": "state_123",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            # Second chunk with finish_reason
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


class FakeClientNamespacedFunctionCall:
    """Client that returns a flattened namespaced function call."""

    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "mcp__playwright__browser_navigate",
                                    "arguments": {
                                        "url": "http://localhost:8090",
                                    },
                                },
                                "functions_state_id": "state_123",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


class FakeClientFunctionCallStreamed:
    """Client that returns function call with arguments streamed across multiple chunks"""

    def astream(self, chat):
        async def gen():
            # First chunk with function name
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "search",
                                    "arguments": '{"query":',
                                },
                                "functions_state_id": "state_456",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            # Second chunk with more arguments
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "function_call": {
                                    "arguments": ' "test"}',
                                },
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            # Final chunk
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


class FakeClientFunctionCallReservedWebSearch:
    """Client that returns a reserved tool name (aliased on GigaChat side)."""

    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "__gpt2giga_user_search_web",
                                    "arguments": {"query": "Moscow"},
                                },
                                "functions_state_id": "state_999",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


async def test_stream_responses_generator_function_call():
    """Test streaming with function call (single chunk)"""
    req = FakeRequest(FakeClientFunctionCall())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="fc_test"):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    # Expected events:
    # 1. response.created
    # 2. response.in_progress
    # 3. response.output_item.added (function_call)
    # 4. response.function_call_arguments.delta
    # 5. response.function_call_arguments.done
    # 6. response.output_item.done
    # 7. response.completed
    assert len(lines) == 7

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"

    event_type, data = parse_sse(lines[1])
    assert event_type == "response.in_progress"

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["type"] == "function_call"
    assert data["item"]["name"] == "get_weather"
    assert data["item"]["status"] == "in_progress"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.function_call_arguments.delta"
    assert "location" in data["delta"]

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.done"
    assert data["name"] == "get_weather"
    assert "location" in data["arguments"]

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_item.done"
    assert data["item"]["type"] == "function_call"
    assert data["item"]["status"] == "completed"
    assert data["item"]["name"] == "get_weather"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["status"] == "completed"
    assert data["response"]["output"][0]["type"] == "function_call"
    assert data["response"]["output"][0]["name"] == "get_weather"
    assert json.loads(data["response"]["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "name": "get_weather",
            "arguments": {"location": "Moscow"},
            "tools_state_id": "state_123",
        }
    ]


async def test_stream_responses_generator_function_call_restores_namespace():
    req = FakeRequest(FakeClientNamespacedFunctionCall())
    chat = SimpleNamespace(model="giga")
    lines = []
    request_tools = [
        {
            "type": "namespace",
            "name": "mcp__playwright",
            "tools": [
                {
                    "type": "function",
                    "name": "browser_navigate",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                    },
                }
            ],
        }
    ]

    async for line in stream_responses_generator(
        req,
        chat,
        response_id="fc_test",
        request_data={"tools": request_tools},
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["name"] == "browser_navigate"
    assert data["item"]["namespace"] == "mcp__playwright"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_item.done"
    assert data["item"]["name"] == "browser_navigate"
    assert data["item"]["namespace"] == "mcp__playwright"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["namespace"] == "mcp__playwright"
    assert json.loads(data["response"]["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "name": "browser_navigate",
            "arguments": {"url": "http://localhost:8090"},
            "tools_state_id": "state_123",
            "namespace": "mcp__playwright",
        }
    ]


async def test_stream_responses_generator_function_call_streamed_args():
    """Test streaming with function call arguments split across multiple chunks"""
    req = FakeRequest(FakeClientFunctionCallStreamed())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="fc_stream"):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    # Expected events:
    # 1. response.created
    # 2. response.in_progress
    # 3. response.output_item.added (function_call)
    # 4. response.function_call_arguments.delta (first part)
    # 5. response.function_call_arguments.delta (second part)
    # 6. response.function_call_arguments.done
    # 7. response.output_item.done
    # 8. response.completed
    assert len(lines) == 8

    # Verify delta events
    event_type, data = parse_sse(lines[3])
    assert event_type == "response.function_call_arguments.delta"
    assert data["delta"] == '{"query":'

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.delta"
    assert data["delta"] == ' "test"}'

    # Verify final arguments are concatenated
    event_type, data = parse_sse(lines[5])
    assert event_type == "response.function_call_arguments.done"
    assert data["arguments"] == '{"query": "test"}'
    assert data["name"] == "search"

    # Verify completed output
    event_type, data = parse_sse(lines[7])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["type"] == "function_call"
    assert data["response"]["output"][0]["name"] == "search"
    assert data["response"]["output"][0]["arguments"] == '{"query": "test"}'
    assert json.loads(data["response"]["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "name": "search",
            "arguments": {"query": "test"},
            "tools_state_id": "state_456",
        }
    ]


async def test_stream_responses_generator_unmaps_reserved_web_search_name():
    """Reserved tool name coming from GigaChat must be mapped back for client."""
    req = FakeRequest(FakeClientFunctionCallReservedWebSearch())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req, chat, response_id="fc_web_search"
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    # response.output_item.added contains the name
    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["name"] == "web_search"

    # done event must also contain unmapped name
    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.done"
    assert data["name"] == "web_search"

    # final output must contain unmapped name
    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["name"] == "web_search"
