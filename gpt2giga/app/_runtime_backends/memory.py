"""In-memory runtime backend implementation."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, MutableMapping
from typing import Any

from .contracts import EventFeed, RuntimeStateBackend


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

    def query(
        self,
        *,
        limit: int | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """Return recent items filtered by equality-match fields."""
        items = self.recent(limit=limit)
        if not filters:
            return items
        return [
            item
            for item in items
            if isinstance(item, Mapping)
            and all(item.get(key) == value for key, value in filters.items())
        ]

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
