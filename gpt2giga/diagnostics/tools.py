"""Tool compatibility helpers."""

from __future__ import annotations

from gpt2giga.diagnostics.models import BuiltinToolMappingDiagnostic


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
