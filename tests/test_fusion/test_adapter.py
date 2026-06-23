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
from gpt2giga.providers.fusion.limiter import FusionRequestLimiter


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


class RecordingMetricsSink:
    def __init__(self):
        self.increments = []
        self.observations = []

    async def increment(self, name, value=1, attributes=None):
        self.increments.append((name, value, attributes or {}))

    async def observe(self, name, value, attributes=None):
        self.observations.append((name, value, attributes or {}))

    async def flush(self):
        return None


class RecordingObservabilitySink:
    def __init__(self):
        self.events = []

    async def emit(self, name, attributes=None, *, context=None, events=None):
        self.events.append((name, attributes or {}, context, events or []))

    async def flush(self):
        return None


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
        "invocation_mode": "force",
        "decision_mode": "synthesize",
        "prompt_mode": "full",
        "min_successful_panels": 1,
        "timeout_seconds": 1.0,
        "tools_mode": "schema_only",
    }
    values.update(overrides)
    return FusionRequestConfig(**values)


def _adapter(
    provider,
    *,
    metrics_sink=None,
    observability_sink=None,
    request_limiter=None,
    **settings_overrides,
) -> FusionProviderAdapter:
    settings = {
        "enabled": True,
        "max_panel_concurrency": 2,
    }
    settings.update(settings_overrides)
    return FusionProviderAdapter(
        settings=FusionSettings(**settings),
        upstream_provider=provider,
        metrics_sink=metrics_sink,
        observability_sink=observability_sink,
        request_limiter=request_limiter,
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


def _write_file_tool() -> NormalizedTool:
    return NormalizedTool(
        name="write_file",
        description="Write a file",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    )


def _weather_tool() -> NormalizedTool:
    return NormalizedTool(
        name="get_weather",
        description="Get weather",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["city", "date"],
        },
    )


def _hotel_tool() -> NormalizedTool:
    return NormalizedTool(
        name="find_hotel",
        description="Find a hotel",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "nights": {"type": "integer"},
                "max_price_rub": {"type": "integer"},
            },
            "required": ["city", "nights", "max_price_rub"],
        },
    )


def _currency_tool() -> NormalizedTool:
    return NormalizedTool(
        name="convert_currency",
        description="Convert currency",
        parameters={
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "from_currency": {"type": "string"},
                "to_currency": {"type": "string"},
            },
            "required": ["amount", "from_currency", "to_currency"],
        },
    )


def _judge_json(
    final_answer="final answer", final_tool_call=None, task_status=None
) -> str:
    payload = {
        "schema_version": "gpt2giga.fusion.analysis.v1",
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
    if task_status is not None:
        payload["task_status"] = task_status
    return json.dumps(payload)


def _judge_analysis_json(recommendation="Use the combined answer.") -> str:
    return json.dumps(
        {
            "schema_version": "gpt2giga.fusion.analysis.v1",
            "consensus": ["Panels agree on the main answer."],
            "contradictions": [],
            "partial_coverage": [],
            "unique_insights": [],
            "blind_spots": [],
            "risk_flags": [],
            "recommendation": recommendation,
        }
    )


def _verification_json(
    *,
    verdict="approve",
    checked_candidate_id="direct",
    concrete_issues=None,
    corrected_tool_call=None,
    missing_requirements_after_action=None,
    all_required_data_present=False,
) -> str:
    return json.dumps(
        {
            "schema_version": "gpt2giga.fusion.verification.v1",
            "checked_candidate_id": checked_candidate_id,
            "verdict": verdict,
            "concrete_issues": concrete_issues or [],
            "corrected_tool_call": corrected_tool_call,
            "missing_requirements_after_action": (
                missing_requirements_after_action or []
            ),
            "all_required_data_present": all_required_data_present,
            "reason_brief": "checked",
        }
    )


def _action_json(
    *,
    action_type,
    task_status,
    tool_call=None,
    final_answer=None,
    missing_requirements=None,
    selected_candidate_id="direct",
) -> str:
    return json.dumps(
        {
            "schema_version": "gpt2giga.fusion.action_decision.v1",
            "task_status": task_status,
            "action_type": action_type,
            "selected_candidate_id": selected_candidate_id,
            "tool_call": tool_call,
            "final_answer": final_answer,
            "missing_requirements": missing_requirements or [],
            "verifier_findings": [],
            "direct_candidate_errors": [],
            "confidence": 1.0,
            "reason_brief": "next action",
        }
    )


def _selection_json(
    selected_candidate_id="direct",
    *,
    confidence=0.9,
    needs_rewrite=False,
    correction=None,
) -> str:
    return json.dumps(
        {
            "schema_version": "gpt2giga.fusion.selection.v1",
            "selected_candidate_id": selected_candidate_id,
            "confidence": confidence,
            "needs_rewrite": needs_rewrite,
            "correction": correction,
            "reason_brief": "best candidate",
        }
    )


async def test_fusion_adapter_outer_auto_simple_prompt_skips_panels():
    provider = FakeProvider(
        responses={"Outer": _text_response("Outer", "direct answer")}
    )

    response = await _adapter(provider).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(
            invocation_mode="outer_auto",
            decision_mode="tool_result",
            prompt_mode="minimal",
            direct_model="Outer",
        ),
    )

    assert response.choices[0].message.content == "direct answer"
    assert [call.model for call in provider.calls] == ["Outer"]
    assert [tool.name for tool in provider.calls[0].tools] == ["openrouter.fusion"]
    assert response.choices[0].message.tool_calls == []


