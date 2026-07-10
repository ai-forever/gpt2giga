"""Transparent durable job payloads and bounded append-only attempt logs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from gpt2giga.harness.sessions.locking import exclusive_file_lock
from gpt2giga.harness.sessions.redaction import redact_for_storage

MAX_ATTEMPT_LOG_CHARS = 8192


class JobPayloadNotFoundError(KeyError):
    """Raised when an immutable durable job payload is missing."""


class DurableJobPayloadStore:
    """Store payloads outside SQLite so coordination state stays inspectable."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser() / "runtime"
        self.payload_dir = self.root / "job_payloads"
        self.log_dir = self.root / "attempt_logs"

    def save(self, job_id: str, payload: Mapping[str, Any]) -> Path:
        """Persist one redacted immutable payload with an atomic replace."""
        self.payload_dir.mkdir(parents=True, exist_ok=True)
        path = self.payload_dir / f"{job_id}.json"
        safe = redact_for_storage(dict(payload))
        temp = path.with_name(f".{path.name}.tmp")
        with exclusive_file_lock(path):
            if path.exists():
                return path
            temp.write_text(
                json.dumps(safe, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        return path

    def load(self, job_id: str) -> dict[str, Any]:
        """Load one immutable payload."""
        path = self.payload_dir / f"{job_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise JobPayloadNotFoundError(job_id) from exc
        if not isinstance(value, dict):
            raise ValueError(f"invalid durable job payload: {job_id}")
        return value

    def append_attempt_log(self, attempt_id: str, event: Mapping[str, Any]) -> None:
        """Append one redacted, bounded worker/process audit record."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{attempt_id}.jsonl"
        safe = redact_for_storage(dict(event))
        encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        encoded = encoded[:MAX_ATTEMPT_LOG_CHARS]
        with exclusive_file_lock(path):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
