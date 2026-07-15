"""Bounded Harness-owned idempotent side-effect executors."""

from __future__ import annotations

from typing import Any, Mapping

from gpt2giga_harness.runtime.models import SideEffectReservation
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore


class HarnessSideEffectExecutor:
    """Execute the durable runtime-event operation without ambiguous replay."""

    EVENT_OPERATION = "runtime.event.enqueue"

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
