"""Sink registry and hub factory helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import ObservabilitySinkDescriptor
from .hub import ObservabilityHub

_OBSERVABILITY_SINKS: dict[str, ObservabilitySinkDescriptor] = {}


def register_observability_sink(descriptor: ObservabilitySinkDescriptor) -> None:
    """Register an observability sink implementation."""
    _OBSERVABILITY_SINKS[descriptor.name] = descriptor


def create_observability_hub(
    names: Iterable[str],
    *,
    config: Any | None = None,
    logger: Any | None = None,
) -> ObservabilityHub:
    """Instantiate an observability hub for the selected sinks."""
    sinks = {}
    for name in names:
        descriptor = _OBSERVABILITY_SINKS.get(name)
        if descriptor is None:
            available = ", ".join(sorted(_OBSERVABILITY_SINKS)) or "<none>"
            raise RuntimeError(
                f"Unsupported observability sink `{name}`. Available: {available}."
            )
        sinks[name] = descriptor.factory(config=config, logger=logger)
    return ObservabilityHub(sinks)
