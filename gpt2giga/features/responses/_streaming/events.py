"""SSE event helpers for Responses streaming."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ResponsesStreamEventSequencer:
    """Serialize Responses SSE events with monotonically increasing sequence IDs."""

    def __init__(self, formatter: Callable[[str, dict[str, Any]], str]) -> None:
        self._formatter = formatter
        self._sequence_number = 0

    def emit(self, event_type: str, payload: dict[str, Any]) -> str:
        """Format an event and attach type/sequence metadata."""
        body = dict(payload)
        body["type"] = event_type
        body["sequence_number"] = self._sequence_number
        self._sequence_number += 1
        return self._formatter(event_type, body)
