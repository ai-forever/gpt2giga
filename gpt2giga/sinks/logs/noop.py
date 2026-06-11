"""No-op traffic log sink."""

from __future__ import annotations

from typing import Any


class NoopTrafficLogSink:
    """Ignore traffic log events."""

    async def emit(self, event: Any) -> None:
        """Drop a traffic log event."""
        return None

    async def flush(self) -> None:
        """Flush no buffered events."""
        return None