async def test_fusion_adapter_outer_auto_complex_prompt_invokes_fusion():
    provider = FakeProvider(
        responses={
            "Outer": _tool_response(
                "Outer",
                NormalizedToolCall(
                    id="fusion-call",
                    name="openrouter:fusion",
                    arguments={},
                ),
            ),
            "PanelA": _text_response("PanelA", "A analysis"),
            "PanelB": _text_response("PanelB", "B analysis"),
            "Judge": _text_response("Judge", _judge_analysis_json()),
            "Final": _text_response("Final", "final answer"),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(
            invocation_mode="outer_auto",
            decision_mode="tool_result",
            prompt_mode="minimal",
            direct_model="Outer",
            final_model="Final",
        ),
    )

    assert response.choices[0].message.content == "final answer"
    assert provider.calls[0].model == "Outer"
    assert {provider.calls[1].model, provider.calls[2].model} == {"PanelA", "PanelB"}
    assert [call.model for call in provider.calls[3:]] == ["Judge", "Final"]
    final_call = provider.calls[-1]
    assert all(tool.name != "openrouter.fusion" for tool in final_call.tools)
    tool_result = json.loads(final_call.messages[-1].content)
    assert tool_result["status"] == "ok"
    assert tool_result["analysis"]["recommendation"] == "Use the combined answer."
    assert "final_answer" not in tool_result["analysis"]
    assert response.choices[0].message.tool_calls == []


async def test_fusion_adapter_outer_auto_forced_tool_choice_invokes_fusion():
    provider = FakeProvider(
        responses={
            "Outer": _text_response("Outer", "ignored direct answer"),
            "PanelA": _text_response("PanelA", "A analysis"),
            "Judge": _text_response("Judge", _judge_analysis_json()),
            "Final": _text_response("Final", "forced final"),
        }
    )
    request = _request()
    request.tool_choice = {
        "type": "function",
        "function": {"name": "openrouter:fusion"},
    }

    response = await _adapter(provider).chat(
        request,
        context=_context(),
        fusion_config=_fusion_config(
            invocation_mode="outer_auto",
            decision_mode="tool_result",
            prompt_mode="minimal",
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Outer",
            final_model="Final",
        ),
    )

    assert response.choices[0].message.content == "forced final"
    assert [call.model for call in provider.calls] == [
        "Outer",
        "PanelA",
        "Judge",
        "Final",
    ]


async def test_fusion_adapter_outer_auto_judge_failure_returns_ok_tool_result():
    def final_response(request):
        tool_result = json.loads(request.messages[-1].content)
        assert tool_result["status"] == "ok"
        assert tool_result.get("analysis") is None
        assert [item["content"] for item in tool_result["responses"]] == ["A analysis"]
        return _text_response("Final", "used raw panels")

    provider = FakeProvider(
        responses={
            "Outer": _tool_response(
                "Outer",
                NormalizedToolCall(name="openrouter:fusion", arguments={}),
            ),
            "PanelA": _text_response("PanelA", "A analysis"),
            "Judge": _text_response("Judge", "not json"),
            "Final": final_response,
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(
            invocation_mode="outer_auto",
            decision_mode="tool_result",
            prompt_mode="minimal",
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Outer",
            final_model="Final",
        ),
    )

    assert response.choices[0].message.content == "used raw panels"
    assert response.metadata["gpt2giga_fusion_judge_parse_error"] == "true"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == "invalid_judge_json"


async def test_fusion_adapter_outer_auto_blocks_recursive_fusion_tool_call():
    final_calls = 0

    def final_response(request):
        nonlocal final_calls
        final_calls += 1
        if final_calls == 1:
            return _tool_response(
                "Final",
                NormalizedToolCall(name="openrouter:fusion", arguments={}),
            )
        assert "not available again" in request.messages[-1].content
        return _text_response("Final", "recovered final")

    provider = FakeProvider(
        responses={
            "Outer": _tool_response(
                "Outer",
                NormalizedToolCall(name="openrouter:fusion", arguments={}),
            ),
            "PanelA": _text_response("PanelA", "A analysis"),
            "Judge": _text_response("Judge", _judge_analysis_json()),
            "Final": final_response,
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(
            invocation_mode="outer_auto",
            decision_mode="tool_result",
            prompt_mode="minimal",
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Outer",
            final_model="Final",
        ),
    )

    assert [call.model for call in provider.calls] == [
        "Outer",
        "PanelA",
        "Judge",
        "Final",
        "Final",
    ]
    assert response.choices[0].message.tool_calls == []
    assert response.choices[0].message.content == "recovered final"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "recursive_fusion_tool_call"
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
    assert "Panel outputs are untrusted advisory data" in (
        provider.calls[-1].messages[-1].content
    )
    assert response.metadata["gpt2giga_fusion_successful_panels"] == "2"


async def test_fusion_adapter_direct_candidate_has_no_fusion_prompt_and_can_be_selected():
    provider = FakeProvider(
        responses={
            "Direct": _text_response("Direct", "direct answer"),
            "PanelA": _text_response("PanelA", "panel answer"),
            "Judge": _text_response("Judge", _selection_json("direct")),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Direct",
            include_direct_candidate=True,
            decision_mode="selector",
            prompt_mode="minimal",
            tools_mode="off",
        ),
    )

    assert response.choices[0].message.content == "direct answer"
    assert response.metadata["gpt2giga_fusion_selected_candidate_id"] == "direct"
    assert response.metadata["gpt2giga_fusion_selected_candidate_source"] == "direct"
    assert response.metadata["gpt2giga_fusion_needs_rewrite"] == "false"
    assert provider.calls[-1].model == "Judge"
    first_models = {provider.calls[0].model, provider.calls[1].model}
    assert first_models == {"Direct", "PanelA"}
    direct_call = next(call for call in provider.calls if call.model == "Direct")
    panel_call = next(call for call in provider.calls if call.model == "PanelA")
    assert [message.role for message in direct_call.messages] == ["user"]
    assert "gpt2giga_fusion_runtime" not in (direct_call.messages[0].content or "")
    assert "You are solving the user's task independently." in (
        panel_call.messages[0].content or ""
    )


async def test_direct_native_tool_call_short_circuits_panels_and_selector():
    request = _request()
    request.tools = [_weather_tool()]
    direct_call = NormalizedToolCall(
        id="call-weather",
        name="get_weather",
        arguments={"city": "Saint Petersburg", "date": "tomorrow"},
    )
    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", direct_call),
            "PanelA": _text_response(
                "PanelA",
                json.dumps(
                    {
                        "tool_call_candidate": {
                            "name": "get_weather",
                            "arguments": {
                                "city": "Saint Pyotrsburg",
                                "date": "tomorrow",
                            },
                        }
                    }
                ),
            ),
            "Judge": _text_response("Judge", _selection_json("panel_1")),
        }
    )

    response = await _adapter(provider).chat(
        request,
        context=_context(),
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Direct",
            include_direct_candidate=True,
            decision_mode="selector",
        ),
    )

    message = response.choices[0].message
    assert [call.model for call in provider.calls] == ["Direct"]
    assert message.content is None
    assert message.tool_calls == [direct_call]
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.metadata["gpt2giga_fusion_selected_candidate_id"] == "direct"


