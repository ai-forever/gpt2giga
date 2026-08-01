"""Shared sink capability helpers."""

from __future__ import annotations

from typing import Any


def is_sink_active(sink: Any) -> bool:
    """Return whether a configured sink can accept runtime events."""
    return sink is not None and not getattr(sink, "is_noop", False)
