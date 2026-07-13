"""Shared tool policy decisions independent of any execution runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from gpt2giga_harness.tools.base import ToolDescriptor, ToolRisk


class PolicyDecision(str, Enum):
    """Portable allow, deny, or ask decision."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class ToolPolicyResolution:
    """Auditable result of evaluating one descriptor."""

    tool_id: str
    policy_id: str
    risk: ToolRisk
    decision: PolicyDecision
    source: str


@dataclass(frozen=True)
class ToolExecutionPolicy:
    """Resolve tool-specific rules before risk defaults and a safe fallback."""

    id: str
    tool_rules: Mapping[str, PolicyDecision] = field(default_factory=dict)
    risk_rules: Mapping[ToolRisk, PolicyDecision] = field(default_factory=dict)
    default: PolicyDecision = PolicyDecision.ASK

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("id must not be empty")

    def resolve(self, descriptor: ToolDescriptor) -> ToolPolicyResolution:
        """Return the effective decision and the rule source that selected it."""
        if descriptor.id in self.tool_rules:
            decision = self.tool_rules[descriptor.id]
            source = f"tool:{descriptor.id}"
        elif descriptor.risk in self.risk_rules:
            decision = self.risk_rules[descriptor.risk]
            source = f"risk:{descriptor.risk.value}"
        else:
            decision = self.default
            source = "default"
        return ToolPolicyResolution(
            tool_id=descriptor.id,
            policy_id=self.id,
            risk=descriptor.risk,
            decision=decision,
            source=source,
        )