async def test_selector_prefers_valid_direct_native_tool_over_panel_advisory_tool():
    request = _request()
    request.tools = [_weather_tool()]
    direct_call = NormalizedToolCall(
        id="call-weather",
        name="get_weather",
        arguments={"city": "Saint Petersburg", "date": "tomorrow"},
    )

    def judge_response(selector_request):
        prompt = selector_request.messages[-1].content
        assert '"city": "Saint Petersburg"' in prompt
        assert '"city": "Saint Pyotrsburg"' in prompt
        assert '"native": true' in prompt
        assert '"advisory": true' in prompt
        assert '"valid": true' in prompt
        assert '"repeated": false' in prompt
        assert '"meta": false' in prompt
        return _text_response("Judge", _selection_json("panel_1"))

    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", direct_call),
            "PanelA": _text_response(
                "PanelA",
                json.dumps(
                    {
                        "tool_call_candidate": {
                            "name": "get_weather",
                            "arguments": {
                                "city": "Saint Pyotrsburg",
                                "date": "tomorrow",
                            },
                        }
                    }
                ),
            ),
            "Judge": judge_response,
        }
    )

    response = await _adapter(provider).chat(
        request,
        context=_context(),
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Direct",
            include_direct_candidate=True,
            decision_mode="selector",
            direct_tool_call_policy="selector",
        ),
    )

    message = response.choices[0].message
    assert [call.model for call in provider.calls] == ["Direct", "PanelA", "Judge"]
    assert message.tool_calls == [direct_call]
    assert response.metadata["gpt2giga_fusion_selected_candidate_id"] == "direct"
    assert response.metadata["gpt2giga_fusion_selected_candidate_source"] == "direct"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "direct_native_tool_call_preferred"
    )
    assert response.metadata["gpt2giga_fusion_invocation_mode"] == "force"
    assert response.metadata["gpt2giga_fusion_decision_mode"] == "selector"
    assert response.metadata["gpt2giga_fusion_tools_mode"] == "schema_only"
    assert response.metadata["gpt2giga_fusion_direct_tool_call_policy"] == "selector"
    assert response.metadata["gpt2giga_fusion_post_tool_mode"] == "direct_continuation"


async def test_selector_selected_panel_advisory_tool_returns_tool_call():
    request = _request()
    request.tools = [_write_file_tool()]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response(
                "PanelA",
                (
                    "```json\n"
                    '{"name":"write_file","parameters":'
                    '{"file_path":"hello.py","content":"print(1)"}}'
                    "\n```"
                ),
            ),
            "Judge": _text_response("Judge", _selection_json("panel_1")),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["implementer"],
            decision_mode="selector",
        ),
    )

    message = response.choices[0].message
    assert response.error is None
    assert message.content is None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].name == "write_file"
    assert message.tool_calls[0].arguments == {
        "file_path": "hello.py",
        "content": "print(1)",
    }
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.metadata["gpt2giga_fusion_selected_candidate_id"] == "panel_1"


async def test_selector_selected_panel_tool_survives_return_selected_candidate_false():
    request = _request()
    request.tools = [_write_file_tool()]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response(
                "PanelA",
                json.dumps(
                    {
                        "tool_call_candidate": {
                            "name": "write_file",
                            "arguments": {
                                "file_path": "hello.py",
                                "content": "print(1)",
                            },
                        }
                    }
                ),
            ),
            "Judge": _text_response("Judge", _selection_json("panel_1")),
            "Final": _text_response("Final", "should not run"),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["implementer"],
            decision_mode="selector",
            final_model="Final",
            return_selected_candidate=False,
        ),
    )

    assert response.error is None
    assert response.choices[0].message.content is None
    assert response.choices[0].message.tool_calls[0].name == "write_file"
    assert [call.model for call in provider.calls] == ["PanelA", "Judge"]


