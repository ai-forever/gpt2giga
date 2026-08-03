"""Single-owner and no-fallback invariants for Responses dispatch."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import pytest

from gpt2giga.app.responses_mode import (
    ResponsesExecutionMode,
    ResponsesExecutionSelection,
)


responses_module = importlib.import_module("gpt2giga.routers.openai.responses")


@dataclass
class _Recorder:
    calls: int = 0
    payload: dict[str, Any] | None = None


class _Executor:
    def __init__(
        self,
        recorder: _Recorder,
        *,
        result: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.recorder = recorder
        self.result = result
        self.error = error

    async def execute(self, _request, data: dict[str, Any]) -> Any:
        self.recorder.calls += 1
        self.recorder.payload = dict(data)
        if self.error is not None:
            raise self.error
        return self.result


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(responses_module.router)
    return app


def _install_dispatch(
    monkeypatch,
    *,
    mode: ResponsesExecutionMode,
    native: _Executor,
    normalized: _Executor,
) -> list[Any]:
    selections: list[Any] = []

    def select(_state, *, requested_model):
        selections.append(requested_model)
        return ResponsesExecutionSelection(mode=mode, reason="test_selection")

    monkeypatch.setattr(responses_module, "select_responses_execution", select)
    monkeypatch.setattr(
        responses_module,
        "NativeGigaChatResponsesExecutor",
        lambda: native,
    )
    monkeypatch.setattr(
        responses_module,
        "NormalizedBridgeResponsesExecutor",
        lambda: normalized,
    )
    return selections


@pytest.mark.parametrize(
    "mode",
    [
        ResponsesExecutionMode.NATIVE_GIGACHAT,
        ResponsesExecutionMode.NORMALIZED_BRIDGE,
    ],
)
def test_selection_and_selected_owner_run_exactly_once(
    monkeypatch,
    mode: ResponsesExecutionMode,
) -> None:
    native_recorder = _Recorder()
    normalized_recorder = _Recorder()
    native = _Executor(native_recorder, result={"owner": "native"})
    normalized = _Executor(normalized_recorder, result={"owner": "normalized"})
    selections = _install_dispatch(
        monkeypatch,
        mode=mode,
        native=native,
        normalized=normalized,
    )
    payload = {
        "model": "selected-model",
        "input": "hello",
        "provider": "request-value-must-not-reroute",
    }

    response = TestClient(_app()).post("/responses", json=payload)

    assert response.status_code == 200
    assert selections == ["selected-model"]
    if mode is ResponsesExecutionMode.NATIVE_GIGACHAT:
        assert (native_recorder.calls, normalized_recorder.calls) == (1, 0)
        assert native_recorder.payload == payload
    else:
        assert (native_recorder.calls, normalized_recorder.calls) == (0, 1)
        assert normalized_recorder.payload == payload


@pytest.mark.parametrize(
    "mode",
    [
        ResponsesExecutionMode.NATIVE_GIGACHAT,
        ResponsesExecutionMode.NORMALIZED_BRIDGE,
    ],
)
def test_selected_owner_failure_never_retries_the_other_owner(
    monkeypatch,
    mode: ResponsesExecutionMode,
) -> None:
    native_recorder = _Recorder()
    normalized_recorder = _Recorder()
    native = _Executor(
        native_recorder,
        result={"unexpected": "native fallback"},
        error=(
            RuntimeError("native failed")
            if mode is ResponsesExecutionMode.NATIVE_GIGACHAT
            else None
        ),
    )
    normalized = _Executor(
        normalized_recorder,
        result={"unexpected": "normalized fallback"},
        error=(
            RuntimeError("normalized failed")
            if mode is ResponsesExecutionMode.NORMALIZED_BRIDGE
            else None
        ),
    )
    selections = _install_dispatch(
        monkeypatch,
        mode=mode,
        native=native,
        normalized=normalized,
    )

    response = TestClient(_app(), raise_server_exceptions=False).post(
        "/responses",
        json={"model": "selected-model", "input": "hello"},
    )

    assert response.status_code == 500
    assert selections == ["selected-model"]
    if mode is ResponsesExecutionMode.NATIVE_GIGACHAT:
        assert (native_recorder.calls, normalized_recorder.calls) == (1, 0)
    else:
        assert (native_recorder.calls, normalized_recorder.calls) == (0, 1)


@pytest.mark.parametrize(
    "mode",
    [
        ResponsesExecutionMode.NATIVE_GIGACHAT,
        ResponsesExecutionMode.NORMALIZED_BRIDGE,
    ],
)
def test_stream_bytes_are_emitted_once_by_only_the_selected_owner(
    monkeypatch,
    mode: ResponsesExecutionMode,
) -> None:
    native_recorder = _Recorder()
    normalized_recorder = _Recorder()

    async def selected_stream():
        yield b"event: response.output_text.delta\ndata: selected-byte\n\n"
        yield b"event: response.completed\ndata: completed-byte\n\n"

    async def fallback_stream():
        yield b"event: response.output_text.delta\ndata: duplicate-byte\n\n"

    selected = StreamingResponse(selected_stream(), media_type="text/event-stream")
    fallback = StreamingResponse(fallback_stream(), media_type="text/event-stream")
    native = _Executor(
        native_recorder,
        result=(
            selected if mode is ResponsesExecutionMode.NATIVE_GIGACHAT else fallback
        ),
    )
    normalized = _Executor(
        normalized_recorder,
        result=(
            selected if mode is ResponsesExecutionMode.NORMALIZED_BRIDGE else fallback
        ),
    )
    selections = _install_dispatch(
        monkeypatch,
        mode=mode,
        native=native,
        normalized=normalized,
    )

    response = TestClient(_app()).post(
        "/responses",
        json={"model": "selected-model", "input": "hello", "stream": True},
    )

    assert response.status_code == 200
    assert selections == ["selected-model"]
    assert response.text.count("selected-byte") == 1
    assert response.text.count("completed-byte") == 1
    assert "duplicate-byte" not in response.text
    if mode is ResponsesExecutionMode.NATIVE_GIGACHAT:
        assert (native_recorder.calls, normalized_recorder.calls) == (1, 0)
    else:
        assert (native_recorder.calls, normalized_recorder.calls) == (0, 1)
