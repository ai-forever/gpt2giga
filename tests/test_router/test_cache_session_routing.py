"""Route-level proof that built cache sessions reach the upstream SDK call.

The router wraps the upstream call in ``gigachat_request_options``, which sets
the SDK's ``session_id_cvar``. Reading ``build_headers()`` from inside the fake
upstream client therefore proves the built ``X-Session-ID`` actually reaches
the real request headers, not just the local options object.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.api.utils import build_headers
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.common.cache_session import build_cache_session_id
from gpt2giga.common.signed_model_override import _model_override_signature
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor

_LONG_SYSTEM = "You are a helpful assistant. " * 300


class _RecordingGigachat:
    def __init__(self) -> None:
        self.session_headers: list[str | None] = []
        self.models: list[str | None] = []
        self.payloads: list[dict] = []
        self.achat = _RecordingChat(self)

    def record(self, chat) -> None:
        # Reflects the SDK context var set by gigachat_request_options.
        self.session_headers.append(build_headers().get("X-Session-ID"))
        self.models.append(chat.get("model") if isinstance(chat, dict) else chat.model)
        self.payloads.append(
            chat if isinstance(chat, dict) else chat.model_dump(mode="json")
        )

    async def astream(self, chat):
        self.record(chat)
        yield _MockResponse(
            {
                "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )


class _RecordingChat:
    def __init__(self, client: _RecordingGigachat) -> None:
        self.client = client

    async def __call__(self, chat):
        self.client.record(chat)
        return _MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )

    async def create(self, chat):
        self.client.record(chat)
        return _MockResponse(self._v2_response())

    async def stream(self, chat):
        self.client.record(chat)
        yield _MockResponse(self._v2_response())

    @staticmethod
    def _v2_response() -> dict:
        return {
            "messages": [{"role": "assistant", "content": [{"text": "ok"}]}],
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class _MockResponse:
    def __init__(self, data) -> None:
        self.data = data

    def model_dump(self, **_kwargs) -> dict:
        return self.data


def _make_app(
    *,
    session_enabled: bool,
    scope: str = "system",
    pass_model: bool = True,
    stitching: bool = False,
    normalization_mode: str = "off",
) -> tuple[FastAPI, _RecordingGigachat]:
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                mode="DEV",
                gigachat_api_mode="v1",
                cache_session_enabled=session_enabled,
                cache_session_scope=scope,
                pass_model=pass_model,
                harness_model_key="synthetic-model-key",
                conversation_stitching_enabled=stitching,
                normalization_mode=normalization_mode,
                legacy_chat_fallback=False,
            ),
            gigachat={"model": "GigaChat-2-Max"},
        )
    )
    client = _RecordingGigachat()
    app.state.gigachat_client = client
    app.state.logger = logger
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    return app, client


def _payload() -> dict:
    return {
        "model": "GigaChat-2-Max",
        "messages": [
            {"role": "system", "content": _LONG_SYSTEM},
            {"role": "user", "content": "Answer with one word: ok"},
        ],
    }


def test_route_forwards_built_session_to_upstream() -> None:
    app, client = _make_app(session_enabled=True)
    response = TestClient(app).post("/chat/completions", json=_payload())

    assert response.status_code == 200
    assert client.session_headers
    assert (client.session_headers[0] or "").startswith("gpt2giga-cache-")


def test_route_is_unchanged_when_session_disabled() -> None:
    app, client = _make_app(session_enabled=False)
    response = TestClient(app).post("/chat/completions", json=_payload())

    assert response.status_code == 200
    assert client.session_headers
    assert client.session_headers[0] is None


def test_route_keeps_client_supplied_session() -> None:
    app, client = _make_app(session_enabled=True)
    response = TestClient(app).post(
        "/chat/completions",
        json=_payload(),
        headers={"X-Session-ID": "client-session"},
    )

    assert response.status_code == 200
    assert client.session_headers
    assert client.session_headers[0] == "client-session"


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("scope", ["system", "prefix"])
@pytest.mark.parametrize("role", ["system", "developer"])
def test_responses_input_system_roles_reach_upstream(mode, stream, scope, role) -> None:
    app, upstream = _make_app(session_enabled=True, scope=scope)
    payload = {
        "model": "GigaChat-2-Max",
        "input": [
            {"role": role, "content": [{"type": "input_text", "text": _LONG_SYSTEM}]},
            {"role": "user", "content": "Answer: ok"},
        ],
        "stream": stream,
    }

    response = TestClient(app).post(f"/{mode}/responses", json=payload)

    assert response.status_code == 200, response.text
    assert "ok" in response.text
    assert len(upstream.session_headers) == 1
    assert (upstream.session_headers[0] or "").startswith("gpt2giga-cache-")
    assert upstream.session_headers[0] == build_cache_session_id(
        payload, scope=scope, model="GigaChat-2-Max"
    )


def _gemini_payload() -> dict:
    return {
        "systemInstruction": {"parts": [{"text": _LONG_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": "Answer: ok"}]}],
    }


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
def test_gemini_cache_session_uses_url_model(mode, stream) -> None:
    app, upstream = _make_app(session_enabled=True)
    client = TestClient(app)
    action = "streamGenerateContent" if stream else "generateContent"
    payload = _gemini_payload()

    for model in ("GigaChat-2-Max", "GigaChat-2-Pro"):
        response = client.post(f"/{mode}/v1beta/models/{model}:{action}", json=payload)
        assert response.status_code == 200, response.text
        assert "ok" in response.text
        assert upstream.models[-1] == model
        assert upstream.session_headers[-1] == build_cache_session_id(
            payload, scope="system", model=model
        )

    assert upstream.session_headers[0] != upstream.session_headers[1]


@pytest.mark.parametrize("scope", ["system", "prefix"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("protocol", ["responses", "anthropic", "gemini"])
def test_cache_session_reuses_stitched_prefix(protocol, stream, scope) -> None:
    app, upstream = _make_app(session_enabled=True, stitching=True, scope=scope)
    client = TestClient(app)
    if protocol == "gemini":
        action = "streamGenerateContent" if stream else "generateContent"
        path = f"/v1beta/models/GigaChat-2-Max:{action}"
        first_payload = _gemini_payload()
        next_payload = {"contents": [{"parts": [{"text": "Next question"}]}]}
    elif protocol == "anthropic":
        path = "/v1/messages"
        first_payload = {
            "model": "GigaChat-2-Max",
            "system": _LONG_SYSTEM,
            "messages": [{"role": "user", "content": "Answer: ok"}],
            "max_tokens": 16,
            "stream": stream,
        }
        next_payload = {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "Next question"}],
            "max_tokens": 16,
            "stream": stream,
        }
    else:
        path = "/v1/responses"
        first_payload = {
            "model": "GigaChat-2-Max",
            "input": [
                {"role": "developer", "content": _LONG_SYSTEM},
                {"role": "user", "content": "Answer: ok"},
            ],
            "stream": stream,
        }
        next_payload = {
            "model": "GigaChat-2-Max",
            "input": [{"role": "user", "content": "Next question"}],
            "stream": stream,
        }
    headers = {"x-gpt2giga-conversation-id": "synthetic-conversation"}

    for payload in (first_payload, next_payload):
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert "ok" in response.text

    assert len(upstream.payloads[-1]["messages"]) == 4
    assert (upstream.session_headers[0] or "").startswith("gpt2giga-cache-")
    assert upstream.session_headers[0] == upstream.session_headers[1]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("mode", "selector", "identity"),
    [
        ("v1", {"assistant_id": "assistant-one"}, "assistant:assistant-one"),
        ("v1", {"storage": {"thread_id": "thread-one"}}, "thread:thread-one"),
        ("v2", {"assistant_id": "assistant-one"}, "assistant:assistant-one"),
        ("v2", {"previous_response_id": "resp_thread-one"}, "thread:thread-one"),
    ],
)
def test_cache_session_uses_resolved_assistant_or_thread(
    mode, selector, identity, stream
):
    app, upstream = _make_app(session_enabled=True)
    client = TestClient(app)
    for model in ("GigaChat-2-Max", "GigaChat-2-Pro"):
        payload = {
            "model": model,
            "instructions": _LONG_SYSTEM,
            "input": "Answer: ok",
            "stream": stream,
            **selector,
        }
        response = client.post(f"/{mode}/responses", json=payload)
        assert response.status_code == 200, response.text
        assert "ok" in response.text
        assert upstream.models[-1] is None
        assert upstream.session_headers[-1] == build_cache_session_id(
            payload, scope="system", model=identity
        )

    assert upstream.session_headers[0] == upstream.session_headers[1]


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("protocol", ["gemini", "anthropic"])
@pytest.mark.parametrize("normalization_mode", ["off", "on"])
def test_cache_session_uses_authenticated_model_override(
    mode, stream, protocol, normalization_mode
) -> None:
    app, upstream = _make_app(
        session_enabled=True, pass_model=False, normalization_mode=normalization_mode
    )
    client = TestClient(app)
    if protocol == "gemini":
        action = "streamGenerateContent" if stream else "generateContent"
        path = f"/{mode}/v1beta/models/client-model:{action}"
        payload = _gemini_payload()
        user_agent = "GeminiCLI/1.0"
    else:
        path = f"/{mode}/messages"
        payload = {
            "model": "client-model",
            "system": _LONG_SYSTEM,
            "messages": [{"role": "user", "content": "Answer: ok"}],
            "max_tokens": 16,
            "stream": stream,
        }
        user_agent = "claude-cli/1.0"

    for model in ("GigaChat-2-Max", "GigaChat-2-Pro"):
        response = client.post(
            path,
            json=payload,
            headers={
                "user-agent": user_agent,
                "x-gigaloom-model": model,
                "x-gpt2giga-pass-model": "false",
                "x-gigaloom-model-signature": _model_override_signature(
                    "synthetic-model-key", protocol=protocol, model=model
                ),
            },
        )
        assert response.status_code == 200, response.text
        assert "ok" in response.text
        assert upstream.models[-1] == model
        assert upstream.session_headers[-1] == build_cache_session_id(
            payload, scope="system", model=model
        )

    assert upstream.session_headers[0] != upstream.session_headers[1]


@pytest.mark.parametrize("protocol", ["gemini", "openai"])
@pytest.mark.parametrize("normalization_mode", ["off", "on"])
def test_cache_session_uses_configured_model_when_forwarding_disabled(
    protocol, normalization_mode
) -> None:
    app, upstream = _make_app(
        session_enabled=True, pass_model=False, normalization_mode=normalization_mode
    )
    client = TestClient(app)
    if protocol == "gemini":
        path = "/v1beta/models/client-model:generateContent"
        payload = _gemini_payload()
    else:
        path = "/v1/chat/completions"
        payload = _payload()

    for model in ("GigaChat-2-Max", "GigaChat-2-Pro"):
        app.state.config.gigachat_settings.model = model
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        # The SDK applies its configured model when the request omits it.
        assert upstream.models[-1] is None
        assert upstream.session_headers[-1] == build_cache_session_id(
            payload, scope="system", model=model
        )

    assert upstream.session_headers[0] != upstream.session_headers[1]


@pytest.mark.parametrize("protocol", ["responses", "anthropic", "gemini"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("guard", ["disabled", "client", "global"])
def test_generation_routes_preserve_session_precedence(protocol, stream, guard) -> None:
    app, upstream = _make_app(session_enabled=guard != "disabled")
    if guard == "global":
        app.state.config.gigachat_settings.session_id = "global-session"
    headers = {"X-Session-ID": "client-session"} if guard == "client" else {}
    if protocol == "gemini":
        action = "streamGenerateContent" if stream else "generateContent"
        path = f"/v1beta/models/GigaChat-2-Max:{action}"
        payload = _gemini_payload()
    elif protocol == "anthropic":
        path = "/v1/messages"
        payload = {
            "model": "GigaChat-2-Max",
            "system": _LONG_SYSTEM,
            "messages": [{"role": "user", "content": "Answer: ok"}],
            "max_tokens": 16,
            "stream": stream,
        }
    else:
        path = "/v1/responses"
        payload = {
            "model": "GigaChat-2-Max",
            "input": [
                {"role": "developer", "content": _LONG_SYSTEM},
                {"role": "user", "content": "Answer: ok"},
            ],
            "stream": stream,
        }

    response = TestClient(app).post(path, json=payload, headers=headers)

    assert response.status_code == 200, response.text
    assert "ok" in response.text
    # Global defaults remain the SDK's responsibility; no derived header is set.
    assert upstream.session_headers == ["client-session" if guard == "client" else None]
