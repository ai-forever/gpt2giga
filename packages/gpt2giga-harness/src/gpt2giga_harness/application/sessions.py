"""Session application flow shared by Web and CLI clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga_harness.runtime.models import RuntimeJob
from gpt2giga_harness.runtime.policy import ApprovalDecision, ApprovalRequest
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableSubmission
from gpt2giga_harness.session_runner import (
    HarnessSessionRunResult,
    HarnessSessionRunner,
)
from gpt2giga_harness.sessions.event_stream import EventTailPage
from gpt2giga_harness.sessions.models import (
    HarnessRun,
    HarnessSession,
    HarnessStoredEvent,
)
from gpt2giga_harness.sessions.store import new_id, title_from_prompt, utc_now
from gpt2giga_harness.settings import HarnessSettingsStore


class DurableRuntimeUnavailableError(RuntimeError):
    """Raised when a durable application operation has no runtime owner."""


@dataclass(frozen=True)
class ApprovalDecisionResult:
    """Approval decision plus its durable job continuation state."""

    approval: ApprovalRequest
    job: RuntimeJob | None
    retry_action: bool


class SessionApplicationService:
    """Coordinate one session vertical over existing runtime authorities."""

    def __init__(
        self,
        *,
        runner: HarnessSessionRunner,
        settings_store: HarnessSettingsStore,
        runtime_store: RuntimeCoordinationStore | None = None,
        dispatcher: DurableJobDispatcher | None = None,
    ) -> None:
        self.runner = runner
        self.store = runner.store
        self.settings_store = settings_store
        self.runtime_store = runtime_store
        self.dispatcher = dispatcher

    def create_session(
        self,
        payload: Mapping[str, Any],
        *,
        title_from_turn: bool = False,
        validate_harness: bool = False,
    ) -> HarnessSession:
        """Create one session from backend-owned defaults and client overrides."""
        defaults = self.settings_store.load().defaults
        harness_id = str(payload.get("harness_id") or defaults.default_harness_id)
        if validate_harness:
            self.runner.registry.get(harness_id)
        title = _optional_text(payload.get("title"))
        if title is None and title_from_turn:
            title = title_from_prompt(str(payload.get("prompt") or ""))
        return self.runner.create_session(
            title=title,
            workspace=_optional_text(payload.get("workspace")),
            default_harness_id=harness_id,
            default_model=(
                _optional_text(payload.get("model"))
                if "model" in payload
                else defaults.default_model
            ),
            default_api_mode=payload.get("api_mode") or defaults.default_api_mode,
            default_mode=str(payload.get("mode") or defaults.mode),
        )

    def prepare_turn_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Apply backend-only turn defaults without changing public input fields."""
        effective_payload = dict(payload)
        extra = _mapping(payload.get("extra"))
        if (
            bool(extra.get("generate_session_title"))
            and _optional_text(extra.get("session_title_model")) is None
        ):
            title_model = self.settings_store.load().defaults.default_title_model
            if title_model is not None:
                extra["session_title_model"] = title_model
        effective_payload["extra"] = extra
        return effective_payload

    def submit_turn(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        origin: str = "interactive",
    ) -> DurableSubmission:
        """Submit one turn to the existing durable dispatcher and policy owner."""
        if self.dispatcher is None:
            raise DurableRuntimeUnavailableError(
                "Durable runtime is required for session turn submission"
            )
        return self.dispatcher.submit(
            session_id,
            self.prepare_turn_payload(payload),
            idempotency_key=idempotency_key,
            origin=origin,
        )

    def run_turn(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any | None = None,
    ) -> HarnessSessionRunResult:
        """Run one request-bound compatibility turn through the existing runner."""
        return self.runner.run_in_session(
            session_id,
            self.prepare_turn_payload(payload),
            cancel_event=cancel_event,
        )

    def create_and_run(
        self,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any | None = None,
    ) -> HarnessSessionRunResult:
        """Create a session and execute one request-bound compatibility turn."""
        return self.runner.create_and_run(
            self.prepare_turn_payload(payload),
            cancel_event=cancel_event,
        )

    def get_run(self, run_id: str) -> HarnessRun:
        """Read one run through the session application boundary."""
        return self.store.get_run(run_id)

    def list_run_events(
        self,
        run_id: str,
        *,
        after_id: str | None = None,
    ) -> tuple[HarnessStoredEvent, ...]:
        """Return normalized persisted events for one run."""
        run = self.store.get_run(run_id)
        return self.store.list_events(
            run.session_id,
            run_id=run.id,
            after_id=after_id,
        )

    def read_run_event_tail(
        self,
        run_id: str,
        offset: int,
        *,
        limit: int = 100,
        max_bytes: int = 1024 * 1024,
    ) -> tuple[HarnessRun, EventTailPage]:
        """Read one bounded event-tail page from the authoritative session store."""
        run = self.store.get_run(run_id)
        reader = getattr(self.store, "list_event_tail_page", None)
        if not callable(reader):
            raise ValueError("session store does not support durable event tails")
        page = reader(
            run.session_id,
            run_id=run.id,
            offset=offset,
            limit=limit,
            max_bytes=max_bytes,
        )
        return run, page

    def find_job_for_run(self, run_id: str) -> RuntimeJob | None:
        """Return the durable job linked to a run, when runtime is available."""
        if self.runtime_store is None:
            return None
        return self.runtime_store.find_job_for_run(run_id)

    def decide_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision | str,
        *,
        project_expiry_seconds: float | None = None,
    ) -> ApprovalDecisionResult:
        """Decide one approval and project the existing job/run continuation."""
        if self.runtime_store is None:
            raise DurableRuntimeUnavailableError(
                "Durable runtime is unavailable for approval decisions"
            )
        parsed_decision = ApprovalDecision(decision)
        approval = self.runtime_store.decide_approval_request(
            approval_id,
            parsed_decision,
            project_expiry_seconds=project_expiry_seconds,
        )
        self._append_decision_event(approval)
        job = self.runtime_store.get_job(approval.job_id) if approval.job_id else None
        if (
            job is not None
            and job.status.value == "canceled"
            and approval.run_id
            and hasattr(self.store, "update_run")
        ):
            self.store.update_run(
                approval.run_id,
                status="canceled",
                error="approval denied",
                finished_at=utc_now(),
            )
        return ApprovalDecisionResult(
            approval=approval,
            job=job,
            retry_action=job is None and parsed_decision is not ApprovalDecision.DENY,
        )

    def _append_decision_event(self, approval: ApprovalRequest) -> None:
        if not approval.session_id or not hasattr(self.store, "append_event"):
            return
        self.store.append_event(
            HarnessStoredEvent(
                id=new_id("evt"),
                session_id=approval.session_id,
                run_id=approval.run_id,
                type="approval_decided",
                message=(f"Approval {approval.status.value}: {approval.action.value}."),
                payload={
                    "approval_id": approval.id,
                    "action": approval.action.value,
                    "decision": (
                        approval.decision.value if approval.decision else None
                    ),
                    "enforcement": approval.enforcement.value,
                },
                created_at=utc_now(),
                trace_id=approval.job_id or approval.run_id,
                job_id=approval.job_id,
                span_kind="approval",
                span_status=approval.status.value,
            )
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
