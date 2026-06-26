"""Tool compatibility helpers."""

from __future__ import annotations

from gpt2giga.diagnostics.models import (
    BuiltinToolMappingDiagnostic,
    ToolDecision,
    ToolDecisionCategory,
    ToolDecisionDiagnostic,
)


def build_builtin_tool_mapping(
    *,
    from_name: str,
    to_name: str,
    reason: str | None = None,
) -> BuiltinToolMappingDiagnostic:
    """Build one provider built-in tool mapping diagnostic."""
    return BuiltinToolMappingDiagnostic(
        from_name=from_name,
        to_name=to_name,
        reason=reason,
    )


def build_tool_decision(
    *,
    source: str,
    category: ToolDecisionCategory,
    decision: ToolDecision,
    name: str | None = None,
    target: str | None = None,
    reason: str | None = None,
    field: str | None = None,
) -> ToolDecisionDiagnostic:
    """Build one safe per-tool diagnostic decision."""
    return ToolDecisionDiagnostic(
        source=source,
        category=category,
        decision=decision,
        name=name,
        target=target,
        reason=reason,
        field=field,
    )
