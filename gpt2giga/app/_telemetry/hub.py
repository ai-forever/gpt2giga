"""Observability sink dispatch hub."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import ObservabilitySink


class ObservabilityHub:
    """Dispatch normalized request events into configured telemetry sinks."""

    def __init__(self, sinks: Mapping[str, ObservabilitySink] | None = None) -> None:
        self._sinks = dict(sinks or {})

    @property
    def enabled_sink_names(self) -> list[str]:
        """Return enabled sink names in stable order."""
        return list(self._sinks)

    async def open(self) -> None:
        """Open all configured sinks."""
        for sink in self._sinks.values():
            await sink.open()

    async def close(self) -> None:
        """Close configured sinks in reverse registration order."""
        for sink in reversed(tuple(self._sinks.values())):
            await sink.close()

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Fan out a normalized request event to all sinks."""
        for sink in self._sinks.values():
            sink.record_request_event(event)

    def get_sink(self, name: str) -> ObservabilitySink | None:
        """Return a configured sink by name."""
        return self._sinks.get(name)

    def render_prometheus_text(self) -> str | None:
        """Return the first Prometheus exposition exposed by configured sinks."""
        for sink in self._sinks.values():
            rendered = sink.render_prometheus_text()
            if rendered is not None:
                return rendered
        return None
