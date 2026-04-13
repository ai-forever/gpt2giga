"""Canonical internal request contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

NormalizedContent: TypeAlias = str | list[dict[str, Any]] | None


class NormalizedMessage(BaseModel):
    """Canonical message representation shared across provider adapters."""

    model_config = ConfigDict(extra="forbid")

    role: str
    content: NormalizedContent = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_openai_message(cls, message: dict[str, Any]) -> "NormalizedMessage":
        """Create a normalized message from an OpenAI-style payload."""
        extra = deepcopy(message)
        role = str(extra.pop("role", "user"))
        content = deepcopy(extra.pop("content", None))
        name = extra.pop("name", None)
        tool_call_id = extra.pop("tool_call_id", None)
        tool_calls = deepcopy(extra.pop("tool_calls", []))
        return cls(
            role=role,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            extra=extra,
        )

    def to_openai_message(self) -> dict[str, Any]:
        """Render the canonical message back into the OpenAI-style intermediary."""
        payload = deepcopy(self.extra)
        payload["role"] = self.role
        if self.content is not None:
            payload["content"] = deepcopy(self.content)
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = deepcopy(self.tool_calls)
        return payload


ResponsesInputItem: TypeAlias = NormalizedMessage | dict[str, Any] | str


class NormalizedTool(BaseModel):
    """Canonical tool definition shared across provider adapters."""

    model_config = ConfigDict(extra="forbid")

    kind: str = "function"
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_openai_tool(cls, tool: dict[str, Any]) -> "NormalizedTool":
        """Create a normalized tool from an OpenAI tool entry."""
        tool_payload = deepcopy(tool)
        kind = str(tool_payload.get("type", "function"))
        function_payload = tool_payload.get("function")
        if isinstance(function_payload, dict):
            definition = function_payload
        else:
            definition = tool_payload
        return cls(
            kind=kind,
            name=str(definition.get("name", "")),
            description=definition.get("description"),
            parameters=deepcopy(definition.get("parameters", {})),
            strict=definition.get("strict"),
            raw=tool_payload,
        )

    @classmethod
    def from_openai_function(cls, function: dict[str, Any]) -> "NormalizedTool":
        """Create a normalized tool from a legacy OpenAI function definition."""
        return cls.from_openai_tool({"type": "function", "function": function})

    def to_openai_tool(self) -> dict[str, Any]:
        """Render the canonical tool into an OpenAI tool entry."""
        if self.kind != "function":
            payload = deepcopy(self.raw)
            payload.setdefault("type", self.kind)
            return payload

        payload = deepcopy(self.raw)
        function_payload = payload.get("function")
        if not isinstance(function_payload, dict):
            function_payload = {}
        function_payload["name"] = self.name
        function_payload["parameters"] = deepcopy(self.parameters)
        if self.description is not None:
            function_payload["description"] = self.description
        elif "description" in function_payload:
            function_payload.pop("description")
        if self.strict is not None:
            function_payload["strict"] = self.strict
        elif "strict" in function_payload:
            function_payload.pop("strict")
        payload["type"] = "function"
        payload["function"] = function_payload
        return payload

    def to_openai_function(self) -> dict[str, Any] | None:
        """Render the canonical tool into a legacy OpenAI function definition."""
        if self.kind != "function":
            return None
        return deepcopy(self.to_openai_tool()["function"])


class NormalizedChatRequest(BaseModel):
    """Canonical chat-completions request passed into the feature layer."""

    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[NormalizedMessage] = Field(default_factory=list)
    stream: bool = False
    tools: list[NormalizedTool] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)

    def to_backend_payload(self) -> dict[str, Any]:
        """Render the canonical chat request into the current backend payload."""
        payload = deepcopy(self.options)
        payload["model"] = self.model
        payload["messages"] = [message.to_openai_message() for message in self.messages]
        payload["stream"] = self.stream
        if self.tools:
            payload["tools"] = [tool.to_openai_tool() for tool in self.tools]
        return payload


class NormalizedResponsesRequest(BaseModel):
    """Canonical Responses API request passed into the feature layer."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    input: str | list[ResponsesInputItem] | None = None
    instructions: str | None = None
    stream: bool = False
    tools: list[NormalizedTool] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)

    def to_backend_payload(self) -> dict[str, Any]:
        """Render the canonical Responses request into the backend payload."""
        payload = deepcopy(self.options)
        if isinstance(self.model, str) and self.model:
            payload["model"] = self.model
        if self.instructions is not None:
            payload["instructions"] = self.instructions
        if self.input is not None:
            if isinstance(self.input, list):
                payload["input"] = [
                    item.to_openai_message()
                    if isinstance(item, NormalizedMessage)
                    else deepcopy(item)
                    for item in self.input
                ]
            else:
                payload["input"] = self.input
        payload["stream"] = self.stream
        if self.tools:
            payload["tools"] = [tool.to_openai_tool() for tool in self.tools]
        return payload


class NormalizedEmbeddingsRequest(BaseModel):
    """Canonical embeddings request passed into the feature layer."""

    model_config = ConfigDict(extra="forbid")

    model: str
    input: str | list[Any]
    options: dict[str, Any] = Field(default_factory=dict)

    def to_backend_payload(self) -> dict[str, Any]:
        """Render the canonical embeddings request into the backend payload."""
        payload = deepcopy(self.options)
        payload["model"] = self.model
        payload["input"] = deepcopy(self.input)
        return payload


class NormalizedStreamEvent(BaseModel):
    """Canonical stream event shared by provider-specific presenters."""

    model_config = ConfigDict(extra="forbid")

    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence_number: int | None = None


NormalizedRequestData: TypeAlias = (
    NormalizedChatRequest | NormalizedResponsesRequest | NormalizedEmbeddingsRequest
)


def to_backend_payload(data: NormalizedRequestData | dict[str, Any]) -> dict[str, Any]:
    """Coerce a normalized request into the current backend payload shape."""
    if isinstance(data, dict):
        return deepcopy(data)
    return data.to_backend_payload()


def get_request_model(
    data: NormalizedRequestData | dict[str, Any] | None,
    *,
    default: str = "unknown",
) -> str:
    """Extract the configured model id from either normalized or legacy payloads."""
    if data is None:
        return default
    if isinstance(data, dict):
        model = data.get("model")
    else:
        model = data.model
    return model if isinstance(model, str) and model else default
