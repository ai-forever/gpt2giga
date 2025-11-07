from loguru import logger

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer


def test_transform_response_format_instructions_and_list_messages():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "instructions": "be nice",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            {"type": "function_call", "name": "sum", "arguments": "{}"},
            {"type": "function_call_output", "output": "42"},
        ],
    }
    payload = rt.transform_response_format(data)
    # Ожидаем system + function_call (как mock_completion) + function output + user
    roles = [m["role"] for m in payload]
    assert roles[0] == "system" and roles[-1] in ("user", "function")
