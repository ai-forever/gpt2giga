"""Harness-owned normalized response contracts for provider adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NormalizedBaseModel(BaseModel):
    """Base normalized model with explicit provider extension buckets."""

    raw_extensions: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    def to_json_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json", exclude_none=exclude_none)


class NormalizedToolCall(NormalizedBaseModel):
    """Represent a provider-independent tool/function call."""

    id: str | None = None
    type: str = "function"
    name: str | None = None
    arguments: Any | None = None


class NormalizedMessage(NormalizedBaseModel):
    """Represent one normalized response message."""

    role: str
    content: str | None = None
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)


class NormalizedUsage(NormalizedBaseModel):
    """Represent provider token usage."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class NormalizedError(NormalizedBaseModel):
    """Represent a normalized provider or adapter error."""

    type: str
    message: str
    code: str | int | None = None
    param: str | None = None


class NormalizedChoice(NormalizedBaseModel):
    """Represent one normalized response choice."""

    index: int = 0
    message: NormalizedMessage | None = None
    finish_reason: str | None = None


class NormalizedResponse(NormalizedBaseModel):
    """Represent a normalized non-streaming provider response."""

    id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: str | None = None
    provider: str | None = None
    choices: list[NormalizedChoice] = Field(default_factory=list)
    usage: NormalizedUsage | None = None
    error: NormalizedError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


NormalizedStreamEventType = Literal[
    "message_start",
    "content_delta",
    "reasoning_delta",
    "tool_call_start",
    "tool_call_delta",
    "usage",
    "message_end",
    "error",
    "heartbeat",
]


class NormalizedStreamEvent(NormalizedBaseModel):
    """Represent one normalized incremental provider event."""

    type: NormalizedStreamEventType
    id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: str | None = None
    sequence: int | None = None
    choice_index: int = 0
    content_delta: str | None = None
    reasoning_delta: str | None = None
    tool_call: NormalizedToolCall | None = None
    usage: NormalizedUsage | None = None
    error: NormalizedError | None = None
    finish_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
