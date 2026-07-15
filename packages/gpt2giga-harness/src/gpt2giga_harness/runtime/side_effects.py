"""Bounded Harness-owned idempotent side-effect executors."""

from __future__ import annotations

from typing import Any, Mapping

from gpt2giga_harness.runtime.models import SideEffectReservation
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore


class HarnessSideEffectExecutor:
    """Execute the durable runtime-event operation without ambiguous replay."""

    EVENT_OPERATION = "runtime.event.enqueue"
    RECOVERY_MARKER_EVENT_TYPE = "durable_side_effect_recorded"
    RECOVERY_MARKER_MESSAGE = "Recorded one durable Harness-owned side effect."

    def __init__(self, store: RuntimeCoordinationStore) -> None:
        self.store = store

    def record_event_once(
        self,
        *,
        job_id: str,
        attempt_id: str,
        token: str,
        event_type: str,
        message: str,
        payload: Mapping[str, Any],
    ) -> SideEffectReservation:
        """Enqueue one event or reuse its immutable completed evidence."""
        return self.store.enqueue_side_effect_event(
            job_id=job_id,
            attempt_id=attempt_id,
            token=token,
            event_type=event_type,
            message=message,
            payload=payload,
        )

    @classmethod
    def recovery_marker_intent(cls, job_id: str) -> dict[str, Any]:
        """Return the fixed public intent for one durable recovery marker."""
        return {
            "event_type": cls.RECOVERY_MARKER_EVENT_TYPE,
            "message": cls.RECOVERY_MARKER_MESSAGE,
            "payload": {"job_id": job_id, "result": "recorded"},
        }

    def record_recovery_marker_once(
        self,
        *,
        job_id: str,
        attempt_id: str,
        identity: str,
    ) -> SideEffectReservation:
        """Record one fixed durable-job marker or reuse completed evidence."""
        intent = self.recovery_marker_intent(job_id)
        return self.record_event_once(
            job_id=job_id,
            attempt_id=attempt_id,
            token=identity,
            event_type=str(intent["event_type"]),
            message=str(intent["message"]),
            payload=intent["payload"],
        )
