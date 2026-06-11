"""Diagnostics for normalized shadow-mode translation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class NormalizationDiagnosticEvent(BaseModel):
    """Represent one safe normalized shadow-mode diagnostic event."""

    request_id: Optional[str] = None
    route: str
    normalization_status: Literal["ok", "error"]
    normalized_shape_hash: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def to_json_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable diagnostic dictionary."""
        return self.model_dump(mode="json", exclude_none=exclude_none)


def build_normalization_diagnostic(
    *,
    request_id: str | None,
    route: str,
    normalization_status: Literal["ok", "error"],
    normalized_payload: Any = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> NormalizationDiagnosticEvent:
    """Build a diagnostic event without including raw prompt or response content."""
    shape_hash = None
    if normalized_payload is not None:
        shape_hash = normalized_shape_hash(normalized_payload)

    return NormalizationDiagnosticEvent(
        request_id=request_id,
        route=route,
        normalization_status=normalization_status,
        normalized_shape_hash=shape_hash,
        warnings=warnings or [],
        errors=errors or [],
    )


def normalized_shape_hash(payload: Any) -> str:
    """Return a stable hash of a payload shape, excluding scalar values."""
    shape = _shape_only(payload)
    encoded = json.dumps(shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()[:16]}"


def _shape_only(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)

    if isinstance(value, Mapping):
        return {
            str(key): _shape_only(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }

    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "items": [_shape_only(item) for item in value],
        }

    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__
