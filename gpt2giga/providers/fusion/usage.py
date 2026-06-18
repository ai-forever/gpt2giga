"""Usage aggregation helpers for Fusion provider runs."""

from __future__ import annotations

from collections.abc import Iterable

from gpt2giga.protocols.normalized.models import NormalizedUsage


def aggregate_usage(usages: Iterable[NormalizedUsage | None]) -> NormalizedUsage | None:
    """Sum known token usage fields across panel and judge calls."""
    values = [usage for usage in usages if usage is not None]
    if not values:
        return None

    return NormalizedUsage(
        input_tokens=_sum_optional(usage.input_tokens for usage in values),
        output_tokens=_sum_optional(usage.output_tokens for usage in values),
        total_tokens=_sum_optional(usage.total_tokens for usage in values),
    )


def _sum_optional(values: Iterable[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known)
