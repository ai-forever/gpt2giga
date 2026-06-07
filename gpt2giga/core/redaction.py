"""Redaction helpers for durable traffic log payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gpt2giga.constants import SENSITIVE_KEYS
from gpt2giga.logger import redact_sensitive

TRAFFIC_LOG_REDACTION_KEYS = frozenset(
    {
        *SENSITIVE_KEYS,
        "cookie",
        "set-cookie",
    }
)
REDACTION_REPLACEMENT = "***"


def normalize_redaction_key(key: str) -> str:
    """Normalize a redaction key for case-insensitive matching."""
    return key.strip().lower().replace("-", "_")


def build_redaction_keys(extra_keys: Sequence[str] | None = None) -> frozenset[str]:
    """Return default traffic-log redaction keys plus caller-provided keys."""
    keys = set[str]()
    for key in TRAFFIC_LOG_REDACTION_KEYS:
        keys.add(key.lower())
        keys.add(normalize_redaction_key(key))
    for key in extra_keys or ():
        keys.add(key.strip().lower())
        keys.add(normalize_redaction_key(key))
    return frozenset(key for key in keys if key)


def is_sensitive_key(key: object, redaction_keys: frozenset[str] | None = None) -> bool:
    """Return whether a mapping key should be redacted."""
    key_text = str(key)
    keys = redaction_keys or build_redaction_keys()
    return key_text.strip().lower() in keys or normalize_redaction_key(key_text) in keys


def redact_traffic_payload(
    value: Any,
    *,
    enabled: bool = True,
    extra_keys: Sequence[str] | None = None,
    replacement: str = REDACTION_REPLACEMENT,
) -> Any:
    """Return a redacted copy of a traffic-log payload."""
    if not enabled:
        return value
    redaction_keys = build_redaction_keys(extra_keys)
    return _redact_value(value, redaction_keys=redaction_keys, replacement=replacement)


def _redact_value(
    value: Any, *, redaction_keys: frozenset[str], replacement: str
) -> Any:
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            if is_sensitive_key(key, redaction_keys):
                redacted[key] = replacement
            else:
                redacted[key] = _redact_value(
                    item, redaction_keys=redaction_keys, replacement=replacement
                )
        return redacted

    if isinstance(value, str):
        return redact_sensitive(value)

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [
            _redact_value(item, redaction_keys=redaction_keys, replacement=replacement)
            for item in value
        ]

    return value
