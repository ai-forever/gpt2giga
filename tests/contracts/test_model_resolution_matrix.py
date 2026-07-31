"""End-to-end stable SDK model-resolution contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.core.context import RequestContext, request_context_var
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.protocols.normalized import NormalizedChatRequest, NormalizedMessage
from gpt2giga.providers.gigachat.adapter import GigaChatProviderAdapter
from gpt2giga.providers.gigachat.model_resolution import UpstreamModelRequiredError
from gpt2giga.routers.openai import router as openai_router


@dataclass(frozen=True)
class ModelCase:
    requested: str | None
    pass_model: bool
    forced: str | None
    configured: str | None
    expected: str
    source: str


MODEL_CASES = [
    pytest.param(
        ModelCase(
            "request-model", True, None, "configured-model", "request-model", "payload"
        ),
        id="request-model",
    ),
    pytest.param(
        ModelCase(
            "request-model",
            False,
            None,
            "configured-model",
            "configured-model",
            "settings",
        ),
        id="pass-model-disabled",
    ),
    pytest.param(
        ModelCase(
            "request-model",
            False,
            "forced-model",
            "configured-model",
            "forced-model",
            "forced",
        ),
        id="signed-override",
    ),
    pytest.param(
        ModelCase(None, True, None, "configured-model", "configured-model", "settings"),
        id="configured-fallback",
    ),
    pytest.param(
        ModelCase("  ", True, None, "configured-model", "configured-model", "settings"),
        id="blank-is-missing",
    ),
]


def _payload_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return payload.model_dump(exclude_none=True, by_alias=True)


@pytest.mark.parametrize("case", MODEL_CASES)
@pytest.mark.parametrize("api_mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
async def test_model_precedence_reaches_sdk_limiter_and_telemetry(
    case: ModelCase,
    api_mode: Literal["v1", "v2"],
    stream: bool,
    stable_sdk_client: Any,
    recording_limiter: Any,
    request_context: RequestContext,
) -> None:
    config = ProxyConfig(
        proxy=ProxySettings(pass_model=case.pass_model, gigachat_api_mode=api_mode),
        gigachat={"model": case.configured},
    )
    stable_sdk_client.configured_model = case.configured
    adapter = GigaChatProviderAdapter(
        config=config,
        request_transformer=RequestTransformer(config, logger=logger),
        giga_client=stable_sdk_client,
        model_limiter=recording_limiter,
        response_processor=ResponseProcessor(logger=logger),
        api_mode=api_mode,
        forced_model=case.forced,
    )
    request = NormalizedChatRequest(
        model=case.requested,
        stream=stream,
        messages=[NormalizedMessage(role="user", content="contract")],
    )
    token = request_context_var.set(request_context)
    try:
        if stream:
            events = [
                event
                async for event in adapter.stream_chat(request, context=request_context)
            ]
            assert events[-1].type == "message_end"
        else:
            response = await adapter.chat(request, context=request_context)
            assert response.choices[0].message is not None
    finally:
        request_context_var.reset(token)

    [(operation, upstream_payload)] = stable_sdk_client.calls
    assert operation == f"{api_mode}.{'stream' if stream else 'chat'}"
    raw_model = _payload_dict(upstream_payload).get("model")
    if case.source in {"payload", "forced"}:
        assert raw_model == case.expected
    else:
        assert raw_model is None
    assert stable_sdk_client.effective_models == [case.expected]
    assert recording_limiter.calls == [(case.expected, "openai")]
    assert request_context.model_effective == case.expected
    assert request_context.metadata["model_source"] == case.source


class StatefulV2Transformer(RequestTransformer):
    """Inject one SDK-supported model-less v2 flow after protocol conversion."""

    def __init__(
        self, *args: Any, state: Literal["assistant", "thread"], **kwargs: Any
    ):
        super().__init__(*args, **kwargs)
        self.state = state

    async def prepare_chat_completion(self, data: dict, giga_client: Any = None):
        payload = await super().prepare_chat_completion(data, giga_client)
        if self.state == "assistant":
            return payload.model_copy(update={"assistant_id": "assistant-1"})
        return payload.model_copy(update={"storage": {"thread_id": "thread-1"}})


@pytest.mark.parametrize(
    ("state", "limiter_key", "source"),
    [
        ("assistant", "assistant:assistant-1", "assistant"),
        ("thread", "thread:thread-1", "thread"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
async def test_v2_stateful_flow_omits_model_without_sdk_sentinel(
    state: Literal["assistant", "thread"],
    limiter_key: str,
    source: str,
    stream: bool,
    stable_sdk_client: Any,
    recording_limiter: Any,
    request_context: RequestContext,
) -> None:
    config = ProxyConfig(proxy=ProxySettings(pass_model=False, gigachat_api_mode="v2"))
    adapter = GigaChatProviderAdapter(
        config=config,
        request_transformer=StatefulV2Transformer(config, logger=logger, state=state),
        giga_client=stable_sdk_client,
        model_limiter=recording_limiter,
        response_processor=ResponseProcessor(logger=logger),
        api_mode="v2",
    )
    request = NormalizedChatRequest(
        stream=stream,
        messages=[NormalizedMessage(role="user", content="contract")],
    )
    token = request_context_var.set(request_context)
    try:
        if stream:
            _ = [event async for event in adapter.stream_chat(request)]
        else:
            await adapter.chat(request)
    finally:
        request_context_var.reset(token)

    [(_operation, upstream_payload)] = stable_sdk_client.calls
    assert "model" not in _payload_dict(upstream_payload)
    assert stable_sdk_client.effective_models == [None]
    assert recording_limiter.calls == [(limiter_key, "openai")]
    assert request_context.model_effective is None
    assert request_context.metadata["model_source"] == source


def _model_required_app(api_mode: Literal["v1", "v2"], sdk_client: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(openai_router)
    config = ProxyConfig(
        proxy=ProxySettings(pass_model=False, gigachat_api_mode=api_mode)
    )
    app.state.config = config
    app.state.gigachat_client = sdk_client
    app.state.request_transformer = RequestTransformer(config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app


@pytest.mark.parametrize("api_mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
def test_missing_model_returns_controlled_400_before_sdk_io(
    api_mode: Literal["v1", "v2"],
    stream: bool,
    stable_sdk_client: Any,
) -> None:
    app = _model_required_app(api_mode, stable_sdk_client)

    response = TestClient(app).post(
        "/chat/completions",
        json={
            "model": "public-alias",
            "messages": [{"role": "user", "content": "contract"}],
            "stream": stream,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "message": UpstreamModelRequiredError.message,
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_required",
        }
    }
    assert stable_sdk_client.calls == []
