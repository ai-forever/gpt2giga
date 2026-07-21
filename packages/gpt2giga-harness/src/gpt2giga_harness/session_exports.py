"""Safe atomic persistence for sanitized session transcript exports."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def write_session_export(export_dir: Path, body: str) -> Path:
    """Write one export without deriving filesystem paths from request data."""
    export_dir.mkdir(parents=True, exist_ok=True)
    export_id = uuid4().hex
    path = export_dir / f"session-{export_id}.md"
    temporary = export_dir / f".session-{export_id}.tmp"
    try:
        temporary.write_text(body, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