async def test_selector_invalid_advisory_tool_json_does_not_leak_as_text():
    request = _request()
    request.tools = [_write_file_tool()]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response(
                "PanelA",
                '{"name":"unknown_tool","parameters":{"file_path":"hello.py"}}',
            ),
            "Judge": _text_response("Judge", _selection_json("panel_1")),
            "Final": _text_response("Final", "safe fallback"),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["implementer"],
            decision_mode="selector",
            final_model="Final",
        ),
    )

    assert response.error is None
    assert response.choices[0].message.content == "safe fallback"
    assert response.choices[0].message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"
    assert [call.model for call in provider.calls] == ["PanelA", "Judge", "Final"]


async def test_selector_finalizer_tool_json_does_not_leak_as_text():
    request = _request()
    request.tools = [_write_file_tool()]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response(
                "PanelA",
                '{"name":"write_file","arguments":{"file_path":"hello.py"}}',
            ),
            "Judge": _text_response("Judge", _selection_json("panel_1")),
            "Final": _text_response(
                "Final",
                '```json\n{"name":"write_file","arguments":{"file_path":"hello.py"}}\n```',
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["implementer"],
            decision_mode="selector",
            final_model="Final",
        ),
    )

    assert response.error is not None
    assert response.error.code == "empty_fusion_result"
    assert response.choices == []
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "empty_fusion_result"
    )
    assert [call.model for call in provider.calls] == ["PanelA", "Judge", "Final"]


async def test_fusion_adapter_selector_runs_finalizer_only_when_rewrite_needed():
    provider = FakeProvider(
        responses={
            "Direct": _text_response("Direct", "direct answer"),
            "PanelA": _text_response("PanelA", "panel answer"),
            "Judge": _text_response(
                "Judge",
                _selection_json(
                    "direct",
                    needs_rewrite=True,
                    correction="Make the answer explicit.",
                ),
            ),
            "Final": _text_response("Final", "rewritten answer"),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Direct",
            include_direct_candidate=True,
            decision_mode="selector",
            final_model="Final",
            tools_mode="off",
        ),
    )

    assert response.choices[0].message.content == "rewritten answer"
    assert {provider.calls[0].model, provider.calls[1].model} == {"PanelA", "Direct"}
    assert [call.model for call in provider.calls[2:]] == ["Judge", "Final"]
    finalizer_call = provider.calls[-1]
    assert finalizer_call.metadata["gpt2giga_fusion_stage"] == "selector_finalizer"
    assert "Make the answer explicit." in finalizer_call.messages[-1].content
    assert response.metadata["gpt2giga_fusion_needs_rewrite"] == "true"


async def test_fusion_adapter_preserves_generation_settings_when_preset_values_are_none():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "panel answer"),
            "Judge": _text_response("Judge", _judge_json("final answer")),
        }
    )
    request = _request()
    request.generation_config.temperature = 0.7
    request.generation_config.max_tokens = 123

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            temperature=None,
            max_completion_tokens=None,
        ),
    )

    assert response.choices[0].message.content == "final answer"
    for call in provider.calls:
        assert call.generation_config.temperature == 0.7
        assert call.generation_config.max_tokens == 123


async def test_fusion_adapter_truncates_panel_outputs_before_judge_prompt():
    long_answer = "A" * 200 + "TAIL"

    def judge_response(request):
        prompt = request.messages[-1].content
        assert "...[truncated by gpt2giga fusion]..." in prompt
        assert len(prompt) < 1200
        assert "TAIL" in prompt
        return _text_response("Judge", _judge_json("final answer"))

    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", long_answer),
            "Judge": judge_response,
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            max_panel_output_chars=80,
            max_total_panel_output_chars=80,
        ),
    )

    assert response.choices[0].message.content == "final answer"
    assert response.provider_metadata["fusion"]["panel_truncated"] is True


async def test_fusion_adapter_fallback_prefers_direct_candidate_over_panel_answer():
    provider = FakeProvider(
        responses={
            "Direct": _text_response("Direct", "direct usable answer"),
            "PanelA": _text_response("PanelA", "panel usable answer"),
            "Judge": _text_response("Judge", "not json"),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(
            analysis_models=["PanelA"],
            panel_roles=["solver"],
            direct_model="Direct",
            include_direct_candidate=True,
        ),
    )

    assert response.choices[0].message.content == "direct usable answer"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == "invalid_judge_json"


async def test_fusion_adapter_wraps_client_instructions_without_duplication():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A answer"),
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response("Judge", _judge_json("merged final")),
        }
    )
    request = NormalizedChatRequest(
        model="gpt2giga/fusion-code",
        metadata={"source_protocol": "openai_chat"},
        messages=[
            NormalizedMessage(role="system", content="You are Codex."),
            NormalizedMessage(role="developer", content="Use repository rules."),
            NormalizedMessage(role="user", content="Implement it"),
        ],
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    assert response.choices[0].message.content == "merged final"
    panel_call = provider.calls[0]
    judge_call = provider.calls[-1]
    for call in (panel_call, judge_call):
        envelope = call.messages[0]
        envelope_content = envelope.content or ""
        conversation_content = "\n".join(
            message.content or ""
            for message in call.messages[1:]
            if isinstance(message.content, str)
        )
        assert envelope.role == "system"
        assert '<client_harness_contract source="openai_chat">' in envelope_content
        assert '<instruction index="0" role="system">' in envelope_content
        assert '<instruction index="1" role="developer">' in envelope_content
        assert "You are Codex." in envelope_content
        assert "Use repository rules." in envelope_content
        assert "compatibility behavior expected by the client" in envelope_content
        assert "You are Codex." not in conversation_content
        assert "Use repository rules." not in conversation_content
    assert [message.role for message in panel_call.messages[1:]] == ["user"]
    assert [message.role for message in judge_call.messages[1:-1]] == ["user"]


async def test_fusion_adapter_uses_shared_request_limiter():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A answer"),
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response("Judge", _judge_json("merged final")),
        },
        delays={"PanelA": 0.05, "PanelB": 0.05},
    )
    limiter = FusionRequestLimiter(max_concurrent_requests=1)
    adapter = _adapter(provider, request_limiter=limiter)

    responses = await asyncio.gather(
        adapter.chat(_request(), context=_context(), fusion_config=_fusion_config()),
        adapter.chat(_request(), context=_context(), fusion_config=_fusion_config()),
    )

    assert [response.error for response in responses] == [None, None]
    assert provider.max_in_flight == 2
    assert [call.model for call in provider.calls] == [
        "PanelA",
        "PanelB",
        "Judge",
        "PanelA",
        "PanelB",
        "Judge",
    ]


