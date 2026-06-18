import asyncio
import json
import time
from datetime import datetime, timezone

import pytest

from gpt2giga.core.context import RequestContext
from gpt2giga.models.config import FusionSettings
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.providers.fusion.adapter import FusionProviderAdapter
from gpt2giga.providers.fusion.detection import FusionRequestConfig


class FakeProvider:
    def __init__(self, responses=None, delays=None, errors=None):
        self.responses = responses or {}
        self.delays = delays or {}
        self.errors = errors or {}
        self.calls = []
        self.cancelled_models = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def chat(self, request, *, context=None):
        self.calls.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            delay = self.delays.get(request.model, 0)
            if delay:
                await asyncio.sleep(delay)
            error = self.errors.get(request.model)
            if error is not None:
                raise error
            response = self.responses.get(request.model)
            if callable(response):
                return response(request)
            if response is not None:
                return response
            return _text_response(request.model, f"{request.model} answer")
        except asyncio.CancelledError:
            self.cancelled_models.append(request.model)
            raise
        finally:
            self.in_flight -= 1


def _request() -> NormalizedChatRequest:
    return NormalizedChatRequest(
        model="gpt2giga/fusion-code",
        stream=True,
        messages=[NormalizedMessage(role="user", content="Implement it")],
    )


def _fusion_config(**overrides) -> FusionRequestConfig:
    values = {
        "source": "model",
        "requested_model": "gpt2giga/fusion-code",
        "preset": "code-budget",
        "analysis_models": ["PanelA", "PanelB"],
        "judge_model": "Judge",
        "panel_roles": ["implementer", "reviewer"],
        "temperature": 0.1,
        "max_completion_tokens": 512,
        "min_successful_panels": 1,
        "timeout_seconds": 1.0,
        "tools_mode": "schema_only",
    }
    values.update(overrides)
    return FusionRequestConfig(**values)


def _adapter(provider, **settings_overrides) -> FusionProviderAdapter:
    settings = {
        "enabled": True,
        "max_panel_concurrency": 2,
    }
    settings.update(settings_overrides)
    return FusionProviderAdapter(
        settings=FusionSettings(**settings),
        upstream_provider=provider,
    )


def _context() -> RequestContext:
    return RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="openai",
        route="/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )


def _text_response(
    model: str | None,
    content: str,
    *,
    usage: NormalizedUsage | None = None,
) -> NormalizedResponse:
    return NormalizedResponse(
        model=model,
        provider="fake",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=usage,
    )


def _tool_response(
    model: str | None,
    tool_call: NormalizedToolCall,
) -> NormalizedResponse:
    return NormalizedResponse(
        model=model,
        provider="fake",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[tool_call],
                ),
                finish_reason="tool_calls",
            )
        ],
    )


def _judge_json(final_answer="final answer", final_tool_call=None) -> str:
    return json.dumps(
        {
            "consensus": ["Both panels agree."],
            "contradictions": [],
            "partial_coverage": [],
            "unique_insights": [],
            "blind_spots": [],
            "risk_flags": [],
            "selected_strategy": "Use the safer change.",
            "final_answer": final_answer,
            "final_tool_call": final_tool_call,
        }
    )


async def test_fusion_adapter_runs_panels_in_parallel_and_judges_result():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response(
                "PanelA",
                "A answer",
                usage=NormalizedUsage(
                    input_tokens=1,
                    output_tokens=2,
                    total_tokens=3,
                ),
            ),
            "PanelB": _text_response(
                "PanelB",
                "B answer",
                usage=NormalizedUsage(
                    input_tokens=4,
                    output_tokens=5,
                    total_tokens=9,
                ),
            ),
            "Judge": _text_response(
                "Judge",
                _judge_json("merged final"),
                usage=NormalizedUsage(
                    input_tokens=10,
                    output_tokens=11,
                    total_tokens=21,
                ),
            ),
        },
        delays={"PanelA": 0.05, "PanelB": 0.05},
    )

    response = await _adapter(provider).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(),
    )

    assert response.id == "req-1"
    assert response.model == "gpt2giga/fusion-code"
    assert response.provider == "fusion"
    assert response.choices[0].message.content == "merged final"
    assert response.usage.input_tokens == 15
    assert response.usage.output_tokens == 18
    assert response.usage.total_tokens == 33
    assert provider.max_in_flight == 2
    assert [call.model for call in provider.calls] == ["PanelA", "PanelB", "Judge"]
    assert provider.calls[0].stream is False
    assert provider.calls[0].generation_config.temperature == 0.1
    assert provider.calls[0].generation_config.max_tokens == 512
    assert "likely files" in provider.calls[0].messages[0].content
    assert "Panel responses" in provider.calls[-1].messages[-1].content
    assert response.metadata["gpt2giga_fusion_successful_panels"] == "2"


