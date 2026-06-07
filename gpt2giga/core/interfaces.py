"""Internal extension interfaces for modular gateway components."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from gpt2giga.core.context import RequestContext


@runtime_checkable
class ProtocolAdapter(Protocol):
    """Translate public protocol payloads to and from normalized shapes."""

    name: str

    async def to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> Any:
        """Convert a protocol-specific request payload to a normalized object."""

    async def from_normalized(
        self,
        payload: Any,
        *,
        context: RequestContext | None = None,
    ) -> Any:
        """Convert a normalized response object to a protocol-specific payload."""


@runtime_checkable
class ProviderAdapter(Protocol):
    """Execute normalized requests against a concrete upstream provider."""

    name: str

    async def complete(
        self,
        request: Any,
        *,
        context: RequestContext | None = None,
    ) -> Any:
        """Execute a non-streaming provider request."""

    def stream(
        self,
        request: Any,
        *,
        context: RequestContext | None = None,
    ) -> AsyncIterator[Any]:
        """Execute a streaming provider request."""


@runtime_checkable
class TrafficLogSink(Protocol):
    """Receive traffic log events without coupling callers to a storage backend."""

    async def emit(self, event: Any) -> None:
        """Store or forward a traffic log event."""

    async def flush(self) -> None:
        """Flush buffered traffic log events best effort."""


@runtime_checkable
class TrafficLogQueryStore(Protocol):
    """Read traffic log events from a queryable backend."""

    async def get(self, event_id: str) -> Any | None:
        """Return one event by storage id, if it exists."""

    async def get_by_request_id(self, request_id: str) -> Sequence[Any]:
        """Return events associated with one gateway request id."""

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        filters: Mapping[str, Any] | None = None,
    ) -> Sequence[Any]:
        """Return a page of events matching optional filters."""

    async def purge_expired(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        dry_run: bool = True,
        max_batches: int = 1,
    ) -> Mapping[str, Any]:
        """Delete or count events older than the retention cutoff."""

    async def redact_payloads(
        self,
        event_id: str,
        *,
        fields: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        """Redact stored payload fields for one traffic log event."""


@runtime_checkable
class ObservabilitySink(Protocol):
    """Receive trace/observability events without exposing vendor SDKs."""

    async def emit(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        context: RequestContext | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Record an observability event."""

    async def flush(self) -> None:
        """Flush pending observability data best effort."""


@runtime_checkable
class MetricsSink(Protocol):
    """Receive metric updates without exposing a metrics backend."""

    async def increment(
        self,
        name: str,
        value: int = 1,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Increment a counter metric."""

    async def observe(
        self,
        name: str,
        value: float,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a numeric observation."""

    async def flush(self) -> None:
        """Flush pending metric data best effort."""