async def test_fusion_adapter_emits_safe_telemetry_without_prompt_leakage():
    metrics = RecordingMetricsSink()
    observability = RecordingObservabilitySink()
    provider = FakeProvider(
        responses={
            "PanelA": _text_response(
                "PanelA",
                "SECRET_PANEL_A",
                usage=NormalizedUsage(input_tokens=1, output_tokens=2),
            ),
            "PanelB": _text_response("PanelB", "SECRET_PANEL_B"),
            "Judge": _text_response(
                "Judge",
                _judge_json("final answer"),
                usage=NormalizedUsage(input_tokens=3, output_tokens=4),
            ),
        }
    )
    adapter = _adapter(
        provider,
        metrics_sink=metrics,
        observability_sink=observability,
    )
    request = _request()
    request.messages[0].content = "SECRET_PROMPT"

    response = await adapter.chat(
        request,
        context=_context(),
        fusion_config=_fusion_config(),
    )

    assert response.error is None
    assert [event[0] for event in observability.events] == ["GigaFusion"]
    _name, attributes, emitted_context, span_events = observability.events[0]
    assert emitted_context is not None
    dumped = json.dumps(
        {"attributes": attributes, "events": span_events},
        sort_keys=True,
        default=str,
    )
    assert attributes["gpt2giga.provider"] == "fusion"
    assert attributes["gpt2giga.fusion.successful_panel_count"] == 2
    assert "SECRET_PROMPT" not in dumped
    assert "SECRET_PANEL_A" not in dumped
    assert "SECRET_PANEL_B" not in dumped
    assert any(
        name == "gpt2giga_fusion_requests_total"
        and labels == {"preset": "code-budget", "status": "ok"}
        for name, _value, labels in metrics.increments
    )
    assert any(
        name == "gpt2giga_fusion_judge_latency_seconds"
        and labels == {"model": "Judge", "status": "ok"}
        for name, _value, labels in metrics.observations
    )


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


async def test_fusion_adapter_direct_fallback_when_panel_stage_fails_and_flag_disabled():
    provider = FakeProvider(
        responses={
            "Judge": _text_response(
                "Judge",
                "single model fallback",
                usage=NormalizedUsage(input_tokens=3, output_tokens=4),
            ),
        },
        errors={
            "PanelA": RuntimeError("boom"),
            "PanelB": RuntimeError("boom"),
        },
    )

    response = await _adapter(provider, fail_on_all_panels_failed=False).chat(
        _request(),
        context=_context(),
        fusion_config=_fusion_config(min_successful_panels=1),
    )

    assert response.error is None
    assert response.model == "gpt2giga/fusion-code"
    assert response.provider == "fusion"
    assert response.choices[0].message.content == "single model fallback"
    assert response.usage.input_tokens == 3
    assert response.usage.output_tokens == 4
    assert [call.model for call in provider.calls] == ["PanelA", "PanelB", "Judge"]
    assert provider.calls[-1].stream is False
    assert provider.calls[-1].metadata["gpt2giga_fusion_stage"] == "direct_fallback"
    assert response.metadata["gpt2giga_fusion_failed_panels"] == "2"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "all_panels_failed_direct_fallback"
    )


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


async def test_fusion_adapter_repairs_malformed_judge_json_once():
    judge_calls = 0

    def judge_response(request):
        nonlocal judge_calls
        judge_calls += 1
        if request.metadata["gpt2giga_fusion_stage"] == "judge_repair":
            return _text_response("Judge", _judge_json("repaired final"))
        return _text_response(
            "Judge",
            '{"schema_version":"gpt2giga.fusion.analysis.v1","final_answer":"bad",}',
        )

    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A usable answer"),
            "PanelB": _text_response("PanelB", "B usable answer"),
            "Judge": judge_response,
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(),
    )

    assert judge_calls == 2
    assert response.choices[0].message.content == "repaired final"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "judge_repaired:invalid_judge_json"
    )


async def test_fusion_adapter_skips_repair_when_call_budget_is_exhausted():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A usable answer"),
            "PanelB": _text_response("PanelB", "B usable answer"),
            "Judge": _text_response(
                "Judge",
                '{"schema_version":"gpt2giga.fusion.analysis.v1","final_answer":"bad",}',
            ),
        }
    )

    response = await _adapter(
        provider,
        max_total_upstream_calls_per_request=3,
    ).chat(
        _request(),
        fusion_config=_fusion_config(),
    )

    assert [call.model for call in provider.calls] == ["PanelA", "PanelB", "Judge"]
    assert response.choices[0].message.content == "A usable answer"
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == "invalid_judge_json"


