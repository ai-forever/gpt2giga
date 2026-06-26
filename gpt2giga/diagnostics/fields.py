"""Field compatibility helpers."""

from __future__ import annotations

from collections.abc import Iterable

from gpt2giga.diagnostics.models import FieldCompatibility


def build_field_compatibility(
    *,
    supported: Iterable[str] = (),
    accepted_ignored: Iterable[str] = (),
    accepted_diagnostic_only: Iterable[str] = (),
    approximated: Iterable[str] = (),
    rejected: Iterable[str] = (),
) -> FieldCompatibility:
    """Build a field compatibility summary from classified field names."""
    return FieldCompatibility(
        supported=sorted(set(supported)),
        accepted_ignored=sorted(set(accepted_ignored)),
        accepted_diagnostic_only=sorted(set(accepted_diagnostic_only)),
        approximated=sorted(set(approximated)),
        rejected=sorted(set(rejected)),
    )
