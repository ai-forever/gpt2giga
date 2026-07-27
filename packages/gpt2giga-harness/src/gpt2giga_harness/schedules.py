"""Immutable project schedules and SQLite-backed trigger coordination."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import rrule, tz
import yaml

from gpt2giga_harness.agents import agent_profile_to_dict, load_agent_profile
from gpt2giga_harness.evals import (
    FilesystemHarnessEvalStore,
    eval_run_to_dict,
    eval_spec_from_mapping,
    eval_spec_to_dict,
    load_eval_spec,
    queue_eval,
)
from gpt2giga_harness.project import (
    HarnessProject,
    load_project_config,
    project_preset_to_dict,
    resolve_project,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.models import run_to_dict
from gpt2giga_harness.sessions.store import title_from_prompt
from gpt2giga_harness.workflows import (
    WorkflowCoordinator,
    parse_workflow_definition,
    load_workflow,
    workflow_definition_to_dict,
    workflow_run_to_dict,
)

SCHEDULE_DIRECTORY = Path(".giga") / "schedules"
ACTIVE_OCCURRENCE_STATUSES = ("claimed", "dispatching", "queued", "running")
DEFAULT_PREVIEW_COUNT = 5


@dataclass(frozen=True)
class ScheduleDefinition:
    """One shareable, immutable-at-run-time schedule definition."""

    id: str
    title: str
    target_kind: str
    target_id: str
    target_hash: str
    target_snapshot: Mapping[str, Any]
    cadence_kind: str
    timezone: str
    start_at: str
    interval_seconds: float | None = None
    rrule_text: str | None = None
    prompt: str | None = None
    inputs: Mapping[str, Any] | None = None
    destination: str = "new_task"
    session_id: str | None = None
    workspace_policy: str = "worktree"
    timeout_seconds: float = 3600.0
    max_attempts: int = 1
    overlap_policy: str = "skip"
    max_concurrency: int = 1
    misfire_policy: str = "skip"
    misfire_grace_seconds: float = 60.0
    notifications: Mapping[str, Any] | None = None
    source_hash: str = ""


@dataclass(frozen=True)
class ScheduleOccurrence:
    """One persisted scheduled or manually triggered occurrence."""

    id: str
    schedule_id: str
    definition_hash: str
    scheduled_for: str
    trigger: str
    status: str
    destination_session_id: str | None = None
    history_cutoff: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    error_summary: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class ScheduleError(ValueError):
    """Raised for safe schedule validation or lifecycle failures."""


class ScheduleConflictError(ScheduleError):
    """Raised when a schedule changes after an optimistic preview."""


def build_schedule_definition(
    project: HarnessProject, payload: Mapping[str, Any]
) -> ScheduleDefinition:
    """Validate user input and capture an immutable target snapshot."""
    schedule_id = _safe_id(payload.get("id"), "schedule id")
    target = _mapping(payload.get("target"))
    target_kind = str(target.get("kind") or "").strip().lower()
    target_id = _safe_id(target.get("id"), "target id")
    snapshot = _target_snapshot(project, target_kind, target_id)
    target_hash = _hash(snapshot)
    cadence = _mapping(payload.get("cadence"))
    cadence_kind = str(cadence.get("kind") or "").strip().lower()
    if cadence_kind not in {"once", "interval", "rrule"}:
        raise ScheduleError("cadence.kind must be once, interval, or rrule")
    timezone_name = str(cadence.get("timezone") or "").strip()
    _timezone(timezone_name)
    start_at = _local_datetime_text(cadence.get("start_at"), timezone_name)
    interval_seconds = _optional_positive(cadence.get("interval_seconds"))
    rrule_text = _optional_text(cadence.get("rrule"))
    if cadence_kind == "interval" and interval_seconds is None:
        raise ScheduleError("interval cadence requires interval_seconds")
    if cadence_kind == "rrule" and rrule_text is None:
        raise ScheduleError("rrule cadence requires rrule")
    if rrule_text:
        try:
            rrule.rrulestr(rrule_text, dtstart=datetime.fromisoformat(start_at))
        except (ValueError, TypeError) as exc:
            raise ScheduleError(f"Invalid RRULE: {exc}") from exc
    destination = str(payload.get("destination") or "new_task").strip().lower()
    session_id = _optional_text(payload.get("session_id"))
    if destination not in {"new_task", "resume"}:
        raise ScheduleError("destination must be new_task or resume")
    if destination == "resume" and not session_id:
        raise ScheduleError("resume destination requires session_id")
    workspace_policy = str(payload.get("workspace_policy") or "worktree")
    if workspace_policy != "worktree":
        raise ScheduleError("scheduled work must use dedicated worktree isolation")
    definition = ScheduleDefinition(
        id=schedule_id,
        title=str(payload.get("title") or schedule_id).strip(),
        target_kind=target_kind,
        target_id=target_id,
        target_hash=target_hash,
        target_snapshot=snapshot,
        cadence_kind=cadence_kind,
        timezone=timezone_name,
        start_at=start_at,
        interval_seconds=interval_seconds,
        rrule_text=rrule_text,
        prompt=_optional_text(payload.get("prompt")),
        inputs=dict(_mapping(payload.get("inputs"))),
        destination=destination,
        session_id=session_id,
        workspace_policy=workspace_policy,
        timeout_seconds=_positive(payload.get("timeout_seconds"), 3600.0),
        max_attempts=max(int(payload.get("max_attempts") or 1), 1),
        overlap_policy=str(payload.get("overlap_policy") or "skip"),
        max_concurrency=max(int(payload.get("max_concurrency") or 1), 1),
        misfire_policy=str(payload.get("misfire_policy") or "skip"),
        misfire_grace_seconds=_positive(payload.get("misfire_grace_seconds"), 60.0),
        notifications={
            "desktop": bool(_mapping(payload.get("notifications")).get("desktop"))
        },
    )
    if definition.overlap_policy not in {"skip", "allow"}:
        raise ScheduleError("overlap_policy must be skip or allow")
    if definition.misfire_policy not in {"skip", "run_once"}:
        raise ScheduleError("misfire_policy must be skip or run_once")
    return replace(
        definition,
        source_hash=_hash(schedule_definition_to_dict(definition, include_hash=False)),
    )


def save_schedule(
    project: HarnessProject,
    definition: ScheduleDefinition,
    *,
    expected_hash: str | None = None,
) -> Path:
    """Atomically persist one shareable schedule definition."""
    directory = Path(project.root) / SCHEDULE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{definition.id}.yaml"
    with exclusive_file_lock(path):
        if expected_hash is not None:
            try:
                actual_hash = load_schedule(project.root, definition.id).source_hash
            except KeyError:
                actual_hash = None
            if actual_hash != expected_hash:
                raise ScheduleConflictError("Schedule changed since it was loaded")
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temp.write_text(
            yaml.safe_dump(
                schedule_definition_to_dict(definition, include_hash=False),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        temp.replace(path)
    return path


def load_schedule(project_root: str | Path, schedule_id: str) -> ScheduleDefinition:
    """Load and validate one schedule, retaining its captured target snapshot."""
    safe_id = _safe_id(schedule_id, "schedule id")
    path = Path(project_root) / SCHEDULE_DIRECTORY / f"{safe_id}.yaml"
    if not path.is_file():
        raise KeyError(safe_id)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScheduleError(f"Invalid schedule YAML: {path.name}") from exc
    return _definition_from_saved(_mapping(data))


def discover_schedules(project_root: str | Path) -> tuple[ScheduleDefinition, ...]:
    """Return valid schedule definitions in stable id order."""
    directory = Path(project_root) / SCHEDULE_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(
        load_schedule(project_root, path.stem)
        for path in sorted(directory.glob("*.yaml"))
    )


def next_occurrences(
    definition: ScheduleDefinition,
    *,
    after: datetime | None = None,
    count: int = DEFAULT_PREVIEW_COUNT,
) -> tuple[dict[str, Any], ...]:
    """Compute future UTC instants with explicit DST skip/fold semantics."""
    after_utc = _aware_utc(after or datetime.now(timezone.utc))
    zone = _timezone(definition.timezone)
    local_after = after_utc.astimezone(zone).replace(tzinfo=None)
    start = datetime.fromisoformat(definition.start_at)
    candidates: list[datetime] = []
    if definition.cadence_kind == "once":
        candidates = [start]
    elif definition.cadence_kind == "interval":
        seconds = float(definition.interval_seconds or 0)
        if seconds <= 0:
            return ()
        elapsed = max((local_after - start).total_seconds(), 0.0)
        step = int(elapsed // seconds) + 1 if local_after >= start else 0
        candidates = [
            start + timedelta(seconds=seconds * (step + i)) for i in range(count * 3)
        ]
    else:
        rule = rrule.rrulestr(definition.rrule_text or "", dtstart=start)
        cursor = local_after
        for _ in range(count * 3):
            item = rule.after(cursor, inc=False)
            if item is None:
                break
            candidates.append(item.replace(tzinfo=None))
            cursor = item
    result: list[dict[str, Any]] = []
    dateutil_zone = tz.gettz(definition.timezone)
    for local_value in candidates:
        aware = local_value.replace(tzinfo=dateutil_zone)
        if not tz.datetime_exists(aware):
            result.append(
                {
                    "local": local_value.isoformat(),
                    "utc": None,
                    "status": "misfire",
                    "reason": "nonexistent_local_time",
                }
            )
        else:
            if tz.datetime_ambiguous(aware):
                aware = tz.enfold(aware, fold=0)
            instant = aware.astimezone(timezone.utc)
            if instant > after_utc:
                result.append(
                    {
                        "local": local_value.isoformat(),
                        "utc": instant.isoformat(),
                        "status": "scheduled",
                        "reason": "ambiguous_first_instant"
                        if tz.datetime_ambiguous(aware)
                        else None,
                    }
                )
        if len(result) >= count:
            break
    return tuple(result)


class ScheduleService:
    """Coordinate schedule CRUD, test grants, and worker-driven triggers."""

    def __init__(
        self,
        *,
        runtime_store: RuntimeCoordinationStore,
        runner: Any,
        dispatcher: DurableJobDispatcher,
        eval_store: FilesystemHarnessEvalStore,
    ) -> None:
        self.runtime_store = runtime_store
        self.runner = runner
        self.dispatcher = dispatcher
        self.eval_store = eval_store

    def upsert(
        self,
        project: HarnessProject,
        payload: Mapping[str, Any],
        *,
        expected_hash: str | None = None,
    ) -> dict[str, Any]:
        definition = build_schedule_definition(project, payload)
        save_schedule(project, definition, expected_hash=expected_hash)
        next_run = _first_scheduled(definition)
        now = _utc_now()
        schedule_key = _schedule_key(project.id, definition.id)
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO schedule_states (
                    schedule_key, schedule_id, project_id, project_root, definition_hash,
                    definition_json, status, enabled, timezone, next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'paused', 0, ?, ?, ?, ?)
                ON CONFLICT(schedule_key) DO UPDATE SET
                    project_id=excluded.project_id, project_root=excluded.project_root,
                    definition_hash=excluded.definition_hash,
                    definition_json=excluded.definition_json, timezone=excluded.timezone,
                    next_run_at=excluded.next_run_at, status='paused', enabled=0,
                    tested_hash=NULL, tested_at=NULL, updated_at=excluded.updated_at
                """,
                (
                    schedule_key,
                    definition.id,
                    project.id,
                    project.root,
                    definition.source_hash,
                    json.dumps(
                        schedule_definition_to_dict(definition),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    definition.timezone,
                    next_run,
                    now,
                    now,
                ),
            )
            connection.commit()
        self.runtime_store.wake_workers()
        return self.detail(project, definition.id)

    def detail(self, project: HarnessProject, schedule_id: str) -> dict[str, Any]:
        definition = load_schedule(project.root, schedule_id)
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            state = connection.execute(
                "SELECT * FROM schedule_states WHERE project_id = ? AND schedule_id = ?",
                (project.id, schedule_id),
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM schedule_occurrences WHERE schedule_key = ? ORDER BY created_at DESC LIMIT 50",
                (_schedule_key(project.id, schedule_id),),
            ).fetchall()
        return {
            "definition": schedule_definition_to_dict(definition),
            "state": dict(state) if state is not None else None,
            "occurrences": [
                occurrence_to_dict(_occurrence_from_row(row)) for row in rows
            ],
            "preview": list(next_occurrences(definition)),
            "worker": self.worker_health(),
        }

    def list(self, project: HarnessProject) -> tuple[dict[str, Any], ...]:
        return tuple(
            self.detail(project, item.id) for item in discover_schedules(project.root)
        )

    def automation_overview(self, project: HarnessProject) -> dict[str, Any]:
        """Return live definitions plus archived audit rows for the UI center."""
        live = {item["definition"]["id"]: item for item in self.list(project)}
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            states = connection.execute(
                "SELECT * FROM schedule_states WHERE project_id = ? ORDER BY updated_at DESC, schedule_id",
                (project.id,),
            ).fetchall()
            occurrence_rows = connection.execute(
                """
                SELECT schedule_occurrences.* FROM schedule_occurrences
                JOIN schedule_states USING (schedule_key)
                WHERE schedule_states.project_id = ?
                ORDER BY schedule_occurrences.created_at DESC LIMIT 200
                """,
                (project.id,),
            ).fetchall()
        schedules: list[dict[str, Any]] = list(live.values())
        for state in states:
            schedule_id = str(state["schedule_id"])
            if schedule_id in live:
                continue
            try:
                definition = json.loads(str(state["definition_json"] or "{}"))
            except json.JSONDecodeError:
                definition = {}
            schedules.append(
                {
                    "definition": definition
                    or {
                        "id": schedule_id,
                        "title": schedule_id,
                        "source_hash": str(state["definition_hash"]),
                    },
                    "state": dict(state),
                    "occurrences": [],
                    "preview": [],
                    "worker": self.worker_health(),
                }
            )
        schedules.sort(
            key=lambda item: (
                str((item.get("state") or {}).get("status") == "archived"),
                str(item["definition"].get("title") or item["definition"].get("id")),
            )
        )
        return {
            "schedules": schedules,
            "history": [
                occurrence_to_dict(_occurrence_from_row(row)) for row in occurrence_rows
            ],
            "worker": self.worker_health(),
        }

    def test_now(
        self,
        project: HarnessProject,
        schedule_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        definition = load_schedule(project.root, schedule_id)
        occurrence = self._create_occurrence(
            definition,
            schedule_key=_schedule_key(project.id, schedule_id),
            trigger="test",
            scheduled_for=_utc_now(),
            idempotency_key=idempotency_key,
        )
        return self._execute(project, definition, occurrence, dry_run=True)

    def enable(self, project: HarnessProject, schedule_id: str) -> dict[str, Any]:
        definition = load_schedule(project.root, schedule_id)
        if not self.worker_health()["online"]:
            raise ScheduleError("A local durable worker must be online before enable")
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "SELECT tested_hash FROM schedule_states WHERE schedule_key = ?",
                (_schedule_key(project.id, schedule_id),),
            ).fetchone()
            if row is None or row[0] != definition.source_hash:
                raise ScheduleError(
                    "Test now must succeed for this exact schedule hash before enable"
                )
            connection.execute(
                "UPDATE schedule_states SET enabled = 1, status = 'active', next_run_at = ?, updated_at = ? WHERE schedule_key = ?",
                (
                    _first_scheduled(definition),
                    _utc_now(),
                    _schedule_key(project.id, schedule_id),
                ),
            )
        self.runtime_store.wake_workers()
        return self.detail(project, schedule_id)

    def pause(self, project: HarnessProject, schedule_id: str) -> dict[str, Any]:
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute(
                "UPDATE schedule_states SET enabled = 0, status = 'paused', updated_at = ? WHERE schedule_key = ?",
                (_utc_now(), _schedule_key(project.id, schedule_id)),
            )
        self.runtime_store.wake_workers()
        return self.detail(project, schedule_id)

    def archive(
        self,
        project: HarnessProject,
        schedule_id: str,
        *,
        expected_hash: str | None = None,
    ) -> dict[str, Any]:
        """Remove the shareable definition while retaining immutable audit rows."""
        path = Path(project.root) / SCHEDULE_DIRECTORY / f"{schedule_id}.yaml"
        with exclusive_file_lock(path):
            definition = load_schedule(project.root, schedule_id)
            if expected_hash is not None and definition.source_hash != expected_hash:
                raise ScheduleConflictError("Schedule changed since the delete preview")
            self.pause(project, schedule_id)
            path.unlink()
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute(
                "UPDATE schedule_states SET status = 'archived', enabled = 0, definition_json = ?, updated_at = ? WHERE schedule_key = ?",
                (
                    json.dumps(
                        schedule_definition_to_dict(definition),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    _utc_now(),
                    _schedule_key(project.id, schedule_id),
                ),
            )
        return {"archived": True, "schedule_id": schedule_id}

    def run_now(
        self,
        project: HarnessProject,
        schedule_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        definition = load_schedule(project.root, schedule_id)
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            state = connection.execute(
                "SELECT tested_hash FROM schedule_states WHERE schedule_key = ?",
                (_schedule_key(project.id, schedule_id),),
            ).fetchone()
        if state is None or state[0] != definition.source_hash:
            raise ScheduleError(
                "Test now must succeed for this exact schedule hash before run-now"
            )
        occurrence = self._create_occurrence(
            definition,
            schedule_key=_schedule_key(project.id, schedule_id),
            trigger="run_now",
            scheduled_for=_utc_now(),
            idempotency_key=idempotency_key,
        )
        return self._execute(project, definition, occurrence, dry_run=False)

    def tick(self) -> int:
        """Dispatch all currently due definitions; called by the local worker."""
        self._sync_occurrences()
        recovered = self._recover_dispatching_occurrences()
        now = _utc_now()
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                "SELECT * FROM schedule_states WHERE enabled = 1 AND status = 'active' AND next_run_at <= ? ORDER BY next_run_at",
                (now,),
            ).fetchall()
        dispatched = recovered
        for state in rows:
            try:
                project = resolve_project(
                    str(state["project_root"]),
                    data_dir=self.eval_store.data_dir,
                )
                if project.id != str(state["project_id"]):
                    raise ScheduleError(
                        "scheduled project identity changed; refusing dispatch"
                    )
                definition = load_schedule(project.root, str(state["schedule_id"]))
                scheduled_for = str(state["next_run_at"])
                future = next_occurrences(
                    definition,
                    after=datetime.fromisoformat(scheduled_for),
                    count=8,
                )
                next_run = next(
                    (str(item["utc"]) for item in future if item["utc"]), None
                )
                for item in future:
                    if item["status"] != "misfire":
                        break
                    self._create_occurrence(
                        definition,
                        schedule_key=str(state["schedule_key"]),
                        trigger="schedule",
                        scheduled_for=(f"{item['local']}[{definition.timezone}]"),
                        status="misfired",
                        error=str(item["reason"]),
                    )
                delay = (
                    datetime.now(timezone.utc) - datetime.fromisoformat(scheduled_for)
                ).total_seconds()
                if (
                    delay > definition.misfire_grace_seconds
                    and definition.misfire_policy == "skip"
                ):
                    self._create_occurrence(
                        definition,
                        schedule_key=str(state["schedule_key"]),
                        trigger="schedule",
                        scheduled_for=scheduled_for,
                        status="misfired",
                        error="missed occurrence; automatic catch-up disabled",
                    )
                else:
                    occurrence = self._create_occurrence(
                        definition,
                        schedule_key=str(state["schedule_key"]),
                        trigger="schedule",
                        scheduled_for=scheduled_for,
                    )
                    if occurrence.status == "claimed":
                        self._execute(project, definition, occurrence, dry_run=False)
                        dispatched += 1
                with self.runtime_store._connect() as connection:  # noqa: SLF001
                    connection.execute(
                        "UPDATE schedule_states SET next_run_at = ?, last_run_at = ?, updated_at = ? WHERE schedule_key = ?",
                        (
                            next_run,
                            scheduled_for,
                            _utc_now(),
                            str(state["schedule_key"]),
                        ),
                    )
            except Exception as exc:
                self._mark_attention(str(state["schedule_key"]), str(exc))
        return dispatched

    def _recover_dispatching_occurrences(self) -> int:
        """Resume schedule dispatch after owner loss without duplicating child state."""
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                """
                SELECT schedule_occurrences.*, schedule_states.project_id,
                       schedule_states.project_root
                FROM schedule_occurrences
                JOIN schedule_states USING (schedule_key)
                WHERE schedule_occurrences.status = 'dispatching'
                ORDER BY schedule_occurrences.created_at, schedule_occurrences.id
                """
            ).fetchall()
        recovered = 0
        for row in rows:
            occurrence = _occurrence_from_row(row)
            try:
                project = resolve_project(
                    str(row["project_root"]), data_dir=self.eval_store.data_dir
                )
                if project.id != str(row["project_id"]):
                    raise ScheduleError(
                        "scheduled project identity changed; refusing recovery"
                    )
                definition = load_schedule(project.root, occurrence.schedule_id)
                if definition.source_hash != occurrence.definition_hash:
                    raise ScheduleError(
                        "schedule definition changed during dispatch recovery"
                    )
                if definition.target_kind not in {"agent", "preset", "workflow"}:
                    raise ScheduleError(
                        "scheduled-start recovery is not proven for this target kind"
                    )
                result, job_id, run_id, session_id = self._dispatch_target(
                    project,
                    definition,
                    occurrence,
                    dry_run=occurrence.trigger == "test",
                )
                del result
                self._finish_occurrence(
                    occurrence.id,
                    "queued",
                    job_id=job_id,
                    run_id=run_id,
                    session_id=session_id,
                )
                recovered += 1
            except Exception as exc:
                self._finish_occurrence(occurrence.id, "failed", error=str(exc))
        return recovered

    def worker_health(self) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=15)
        online = [
            item
            for item in self.runtime_store.list_workers()
            if item.status == "online"
            and datetime.fromisoformat(item.heartbeat_at) >= cutoff
        ]
        return {"online": bool(online), "count": len(online)}

    def _create_occurrence(
        self,
        definition: ScheduleDefinition,
        *,
        schedule_key: str,
        trigger: str,
        scheduled_for: str,
        status: str = "claimed",
        error: str | None = None,
        idempotency_key: str | None = None,
    ) -> ScheduleOccurrence:
        occurrence_id = (
            _manual_occurrence_id(
                schedule_key,
                trigger,
                idempotency_key,
            )
            if idempotency_key is not None
            else f"occurrence_{uuid4().hex}"
        )
        now = _utc_now()
        session_id = (
            definition.session_id if definition.destination == "resume" else None
        )
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM schedule_occurrences WHERE id = ?",
                (occurrence_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["definition_hash"]) != definition.source_hash
                    or str(existing["trigger"]) != trigger
                ):
                    connection.rollback()
                    raise ScheduleError(
                        "idempotency key is already bound to a different schedule action"
                    )
                connection.commit()
                return _occurrence_from_row(existing)
            existing = connection.execute(
                """
                SELECT * FROM schedule_occurrences
                WHERE schedule_key = ? AND scheduled_for = ? AND trigger = ?
                """,
                (schedule_key, scheduled_for, trigger),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return _occurrence_from_row(existing)
            active = connection.execute(
                "SELECT COUNT(*) FROM schedule_occurrences WHERE schedule_key = ? AND trigger != 'test' AND status IN ('claimed','dispatching','queued','running')",
                (schedule_key,),
            ).fetchone()[0]
            serialized = 0
            if session_id:
                serialized = connection.execute(
                    "SELECT COUNT(*) FROM schedule_occurrences WHERE destination_session_id = ? AND status IN ('claimed','dispatching','queued','running')",
                    (session_id,),
                ).fetchone()[0]
            if status == "claimed" and (
                (
                    active >= definition.max_concurrency
                    and definition.overlap_policy == "skip"
                )
                or serialized
            ):
                status, error = "skipped", "overlap policy skipped active occurrence"
            connection.execute(
                """
                INSERT INTO schedule_occurrences (
                    id, schedule_key, schedule_id, definition_hash, scheduled_for, trigger,
                    status, destination_session_id, history_cutoff, error_summary,
                    created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurrence_id,
                    schedule_key,
                    definition.id,
                    definition.source_hash,
                    scheduled_for,
                    trigger,
                    status,
                    session_id,
                    now if session_id else None,
                    error,
                    now,
                    now if status == "claimed" else None,
                    now if status not in ACTIVE_OCCURRENCE_STATUSES else None,
                ),
            )
            connection.execute(
                """
                UPDATE schedule_states
                SET last_status = ?, last_error = ?, updated_at = ?
                WHERE schedule_key = (
                    SELECT schedule_key FROM schedule_occurrences WHERE id = ?
                )
                """,
                (status, error, _utc_now(), occurrence_id),
            )
            connection.commit()
        return ScheduleOccurrence(
            occurrence_id,
            definition.id,
            definition.source_hash,
            scheduled_for,
            trigger,
            status,
            session_id,
            now if session_id else None,
            error_summary=error,
            created_at=now,
            started_at=now if status == "claimed" else None,
        )

    def _execute(
        self,
        project: HarnessProject,
        definition: ScheduleDefinition,
        occurrence: ScheduleOccurrence,
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        occurrence, dispatch_claimed = self._claim_dispatch(occurrence.id)
        if not dispatch_claimed:
            return {"occurrence": occurrence_to_dict(occurrence), "result": None}
        try:
            result, job_id, run_id, session_id = self._dispatch_target(
                project, definition, occurrence, dry_run=dry_run
            )
        except Exception as exc:
            self._finish_occurrence(occurrence.id, "failed", error=str(exc))
            if occurrence.trigger == "test":
                raise ScheduleError(f"Scheduled target test failed: {exc}") from exc
            raise
        self._finish_occurrence(
            occurrence.id,
            "queued",
            job_id=job_id,
            run_id=run_id,
            session_id=session_id,
        )
        return {
            "occurrence": occurrence_to_dict(self._get_occurrence(occurrence.id)),
            "result": result,
        }

    def _claim_dispatch(self, occurrence_id: str) -> tuple[ScheduleOccurrence, bool]:
        """Atomically grant one delivery the right to create target state."""
        now = _utc_now()
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE schedule_occurrences
                SET status = 'dispatching', started_at = COALESCE(started_at, ?)
                WHERE id = ? AND status = 'claimed'
                """,
                (now, occurrence_id),
            )
            claimed = connection.execute("SELECT changes()").fetchone()[0] == 1
            row = connection.execute(
                "SELECT * FROM schedule_occurrences WHERE id = ?", (occurrence_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(occurrence_id)
            if claimed:
                connection.execute(
                    """
                    UPDATE schedule_states
                    SET last_status = 'dispatching', last_error = NULL, updated_at = ?
                    WHERE schedule_key = ?
                    """,
                    (now, str(row["schedule_key"])),
                )
            connection.commit()
        return _occurrence_from_row(row), claimed

    def _sync_occurrences(self) -> None:
        """Project terminal job, workflow, and eval state into occurrence history."""
        from gpt2giga_harness.runtime.models import TERMINAL_JOB_STATUSES
        from gpt2giga_harness.workflows import WorkflowRepository

        with self.runtime_store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                """
                SELECT schedule_occurrences.*, schedule_states.project_root
                FROM schedule_occurrences
                JOIN schedule_states USING (schedule_key)
                WHERE schedule_occurrences.status IN ('queued', 'running')
                """
            ).fetchall()
        for row in rows:
            status = None
            error = None
            scheduled_eval_regression = False
            if row["job_id"]:
                job = self.runtime_store.get_job(str(row["job_id"]))
                if job.status in TERMINAL_JOB_STATUSES:
                    status = job.status.value
                    error = job.error_summary
                elif job.status.value == "running":
                    status = "running"
            elif row["run_id"]:
                try:
                    definition = load_schedule(
                        str(row["project_root"]), str(row["schedule_id"])
                    )
                    if definition.target_kind == "workflow":
                        current = WorkflowRepository(self.runtime_store).get_run(
                            str(row["run_id"])
                        )
                        status = current.status.value
                        error = current.error_summary
                    elif definition.target_kind == "eval":
                        current_eval = self.eval_store.get_any(str(row["run_id"]))
                        status = current_eval.status
                        if status == "failed" and row["trigger"] != "test":
                            summary = current_eval.summary
                            error = (
                                "scheduled eval regression: "
                                f"{summary.get('failed', 0)} failed, "
                                f"{summary.get('errors', 0)} errors across "
                                f"{summary.get('total', 0)} cells"
                            )
                            scheduled_eval_regression = True
                except (KeyError, ScheduleError):
                    continue
            if status in {"succeeded", "failed", "canceled", "passed"}:
                terminal_status = "succeeded" if status == "passed" else status
                self._finish_occurrence(
                    str(row["id"]),
                    terminal_status,
                    error=error,
                )
                if scheduled_eval_regression:
                    self._mark_attention(
                        str(row["schedule_key"]), error or "eval failed"
                    )
                if row["trigger"] == "test" and terminal_status == "succeeded":
                    now = _utc_now()
                    with self.runtime_store._connect() as connection:  # noqa: SLF001
                        connection.execute(
                            "UPDATE schedule_states SET tested_hash = ?, tested_at = ?, updated_at = ? WHERE schedule_key = ?",
                            (
                                str(row["definition_hash"]),
                                now,
                                now,
                                str(row["schedule_key"]),
                            ),
                        )
            elif status == "running":
                self._finish_occurrence(str(row["id"]), "running")

    def _dispatch_target(
        self,
        project: HarnessProject,
        definition: ScheduleDefinition,
        occurrence: ScheduleOccurrence,
        *,
        dry_run: bool,
    ) -> tuple[dict[str, Any], str | None, str | None, str | None]:
        snapshot = dict(definition.target_snapshot)
        if _hash(snapshot) != definition.target_hash:
            raise ScheduleError("target snapshot hash mismatch")
        if definition.target_kind in {"agent", "preset"}:
            prompt = definition.prompt or str(
                snapshot.get("prompt") or definition.title
            )
            if definition.target_kind == "agent" and snapshot.get("instructions"):
                prompt = (
                    f"Agent role instructions:\n{snapshot['instructions']}\n\n"
                    f"Task:\n{prompt}"
                )
            harness_id = str(
                snapshot.get("harness_id") or snapshot.get("harness") or "echo"
            )
            mode = str(snapshot.get("mode") or "read")
            session = (
                self.runner.store.get_session(definition.session_id)
                if definition.destination == "resume"
                else self.runner.create_session(
                    title=title_from_prompt(prompt),
                    workspace=project.root,
                    default_harness_id=harness_id,
                    default_model=_optional_text(snapshot.get("model")),
                    default_mode=mode,
                )
            )
            payload = {
                "harness_id": harness_id,
                "prompt": prompt,
                "model": snapshot.get("model"),
                "api_mode": snapshot.get("api_mode") or "v2",
                "invocation_mode": snapshot.get("invocation_mode") or "headless",
                "mode": mode,
                "workspace": project.root,
                "workspace_policy": "worktree",
                "timeout_seconds": definition.timeout_seconds,
                "max_attempts": definition.max_attempts,
                "permission_profile": "unattended",
                "schedule_id": definition.id,
                "agent_id": definition.target_id
                if definition.target_kind == "agent"
                else None,
                "dry_run": dry_run,
                "extra": {
                    "schedule_id": definition.id,
                    "schedule_hash": definition.source_hash,
                    "target_snapshot": snapshot,
                    "history_cutoff": occurrence.history_cutoff,
                },
            }
            if payload["invocation_mode"] == "native":
                payload["execution_transport"] = "native_structured"
            submission = self.dispatcher.submit(
                session.id,
                payload,
                idempotency_key=f"schedule:{definition.id}:{occurrence.id}",
                origin="scheduled",
            )
            return (
                run_to_dict(submission.queued.run),
                submission.job.id,
                submission.queued.run.id,
                session.id,
            )
        if definition.target_kind == "workflow":
            workflow = parse_workflow_definition(
                yaml.safe_dump(snapshot, sort_keys=False), allow_unknown=True
            )
            coordinator = WorkflowCoordinator(
                project=project,
                runtime_store=self.runtime_store,
                runner=self.runner,
                dispatcher=self.dispatcher,
                origin="scheduled",
                schedule_id=definition.id,
            )
            run = coordinator.start(
                workflow,
                inputs=dict(definition.inputs or {}),
                prompt=definition.prompt,
                idempotency_key=f"schedule:{definition.id}:{occurrence.id}",
            )
            return (
                workflow_run_to_dict(run, coordinator.repository.list_steps(run.id)),
                None,
                run.id,
                run.session_id,
            )
        if definition.target_kind == "eval":
            spec = eval_spec_from_mapping(
                snapshot,
                path=Path(project.root) / SCHEDULE_DIRECTORY / f"{definition.id}.yaml",
            )
            eval_run = queue_eval(
                runner=self.runner,
                dispatcher=self.dispatcher,
                eval_store=self.eval_store,
                project=project,
                spec=spec,
                dry_run=dry_run,
                origin="scheduled",
                schedule_id=definition.id,
            )
            return eval_run_to_dict(eval_run), None, eval_run.id, eval_run.session_id
        raise ScheduleError(f"Unsupported target kind: {definition.target_kind}")

    def _finish_occurrence(
        self,
        occurrence_id: str,
        status: str,
        *,
        job_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute(
                "UPDATE schedule_occurrences SET status = ?, job_id = COALESCE(?, job_id), run_id = COALESCE(?, run_id), destination_session_id = COALESCE(?, destination_session_id), error_summary = ?, finished_at = CASE WHEN ? IN ('tested','succeeded','failed','canceled','skipped','misfired') THEN ? ELSE finished_at END WHERE id = ?",
                (
                    status,
                    job_id,
                    run_id,
                    session_id,
                    error,
                    status,
                    _utc_now(),
                    occurrence_id,
                ),
            )
            connection.execute(
                """
                UPDATE schedule_states
                SET last_status = ?, last_error = ?, updated_at = ?
                WHERE schedule_key = (
                    SELECT schedule_key FROM schedule_occurrences WHERE id = ?
                )
                """,
                (status, error, _utc_now(), occurrence_id),
            )

    def _get_occurrence(self, occurrence_id: str) -> ScheduleOccurrence:
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "SELECT * FROM schedule_occurrences WHERE id = ?", (occurrence_id,)
            ).fetchone()
        return _occurrence_from_row(row)

    def _mark_attention(self, schedule_key: str, error: str) -> None:
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute(
                "UPDATE schedule_states SET status = 'needs_attention', enabled = 0, last_status = 'failed', last_error = ?, updated_at = ? WHERE schedule_key = ?",
                (error[:1000], _utc_now(), schedule_key),
            )


def schedule_definition_to_dict(
    definition: ScheduleDefinition, *, include_hash: bool = True
) -> dict[str, Any]:
    payload = {
        "id": definition.id,
        "title": definition.title,
        "target": {
            "kind": definition.target_kind,
            "id": definition.target_id,
            "hash": definition.target_hash,
            "snapshot": dict(definition.target_snapshot),
        },
        "cadence": {
            "kind": definition.cadence_kind,
            "timezone": definition.timezone,
            "start_at": definition.start_at,
            "interval_seconds": definition.interval_seconds,
            "rrule": definition.rrule_text,
        },
        "prompt": definition.prompt,
        "inputs": dict(definition.inputs or {}),
        "destination": definition.destination,
        "session_id": definition.session_id,
        "workspace_policy": definition.workspace_policy,
        "timeout_seconds": definition.timeout_seconds,
        "max_attempts": definition.max_attempts,
        "overlap_policy": definition.overlap_policy,
        "max_concurrency": definition.max_concurrency,
        "misfire_policy": definition.misfire_policy,
        "misfire_grace_seconds": definition.misfire_grace_seconds,
        "notifications": dict(definition.notifications or {"desktop": False}),
    }
    if include_hash:
        payload["source_hash"] = definition.source_hash
    return payload


def occurrence_to_dict(item: ScheduleOccurrence) -> dict[str, Any]:
    return dict(item.__dict__)


def _definition_from_saved(data: Mapping[str, Any]) -> ScheduleDefinition:
    target, cadence = _mapping(data.get("target")), _mapping(data.get("cadence"))
    definition = ScheduleDefinition(
        id=_safe_id(data.get("id"), "schedule id"),
        title=str(data.get("title") or data.get("id")),
        target_kind=str(target.get("kind")),
        target_id=_safe_id(target.get("id"), "target id"),
        target_hash=str(target.get("hash") or ""),
        target_snapshot=dict(_mapping(target.get("snapshot"))),
        cadence_kind=str(cadence.get("kind")),
        timezone=str(cadence.get("timezone")),
        start_at=str(cadence.get("start_at")),
        interval_seconds=_optional_positive(cadence.get("interval_seconds")),
        rrule_text=_optional_text(cadence.get("rrule")),
        prompt=_optional_text(data.get("prompt")),
        inputs=dict(_mapping(data.get("inputs"))),
        destination=str(data.get("destination") or "new_task"),
        session_id=_optional_text(data.get("session_id")),
        workspace_policy=str(data.get("workspace_policy") or "worktree"),
        timeout_seconds=_positive(data.get("timeout_seconds"), 3600),
        max_attempts=max(int(data.get("max_attempts") or 1), 1),
        overlap_policy=str(data.get("overlap_policy") or "skip"),
        max_concurrency=max(int(data.get("max_concurrency") or 1), 1),
        misfire_policy=str(data.get("misfire_policy") or "skip"),
        misfire_grace_seconds=_positive(data.get("misfire_grace_seconds"), 60),
        notifications={
            "desktop": bool(_mapping(data.get("notifications")).get("desktop"))
        },
    )
    source_hash = _hash(schedule_definition_to_dict(definition, include_hash=False))
    if _hash(definition.target_snapshot) != definition.target_hash:
        raise ScheduleError("Persisted target snapshot hash mismatch")
    return replace(definition, source_hash=source_hash)


def _target_snapshot(
    project: HarnessProject, kind: str, target_id: str
) -> dict[str, Any]:
    if kind == "agent":
        return _jsonable(
            agent_profile_to_dict(load_agent_profile(project.root, target_id))
        )
    if kind == "workflow":
        return _jsonable(
            workflow_definition_to_dict(load_workflow(project.root, target_id))
        )
    if kind == "eval":
        return _jsonable(eval_spec_to_dict(load_eval_spec(project.root, target_id)))
    if kind == "preset":
        config = load_project_config(project.root)
        try:
            return _jsonable(
                project_preset_to_dict(target_id, config.presets[target_id])
            )
        except KeyError as exc:
            raise ScheduleError(f"Preset not found: {target_id}") from exc
    raise ScheduleError("target.kind must be agent, preset, workflow, or eval")


def _first_scheduled(
    definition: ScheduleDefinition, after: datetime | None = None
) -> str | None:
    return next(
        (
            str(item["utc"])
            for item in next_occurrences(definition, after=after, count=8)
            if item["utc"]
        ),
        None,
    )


def _schedule_key(project_id: str, schedule_id: str) -> str:
    return hashlib.sha256(f"{project_id}\0{schedule_id}".encode()).hexdigest()


def _manual_occurrence_id(
    schedule_key: str,
    trigger: str,
    idempotency_key: str,
) -> str:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ScheduleError("idempotency key is required")
    if len(key) > 200:
        raise ScheduleError("idempotency key must be at most 200 characters")
    identity = f"{schedule_key}\0{trigger}\0{key}"
    return f"occurrence_{hashlib.sha256(identity.encode()).hexdigest()}"


def _occurrence_from_row(row: Any) -> ScheduleOccurrence:
    return ScheduleOccurrence(
        **{key: row[key] for key in ScheduleOccurrence.__dataclass_fields__}
    )


def _local_datetime_text(value: Any, timezone_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return (
            datetime.now(_timezone(timezone_name))
            .replace(tzinfo=None, microsecond=0)
            .isoformat()
        )
    parsed = datetime.fromisoformat(text)
    return (
        parsed.astimezone(_timezone(timezone_name)).replace(tzinfo=None)
        if parsed.tzinfo
        else parsed
    ).isoformat()


def _timezone(name: str) -> ZoneInfo:
    if not name:
        raise ScheduleError("An explicit IANA timezone is required")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleError(f"Unknown IANA timezone: {name}") from exc


def _safe_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for char in text
    ):
        raise ScheduleError(
            f"{label} must contain only letters, digits, underscore, or hyphen"
        )
    return text


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_positive(value: Any) -> float | None:
    if value is None:
        return None
    return _positive(value, 0)


def _positive(value: Any, default: float) -> float:
    number = float(value if value is not None else default)
    if number <= 0:
        raise ScheduleError("numeric schedule limits must be positive")
    return number


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
