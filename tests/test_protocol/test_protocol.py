import pytest
from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor
from loguru import logger


class DummyClient:
    def __init__(self):
        self.called = False


def test_attachment_processor_construction():
    p = AttachmentProcessor(DummyClient(), logger)
    assert hasattr(p, "upload_file")


@pytest.mark.asyncio
async def test_request_transformer_collapse_messages():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "world"},
    ]
    data = {"messages": messages}
    chat = await rt.send_to_gigachat(data)
    # После collapse два подряд user должны склеиться
    # chat is now a dict
    assert len(chat["messages"]) == 1
    assert (
        "hello" in chat["messages"][0]["content"]
        and "world" in chat["messages"][0]["content"]
    )


@pytest.mark.asyncio
async def test_request_transformer_tools_to_functions():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    data = {
        "model": "gpt-4o",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "sum",
                    "description": "calc",
                    "parameters": {
                        "type": "object",
                        "properties": {"a": {"type": "number"}},
                    },
                },
            }
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
    chat = await rt.send_to_gigachat(data)
    # chat is dict
    assert chat.get("functions") and len(chat["functions"]) == 1


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


def test_response_processor_process_function_call():
    rp = ResponseProcessor(logger)
    # Синтетический ответ GigaChat с function_call
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {"name": "sum", "arguments": {"a": 1}},
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")
    choice = out["choices"][0]
    assert choice["message"]["tool_calls"][0]["type"] == "function"


def test_response_processor_stream_chunk_handles_delta():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "hel",
                    }
                }
            ],
            "usage": None,
        }
    )
    out = rp.process_stream_chunk(giga_resp, gpt_model="gpt-x", response_id="1")
    assert out["object"] == "chat.completion.chunk"