async def test_fusion_adapter_accepts_fenced_judge_json():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A usable answer"),
            "PanelB": _text_response("PanelB", "B usable answer"),
            "Judge": _text_response(
                "Judge",
                f"```json\n{_judge_json('fenced final')}\n```",
            ),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(),
    )

    assert response.choices[0].message.content == "fenced final"


async def test_fusion_adapter_accepts_prefixed_judge_json():
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A usable answer"),
            "PanelB": _text_response("PanelB", "B usable answer"),
            "Judge": _text_response(
                "Judge",
                f"Here is the JSON:\n{_judge_json('prefixed final')}\nDone.",
            ),
        }
    )

    response = await _adapter(provider).chat(
        _request(),
        fusion_config=_fusion_config(),
    )

    assert response.choices[0].message.content == "prefixed final"


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
    assert "Tool schemas are reference-only" in panel_calls[0].messages[0].content
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


async def test_fusion_adapter_final_answer_wins_over_meta_tool_call():
    update_topic = NormalizedTool(
        name="update_topic",
        description="Update conversation topic",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [update_topic]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "panel answer"),
            "PanelB": _text_response("PanelB", "panel answer"),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer="hello.py is done",
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "update_topic",
                        "arguments": {"topic": "done"},
                    },
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    message = response.choices[0].message
    assert message.content == "hello.py is done"
    assert message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"


async def test_fusion_adapter_repeated_meta_tool_call_returns_text_fallback():
    update_topic = NormalizedTool(
        name="update_topic",
        description="Update conversation topic",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [update_topic]
    request.messages = [
        NormalizedMessage(role="user", content="Implement it"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-previous",
                    name="update_topic",
                    arguments={"topic": "done"},
                )
            ],
        ),
    ]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "panel fallback answer"),
            "PanelB": _text_response("PanelB", "panel fallback answer"),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer=None,
                    final_tool_call={
                        "id": "call-next",
                        "type": "function",
                        "name": "update_topic",
                        "arguments": {"topic": "done"},
                    },
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    message = response.choices[0].message
    assert message.content == "panel fallback answer"
    assert message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"
    assert (
        response.metadata["gpt2giga_fusion_fallback_reason"]
        == "repeated_final_tool_call"
    )


async def test_fusion_adapter_complete_task_status_drops_tool_call():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "panel answer"),
            "PanelB": _text_response("PanelB", "panel answer"),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer="task complete",
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "lookup",
                        "arguments": {"q": "ping"},
                    },
                    task_status="complete",
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    message = response.choices[0].message
    assert message.content == "task complete"
    assert message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"


async def test_fusion_adapter_needs_tool_status_preserves_progress_tool_call():
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
            "PanelB": _text_response("PanelB", "Use lookup."),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer="internal rationale",
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "lookup",
                        "arguments": {"q": "ping"},
                    },
                    task_status="needs_tool",
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

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


async def test_fusion_adapter_required_meta_tool_only_returns_safe_error():
    update_topic = NormalizedTool(
        name="update_topic",
        description="Update conversation topic",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [update_topic]
    request.tool_choice = "required"
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A answer"),
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer=None,
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "update_topic",
                        "arguments": {"topic": "done"},
                    },
                    task_status="needs_tool",
                ),
            ),
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
        response.metadata["gpt2giga_fusion_fallback_reason"] == "meta_final_tool_call"
    )


async def test_post_tool_turn_uses_direct_continuation_with_tools_enabled():
    request = _request()
    request.tools = [_weather_tool(), _hotel_tool()]
    request.messages = [
        NormalizedMessage(
            role="user",
            content=(
                "Plan a 2-night trip to Saint Petersburg tomorrow using weather "
                "and hotel data."
            ),
        ),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-weather",
                    name="get_weather",
                    arguments={"city": "Saint Petersburg", "date": "tomorrow"},
                )
            ],
        ),
        NormalizedMessage(
            role="tool",
            content="weather result",
            tool_call_id="call-weather",
        ),
    ]
    hotel_call = NormalizedToolCall(
        id="call-hotel",
        name="find_hotel",
        arguments={
            "city": "Saint Petersburg",
            "nights": 2,
            "max_price_rub": 15000,
        },
    )
    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", hotel_call),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(direct_model="Direct"),
    )

    assert response.error is None
    assert response.choices[0].message.tool_calls == [hotel_call]
    assert response.choices[0].finish_reason == "tool_calls"
    assert [call.model for call in provider.calls] == ["Direct"]
    assert [tool.name for tool in provider.calls[0].tools] == [
        "get_weather",
        "find_hotel",
    ]
    assert provider.calls[0].metadata["gpt2giga_fusion_stage"] == "outer_direct"


async def test_verified_tool_loop_first_turn_returns_direct_native_tool_call():
    request = _request()
    request.tools = [_weather_tool(), _hotel_tool(), _currency_tool()]
    direct_call = NormalizedToolCall(
        id="call-weather",
        name="get_weather",
        arguments={"city": "Saint Petersburg", "date": "tomorrow"},
    )

    def action_judge_response(judge_request):
        assert judge_request.metadata["gpt2giga_fusion_stage"] == "action_judge"
        assert judge_request.tools == []
        prompt = judge_request.messages[-1].content
        assert '"already_called_tools": []' in prompt
        assert '"name": "get_weather"' in prompt
        return _text_response(
            "Judge",
            _action_json(
                action_type="tool_call",
                task_status="needs_tool",
                tool_call=direct_call.model_dump(mode="json", exclude_none=True),
                missing_requirements=["weather is needed"],
            ),
        )

    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", direct_call),
            "Verifier": _text_response(
                "Verifier",
                _verification_json(
                    verdict="approve",
                    missing_requirements_after_action=["hotel", "currency"],
                ),
            ),
            "Judge": action_judge_response,
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["Verifier"],
            judge_model="Judge",
            direct_model="Direct",
            panel_roles=["verifier"],
            include_direct_candidate=True,
            decision_mode="action",
            post_tool_mode="verified_continuation",
            direct_tool_call_policy="verify_before_return",
        ),
    )

    assert response.error is None
    assert [call.model for call in provider.calls] == ["Direct", "Verifier", "Judge"]
    message = response.choices[0].message
    assert message.tool_calls == [direct_call]
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.metadata["gpt2giga_fusion_decision_mode"] == "action"
    assert response.metadata["gpt2giga_fusion_selected_candidate_id"] == "direct"


