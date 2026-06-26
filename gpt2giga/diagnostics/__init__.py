"""Compatibility diagnostics contracts."""

from gpt2giga.diagnostics.analyzer import build_empty_analysis
from gpt2giga.diagnostics.models import (
    BackendMode,
    BuiltinToolMappingDiagnostic,
    CompatibilityAnalysis,
    CompatibilityProtocol,
    FieldCompatibility,
    ModelResolutionDiagnostic,
    ProtocolDiagnosticWarning,
    SecurityRedactionDiagnostic,
    ToolCompatibility,
)
from gpt2giga.diagnostics.routes import ADMIN_COMPAT_ANALYZE_ROUTE

__all__ = [
    "ADMIN_COMPAT_ANALYZE_ROUTE",
    "BackendMode",
    "BuiltinToolMappingDiagnostic",
    "CompatibilityAnalysis",
    "CompatibilityProtocol",
    "FieldCompatibility",
    "ModelResolutionDiagnostic",
    "ProtocolDiagnosticWarning",
    "SecurityRedactionDiagnostic",
    "ToolCompatibility",
    "build_empty_analysis",
]
