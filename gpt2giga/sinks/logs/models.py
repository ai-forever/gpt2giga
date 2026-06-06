"""Storage-independent traffic log event models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrafficLogEvent(BaseModel):
    """Represent one redacted gateway traffic event."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str
    trace_id: str
    protocol: str
    route: str
    method: str
    status_code: Optional[int] = None
    model_requested: Optional[str] = None
    model_effective: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[float] = None
    upstream_latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_body_redacted: Optional[Any] = None
    response_body_redacted: Optional[Any] = None

    model_config = ConfigDict(extra="forbid")

    def to_json_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable event dictionary."""
        return self.model_dump(mode="json", exclude_none=exclude_none)
