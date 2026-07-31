"""JSONL traffic log sink for local development and tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from gpt2giga.sinks.logs.serialization import traffic_event_to_json_dict


class JsonlTrafficLogSink:
    """Append traffic log events to a JSONL file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def emit(self, event: Any) -> None:
        """Append one event as a single JSON line."""
        await self.emit_many([event])

    async def emit_many(self, events: list[Any]) -> None:
        """Append a batch with one file open and one worker-thread handoff."""
        if not events:
            return
        lines = "\n".join(
            json.dumps(
                traffic_event_to_json_dict(event),
                ensure_ascii=False,
                sort_keys=True,
            )
            for event in events
        )
        async with self._lock:
            await asyncio.to_thread(self._append_lines, lines)

    async def flush(self) -> None:
        """Flush pending writes.

        Writes are opened and closed per batch, so there is no buffered file handle.
        The method exists to satisfy the sink contract and future implementations.
        """
        return None

    def _append_lines(self, lines: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "a", encoding="utf-8")
        except Exception:
            os.close(descriptor)
            raise
        with stream:
            stream.write(lines)
            stream.write("\n")
