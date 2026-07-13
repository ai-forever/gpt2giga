"""No-op metrics sink."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class NoopMetricsSink:
    """Ignore metric updates."""

    async def increment(
        self,
        name: str,
        value: int = 1,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Drop a counter update."""
        return None

    async def observe(
        self,
        name: str,
        value: float,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Drop a numeric observation."""
        return None

    async def flush(self) -> None:
        """Flush no buffered metrics."""
        return None
