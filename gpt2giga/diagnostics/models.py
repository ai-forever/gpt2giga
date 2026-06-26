"""Pydantic models for compatibility diagnostics."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

CompatibilityProtocol = Literal[
    "openai",
    "anthropic",
    "gemini",
    "litellm",
    "system",
    "unknown",
]
BackendMode = Literal["gigachat_v1", "gigachat_v2", "unknown"]
WarningSeverity = Literal["info", "warning", "error"]
ToolDecisionCategory = Literal["provider_builtin", "tool_choice", "user_function"]
ToolDecision = Literal["ignored", "mapped", "rejected", "supported", "unsupported"]


class DiagnosticBaseModel(BaseModel):
    """Base model for safe compatibility diagnostics."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_json_dict(
        self,
        *,
        exclude_none: bool = True,
        by_alias: bool = True,
    ) -> dict[str, Any]:
        """Return a JSON-serializable diagnostic dictionary."""
        return self.model_dump(
            mode="json",
            exclude_none=exclude_none,
            by_alias=by_alias,
        )


class ProtocolDiagnosticWarning(DiagnosticBaseModel):
    """Represent a compatibility warning without raw request content."""

    code: str
    message: str
    severity: WarningSeverity = "warning"
    field: str | None = None


class FieldCompatibility(DiagnosticBaseModel):
    """Summarize request field compatibility decisions."""

    supported: list[str] = Field(default_factory=list)
    accepted_ignored: list[str] = Field(default_factory=list)
    accepted_diagnostic_only: list[str] = Field(default_factory=list)
    approximated: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)


class BuiltinToolMappingDiagnostic(DiagnosticBaseModel):
    """Describe one provider built-in tool mapping decision."""

    from_name: str = Field(
        validation_alias=AliasChoices("from", "from_name"),
        serialization_alias="from",
    )
    to_name: str = Field(
        validation_alias=AliasChoices("to", "to_name"),
        serialization_alias="to",
    )
    reason: str | None = None


class ToolDecisionDiagnostic(DiagnosticBaseModel):
    """Describe one safe per-tool compatibility decision."""

    source: str
    category: ToolDecisionCategory
    decision: ToolDecision
    name: str | None = None
    target: str | None = None
    reason: str | None = None
    field: str | None = None


class ToolCompatibility(DiagnosticBaseModel):
    """Summarize tool compatibility decisions."""

    user_functions: list[str] = Field(default_factory=list)
    mapped_builtin_tools: list[BuiltinToolMappingDiagnostic] = Field(
        default_factory=list
    )
    unsupported_tools: list[str] = Field(default_factory=list)
    accepted_ignored: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    details: list[ToolDecisionDiagnostic] = Field(default_factory=list)
    mapping_disabled: bool | None = None
    forced_tool_choice_supported: bool | None = None


class ModelResolutionDiagnostic(DiagnosticBaseModel):
    """Explain requested and effective model selection."""

    requested: str | None = None
    effective: str | None = None
    pass_model: bool = False
    source: str | None = None


class SecurityRedactionDiagnostic(DiagnosticBaseModel):
    """Report request components redacted from diagnostics."""

    headers_redacted: list[str] = Field(default_factory=list)
    query_redacted: list[str] = Field(default_factory=list)
    body_fields_redacted: list[str] = Field(default_factory=list)


class CompatibilityAnalysis(DiagnosticBaseModel):
    """Represent a safe machine-readable compatibility analysis."""

    protocol: CompatibilityProtocol
    route: str
    operation: str
    backend_mode: BackendMode = "unknown"
    model: ModelResolutionDiagnostic = Field(default_factory=ModelResolutionDiagnostic)
    fields: FieldCompatibility = Field(default_factory=FieldCompatibility)
    tools: ToolCompatibility = Field(default_factory=ToolCompatibility)
    security: SecurityRedactionDiagnostic = Field(
        default_factory=SecurityRedactionDiagnostic
    )
    warnings: list[ProtocolDiagnosticWarning] = Field(default_factory=list)
    normalized_shape_hash: str | None = None
