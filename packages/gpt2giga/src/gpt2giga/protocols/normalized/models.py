"""Canonical normalized protocol models used by modular adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class NormalizedBaseModel(BaseModel):
    """Base model for normalized payloads with explicit extension buckets."""

    raw_extensions: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    def to_json_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json", exclude_none=exclude_none)


class NormalizedContentPart(NormalizedBaseModel):
    """Represent one normalized message content part."""

    type: str = "text"
    text: Optional[str] = None
    data: Optional[Any] = None
    mime_type: Optional[str] = None
    detail: Optional[str] = None


class NormalizedToolCall(NormalizedBaseModel):
    """Represent a provider-independent tool/function call."""

    id: Optional[str] = None
    type: str = "function"
    name: Optional[str] = None
    arguments: Optional[Any] = None


class NormalizedMessage(NormalizedBaseModel):
    """Represent a normalized chat/message item."""

    role: str
    content: Optional[str | list[NormalizedContentPart]] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)


class NormalizedTool(NormalizedBaseModel):
    """Represent a callable tool exposed to a model."""

    type: str = "function"
    name: str
    description: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class NormalizedResponseFormat(NormalizedBaseModel):
    """Represent model response format constraints."""

    type: str
    json_schema: Optional[dict[str, Any]] = None


class NormalizedGenerationConfig(NormalizedBaseModel):
    """Represent common model generation parameters."""

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    stop: Optional[str | list[str]] = None
    seed: Optional[int] = None


class NormalizedRequest(NormalizedBaseModel):
    """Represent a normalized provider request envelope."""

    id: Optional[str] = None
    protocol: str
    operation: str
    model: Optional[str] = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedChatRequest(NormalizedRequest):
    """Represent a normalized chat completion request."""

    protocol: str = "openai"
    operation: str = "chat"
    messages: list[NormalizedMessage] = Field(default_factory=list)
    tools: list[NormalizedTool] = Field(default_factory=list)
    tool_choice: Optional[Any] = None
    response_format: Optional[NormalizedResponseFormat] = None
    generation_config: NormalizedGenerationConfig = Field(
        default_factory=NormalizedGenerationConfig
    )
    user: Optional[str] = None


class NormalizedEmbeddingRequest(NormalizedRequest):
    """Represent a normalized embeddings request."""

    protocol: str = "openai"
    operation: str = "embeddings"
    input: Any
    dimensions: Optional[int] = None
    encoding_format: Optional[str] = None
    user: Optional[str] = None


class NormalizedUsage(NormalizedBaseModel):
    """Represent token usage returned by a model provider."""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class NormalizedError(NormalizedBaseModel):
    """Represent a normalized provider or adapter error."""

    type: str
    message: str
    code: Optional[str | int] = None
    param: Optional[str] = None


class NormalizedChoice(NormalizedBaseModel):
    """Represent one normalized response choice."""

    index: int = 0
    message: Optional[NormalizedMessage] = None
    delta: Optional[NormalizedMessage] = None
    finish_reason: Optional[str] = None


class NormalizedResponse(NormalizedBaseModel):
    """Represent a normalized non-streaming provider response."""

    id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: Optional[str] = None
    provider: Optional[str] = None
    choices: list[NormalizedChoice] = Field(default_factory=list)
    usage: Optional[NormalizedUsage] = None
    error: Optional[NormalizedError] = None
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
    """Represent one canonical stream event."""

    type: NormalizedStreamEventType
    id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: Optional[str] = None
    sequence: Optional[int] = None
    choice_index: int = 0
    message: Optional[NormalizedMessage] = None
    delta: Optional[NormalizedMessage] = None
    content_delta: Optional[str] = None
    reasoning_delta: Optional[str] = None
    tool_call: Optional[NormalizedToolCall] = None
    usage: Optional[NormalizedUsage] = None
    error: Optional[NormalizedError] = None
    finish_reason: Optional[str] = None
    heartbeat: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
