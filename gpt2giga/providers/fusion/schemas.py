"""Pydantic schemas for Fusion execution results."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from gpt2giga.protocols.normalized.models import NormalizedToolCall, NormalizedUsage


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


class FusionAnalysis(BaseModel):
    """Structured judge analysis over panel responses."""

    consensus: list[str] = Field(default_factory=list)
    contradictions: list[FusionContradiction] = Field(default_factory=list)
    partial_coverage: list[FusionPartialCoverage] = Field(default_factory=list)
    unique_insights: list[FusionUniqueInsight] = Field(default_factory=list)
    blind_spots: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    selected_strategy: Optional[str] = None
    final_answer: Optional[str] = None
    final_tool_call: Optional[NormalizedToolCall] = None

    model_config = ConfigDict(extra="forbid")


class FusionRunResult(BaseModel):
    """Represent one complete Fusion run."""

    status: Literal["ok", "error"]
    requested_model: str
    preset: str
    analysis_models: list[str] = Field(default_factory=list)
    judge_model: str
    final_model: Optional[str] = None
    panel_results: list[FusionPanelResult] = Field(default_factory=list)
    failed_models: list[FusionPanelResult] = Field(default_factory=list)
    analysis: Optional[FusionAnalysis] = None
    fallback_reason: Optional[str] = None
    usage: Optional[NormalizedUsage] = None
    latency_ms: Optional[int] = None

    model_config = ConfigDict(extra="forbid")
