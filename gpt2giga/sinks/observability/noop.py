"""No-op observability sink."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gpt2giga.core.context import RequestContext


class NoopObservabilitySink:
    """Ignore observability events."""

    async def emit(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        context: RequestContext | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Drop an observability event."""
        return None

    async def flush(self) -> None:
        """Flush no buffered events."""
        return None
