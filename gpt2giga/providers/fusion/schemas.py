"""Pydantic schemas for Fusion execution results."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gpt2giga.protocols.normalized.models import NormalizedToolCall, NormalizedUsage

FUSION_ANALYSIS_SCHEMA_VERSION = "gpt2giga.fusion.analysis.v1"
FUSION_SELECTION_SCHEMA_VERSION = "gpt2giga.fusion.selection.v1"
FUSION_ACTION_DECISION_SCHEMA_VERSION = "gpt2giga.fusion.action_decision.v1"
FUSION_VERIFICATION_SCHEMA_VERSION = "gpt2giga.fusion.verification.v1"
FusionTaskStatus = Literal["needs_tool", "complete", "blocked", "answer_only"]


class FusionPanelResult(BaseModel):
    """Represent one analysis model result."""

    model: str
    role: Optional[str] = None
    status: Literal["ok", "error", "timeout"]
    content: Optional[str] = None
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)
    usage: Optional[NormalizedUsage] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    truncated: bool = False

    model_config = ConfigDict(extra="forbid")


class FusionCandidate(BaseModel):
    """Represent one selectable Fusion candidate."""

    candidate_id: str
    source: Literal["direct", "panel"]
    model: str
    role: Optional[str] = None
    status: Literal["ok", "error", "timeout"]
    content: Optional[str] = None
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)
    usage: Optional[NormalizedUsage] = None
    latency_ms: Optional[int] = None
    finish_reason: Optional[str] = None
    truncated: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FusionContradiction(BaseModel):
    """Represent a disagreement across panel models."""

    topic: str
    stances: list[dict[str, str]] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class FusionPartialCoverage(BaseModel):
    """Represent a point only covered by some panel models."""

    models: list[str] = Field(default_factory=list)
    point: str

    model_config = ConfigDict(extra="forbid")


class FusionUniqueInsight(BaseModel):
    """Represent a useful insight that came from one model."""

    model: str
    insight: str

    model_config = ConfigDict(extra="forbid")


class FusionJudgeAnalysis(BaseModel):
    """Structured server-tool judge analysis over panel responses."""

    schema_version: Literal["gpt2giga.fusion.analysis.v1"] = (
        FUSION_ANALYSIS_SCHEMA_VERSION
    )
    consensus: list[str] = Field(default_factory=list)
    contradictions: list[FusionContradiction] = Field(default_factory=list)
    partial_coverage: list[FusionPartialCoverage] = Field(default_factory=list)
    unique_insights: list[FusionUniqueInsight] = Field(default_factory=list)
    blind_spots: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    recommendation: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FusionAnalysis(BaseModel):
    """Structured judge analysis over panel responses."""

    schema_version: Literal["gpt2giga.fusion.analysis.v1"] = (
        FUSION_ANALYSIS_SCHEMA_VERSION
    )
    consensus: list[str] = Field(default_factory=list)
    contradictions: list[FusionContradiction] = Field(default_factory=list)
    partial_coverage: list[FusionPartialCoverage] = Field(default_factory=list)
    unique_insights: list[FusionUniqueInsight] = Field(default_factory=list)
    blind_spots: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    selected_strategy: Optional[str] = None
    task_status: FusionTaskStatus = "answer_only"
    final_answer: Optional[str] = None
    final_tool_call: Optional[NormalizedToolCall] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def normalize_final_action(self):
        """Keep exactly one client-visible final action."""
        if (
            self.task_status == "answer_only"
            and self.final_tool_call is not None
            and not self.final_answer
        ):
            self.task_status = "needs_tool"

        if self.task_status == "complete":
            self.final_tool_call = None
        elif self.task_status == "needs_tool":
            self.final_answer = None
        elif self.task_status == "blocked":
            self.final_tool_call = None
        elif self.final_answer and self.final_tool_call is not None:
            self.final_tool_call = None
        return self


class FusionSelection(BaseModel):
    """Structured selector judge decision over Fusion candidates."""

    schema_version: Literal["gpt2giga.fusion.selection.v1"] = (
        FUSION_SELECTION_SCHEMA_VERSION
    )
    selected_candidate_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_rewrite: bool = False
    correction: Optional[str] = None
    reason_brief: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FusionVerification(BaseModel):
    """Structured verifier assessment of the direct candidate."""

    schema_version: Literal["gpt2giga.fusion.verification.v1"] = (
        FUSION_VERIFICATION_SCHEMA_VERSION
    )
    checked_candidate_id: str
    verdict: Literal["approve", "reject", "needs_tool", "complete", "blocked"]
    concrete_issues: list[str] = Field(default_factory=list)
    corrected_tool_call: Optional[NormalizedToolCall] = None
    missing_requirements_after_action: list[str] = Field(default_factory=list)
    all_required_data_present: bool = False
    reason_brief: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FusionActionDecision(BaseModel):
    """Structured judge decision for the verified tool loop."""

    schema_version: Literal["gpt2giga.fusion.action_decision.v1"] = (
        FUSION_ACTION_DECISION_SCHEMA_VERSION
    )
    task_status: Literal["needs_tool", "complete", "blocked"]
    action_type: Literal["tool_call", "answer", "blocked"]
    selected_candidate_id: Optional[str] = None
    tool_call: Optional[NormalizedToolCall] = None
    final_answer: Optional[str] = None
    missing_requirements: list[str] = Field(default_factory=list)
    verifier_findings: list[str] = Field(default_factory=list)
    direct_candidate_errors: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reason_brief: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_action(self):
        """Keep the action decision internally consistent."""
        if self.action_type == "tool_call":
            if self.task_status != "needs_tool":
                raise ValueError("tool_call requires task_status=needs_tool")
            if self.tool_call is None:
                raise ValueError("tool_call action requires tool_call")
            if self.final_answer:
                raise ValueError("tool_call action forbids final_answer")
        if self.action_type == "answer":
            if self.task_status != "complete":
                raise ValueError("answer requires task_status=complete")
            if not self.final_answer:
                raise ValueError("answer action requires final_answer")
            if self.tool_call is not None:
                raise ValueError("answer action forbids tool_call")
        return self


class FusionRunResult(BaseModel):
    """Represent one complete Fusion run."""

    status: Literal["ok", "error"]
    requested_model: str
    preset: str
    analysis_models: list[str] = Field(default_factory=list)
    judge_model: str
    final_model: Optional[str] = None
    decision_mode: Literal["tool_result", "synthesize", "selector", "action"] = (
        "tool_result"
    )
    prompt_mode: Literal["full", "minimal"] = "full"
    panel_results: list[FusionPanelResult] = Field(default_factory=list)
    failed_models: list[FusionPanelResult] = Field(default_factory=list)
    candidates: list[FusionCandidate] = Field(default_factory=list)
    analysis: Optional[FusionAnalysis] = None
    selection: Optional[FusionSelection] = None
    verification: Optional[FusionVerification] = None
    action_decision: Optional[FusionActionDecision] = None
    selected_candidate_id: Optional[str] = None
    selected_candidate_source: Optional[Literal["direct", "panel"]] = None
    needs_rewrite: Optional[bool] = None
    judge_parse_error: bool = False
    repair_used: bool = False
    panel_truncated: bool = False
    fallback_reason: Optional[str] = None
    usage: Optional[NormalizedUsage] = None
    judge_usage: Optional[NormalizedUsage] = None
    finalizer_usage: Optional[NormalizedUsage] = None
    latency_ms: Optional[int] = None
    judge_latency_ms: Optional[int] = None
    direct_latency_ms: Optional[int] = None
    finalizer_latency_ms: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


class FusionToolError(BaseModel):
    """Represent an internal Fusion server-tool error."""

    reason: str
    message: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FusionToolResult(BaseModel):
    """Result returned to the outer model from openrouter:fusion."""

    status: Literal["ok", "error"]
    analysis: Optional[FusionJudgeAnalysis] = None
    responses: list[FusionPanelResult] = Field(default_factory=list)
    failed_models: list[FusionPanelResult] = Field(default_factory=list)
    usage: Optional[NormalizedUsage] = None
    metadata: dict[str, object] = Field(default_factory=dict)
    error: Optional[FusionToolError] = None

    model_config = ConfigDict(extra="forbid")
