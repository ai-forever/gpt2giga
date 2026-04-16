"""Contracts and descriptors for runtime state backends."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
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


class QueryableEventFeed(EventFeed, Protocol):
    """Describe an event feed that supports server-side filtering."""

    def query(
        self,
        *,
        limit: int | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """Return recent items filtered by equality-match fields."""


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


class ConfigurableRuntimeStateBackend(RuntimeStateBackend):
    """Base scaffold for custom runtime backends like Redis, Postgres, or S3.

    Subclass this base when you want to plug in an external durable backend:

    1. Implement ``mapping()`` and ``feed()``.
    2. Optionally override ``open()`` and ``close()`` for client lifecycle.
    3. Register the backend via ``register_runtime_backend(MyBackend.descriptor(...))``.

    The shared proxy config is already normalized for you:

    - ``runtime_store_dsn``: backend connection string or object location;
    - ``runtime_store_namespace``: logical tenant/prefix for keys/tables/buckets.

    Example backends usually map these settings like this:

    - Redis: ``redis://redis:6379/0``
    - Postgres: ``postgresql://user:pass@postgres:5432/gpt2giga``
    - S3/MinIO: ``s3://access:secret@minio:9000/runtime-bucket?region=us-east-1``
    """

    name = "custom"

    def __init__(
        self,
        *,
        dsn: str | None = None,
        namespace: str = "gpt2giga",
        logger: Any | None = None,
    ) -> None:
        self.dsn = dsn
        self.namespace = namespace or "gpt2giga"
        self.logger = logger

    @classmethod
    def from_config(
        cls,
        *,
        config: Any | None = None,
        logger: Any | None = None,
    ) -> ConfigurableRuntimeStateBackend:
        """Build a backend instance from the shared proxy config."""
        proxy_settings = getattr(config, "proxy_settings", None)
        runtime_store = getattr(proxy_settings, "runtime_store", None)
        return cls(
            dsn=getattr(
                runtime_store,
                "dsn",
                getattr(proxy_settings, "runtime_store_dsn", None),
            ),
            namespace=getattr(
                runtime_store,
                "namespace",
                getattr(proxy_settings, "runtime_store_namespace", "gpt2giga"),
            ),
            logger=logger,
        )

    @classmethod
    def descriptor(
        cls,
        *,
        name: str | None = None,
        description: str,
    ) -> RuntimeBackendDescriptor:
        """Build a registry descriptor for a custom backend subclass."""
        backend_name = name or cls.name
        return RuntimeBackendDescriptor(
            name=backend_name,
            description=description,
            factory=lambda **kwargs: cls.from_config(
                config=kwargs.get("config"),
                logger=kwargs.get("logger"),
            ),
        )
