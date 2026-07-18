"""Unified Harness package for local gpt2giga smoke and agent runs."""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

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

_LAZY_EXPORTS = {
    "HarnessRegistry": ("gpt2giga_harness.registry", "HarnessRegistry"),
    "create_default_registry": (
        "gpt2giga_harness.registry",
        "create_default_registry",
    ),
    "Availability": ("gpt2giga_harness.types", "Availability"),
    "AvailabilityStatus": ("gpt2giga_harness.types", "AvailabilityStatus"),
    "GigaChatApiMode": ("gpt2giga_harness.types", "GigaChatApiMode"),
    "HarnessCapability": ("gpt2giga_harness.types", "HarnessCapability"),
    "HarnessChatMessage": ("gpt2giga_harness.types", "HarnessChatMessage"),
    "HarnessRequest": ("gpt2giga_harness.types", "HarnessRequest"),
    "HarnessResult": ("gpt2giga_harness.types", "HarnessResult"),
    "HarnessSpec": ("gpt2giga_harness.types", "HarnessSpec"),
    "emit_event": ("gpt2giga_harness.types", "emit_event"),
}


def __getattr__(name: str) -> Any:
    """Load public runtime contracts only when callers request them."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