async def test_fusion_adapter_times_out_one_panel_and_continues():
    provider = FakeProvider(
        responses={
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response("Judge", _judge_json("judge final")),
        },
        delays={"PanelA": 0.05},
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(timeout_seconds=0.01),
    )

    assert response.error is None
    assert response.choices[0].message.content == "judge final"
    assert response.metadata["gpt2giga_fusion_failed_panels"] == "1"
    panel_metadata = response.provider_metadata["fusion"]["panel_results"]
    assert panel_metadata[0]["status"] == "timeout"
    assert panel_metadata[0]["error_type"] == "timeout"
    assert panel_metadata[0].get("content") is None


async def test_fusion_adapter_returns_error_when_success_threshold_not_met():
    provider = FakeProvider(
        errors={
            "PanelA": RuntimeError("boom"),
            "PanelB": RuntimeError("boom"),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(min_successful_panels=1),
    )

    assert response.error is not None
    assert response.error.code == "all_panels_failed"
    assert response.choices == []
    assert response.metadata["gpt2giga_fusion_failed_panels"] == "2"
    assert [call.model for call in provider.calls] == ["PanelA", "PanelB"]


async def test_fusion_adapter_falls_back_to_panel_when_judge_json_is_invalid():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A usable answer"),
            "PanelB": _text_response("PanelB", "B usable answer"),
            "Judge": _text_response("Judge", "not json"),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(),
    )

    assert response.choices[0].message.content == "A usable answer"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == "invalid_judge_json"


async def test_fusion_adapter_strips_tools_from_panels_and_allows_final_tool_call():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "Use lookup."),
            "PanelB": _text_response("PanelB", "Use lookup with q."),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer=None,
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "lookup",
                        "arguments": {"q": "ping"},
                    },
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    panel_calls = provider.calls[:2]
    judge_call = provider.calls[-1]
    assert panel_calls[0].tools == []
    assert "Tool schemas are reference-only" in panel_calls[0].messages[1].content
    assert judge_call.tools == [tool]
    message = response.choices[0].message
    assert message.content is None
    assert message.tool_calls == [
        NormalizedToolCall(
            id="call-1",
            type="function",
            name="lookup",
            arguments={"q": "ping"},
        )
    ]
    assert response.choices[0].finish_reason == "tool_calls"


async def test_fusion_adapter_tools_mode_off_strips_judge_tools_and_ignores_tool_call():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A answer"),
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer="text answer",
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "lookup",
                        "arguments": {"q": "ping"},
                    },
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(tools_mode="off"),
    )

    judge_call = provider.calls[-1]
    assert judge_call.tools == []
    assert judge_call.tool_choice is None
    assert response.choices[0].message.content == "text answer"
    assert response.choices[0].message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"


async def test_fusion_adapter_final_arbitration_passes_panel_candidates_to_judge():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    provider = FakeProvider(
        responses={
            "PanelA": _tool_response(
                "PanelA",
                NormalizedToolCall(
                    id="call-panel",
                    name="lookup",
                    arguments={"q": "from call"},
                ),
            ),
            "PanelB": _text_response(
                "PanelB",
                '{"tool_call_candidate": {"name": "lookup", "arguments": {"q": "text"}}}',
            ),
            "Judge": _text_response("Judge", _judge_json("final text")),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(tools_mode="final_arbitration"),
    )

    panel_calls = provider.calls[:2]
    judge_call = provider.calls[-1]
    assert panel_calls[0].tools == []
    assert panel_calls[1].tools == []
    assert judge_call.tools == [tool]
    judge_prompt = "\n\n".join(message.content or "" for message in judge_call.messages)
    assert "panel_tool_candidates" in judge_prompt
    assert "call-panel" in judge_prompt
    assert "from call" in judge_prompt
    assert "text" in judge_prompt
    assert response.choices[0].message.content == "final text"


async def test_fusion_adapter_required_tool_choice_errors_when_finalizer_returns_text():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    request.tool_choice = "required"
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A answer"),
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response("Judge", _judge_json("text only")),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    assert response.error is not None
    assert response.error.code == "fusion_tool_required"
    assert response.choices == []
    assert (
        response.metadata["gpt2giga_fusion_fallback_reason"]
        == "required_tool_call_missing"
    )


async def test_fusion_adapter_never_forwards_panel_tool_call_as_fallback():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    provider = FakeProvider(
        responses={
            "PanelA": _tool_response(
                "PanelA",
                NormalizedToolCall(
                    id="call-panel",
                    name="lookup",
                    arguments={"q": "from call"},
                ),
            ),
            "Judge": _text_response("Judge", "not json"),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["implementer"],
        ),
    )

    assert response.error is not None
    assert response.error.code == "empty_fusion_result"
    assert response.choices == []
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == "invalid_judge_json"


async def test_fusion_adapter_cancels_panel_tasks_on_disconnect():
    provider = FakeProvider(delays={"PanelA": 1.0, "PanelB": 1.0})
    checks = 0

    async def is_disconnected():
        nonlocal checks
        checks += 1
        return checks > 3

    started = time.perf_counter()
    with pytest.raises(asyncio.CancelledError):
        await _adapter(provider).chat(
            _request(),
            fusion_config=_fusion_config(timeout_seconds=1.0),
            is_disconnected=is_disconnected,
        )

    assert time.perf_counter() - started < 0.5
    assert sorted(provider.cancelled_models) == ["PanelA", "PanelB"]
