"""Bounded per-run notifications and durable event-tail page contracts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import json
import threading
from uuid import uuid4

from gpt2giga_harness.sessions.models import HarnessStoredEvent, event_to_dict


@dataclass(frozen=True)
class EventTailItem:
    """One retained event and the durable offset immediately after it."""

    event: HarnessStoredEvent
    next_offset: int


@dataclass(frozen=True)
class EventTailPage:
    """One byte- and item-bounded append-order event-tail page."""

    items: tuple[EventTailItem, ...]
    next_offset: int
    has_more: bool
    byte_count: int


@dataclass(frozen=True)
class EventCursorPosition:
    """Resolved legacy event identity inside a durable event tail."""

    offset: int
    terminal_seen: bool


class StreamSignal(str, Enum):
    """Content-free notification delivered to one live stream."""

    CHANGED = "changed"
    RESNAPSHOT_REQUIRED = "resnapshot_required"


class StreamCapacityError(RuntimeError):
    """Raised when the bounded live-stream subscriber budget is exhausted."""


class RunEventSubscription:
    """One loop-owned bounded notification queue for an event stream."""

    def __init__(
        self,
        broker: RunEventBroker,
        scope: str,
        scope_id: str,
        queue_size: int,
    ) -> None:
        self._broker = broker
        self._scope = scope
        self._scope_id = scope_id
        self._token = uuid4().hex
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[StreamSignal] = asyncio.Queue(maxsize=queue_size)
        self._closed = False
        self._resnapshot_pending = False

    @property
    def token(self) -> str:
        """Return the content-free subscriber identity."""
        return self._token

    @property
    def run_id(self) -> str:
        """Return the subscribed durable run identity."""
        return self._scope_id

    @property
    def scope(self) -> str:
        """Return whether this subscription follows a run or a session."""
        return self._scope

    @property
    def scope_id(self) -> str:
        """Return the exact subscribed durable identity."""
        return self._scope_id

    async def wait(self, timeout: float) -> StreamSignal | None:
        """Wait for a change signal, returning ``None`` for a heartbeat timeout."""
        try:
            signal = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        if signal is StreamSignal.RESNAPSHOT_REQUIRED:
            self._resnapshot_pending = False
        return signal

    def close(self) -> None:
        """Detach this subscriber; repeated cleanup is harmless."""
        if self._closed:
            return
        self._closed = True
        self._broker._remove(self)

    def schedule(self, signal: StreamSignal) -> None:
        """Schedule a thread-safe content-free signal on the owning loop."""
        if not self._closed:
            self._loop.call_soon_threadsafe(self._offer, signal)

    def _offer(self, signal: StreamSignal) -> None:
        if self._closed:
            return
        if self._resnapshot_pending:
            return
        if not self._queue.full():
            self._queue.put_nowait(signal)
            return
        while not self._queue.empty():
            self._queue.get_nowait()
        self._resnapshot_pending = True
        self._queue.put_nowait(StreamSignal.RESNAPSHOT_REQUIRED)


class RunEventBroker:
    """Fan out content-free append notifications through bounded event queues."""

    def __init__(
        self,
        *,
        queue_size: int = 8,
        max_subscribers: int = 256,
        max_subscribers_per_run: int = 32,
    ) -> None:
        self.queue_size = max(queue_size, 1)
        self.max_subscribers = max(max_subscribers, 1)
        self.max_subscribers_per_run = max(max_subscribers_per_run, 1)
        self._lock = threading.Lock()
        self._subscriptions: dict[str, dict[str, RunEventSubscription]] = {}
        self._session_subscriptions: dict[str, dict[str, RunEventSubscription]] = {}

    def subscribe(self, run_id: str) -> RunEventSubscription:
        """Register one bounded subscriber for an exact run."""
        subscription = RunEventSubscription(self, "run", run_id, self.queue_size)
        with self._lock:
            total = self._subscriber_total()
            run_items = self._subscriptions.setdefault(run_id, {})
            if (
                total >= self.max_subscribers
                or len(run_items) >= self.max_subscribers_per_run
            ):
                if not run_items:
                    self._subscriptions.pop(run_id, None)
                raise StreamCapacityError("live event stream capacity is exhausted")
            run_items[subscription.token] = subscription
        return subscription

    def subscribe_session(self, session_id: str) -> RunEventSubscription:
        """Register one bounded subscriber for all events in a session."""
        subscription = RunEventSubscription(
            self, "session", session_id, self.queue_size
        )
        with self._lock:
            total = self._subscriber_total()
            session_items = self._session_subscriptions.setdefault(session_id, {})
            if (
                total >= self.max_subscribers
                or len(session_items) >= self.max_subscribers_per_run
            ):
                if not session_items:
                    self._session_subscriptions.pop(session_id, None)
                raise StreamCapacityError("live event stream capacity is exhausted")
            session_items[subscription.token] = subscription
        return subscription

    def publish(self, event: HarnessStoredEvent) -> None:
        """Wake subscribers for the persisted event's exact run and session."""
        with self._lock:
            subscriptions = (
                *self._subscriptions.get(event.run_id, {}).values(),
                *(
                    self._session_subscriptions.get(event.session_id, {}).values()
                    if event.type.startswith("session.")
                    else ()
                ),
            )
        for subscription in subscriptions:
            subscription.schedule(StreamSignal.CHANGED)

    def publish_session(self, session_id: str) -> None:
        """Wake session subscribers after a non-event state transition."""
        with self._lock:
            subscriptions = tuple(
                self._session_subscriptions.get(session_id, {}).values()
            )
        for subscription in subscriptions:
            subscription.schedule(StreamSignal.CHANGED)

    def subscriber_count(self, run_id: str | None = None) -> int:
        """Return aggregate content-free occupancy for tests and diagnostics."""
        with self._lock:
            if run_id is not None:
                return len(self._subscriptions.get(run_id, ()))
            return self._subscriber_total()

    def session_subscriber_count(self, session_id: str | None = None) -> int:
        """Return session-stream occupancy for tests and diagnostics."""
        with self._lock:
            if session_id is not None:
                return len(self._session_subscriptions.get(session_id, ()))
            return sum(len(items) for items in self._session_subscriptions.values())

    def snapshot(self) -> dict[str, int | bool]:
        """Return aggregate content-free queue and occupancy diagnostics."""
        with self._lock:
            run_subscribers = sum(len(items) for items in self._subscriptions.values())
            session_subscribers = sum(
                len(items) for items in self._session_subscriptions.values()
            )
            subscribers = run_subscribers + session_subscribers
            active_runs = len(self._subscriptions)
            active_sessions = len(self._session_subscriptions)
        return {
            "content_free": True,
            "subscribers": subscribers,
            "run_subscribers": run_subscribers,
            "session_subscribers": session_subscribers,
            "active_runs": active_runs,
            "active_sessions": active_sessions,
            "queue_size": self.queue_size,
            "max_subscribers": self.max_subscribers,
            "max_subscribers_per_run": self.max_subscribers_per_run,
        }

    def _remove(self, subscription: RunEventSubscription) -> None:
        with self._lock:
            subscriptions = (
                self._subscriptions
                if subscription.scope == "run"
                else self._session_subscriptions
            )
            scope_items = subscriptions.get(subscription.scope_id)
            if scope_items is None:
                return
            scope_items.pop(subscription.token, None)
            if not scope_items:
                subscriptions.pop(subscription.scope_id, None)

    def _subscriber_total(self) -> int:
        return sum(len(items) for items in self._subscriptions.values()) + sum(
            len(items) for items in self._session_subscriptions.values()
        )


def event_stream_size(event: HarnessStoredEvent) -> int:
    """Return the exact UTF-8 JSON size used for one stored stream event."""
    return len(
        json.dumps(
            event_to_dict(event),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
