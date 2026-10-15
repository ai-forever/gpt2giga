"""Native Responses streams expose upstream incomplete termination reasons."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor


def _app(*, finish_reason, output_kind):
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(mode="DEV", pass_model=True),
            gigachat={"model": "GigaChat-2-Max"},
        )
    )
    function_call = {"name": "lookup", "arguments": '{"city": "Paris"}'}

    async def astream(_payload):
        delta = (
            {"content": "partial text"}
            if output_kind == "text"
            else {"function_call": function_call}
        )
        yield SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "choices": [{"delta": delta, "finish_reason": finish_reason}]
            }
        )

    async def stream(_payload):
        part = (
            {"text": "partial text"}
            if output_kind == "text"
            else {"function_call": function_call}
        )
        yield SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "messages": [{"role": "assistant", "content": [part]}],
                "finish_reason": finish_reason,
            }
        )

    app.state.gigachat_client = SimpleNamespace(
        astream=astream, achat=SimpleNamespace(stream=stream)
    )
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("output_kind", ["text", "function_call"])
@pytest.mark.parametrize(
    ("finish_reason", "status", "reason"),
    [
        ("stop", "completed", None),
        ("length", "incomplete", "max_output_tokens"),
        ("max_tokens", "incomplete", "max_output_tokens"),
        ("content_filter", "incomplete", "content_filter"),
    ],
)
def test_native_responses_stream_reports_incomplete_termination(
    mode, output_kind, finish_reason, status, reason
):
    app = _app(finish_reason=finish_reason, output_kind=output_kind)
    response = TestClient(app).post(
        f"/{mode}/responses",
        json={"model": "GigaChat-2-Max", "input": "hello", "stream": True},
    )
    assert response.status_code == 200, response.text
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    terminal = [
        event
        for event in events
        if event["type"] in {"response.completed", "response.incomplete"}
    ]
    assert len(terminal) == 1
    assert terminal[0]["type"] == f"response.{status}"
    result = terminal[0]["response"]
    assert result["status"] == status
    assert result["incomplete_details"] == ({"reason": reason} if reason else None)
    if output_kind == "text":
        assert result["output"][0]["content"][0]["text"] == "partial text"
    else:
        assert result["output"][0]["arguments"] == '{"city": "Paris"}'
