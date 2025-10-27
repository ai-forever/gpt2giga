from types import SimpleNamespace

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor


class DummyClient:
    def __init__(self):
        self.called = False


def test_attachment_processor_construction():
    p = AttachmentProcessor(DummyClient())
    assert hasattr(p, "upload_image")


def test_request_transformer_collapse_messages():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "world"},
    ]
    data = {"messages": messages}
    chat = rt.send_to_gigachat(data)
    # После collapse два подряд user должны склеиться
    assert len(chat.messages) == 1
    assert "hello" in chat.messages[0].content and "world" in chat.messages[0].content


def test_request_transformer_tools_to_functions():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg)
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
    chat = rt.send_to_gigachat(data)
    assert chat.functions and len(chat.functions) == 1


def test_response_processor_process_function_call():
    rp = ResponseProcessor()
    # Синтетический ответ GigaChat с function_call
    giga_resp = SimpleNamespace(
        dict=lambda: {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {"name": "sum", "arguments": {"a": 1}},
                        "finish_reason": "function_call",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", is_tool_call=True)
    choice = out["choices"][0]
    assert choice["message"]["tool_calls"][0]["type"] == "function"


def test_response_processor_stream_chunk_handles_delta():
    rp = ResponseProcessor()
    giga_resp = SimpleNamespace(
        dict=lambda: {
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
    out = rp.process_stream_chunk(giga_resp, gpt_model="gpt-x")
    assert out["object"] == "chat.completion.chunk"
