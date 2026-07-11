"""Capability negotiation for structured and legacy harness adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gpt2giga.harness.types import HarnessSpec


@dataclass(frozen=True)
class HarnessExecutionCapabilities:
    """Runtime features explicitly supported by one harness adapter."""

    structured_events: bool
    streaming: bool
    cancellation: bool
    synchronous_fallback: bool = True


def negotiate_execution_capabilities(value: Any) -> HarnessExecutionCapabilities:
    """Negotiate optional runtime behavior while preserving ``run()`` fallback."""
    spec = value if isinstance(value, HarnessSpec) else value.spec()
    streaming = bool(getattr(spec, "supports_streaming", False))
    return HarnessExecutionCapabilities(
        structured_events=bool(
            getattr(spec, "supports_structured_events", False) or streaming
        ),
        streaming=streaming,
        cancellation=bool(getattr(spec, "supports_cancellation", False)),
    )


def execution_capabilities_to_dict(
    capabilities: HarnessExecutionCapabilities,
) -> dict[str, bool]:
    """Serialize negotiated runtime behavior."""
    return {
        "structured_events": capabilities.structured_events,
        "streaming": capabilities.streaming,
        "cancellation": capabilities.cancellation,
        "synchronous_fallback": capabilities.synchronous_fallback,
    }
