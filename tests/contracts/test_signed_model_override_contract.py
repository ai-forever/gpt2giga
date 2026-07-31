"""Legacy signed-model wire contract across Anthropic and Gemini adapters."""

from __future__ import annotations

from typing import Literal

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from gpt2giga.common.signed_model_override import (
    LEGACY_GIGALOOM_HMAC_DOMAIN,
    LEGACY_GIGALOOM_MODEL_HEADER,
    LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER,
    PASS_MODEL_HEADER,
    _model_override_signature,
)
from gpt2giga.protocols.anthropic import AnthropicProtocolAdapter
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.routers.anthropic.messages import _claude_cli_model_override
from gpt2giga.routers.gemini.generate_content import _gemini_cli_model_override


def _request(app: FastAPI, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/contract",
            "raw_path": b"/contract",
            "query_string": b"",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "app": app,
        }
    )


@pytest.mark.parametrize("protocol", ["anthropic", "gemini"])
async def test_signed_override_pins_model_through_protocol_and_provider(
    protocol: Literal["anthropic", "gemini"],
    contract_stack,
) -> None:
    key = "contract-key"
    forced_model = "GigaChat-Selected"
    stack = contract_stack(
        provider=protocol,
        api_mode="v2",
        forced_model=forced_model,
        pass_model=False,
        harness_model_key=key,
    )
    app = FastAPI()
    app.state.config = stack.config
    user_agent = "Claude-CLI/1.0" if protocol == "anthropic" else "GeminiCLI/1.0"
    request = _request(
        app,
        {
            "user-agent": user_agent,
            PASS_MODEL_HEADER: "false",
            LEGACY_GIGALOOM_MODEL_HEADER: forced_model,
            LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER: _model_override_signature(
                key,
                protocol=protocol,
                model=forced_model,
            ),
        },
    )

    if protocol == "anthropic":
        resolved = _claude_cli_model_override(request)
        normalized = AnthropicProtocolAdapter().messages_to_normalized(
            {
                "model": "public-model",
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "contract"}],
            }
        )
    else:
        resolved = _gemini_cli_model_override(request)
        normalized = GeminiProtocolAdapter().generate_content_to_normalized(
            {"contents": [{"parts": [{"text": "contract"}]}]},
            model="public-model",
        )

    assert resolved == forced_model
    stack.adapter.forced_model = resolved
    await stack.adapter.chat(normalized)

    [(_operation, sdk_payload)] = stack.client.calls
    assert sdk_payload.model == forced_model
    assert stack.limiter.calls == [(forced_model, protocol)]
    assert LEGACY_GIGALOOM_HMAC_DOMAIN == "gigaloom-model/v1"
    assert LEGACY_GIGALOOM_MODEL_HEADER == "x-gigaloom-model"
    assert LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER == "x-gigaloom-model-signature"


@pytest.mark.parametrize("protocol", ["anthropic", "gemini"])
def test_tampered_signature_cannot_activate_override(
    protocol: Literal["anthropic", "gemini"],
    contract_stack,
) -> None:
    stack = contract_stack(
        provider=protocol,
        api_mode="v2",
        pass_model=False,
        harness_model_key="contract-key",
    )
    app = FastAPI()
    app.state.config = stack.config
    user_agent = "Claude-CLI/1.0" if protocol == "anthropic" else "GeminiCLI/1.0"
    request = _request(
        app,
        {
            "user-agent": user_agent,
            PASS_MODEL_HEADER: "false",
            LEGACY_GIGALOOM_MODEL_HEADER: "GigaChat-Selected",
            LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER: "v1:tampered",
        },
    )

    resolved = (
        _claude_cli_model_override(request)
        if protocol == "anthropic"
        else _gemini_cli_model_override(request)
    )

    assert resolved is None
