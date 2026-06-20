import json

from gpt2giga.protocols.normalized import NormalizedToolCall, NormalizedUsage
from gpt2giga.providers.fusion.detection import FusionRequestConfig
from gpt2giga.providers.fusion.schemas import (
    FusionCandidate,
    FusionPanelResult,
    FusionRunResult,
    FusionSelection,
)
from gpt2giga.providers.fusion.telemetry import (
    build_fusion_observability_attributes,
    build_fusion_span_events,
    emit_fusion_metrics,
)
from gpt2giga.sinks.metrics.prometheus import PrometheusMetricsSink


def _fusion_config() -> FusionRequestConfig:
    return FusionRequestConfig(
        source="model",
        requested_model="gpt2giga/fusion-code",
        preset="code-high",
        analysis_models=["PanelA", "PanelB"],
        judge_model="Judge",
        tools_mode="schema_only",
    )


def _run_result() -> FusionRunResult:
    return FusionRunResult(
        status="ok",
        requested_model="gpt2giga/fusion-code",
        preset="code-high",
        analysis_models=["PanelA", "PanelB"],
        judge_model="Judge",
        decision_mode="selector",
        prompt_mode="minimal",
        panel_results=[
            FusionPanelResult(
                model="PanelA",
                role="architect",
                status="ok",
                content="SECRET_PANEL_TEXT",
                tool_calls=[
                    NormalizedToolCall(
                        id="call-1",
                        name="write_file",
                        arguments={"path": "SECRET_TOOL_ARG"},
                    )
                ],
                usage=NormalizedUsage(input_tokens=2, output_tokens=3),
                latency_ms=120,
            ),
            FusionPanelResult(
                model="PanelB",
                role="reviewer",
                status="timeout",
                error_type="timeout",
                error_message="SECRET_ERROR_MESSAGE",
                latency_ms=250,
            ),
        ],
        candidates=[
            FusionCandidate(
                candidate_id="direct",
                source="direct",
                model="Judge",
                status="ok",
                content="SECRET_DIRECT_TEXT",
                usage=NormalizedUsage(input_tokens=1, output_tokens=1),
                latency_ms=80,
            ),
            FusionCandidate(
                candidate_id="panel_1",
                source="panel",
                model="PanelA",
                role="architect",
                status="ok",
                content="SECRET_PANEL_TEXT",
                truncated=True,
            ),
        ],
        selection=FusionSelection(
            selected_candidate_id="direct",
            confidence=0.9,
            needs_rewrite=True,
        ),
        selected_candidate_id="direct",
        selected_candidate_source="direct",
        needs_rewrite=True,
        judge_parse_error=True,
        repair_used=True,
        panel_truncated=True,
        failed_models=[
            FusionPanelResult(
                model="PanelB",
                role="reviewer",
                status="timeout",
                error_type="timeout",
                error_message="SECRET_ERROR_MESSAGE",
                latency_ms=250,
            )
        ],
        fallback_reason="invalid_judge_json",
        usage=NormalizedUsage(input_tokens=7, output_tokens=11, total_tokens=18),
        judge_usage=NormalizedUsage(input_tokens=5, output_tokens=8, total_tokens=13),
        finalizer_usage=NormalizedUsage(
            input_tokens=3, output_tokens=4, total_tokens=7
        ),
        latency_ms=420,
        direct_latency_ms=80,
        judge_latency_ms=140,
        finalizer_latency_ms=90,
    )


def test_fusion_observability_attributes_omit_raw_content():
    attributes = build_fusion_observability_attributes(_run_result(), _fusion_config())
    events = build_fusion_span_events(_run_result())

    dumped = json.dumps(
        {"attributes": attributes, "events": events},
        sort_keys=True,
        default=str,
    )

    assert attributes["gpt2giga.provider"] == "fusion"
    assert attributes["gpt2giga.fusion.analysis_model_count"] == 2
    assert attributes["gpt2giga.fusion.failed_panel_count"] == 1
    assert attributes["gpt2giga.fusion.tools_mode"] == "schema_only"
    assert attributes["gpt2giga.fusion.decision_mode"] == "selector"
    assert attributes["gpt2giga.fusion.selected_candidate_id"] == "direct"
    assert attributes["gpt2giga.fusion.needs_rewrite"] is True
    assert "SECRET_PANEL_TEXT" not in dumped
    assert "SECRET_DIRECT_TEXT" not in dumped
    assert "SECRET_TOOL_ARG" not in dumped
    assert "SECRET_ERROR_MESSAGE" not in dumped


async def test_fusion_metrics_render_bounded_series_without_content():
    sink = PrometheusMetricsSink()

    await emit_fusion_metrics(sink, run_result=_run_result())

    text = sink.render()

    assert 'gpt2giga_fusion_requests_total{preset="code-high",status="ok"} 1' in text
    assert (
        'gpt2giga_fusion_panel_calls_total{model="PanelB",status="timeout"} 1' in text
    )
    assert (
        'gpt2giga_fusion_latency_seconds_count{preset="code-high",status="ok"} 1'
        in text
    )
    assert (
        'gpt2giga_fusion_judge_latency_seconds_count{model="Judge",status="ok"} 1'
        in text
    )
    assert 'gpt2giga_fusion_tokens_total{input_output="input",phase="panel"} 2' in text
    assert (
        'gpt2giga_fusion_selected_candidate_total{candidate_id="direct",candidate_type="direct"} 1'
        in text
    )
    assert 'gpt2giga_fusion_rewrite_total{mode="selector"} 1' in text
    assert "gpt2giga_fusion_judge_parse_errors_total 1" in text
    assert "gpt2giga_fusion_repair_calls_total 1" in text
    assert 'gpt2giga_fusion_fallback_total{reason="invalid_judge_json"} 1' in text
    assert (
        'gpt2giga_fusion_stage_latency_seconds_count{model="Judge",stage="direct"} 1'
        in text
    )
    assert 'gpt2giga_fusion_stage_input_tokens{model="Judge",stage="direct"} 1' in text
    assert (
        'gpt2giga_fusion_panel_truncated_total{model="PanelA",role="architect"} 1'
        in text
    )
    assert 'gpt2giga_fusion_failures_total{reason="timeout"} 1' in text
    assert 'gpt2giga_fusion_failures_total{reason="invalid_judge_json"} 1' in text
    assert "SECRET_PANEL_TEXT" not in text
    assert "SECRET_DIRECT_TEXT" not in text
    assert "SECRET_TOOL_ARG" not in text
    assert "SECRET_ERROR_MESSAGE" not in text
