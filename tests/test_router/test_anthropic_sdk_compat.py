import json

import httpx
from anthropic import Anthropic
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.middlewares.rquid_context import RquidMiddleware
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.routers.anthropic import router as anthropic_router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeTokensCount:
    def __init__(self, tokens):
        self.tokens = tokens


class FakeHttpClient:
    def __init__(self):
        self.event_hooks = {"request": []}


class FakeGigachat:
    def __init__(self):
        self._aclient = FakeHttpClient()
        self.chat_payloads = []
        self.token_inputs = []
        self.last_upstream_headers = {}
        self.last_upstream_query = ""

    async def _apply_request_hooks(self):
        request = httpx.Request(
            "POST",
            "https://gigachat.example/chat",
            headers={"content-type": "application/json"},
            content=json.dumps({"model": "GigaChat"}).encode("utf-8"),
        )
        for hook in self._aclient.event_hooks["request"]:
            await hook(request)
        self.last_upstream_headers = dict(request.headers)
        self.last_upstream_query = request.url.query.decode("ascii")

    async def achat(self, chat):
        self.chat_payloads.append(chat)
        await self._apply_request_hooks()
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            }
        )

    def astream(self, chat):
        self.chat_payloads.append(chat)

        async def gen():
            await self._apply_request_hooks()
            yield MockResponse(
                {"choices": [{"delta": {"content": "o"}}], "usage": None}
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "k"}}],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                }
            )

        return gen()

    async def atokens_count(self, input_, model=None):
        self.token_inputs = list(input_)
        await self._apply_request_hooks()
        return [FakeTokensCount(tokens=len(text.split())) for text in input_]


def _make_app():
    app = FastAPI()
    app.add_middleware(RquidMiddleware)
    app.include_router(anthropic_router)
    app.include_router(anthropic_router, prefix="/v1")
    config = ProxyConfig()
    app.state.config = config
    app.state.logger = logger
    app.state.gigachat_client = FakeGigachat()
    app.state.request_transformer = RequestTransformer(config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app


def _make_anthropic_client(app):
    test_client = TestClient(app)
    return Anthropic(
        api_key="test",
        base_url=str(test_client.base_url),
        http_client=test_client,
    )


def test_anthropic_sdk_messages_create():
    app = _make_app()
    client = _make_anthropic_client(app)

    message = client.messages.create(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert message.content[0].text == "ok"
    assert app.state.gigachat_client.chat_payloads[-1]["messages"][0]["content"] == (
        "hello"
    )


def test_anthropic_sdk_messages_stream():
    app = _make_app()
    client = _make_anthropic_client(app)

    with client.messages.stream(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
    ) as stream:
        text = stream.get_final_text()

    assert text == "ok"


def test_anthropic_sdk_messages_count_tokens():
    app = _make_app()
    client = _make_anthropic_client(app)

    result = client.messages.count_tokens(
        model="GigaChat",
        messages=[{"role": "user", "content": "hello world"}],
    )

    assert result.input_tokens == 2
    assert app.state.gigachat_client.token_inputs == ["hello world"]


def test_anthropic_sdk_raw_response_exposes_request_id_header():
    app = _make_app()
    client = _make_anthropic_client(app)

    raw_response = client.messages.with_raw_response.create(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert raw_response.headers.get("x-request-id")
    assert raw_response.parse().content[0].text == "ok"


def test_anthropic_sdk_extra_body_supported_key_reaches_additional_fields():
    app = _make_app()
    client = _make_anthropic_client(app)

    client.messages.create(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
        extra_body={"profanity_check": False},
    )

    assert app.state.gigachat_client.chat_payloads[-1]["additional_fields"] == {
        "profanity_check": False
    }


def test_anthropic_sdk_extra_headers_uses_safe_forwarding_policy():
    app = _make_app()
    client = _make_anthropic_client(app)

    client.messages.create(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
        extra_headers={
            "authorization": "Bearer leak",
            "x-custom": "sdk-custom",
            "x-request-id": "sdk-request-id",
            "x-session-id": "sdk-session-id",
            "x-stainless-test": "drop-me",
        },
        extra_query={"unsafe": "1"},
    )

    upstream_headers = app.state.gigachat_client.last_upstream_headers
    assert upstream_headers["x-request-id"] == "sdk-request-id"
    assert upstream_headers["x-session-id"] == "sdk-session-id"
    assert upstream_headers["x-custom"] == "sdk-custom"
    assert "authorization" not in upstream_headers
    assert "x-stainless-test" not in upstream_headers
    assert app.state.gigachat_client.last_upstream_query == ""


def test_anthropic_sdk_custom_extra_body_reaches_additional_fields():
    app = _make_app()
    client = _make_anthropic_client(app)

    client.messages.create(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
        extra_body={"custom_flag": "on"},
    )

    assert app.state.gigachat_client.chat_payloads[-1]["additional_fields"] == {
        "custom_flag": "on"
    }


def test_anthropic_sdk_ignores_unsupported_beta_feature():
    app = _make_app()
    client = _make_anthropic_client(app)

    message = client.messages.create(
        model="GigaChat",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
        extra_body={"mcp_servers": [{"type": "url", "url": "https://mcp.test"}]},
    )

    assert message.content[0].text == "ok"
    assert "mcp_servers" not in app.state.gigachat_client.chat_payloads[-1]
