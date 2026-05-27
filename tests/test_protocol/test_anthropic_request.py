from loguru import logger

from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)


def test_build_openai_data_from_anthropic_request_preserves_literal_extra_options():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "extra_body": {"profanity_check": False},
        "extra_headers": {"x-me": "kus"},
        "extra_query": {"beta": "true"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["extra_body"] == {"profanity_check": False}
    assert openai_data["extra_headers"] == {"x-me": "kus"}
    assert openai_data["extra_query"] == {"beta": "true"}


def test_build_openai_data_from_anthropic_request_drops_sdk_style_top_k():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "top_k": 50,
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "top_k" not in openai_data
    assert "extra_body" not in openai_data
