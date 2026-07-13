"""Redaction helpers for persisted Unified Harness sessions."""

from __future__ import annotations

import json
from typing import Any, Mapping

from gpt2giga_harness.types import redact_secrets

MAX_STORED_EVENT_VALUE_CHARS = 16_000
_TRUNCATED_SUFFIX = "\n… <truncated>"


def redact_for_storage(value: Any) -> Any:
    """Return a JSON-compatible value with secret-looking data redacted."""
    return redact_secrets(value)


def redact_event_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Redact and bound each stored event field for safe live inspection."""
    redacted = redact_for_storage(dict(value))
    if not isinstance(redacted, Mapping):
        return {}
    return {str(key): _bounded_event_value(item) for key, item in redacted.items()}


def _bounded_event_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return _truncate(str(value))
    if len(serialized) <= MAX_STORED_EVENT_VALUE_CHARS:
        return value
    return {
        "preview": _truncate(serialized),
        "truncated": True,
    }


def _truncate(value: str) -> str:
    if len(value) <= MAX_STORED_EVENT_VALUE_CHARS:
        return value
    limit = MAX_STORED_EVENT_VALUE_CHARS - len(_TRUNCATED_SUFFIX)
    return f"{value[:limit]}{_TRUNCATED_SUFFIX}"
