"""Route-level proof that derived cache sessions reach the upstream SDK call.

The router wraps the upstream call in ``gigachat_request_options``, which sets
the SDK's ``session_id_cvar``. Reading ``build_headers()`` from inside the fake
upstream client therefore proves the derived ``X-Session-ID`` actually reaches
the real request headers, not just the local options object.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.api.utils import build_headers
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.routers.openai import router

_LONG_SYSTEM = "You are a helpful assistant. " * 300


class _RecordingGigachat:
    def __init__(self) -> None:
        self.session_headers: list[str | None] = []

    async def achat(self, chat):
        # Reflects the SDK context var set by gigachat_request_options.
        self.session_headers.append(build_headers().get("X-Session-ID"))
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


class _MockResponse:
    def __init__(self, data) -> None:
        self.data = data

    def model_dump(self) -> dict:
        return self.data


def _make_app(*, derivation_enabled: bool) -> tuple[FastAPI, _RecordingGigachat]:
    app = FastAPI()
    app.include_router(router)
    client = _RecordingGigachat()
    app.state.gigachat_client = client
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v1",
            cache_session_derivation_enabled=derivation_enabled,
        )
    )
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


def test_route_forwards_derived_session_to_upstream() -> None:
    app, client = _make_app(derivation_enabled=True)
    response = TestClient(app).post("/chat/completions", json=_payload())

    assert response.status_code == 200
    assert client.session_headers
    assert (client.session_headers[0] or "").startswith("gpt2giga-cache-")


def test_route_is_unchanged_when_derivation_disabled() -> None:
    app, client = _make_app(derivation_enabled=False)
    response = TestClient(app).post("/chat/completions", json=_payload())

    assert response.status_code == 200
    assert client.session_headers
    assert client.session_headers[0] is None


def test_route_keeps_client_supplied_session() -> None:
    app, client = _make_app(derivation_enabled=True)
    response = TestClient(app).post(
        "/chat/completions",
        json=_payload(),
        headers={"X-Session-ID": "client-session"},
    )

    assert response.status_code == 200
    assert client.session_headers
    assert client.session_headers[0] == "client-session"
