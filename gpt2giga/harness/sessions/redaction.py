"""Redaction helpers for persisted Unified Harness sessions."""

from __future__ import annotations

from typing import Any

from gpt2giga.harness.types import redact_secrets


def redact_for_storage(value: Any) -> Any:
    """Return a JSON-compatible value with secret-looking data redacted."""
    return redact_secrets(value)