async def test_verified_tool_loop_post_tool_continues_with_tools_enabled():
    request = _request()
    request.tools = [_weather_tool(), _hotel_tool(), _currency_tool()]
    request.messages = [
        NormalizedMessage(role="user", content="Plan a trip"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-weather",
                    name="get_weather",
                    arguments={"city": "Saint Petersburg", "date": "tomorrow"},
                )
            ],
        ),
        NormalizedMessage(
            role="tool",
            tool_call_id="call-weather",
            content='{"forecast":"snow"}',
        ),
    ]
    hotel_call = NormalizedToolCall(
        id="call-hotel",
        name="find_hotel",
        arguments={
            "city": "Saint Petersburg",
            "nights": 2,
            "max_price_rub": 12000,
        },
    )

    def direct_response(direct_request):
        assert direct_request.metadata["gpt2giga_fusion_stage"] == "direct_candidate"
        assert [tool.name for tool in direct_request.tools] == [
            "get_weather",
            "find_hotel",
            "convert_currency",
        ]
        return _tool_response("Direct", hotel_call)

    def action_judge_response(judge_request):
        prompt = judge_request.messages[-1].content
        assert '"name": "get_weather"' in prompt
        assert '"result_present": true' in prompt
        stages = {call.metadata.get("gpt2giga_fusion_stage") for call in provider.calls}
        assert "post_tool_finalizer" not in stages
        return _text_response(
            "Judge",
            _action_json(
                action_type="tool_call",
                task_status="needs_tool",
                tool_call=hotel_call.model_dump(mode="json", exclude_none=True),
                missing_requirements=["currency conversion is still needed"],
            ),
        )

    provider = FakeProvider(
        responses={
            "Direct": direct_response,
            "Verifier": _text_response(
                "Verifier",
                _verification_json(verdict="approve"),
            ),
            "Judge": action_judge_response,
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["Verifier"],
            judge_model="Judge",
            direct_model="Direct",
            panel_roles=["verifier"],
            include_direct_candidate=True,
            decision_mode="action",
            post_tool_mode="verified_continuation",
            direct_tool_call_policy="verify_before_return",
        ),
    )

    assert response.error is None
    assert response.choices[0].message.tool_calls == [hotel_call]
    assert [call.model for call in provider.calls] == ["Direct", "Verifier", "Judge"]


async def test_verified_tool_loop_final_answer_uses_action_decision():
    request = _request()
    request.tools = [_weather_tool(), _hotel_tool(), _currency_tool()]
    request.messages = [
        NormalizedMessage(role="user", content="Plan a trip"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-weather",
                    name="get_weather",
                    arguments={"city": "Saint Petersburg", "date": "tomorrow"},
                )
            ],
        ),
        NormalizedMessage(role="tool", tool_call_id="call-weather", content="snow"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-hotel",
                    name="find_hotel",
                    arguments={
                        "city": "Saint Petersburg",
                        "nights": 2,
                        "max_price_rub": 12000,
                    },
                )
            ],
        ),
        NormalizedMessage(role="tool", tool_call_id="call-hotel", content="Nevsky"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-currency",
                    name="convert_currency",
                    arguments={
                        "amount": 12000,
                        "from_currency": "RUB",
                        "to_currency": "USD",
                    },
                )
            ],
        ),
        NormalizedMessage(role="tool", tool_call_id="call-currency", content="$150"),
    ]

    provider = FakeProvider(
        responses={
            "Direct": _text_response("Direct", "unsafe direct answer"),
            "Verifier": _text_response(
                "Verifier",
                _verification_json(
                    verdict="complete",
                    all_required_data_present=True,
                ),
            ),
            "Judge": _text_response(
                "Judge",
                _action_json(
                    action_type="answer",
                    task_status="complete",
                    final_answer="Weather: snow. Hotel: Nevsky. Budget: $150.",
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["Verifier"],
            judge_model="Judge",
            direct_model="Direct",
            panel_roles=["verifier"],
            include_direct_candidate=True,
            decision_mode="action",
            post_tool_mode="verified_continuation",
            direct_tool_call_policy="verify_before_return",
        ),
    )

    assert response.error is None
    assert response.choices[0].message.content == (
        "Weather: snow. Hotel: Nevsky. Budget: $150."
    )
    assert response.choices[0].message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"


async def test_verified_tool_loop_prefers_valid_direct_over_corrected_typo():
    request = _request()
    request.tools = [_weather_tool()]
    direct_call = NormalizedToolCall(
        id="call-weather",
        name="get_weather",
        arguments={"city": "Saint Petersburg", "date": "tomorrow"},
    )
    typo_call = NormalizedToolCall(
        id="call-weather-typo",
        name="get_weather",
        arguments={"city": "Saint Pyotrsburg", "date": "tomorrow"},
    )
    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", direct_call),
            "Verifier": _text_response(
                "Verifier",
                _verification_json(verdict="approve"),
            ),
            "Judge": _text_response(
                "Judge",
                _action_json(
                    action_type="tool_call",
                    task_status="needs_tool",
                    tool_call=typo_call.model_dump(mode="json", exclude_none=True),
                    selected_candidate_id="verifier",
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["Verifier"],
            judge_model="Judge",
            direct_model="Direct",
            panel_roles=["verifier"],
            include_direct_candidate=True,
            decision_mode="action",
            post_tool_mode="verified_continuation",
            direct_tool_call_policy="verify_before_return",
        ),
    )

    assert response.error is None
    assert response.choices[0].message.tool_calls == [direct_call]
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "direct_native_tool_call_preferred"
    )


async def test_verified_tool_loop_blocks_repeated_identical_tool_call():
    request = _request()
    request.tools = [_weather_tool()]
    repeated_call = NormalizedToolCall(
        id="call-weather-repeat",
        name="get_weather",
        arguments={"city": "Saint Petersburg", "date": "tomorrow"},
    )
    request.messages = [
        NormalizedMessage(role="user", content="Check weather"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-weather",
                    name="get_weather",
                    arguments={"city": "Saint Petersburg", "date": "tomorrow"},
                )
            ],
        ),
        NormalizedMessage(role="tool", tool_call_id="call-weather", content="snow"),
    ]
    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", repeated_call),
            "Verifier": _text_response(
                "Verifier",
                _verification_json(verdict="approve"),
            ),
            "Judge": _text_response(
                "Judge",
                _action_json(
                    action_type="tool_call",
                    task_status="needs_tool",
                    tool_call=repeated_call.model_dump(mode="json", exclude_none=True),
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(
            analysis_models=["Verifier"],
            judge_model="Judge",
            direct_model="Direct",
            panel_roles=["verifier"],
            include_direct_candidate=True,
            decision_mode="action",
            post_tool_mode="verified_continuation",
            direct_tool_call_policy="verify_before_return",
        ),
    )

    assert response.error is not None
    assert response.error.code == "fusion_action_failed"
    assert response.choices == []
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "repeated_action_tool_call"
    )


