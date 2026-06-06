"""JSONL traffic log sink for local development and tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from gpt2giga.sinks.logs.models import TrafficLogEvent


class JsonlTrafficLogSink:
    """Append traffic log events to a JSONL file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def emit(self, event: TrafficLogEvent | Any) -> None:
        """Append one event as a single JSON line."""
        line = json.dumps(_event_to_dict(event), ensure_ascii=False, sort_keys=True)
        async with self._lock:
            await asyncio.to_thread(self._append_line, line)

    async def flush(self) -> None:
        """Flush pending writes.

        Writes are opened and closed per event, so there is no buffered file handle.
        The method exists to satisfy the sink contract and future implementations.
        """
        return None

    def _append_line(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line)
            stream.write("\n")


def _event_to_dict(event: TrafficLogEvent | Any) -> dict[str, Any]:
    if isinstance(event, TrafficLogEvent):
        return event.to_json_dict()
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json", exclude_none=True)
    if isinstance(event, dict):
        return event
    raise TypeError(f"Unsupported traffic log event type: {type(event)!r}")
