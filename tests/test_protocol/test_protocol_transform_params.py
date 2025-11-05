from loguru import logger

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer


def test_transform_chat_parameters_temperature_and_top_p():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"temperature": 0, "model": "gpt-x"})
    # при temperature=0 должен быть top_p=0 и без model (pass_model False по умолчанию)
    assert out.get("top_p") == 0
    assert "model" not in out


def test_transform_chat_parameters_max_tokens_and_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "max_output_tokens": 128,
        "tools": [
            {"type": "function", "function": {"name": "sum", "parameters": {}}},
            {"type": "function", "name": "alt", "parameters": {}},
        ],
    }
    out = rt.transform_chat_parameters(data)
    assert out.get("max_tokens") == 128
    assert "functions" in out and len(out["functions"]) == 2
