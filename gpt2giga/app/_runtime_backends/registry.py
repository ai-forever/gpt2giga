"""Backend registry for runtime state providers."""

from __future__ import annotations

from typing import Any

from .contracts import RuntimeBackendDescriptor, RuntimeStateBackend
from .memory import InMemoryRuntimeStateBackend
from .sqlite import SqliteRuntimeStateBackend

_RUNTIME_BACKENDS: dict[str, RuntimeBackendDescriptor] = {}


def register_runtime_backend(descriptor: RuntimeBackendDescriptor) -> None:
    """Register a state backend implementation."""
    _RUNTIME_BACKENDS[descriptor.name] = descriptor


def get_runtime_backend_descriptor(name: str) -> RuntimeBackendDescriptor | None:
    """Return a registered backend descriptor by name."""
    return _RUNTIME_BACKENDS.get(name)


def list_runtime_backend_descriptors() -> list[RuntimeBackendDescriptor]:
    """Return registered backend descriptors sorted by name."""
    return [
        descriptor
        for _name, descriptor in sorted(
            _RUNTIME_BACKENDS.items(),
            key=lambda item: item[0],
        )
    ]


def create_runtime_backend(
    name: str,
    *,
    config: Any | None = None,
    logger: Any | None = None,
) -> RuntimeStateBackend:
    """Instantiate a configured state backend by name."""
    descriptor = _RUNTIME_BACKENDS.get(name)
    if descriptor is None:
        available = ", ".join(sorted(_RUNTIME_BACKENDS)) or "<none>"
        raise RuntimeError(
            f"Unsupported runtime store backend `{name}`. Available: {available}."
        )
    return descriptor.factory(config=config, logger=logger)


def register_builtin_runtime_backends() -> None:
    """Register the built-in in-memory and SQLite runtime backends."""
    register_runtime_backend(
        RuntimeBackendDescriptor(
            name="memory",
            description="Process-local dictionaries and ring buffers.",
            factory=lambda **_: InMemoryRuntimeStateBackend(),
        )
    )
    register_runtime_backend(
        RuntimeBackendDescriptor(
            name="sqlite",
            description="SQLite-backed runtime stores and recent-event feeds.",
            factory=lambda **kwargs: SqliteRuntimeStateBackend(
                dsn=getattr(
                    getattr(kwargs.get("config"), "proxy_settings", None),
                    "runtime_store_dsn",
                    None,
                ),
                namespace=getattr(
                    getattr(kwargs.get("config"), "proxy_settings", None),
                    "runtime_store_namespace",
                    "gpt2giga",
                ),
                logger=kwargs.get("logger"),
            ),
        )
    )


register_builtin_runtime_backends()
