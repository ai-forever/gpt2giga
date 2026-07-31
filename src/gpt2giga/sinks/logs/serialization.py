"""Traffic log event serialization helpers."""

from __future__ import annotations

from typing import Any

from gpt2giga.sinks.logs.models import TrafficLogEvent


def traffic_event_to_json_dict(event: TrafficLogEvent | Any) -> dict[str, Any]:
    """Return a JSON-serializable event dictionary."""
    if isinstance(event, TrafficLogEvent):
        return event.to_json_dict()
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json", exclude_none=True)
    if isinstance(event, dict):
        return event
    raise TypeError(f"Unsupported traffic log event type: {type(event)!r}")


def traffic_event_to_python_dict(event: TrafficLogEvent | Any) -> dict[str, Any]:
    """Return a Python-mode event dictionary for storage adapters."""
    if isinstance(event, TrafficLogEvent):
        return event.model_dump(mode="python", exclude_none=True)
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="python", exclude_none=True)
    if isinstance(event, dict):
        return event
    raise TypeError(f"Unsupported traffic log event type: {type(event)!r}")
