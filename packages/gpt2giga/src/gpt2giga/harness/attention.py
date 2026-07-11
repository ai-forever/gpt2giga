"""Derived, acknowledgement-only Attention Inbox for durable control-plane state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gpt2giga.harness.project import HarnessProject
from gpt2giga.harness.runtime.models import ApprovalStatus, JobStatus
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.harness.schedules import ScheduleService


@dataclass(frozen=True)
class AttentionItem:
    """One derived attention item with a stable acknowledgement identity."""

    id: str
    kind: str
    severity: str
    title: str
    summary: str
    href: str
    created_at: str
    read: bool = False
    desktop_notification: bool = False


class AttentionService:
    """Combine approvals, failures, and schedule findings without copying them."""

    def __init__(
        self,
        *,
        runtime_store: RuntimeCoordinationStore,
        schedule_service: ScheduleService,
    ) -> None:
        self.runtime_store = runtime_store
        self.schedule_service = schedule_service

    def list(self, project: HarnessProject) -> dict[str, Any]:
        """Return newest-first items and unread counters for one project."""
        items: list[AttentionItem] = []
        for approval in self.runtime_store.list_approval_requests(
            status=ApprovalStatus.PENDING, limit=200
        ):
            if approval.project_id not in {None, project.id}:
                continue
            items.append(
                AttentionItem(
                    id=f"approval:{approval.id}",
                    kind="approval",
                    severity="warning",
                    title=f"Approval needed: {approval.action.value}",
                    summary=approval.reason,
                    href="/approvals",
                    created_at=approval.created_at,
                    desktop_notification=True,
                )
            )
        jobs, _ = self.runtime_store.list_jobs_page(
            statuses=(JobStatus.FAILED,), project_id=project.id, limit=100
        )
        for job in jobs:
            items.append(
                AttentionItem(
                    id=f"job:{job.id}",
                    kind="failed_job",
                    severity="error",
                    title="Durable job failed",
                    summary=job.error_summary or f"{job.origin} job needs review",
                    href=f"/runs/{job.initial_run_id}"
                    if job.initial_run_id
                    else "/runs",
                    created_at=job.updated_at,
                    desktop_notification=True,
                )
            )
        automation = self.schedule_service.automation_overview(project)
        for schedule in automation["schedules"]:
            state = schedule.get("state") or {}
            if state.get("status") != "needs_attention":
                continue
            definition = schedule["definition"]
            notifications = definition.get("notifications") or {}
            schedule_id = str(definition.get("id") or state.get("schedule_id"))
            items.append(
                AttentionItem(
                    id=f"schedule:{project.id}:{schedule_id}:{state.get('updated_at')}",
                    kind="schedule",
                    severity="error",
                    title=f"Schedule needs attention: {definition.get('title') or schedule_id}",
                    summary=str(state.get("last_error") or "Background trigger failed"),
                    href=f"/scheduled/{schedule_id}",
                    created_at=str(
                        state.get("updated_at") or state.get("created_at") or ""
                    ),
                    desktop_notification=bool(notifications.get("desktop")),
                )
            )
        read_ids = self.runtime_store.attention_read_ids(
            tuple(item.id for item in items)
        )
        hydrated = [
            AttentionItem(**{**item.__dict__, "read": item.id in read_ids})
            for item in items
        ]
        hydrated.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return {
            "items": [dict(item.__dict__) for item in hydrated],
            "unread": sum(not item.read for item in hydrated),
            "counts": {
                kind: sum(item.kind == kind for item in hydrated)
                for kind in ("approval", "failed_job", "schedule")
            },
        }

    def mark_read(self, item_ids: tuple[str, ...], *, read: bool) -> None:
        """Acknowledge derived items while retaining every source audit row."""
        self.runtime_store.mark_attention_read(item_ids, read=read)