async def test_post_tool_repeated_direct_tool_call_falls_back_to_finalizer():
    request = _request()
    request.tools = [_weather_tool()]
    request.messages = [
        NormalizedMessage(role="user", content="Check weather."),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-weather",
                    name="get_weather",
                    arguments={"city": "Saint Petersburg", "date": "tomorrow"},
                )
            ],
        ),
        NormalizedMessage(
            role="tool",
            content="weather result",
            tool_call_id="call-weather",
        ),
    ]
    repeated_call = NormalizedToolCall(
        id="call-weather-repeat",
        name="get_weather",
        arguments={"city": "Saint Petersburg", "date": "tomorrow"},
    )
    provider = FakeProvider(
        responses={
            "Direct": _tool_response("Direct", repeated_call),
            "Judge": _text_response("Judge", "safe partial answer"),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(direct_model="Direct"),
    )

    assert response.error is None
    assert response.choices[0].message.content == "safe partial answer"
    assert response.choices[0].message.tool_calls == []
    assert [call.model for call in provider.calls] == ["Direct", "Judge"]
    assert response.metadata["gpt2giga_fusion_fallback_reason"] == (
        "post_tool_finalizer"
    )


async def test_fusion_adapter_post_tool_finalize_mode_disables_tools():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={"type": "object"},
    )
    request = _request()
    request.tools = [tool]
    request.messages = [
        NormalizedMessage(role="user", content="Look this up"),
        NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="call-1",
                    name="lookup",
                    arguments={"q": "ping"},
                )
            ],
        ),
        NormalizedMessage(
            role="tool",
            content="lookup result",
            tool_call_id="call-1",
        ),
    ]
    provider = FakeProvider(
        responses={
            "Judge": _text_response("Judge", "final answer from tool result"),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(post_tool_mode="finalize"),
    )

    assert response.error is None
    assert response.choices[0].message.content == "final answer from tool result"
    assert response.choices[0].finish_reason == "stop"
    assert [call.model for call in provider.calls] == ["Judge"]
    assert provider.calls[0].tools == []
    assert provider.calls[0].tool_choice is None
    assert provider.calls[0].metadata["gpt2giga_fusion_stage"] == (
        "post_tool_finalizer"
    )


async def test_fusion_adapter_invalid_final_tool_args_returns_text_when_available():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
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
                    final_answer="fallback text",
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "lookup",
                        "arguments": {"q": 123},
                    },
                ),
            ),
        }
    )

    response = await _adapter(provider).chat(
        request,
        fusion_config=_fusion_config(),
    )

    assert response.error is None
    assert response.choices[0].message.content == "fallback text"
    assert response.choices[0].message.tool_calls == []
    assert (
        response.metadata["gpt2giga_fusion_fallback_reason"]
        == "invalid_final_tool_call"
    )


async def test_fusion_adapter_required_tool_choice_errors_on_invalid_args():
    tool = NormalizedTool(
        name="lookup",
        description="Lookup data",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    )
    request = _request()
    request.tools = [tool]
    request.tool_choice = "required"
    provider = FakeProvider(
        responses={
            "PanelA": _text_response("PanelA", "A answer"),
            "PanelB": _text_response("PanelB", "B answer"),
            "Judge": _text_response(
                "Judge",
                _judge_json(
                    final_answer=None,
                    final_tool_call={
                        "id": "call-1",
                        "type": "function",
                        "name": "lookup",
                        "arguments": {"q": 123},
                    },
                ),
            ),
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
        == "invalid_final_tool_call"
    )


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
