"""Runtime backend registry for stateful app resources."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

RuntimeResourceKind = Literal["mapping", "feed"]


class EventFeed(Protocol):
    """Describe the minimal surface for append-only recent-event feeds."""

    def append(self, item: Any) -> None:
        """Store a new event item."""

    def recent(self, *, limit: int | None = None) -> list[Any]:
        """Return the newest items in chronological order."""

    def clear(self) -> None:
        """Remove all tracked items."""

    def __len__(self) -> int:
        """Return the current number of tracked items."""


class RuntimeStateBackend:
    """Provision stateful runtime resources for the application."""

    name = "base"

    async def open(self) -> None:
        """Open backend connections when the implementation needs startup work."""

    async def close(self) -> None:
        """Close backend connections when the implementation needs cleanup."""

    def mapping(self, name: str) -> MutableMapping[str, Any]:
        """Return a named key-value resource."""
        raise NotImplementedError

    def feed(self, name: str, *, max_items: int) -> EventFeed:
        """Return a named recent-events feed."""
        raise NotImplementedError


class InMemoryEventFeed:
    """Store recent events in a bounded in-memory ring buffer."""

    def __init__(self, *, max_items: int):
        self._items: deque[Any] = deque(maxlen=max_items)

    def append(self, item: Any) -> None:
        """Append an event to the feed."""
        self._items.append(item)

    def recent(self, *, limit: int | None = None) -> list[Any]:
        """Return recent items in chronological order."""
        items = list(self._items)
        if limit is None:
            return items
        return items[-limit:]

    def clear(self) -> None:
        """Drop all tracked items."""
        self._items.clear()

    def __len__(self) -> int:
        """Return the number of tracked items."""
        return len(self._items)


class InMemoryRuntimeStateBackend(RuntimeStateBackend):
    """Provision all runtime resources from local process memory."""

    name = "memory"

    def __init__(self) -> None:
        self._mappings: dict[str, MutableMapping[str, Any]] = {}
        self._feeds: dict[str, InMemoryEventFeed] = {}

    def mapping(self, name: str) -> MutableMapping[str, Any]:
        """Return a stable named in-memory mapping."""
        return self._mappings.setdefault(name, {})

    def feed(self, name: str, *, max_items: int) -> EventFeed:
        """Return a stable named in-memory feed."""
        feed = self._feeds.get(name)
        if feed is None or feed._items.maxlen != max_items:
            feed = InMemoryEventFeed(max_items=max_items)
            self._feeds[name] = feed
        return feed


RuntimeBackendFactory = Callable[..., RuntimeStateBackend]


@dataclass(frozen=True, slots=True)
class RuntimeBackendDescriptor:
    """Describe a pluggable backend implementation."""

    name: str
    description: str
    factory: RuntimeBackendFactory


@dataclass(frozen=True, slots=True)
class RuntimeResourceDescriptor:
    """Describe a stateful runtime resource provisioned by the backend."""

    name: str
    kind: RuntimeResourceKind
    description: str
    max_items_setting: str | None = None
    default_max_items: int | None = None

    def resolve_max_items(self, config: Any | None) -> int:
        """Resolve feed capacity from config with a safe fallback."""
        if self.kind != "feed":
            raise ValueError(f"Resource `{self.name}` is not a feed.")
        if config is None or self.max_items_setting is None:
            return int(self.default_max_items or 1)

        proxy_settings = getattr(config, "proxy_settings", None)
        configured_value = getattr(proxy_settings, self.max_items_setting, None)
        if configured_value is None:
            return int(self.default_max_items or 1)
        return int(configured_value)


_RUNTIME_BACKENDS: dict[str, RuntimeBackendDescriptor] = {}

RUNTIME_RESOURCE_DESCRIPTORS: tuple[RuntimeResourceDescriptor, ...] = (
    RuntimeResourceDescriptor(
        name="files",
        kind="mapping",
        description="Uploaded file metadata.",
    ),
    RuntimeResourceDescriptor(
        name="batches",
        kind="mapping",
        description="Batch metadata.",
    ),
    RuntimeResourceDescriptor(
        name="responses",
        kind="mapping",
        description="Responses API metadata.",
    ),
    RuntimeResourceDescriptor(
        name="recent_requests",
        kind="feed",
        description="Recent request audit events.",
        max_items_setting="recent_requests_max_items",
        default_max_items=200,
    ),
    RuntimeResourceDescriptor(
        name="recent_errors",
        kind="feed",
        description="Recent request error events.",
        max_items_setting="recent_errors_max_items",
        default_max_items=100,
    ),
)


def register_runtime_backend(descriptor: RuntimeBackendDescriptor) -> None:
    """Register a state backend implementation."""
    _RUNTIME_BACKENDS[descriptor.name] = descriptor


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


def provision_runtime_resources(
    backend: RuntimeStateBackend,
    *,
    config: Any | None = None,
) -> dict[str, Any]:
    """Provision all declared runtime resources from a backend."""
    resources: dict[str, Any] = {}
    for descriptor in RUNTIME_RESOURCE_DESCRIPTORS:
        if descriptor.kind == "mapping":
            resources[descriptor.name] = backend.mapping(descriptor.name)
            continue
        resources[descriptor.name] = backend.feed(
            descriptor.name,
            max_items=descriptor.resolve_max_items(config),
        )
    return resources


register_runtime_backend(
    RuntimeBackendDescriptor(
        name="memory",
        description="Process-local dictionaries and ring buffers.",
        factory=lambda **_: InMemoryRuntimeStateBackend(),
    )
)
