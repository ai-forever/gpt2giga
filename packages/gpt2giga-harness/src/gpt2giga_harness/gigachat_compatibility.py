"""Redaction-safe evidence for concrete gpt2giga-routed Harness runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from gpt2giga_harness.sessions.models import HarnessRun, HarnessStoredEvent
from gpt2giga_harness.types import HarnessEvent, HarnessRequest


GIGACHAT_ROUTE_EVENT = "gigachat_gateway_ready"
GIGACHAT_ROUTE_EVENT_SCHEMA = "gpt2giga-harness/gigachat-route-ready-v1"
GIGACHAT_COMPATIBILITY_SCHEMA = "gpt2giga-harness/gigachat-compatibility-evidence-v1"

GIGACHAT_WIRE_BY_HARNESS = {
    "codex-cli": "openai-responses",
    "claude-code": "anthropic-messages",
    "gemini-cli": "gemini-generate-content",
}

_OBSERVABLE_EVENT_TYPES = frozenset(
    {
        "message_delta",
        "message_completed",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_finished",
        "usage",
        "error",
        "cancel_requested",
        "run_canceled",
        "run_finished",
    }
)


def gigachat_gateway_ready_event(
    request: HarnessRequest,
    *,
    harness_id: str,
    sidecar_started: bool,
) -> HarnessEvent:
    """Record a successful, content-free gpt2giga route readiness check."""
    try:
        wire = GIGACHAT_WIRE_BY_HARNESS[harness_id]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported gpt2giga compatibility harness: {harness_id}"
        ) from exc
    return HarnessEvent(
        type=GIGACHAT_ROUTE_EVENT,
        message="Confirmed the selected gpt2giga compatibility route is ready.",
        payload={
            "schema": GIGACHAT_ROUTE_EVENT_SCHEMA,
            "gateway": "gpt2giga",
            "harness_id": harness_id,
            "wire": wire,
            "api_mode": request.api_mode.value,
            "requested_model": request.model,
            "stream_requested": bool(request.stream),
            "sidecar_started": sidecar_started,
        },
    )


def gigachat_compatibility_evidence(
    run: HarnessRun,
    events: tuple[HarnessStoredEvent, ...],
) -> dict[str, Any] | None:
    """Build one content-addressed observation from stored run events.

    The evidence reports only route readiness and normalized semantics that were
    actually observed. It does not turn adapter capability declarations into a
    claim that a model or protocol behavior succeeded.
    """
    route_events = tuple(
        event for event in events if event.type == GIGACHAT_ROUTE_EVENT
    )
    if not route_events:
        return None
    if len(route_events) != 1:
        raise ValueError("GigaChat compatibility evidence requires one route event")

    payload = _mapping(route_events[0].payload)
    expected_wire = GIGACHAT_WIRE_BY_HARNESS.get(run.harness_id)
    expected = {
        "schema": GIGACHAT_ROUTE_EVENT_SCHEMA,
        "gateway": "gpt2giga",
        "harness_id": run.harness_id,
        "wire": expected_wire,
        "api_mode": run.api_mode.value,
        "requested_model": run.model,
    }
    if expected_wire is None:
        raise ValueError("Unrecognized harness published gpt2giga route evidence")
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"GigaChat route evidence does not match run {key}")
    for key in ("stream_requested", "sidecar_started"):
        if not isinstance(payload.get(key), bool):
            raise ValueError(f"GigaChat route evidence has invalid {key}")

    observed_event_types = sorted(
        {event.type for event in events if event.type in _OBSERVABLE_EVENT_TYPES}
    )
    evidence = {
        "schema": GIGACHAT_COMPATIBILITY_SCHEMA,
        "source_run_id": run.id,
        "harness_id": run.harness_id,
        "route": {
            "gateway": "gpt2giga",
            "wire": expected_wire,
            "api_mode": run.api_mode.value,
            "requested_model": run.model,
            "readiness": "observed",
            "sidecar_started": payload["sidecar_started"],
        },
        "request": {
            "invocation_mode": run.invocation_mode.value,
            "stream_requested": payload["stream_requested"],
        },
        "outcome": {
            "status": run.status.value,
            "observed_event_types": observed_event_types,
            "stream_observed": "message_delta" in observed_event_types,
            "tool_lifecycle_observed": any(
                event_type.startswith("tool_call_")
                for event_type in observed_event_types
            ),
            "usage_observed": "usage" in observed_event_types,
            "error_observed": "error" in observed_event_types,
            "cancellation_observed": "run_canceled" in observed_event_types,
        },
    }
    return {**evidence, "manifest_sha256": _content_hash(evidence)}


def _content_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
