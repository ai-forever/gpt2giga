"""Contracts for pluggable telemetry sinks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


class ObservabilitySink:
    """Base telemetry sink for normalized request audit events."""

    name = "base"

    async def open(self) -> None:
        """Initialize sink resources when needed."""

    async def close(self) -> None:
        """Tear down sink resources when needed."""

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Consume a normalized request event."""

    def render_prometheus_text(self) -> str | None:
        """Return Prometheus exposition text when the sink supports it."""
        return None


ObservabilitySinkFactory = Callable[..., ObservabilitySink]


@dataclass(frozen=True, slots=True)
class ObservabilitySinkDescriptor:
    """Describe a pluggable observability sink."""

    name: str
    description: str
    factory: ObservabilitySinkFactory
