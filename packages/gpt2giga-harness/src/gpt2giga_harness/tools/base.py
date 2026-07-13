"""Common provider and descriptor vocabulary for executable tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class ToolRisk(str, Enum):
    """Coarse risk label used as an input to tool execution policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ToolDescriptor:
    """Execution-neutral metadata for one provider-owned tool."""

    id: str
    provider_id: str
    title: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    risk: ToolRisk = ToolRisk.MEDIUM
    policy_id: str = "default"
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "provider_id", "title", "policy_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")


@runtime_checkable
class ToolProvider(Protocol):
    """Describe tools without requiring discovery or execution side effects."""

    @property
    def id(self) -> str:
        raise NotImplementedError

    def list_tools(self) -> tuple[ToolDescriptor, ...]:
        raise NotImplementedError
