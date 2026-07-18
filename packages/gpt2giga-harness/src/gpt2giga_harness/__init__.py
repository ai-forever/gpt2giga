"""Unified Harness package for local gpt2giga smoke and agent runs."""

from importlib.metadata import PackageNotFoundError, version

from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.types import (
    Availability,
    AvailabilityStatus,
    GigaChatApiMode,
    HarnessCapability,
    HarnessChatMessage,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    emit_event,
)

try:
    __version__ = version("gpt2giga-harness")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0+unknown"

__all__ = [
    "__version__",
    "Availability",
    "AvailabilityStatus",
    "GigaChatApiMode",
    "HarnessCapability",
    "HarnessChatMessage",
    "HarnessRegistry",
    "HarnessRequest",
    "HarnessResult",
    "HarnessSpec",
    "create_default_registry",
    "emit_event",
]
