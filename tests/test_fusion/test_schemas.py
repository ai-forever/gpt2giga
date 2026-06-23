import pytest
from pydantic import ValidationError

from gpt2giga.providers.fusion.schemas import (
    FusionAnalysis,
    FusionCandidate,
    FusionPanelResult,
    FusionRunResult,
    FusionSelection,
)
from gpt2giga.protocols.normalized.models import NormalizedToolCall, NormalizedUsage


def test_fusion_panel_result_defaults_are_isolated():
    first = FusionPanelResult(model="A", status="ok")
    second = FusionPanelResult(model="B", status="ok")

    first.tool_calls.append(NormalizedToolCall(name="search"))

    assert len(first.tool_calls) == 1
    assert second.tool_calls == []


def test_fusion_analysis_accepts_final_tool_call():
    analysis = FusionAnalysis(
        consensus=["Use the smaller change."],
        final_tool_call=NormalizedToolCall(
            id="call-1",
            name="apply_patch",
            arguments={"patch": "..."},
        ),
    )

    assert analysis.final_tool_call is not None
    assert analysis.final_tool_call.name == "apply_patch"
    assert analysis.task_status == "needs_tool"
    assert analysis.blind_spots == []


def test_fusion_analysis_normalizes_conflicting_final_actions():
    analysis = FusionAnalysis(
        final_answer="done",
        final_tool_call=NormalizedToolCall(name="update_topic", arguments={}),
    )

    assert analysis.final_answer == "done"
    assert analysis.final_tool_call is None


def test_fusion_analysis_complete_status_drops_tool_call():
    analysis = FusionAnalysis(
        task_status="complete",
        final_answer="done",
        final_tool_call=NormalizedToolCall(name="lookup", arguments={}),
    )

    assert analysis.final_answer == "done"
    assert analysis.final_tool_call is None


def test_fusion_analysis_needs_tool_drops_client_visible_answer():
    analysis = FusionAnalysis(
        task_status="needs_tool",
        final_answer="internal rationale",
        final_tool_call=NormalizedToolCall(name="lookup", arguments={}),
    )

    assert analysis.final_answer is None
    assert analysis.final_tool_call is not None


def test_fusion_selection_requires_bounded_confidence():
    selection = FusionSelection(
        selected_candidate_id="direct",
        confidence=0.75,
    )

    assert selection.schema_version == "gpt2giga.fusion.selection.v1"
    assert selection.needs_rewrite is False

    with pytest.raises(ValidationError):
        FusionSelection(selected_candidate_id="direct", confidence=1.5)


def test_fusion_run_result_tracks_failed_models_and_usage():
    failed = FusionPanelResult(
        model="A",
        status="timeout",
        error_type="timeout",
        latency_ms=1000,
    )
    result = FusionRunResult(
        status="ok",
        requested_model="gpt2giga/fusion-code",
        preset="code-high",
        analysis_models=["A", "B"],
        judge_model="Judge",
        panel_results=[failed, FusionPanelResult(model="B", status="ok")],
        failed_models=[failed],
        candidates=[
            FusionCandidate(
                candidate_id="direct",
                source="direct",
                model="Judge",
                status="ok",
            )
        ],
        selection=FusionSelection(selected_candidate_id="direct", confidence=0.8),
        selected_candidate_id="direct",
        selected_candidate_source="direct",
        usage=NormalizedUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    )

    assert result.failed_models[0].model == "A"
    assert result.selected_candidate_source == "direct"
    assert result.usage is not None
    assert result.usage.total_tokens == 30


def test_fusion_schemas_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        FusionAnalysis(unexpected=True)
