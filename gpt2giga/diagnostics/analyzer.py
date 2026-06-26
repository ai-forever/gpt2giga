"""Compatibility analysis entry points."""

from __future__ import annotations

from gpt2giga.diagnostics.models import (
    BackendMode,
    CompatibilityAnalysis,
    CompatibilityProtocol,
)


def build_empty_analysis(
    *,
    protocol: CompatibilityProtocol,
    route: str,
    operation: str,
    backend_mode: BackendMode = "unknown",
) -> CompatibilityAnalysis:
    """Build an empty compatibility analysis envelope."""
    return CompatibilityAnalysis(
        protocol=protocol,
        route=route,
        operation=operation,
        backend_mode=backend_mode,
    )
