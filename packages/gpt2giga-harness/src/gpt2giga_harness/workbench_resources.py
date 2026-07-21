"""Bounded tasks, processes, usage, preferences, and integration projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions import HarnessSessionStore
from gpt2giga_harness.sessions.locking import exclusive_file_lock


WORKBENCH_PREFERENCES_SCHEMA_VERSION = 1
MAX_RESOURCE_ITEMS = 100
MAX_PROCESS_OUTPUT_CHARS = 4_096
_TERMINAL_RE = re.compile(
    r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)?|P.*?(?:\x1b\\|$)|\[[0-?]*[ -/]*[@-~]|[@-_])",
    re.DOTALL,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "canceled"})
_ALLOWED_STATUS_FIELDS = frozenset(
    {"provider", "model", "mode", "permission", "policy", "sandbox", "usage"}
)


class WorkbenchResourceError(ValueError):
    """Raised when a resource action or preference write is stale or invalid."""


@dataclass(frozen=True)
class TaskProjection:
    """Content-free task or subagent identity with exact cancellation binding."""

    id: str
    child_id: str
    parent_id: str | None
    session_id: str
    run_id: str | None
    owner: str
    status: str
    generation: int
    version: int
    lease_owner: str | None = None
    leased_until: str | None = None
    cancel_requested: bool = False
    cancelable: bool = False
    result_run_id: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class ProcessProjection:
    """Bounded application-owned native-process lifecycle projection."""

    id: str
    session_id: str
    run_id: str
    owner: str
    status: str
    transport: str
    version: int
    leased_until: str
    cursor: int
    exit_code: int | None = None
    output: str = ""
    output_truncated: bool = False
    cancel_requested: bool = False


@dataclass(frozen=True)
class UsageMetric:
    """One explicitly sourced usage, cost, duration, or budget value."""

    id: str
    value: int | float
    unit: str
    source: str


@dataclass(frozen=True)
class WorkbenchPreferences:
    """Versioned private presentation preferences; native config is out of scope."""

    theme: str = "system"
    keymap: str = "default"
    screen_mode: str = "fullscreen"
    mouse: bool = True
    reduced_motion: bool = False
    screen_reader: bool = False
    status_fields: tuple[str, ...] = (
        "provider",
        "model",
        "mode",
        "permission",
        "policy",
        "sandbox",
    )
    notifications: bool = True


@dataclass(frozen=True)
class PreferenceSnapshot:
    """Preferences plus an optimistic concurrency revision."""

    values: WorkbenchPreferences
    revision: str
    schema_version: int = WORKBENCH_PREFERENCES_SCHEMA_VERSION
    notification_policy: str = "content_free"


@dataclass(frozen=True)
class InventoryProjection:
    """Capability-safe integration target requiring an explicit handoff."""

    id: str
    kind: str
    provider: str
    owner: str
    status: str = "handoff"
    action: str = "provider_handoff"


@dataclass(frozen=True)
class WorkbenchResourceSnapshot:
    """One bounded resource snapshot shared by in-process and attach clients."""

    revision: str
    session_id: str | None
    tasks: tuple[TaskProjection, ...] = ()
    processes: tuple[ProcessProjection, ...] = ()
    usage: tuple[UsageMetric, ...] = ()
    preferences: PreferenceSnapshot = field(
        default_factory=lambda: PreferenceSnapshot(
            WorkbenchPreferences(), _preference_revision(WorkbenchPreferences())
        )
    )
    inventory: tuple[InventoryProjection, ...] = ()


class WorkbenchPreferenceStore:
    """Atomically persist private Workbench-only presentation preferences."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir).expanduser() / "settings" / "workbench.json"
        self.lock_path = self.path.with_suffix(".lock")

    def load(self) -> PreferenceSnapshot:
        """Load strict preferences without consulting or changing native config."""
        with exclusive_file_lock(self.lock_path):
            values = self._read_unlocked()
        return PreferenceSnapshot(values, _preference_revision(values))

    def save(
        self, values: Mapping[str, Any], *, expected_revision: str
    ) -> PreferenceSnapshot:
        """Validate and atomically replace one exact preference revision."""
        normalized = _preferences_from_mapping(values)
        with exclusive_file_lock(self.lock_path):
            current = self._read_unlocked()
            if expected_revision != _preference_revision(current):
                raise WorkbenchResourceError("preference revision changed")
            payload = {
                "schema_version": WORKBENCH_PREFERENCES_SCHEMA_VERSION,
                "preferences": _preferences_to_dict(normalized),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        return self.load()

    def _read_unlocked(self) -> WorkbenchPreferences:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return WorkbenchPreferences()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkbenchResourceError(
                "Workbench preferences are unreadable"
            ) from exc
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "preferences",
        }:
            raise WorkbenchResourceError("Workbench preference fields are invalid")
        if payload.get("schema_version") != WORKBENCH_PREFERENCES_SCHEMA_VERSION:
            raise WorkbenchResourceError("unsupported Workbench preference schema")
        return _preferences_from_mapping(payload.get("preferences"))


class WorkbenchResourceService:
    """Project existing application authority into bounded neutral read models."""

    def __init__(
        self,
        *,
        session_store: HarnessSessionStore,
        runtime_store: RuntimeCoordinationStore | None,
        preference_store: WorkbenchPreferenceStore,
        integration_service: IntegrationFlowService,
    ) -> None:
        self.sessions = session_store
        self.runtime = runtime_store
        self.preferences = preference_store
        self.integrations = integration_service

    def snapshot(self, session_id: str | None) -> WorkbenchResourceSnapshot:
        """Return bounded resource state without task payloads or native config."""
        tasks = self._tasks(session_id)
        processes = self._processes(session_id)
        usage = self._usage(session_id)
        preferences = self.preferences.load()
        inventory = self._inventory()
        revision_payload = {
            "inventory": [asdict(item) for item in inventory],
            "preference_revision": preferences.revision,
            "processes": [asdict(item) for item in processes],
            "session_id": session_id,
            "tasks": [asdict(item) for item in tasks],
            "usage": [asdict(item) for item in usage],
        }
        revision = hashlib.sha256(
            json.dumps(revision_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return WorkbenchResourceSnapshot(
            revision,
            session_id,
            tasks,
            processes,
            usage,
            preferences,
            inventory,
        )

    def cancel_task(self, binding: Mapping[str, Any]) -> TaskProjection:
        """Cancel a durable task only when every presented owner field still matches."""
        if self.runtime is None:
            raise WorkbenchResourceError("durable runtime is unavailable")
        task_id = _required_identity(binding.get("id"), "task id")
        job = self.runtime.get_job(task_id)
        attempts = self.runtime.list_attempts(task_id)
        latest = attempts[-1] if attempts else None
        expected = (
            str(binding.get("session_id") or ""),
            str(binding.get("child_id") or ""),
            int(binding.get("generation") or -1),
            int(binding.get("version") or -1),
            binding.get("lease_owner"),
            binding.get("leased_until"),
        )
        actual = (
            job.session_id,
            job.agent_id or job.id,
            (latest.attempt_number if latest else 1),
            job.version,
            (latest.lease_owner if latest else None),
            (latest.leased_until if latest else None),
        )
        if expected != actual:
            raise WorkbenchResourceError("task binding changed; resnapshot required")
        if job.status.value not in _TERMINAL_JOB_STATES:
            self.runtime.request_cancel(job.id)
        return next(item for item in self._tasks(job.session_id) if item.id == job.id)

    def save_preferences(
        self, values: Mapping[str, Any], *, expected_revision: str
    ) -> PreferenceSnapshot:
        """Persist one Workbench-only preference snapshot."""
        return self.preferences.save(values, expected_revision=expected_revision)

    def validate_process(self, binding: Mapping[str, Any]) -> ProcessProjection:
        """Validate exact process ownership before an external stop side effect."""
        if self.runtime is None:
            raise WorkbenchResourceError("durable runtime is unavailable")
        process_id = _required_identity(binding.get("id"), "process id")
        process = self.runtime.get_native_process(process_id)
        expected = (
            str(binding.get("session_id") or ""),
            str(binding.get("run_id") or ""),
            str(binding.get("owner") or ""),
            int(binding.get("version") or -1),
            str(binding.get("leased_until") or ""),
        )
        actual = (
            process.session_id,
            process.run_id,
            process.owner_id,
            process.version,
            process.leased_until,
        )
        if expected != actual:
            raise WorkbenchResourceError("process binding changed; resnapshot required")
        return next(
            item
            for item in self._processes(process.session_id)
            if item.id == process.id
        )

    def _tasks(self, session_id: str | None) -> tuple[TaskProjection, ...]:
        items: list[TaskProjection] = []
        if self.runtime is not None:
            jobs = reversed(self.runtime.list_jobs())
            for job in jobs:
                if session_id is not None and job.session_id != session_id:
                    continue
                attempts = self.runtime.list_attempts(job.id)
                latest = attempts[-1] if attempts else None
                items.append(
                    TaskProjection(
                        id=job.id,
                        child_id=job.agent_id or job.id,
                        parent_id=job.workflow_id,
                        session_id=job.session_id,
                        run_id=(latest.run_id if latest else job.initial_run_id),
                        owner=job.origin,
                        status=job.status.value,
                        generation=(latest.attempt_number if latest else 1),
                        version=job.version,
                        lease_owner=(latest.lease_owner if latest else None),
                        leased_until=(latest.leased_until if latest else None),
                        cancel_requested=job.cancel_requested_at is not None,
                        cancelable=job.status.value not in _TERMINAL_JOB_STATES,
                        result_run_id=(latest.run_id if latest else job.initial_run_id),
                        updated_at=job.updated_at,
                    )
                )
                if len(items) >= MAX_RESOURCE_ITEMS:
                    return tuple(items)
        if session_id is None:
            return tuple(items)
        known = {item.child_id for item in items}
        for event in reversed(self.sessions.list_events(session_id)):
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            subagent_id = str(payload.get("subagent_id") or "").strip()
            if not subagent_id or subagent_id in known:
                continue
            known.add(subagent_id)
            items.append(
                TaskProjection(
                    id=f"subagent:{subagent_id}",
                    child_id=subagent_id,
                    parent_id=str(payload.get("parent_tool_call_id") or "") or None,
                    session_id=session_id,
                    run_id=event.run_id,
                    owner=str(payload.get("source") or event.agent_id or "provider"),
                    status=str(
                        payload.get("status") or event.span_status or "observed"
                    ),
                    generation=1,
                    version=0,
                    cancelable=False,
                    result_run_id=event.run_id,
                    updated_at=event.created_at,
                )
            )
            if len(items) >= MAX_RESOURCE_ITEMS:
                break
        return tuple(items)

    def _processes(self, session_id: str | None) -> tuple[ProcessProjection, ...]:
        if self.runtime is None:
            return ()
        items: list[ProcessProjection] = []
        for process in reversed(self.runtime.list_native_processes()):
            if session_id is not None and process.session_id != session_id:
                continue
            outputs = self.runtime.read_native_process_outputs(process.id)
            joined = "".join(item.text for item in outputs)
            neutral = _neutralize(joined)
            truncated = len(neutral) > MAX_PROCESS_OUTPUT_CHARS
            ref = process.ref if isinstance(process.ref, Mapping) else {}
            exit_code = ref.get("exit_code")
            items.append(
                ProcessProjection(
                    id=process.id,
                    session_id=process.session_id,
                    run_id=process.run_id,
                    owner=process.owner_id,
                    status=process.status,
                    transport=process.transport,
                    version=process.version,
                    leased_until=process.leased_until,
                    cursor=process.terminal_cursor,
                    exit_code=(exit_code if isinstance(exit_code, int) else None),
                    output=neutral[-MAX_PROCESS_OUTPUT_CHARS:],
                    output_truncated=truncated,
                    cancel_requested=process.cancel_requested_at is not None,
                )
            )
            if len(items) >= MAX_RESOURCE_ITEMS:
                break
        return tuple(items)

    def _usage(self, session_id: str | None) -> tuple[UsageMetric, ...]:
        if session_id is None:
            return ()
        runs = self.sessions.list_runs(session_id)
        events = self.sessions.list_events(session_id)
        totals: dict[tuple[str, str, str], int | float] = {}
        for event in events:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            if event.type == "usage":
                source = str(payload.get("source") or "provider")[:80]
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cached_input_tokens",
                    "reasoning_output_tokens",
                    "tool_tokens",
                ):
                    value = payload.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[(key, "tokens", source)] = value
                for key in ("cost", "cost_usd"):
                    value = payload.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[("provider_cost", "USD", source)] = value
            if event.type.startswith("tool_call_") and event.type.endswith("started"):
                key = ("tool_calls", "calls", "harness_events")
                totals[key] = totals.get(key, 0) + 1
        duration = sum(
            _duration_seconds(run.started_at, run.finished_at) for run in runs
        )
        if duration:
            totals[("duration", "seconds", "harness_clock")] = round(duration, 3)
        changed = 0
        for run in runs:
            metadata = run.metadata if isinstance(run.metadata, Mapping) else {}
            diff = metadata.get("diff_summary")
            if isinstance(diff, Mapping):
                for key in ("added_lines", "deleted_lines"):
                    value = diff.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        changed += max(value, 0)
            budgets = metadata.get("budgets")
            if isinstance(budgets, Mapping):
                for key, value in budgets.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[(f"budget.{key}", "configured", "run_budget")] = value
        if changed:
            totals[("changed_lines", "lines", "harness_diff")] = changed
        return tuple(
            UsageMetric(name, value, unit, source)
            for (name, unit, source), value in sorted(totals.items())
        )[:MAX_RESOURCE_ITEMS]

    def _inventory(self) -> tuple[InventoryProjection, ...]:
        inventory = self.integrations.inventory()
        targets = inventory.get("targets")
        if not isinstance(targets, list):
            return ()
        items: list[InventoryProjection] = []
        for target in targets[:MAX_RESOURCE_ITEMS]:
            if not isinstance(target, Mapping):
                continue
            components = target.get("component_types")
            kinds = components if isinstance(components, list) else ["integration"]
            target_id = str(target.get("id") or "unknown")[:128]
            provider = target_id.split("-", 1)[0]
            owner = str(target.get("execution_owner") or "provider")[:128]
            for kind in kinds[:4]:
                items.append(
                    InventoryProjection(target_id, str(kind)[:64], provider, owner)
                )
        return tuple(items[:MAX_RESOURCE_ITEMS])


def resource_snapshot_to_dict(snapshot: WorkbenchResourceSnapshot) -> dict[str, Any]:
    """Serialize a resource snapshot into the attach contract."""
    return {
        "revision": snapshot.revision,
        "session_id": snapshot.session_id,
        "tasks": [asdict(item) for item in snapshot.tasks],
        "processes": [asdict(item) for item in snapshot.processes],
        "usage": [asdict(item) for item in snapshot.usage],
        "preferences": preference_snapshot_to_dict(snapshot.preferences),
        "inventory": [asdict(item) for item in snapshot.inventory],
    }


def resource_snapshot_from_dict(value: Mapping[str, Any]) -> WorkbenchResourceSnapshot:
    """Strictly parse the bounded attach resource contract."""
    return WorkbenchResourceSnapshot(
        revision=_required_text(value.get("revision"), "resource revision"),
        session_id=_optional_text(value.get("session_id")),
        tasks=tuple(
            TaskProjection(**dict(item))
            for item in _mapping_items(value.get("tasks"), "tasks")
        ),
        processes=tuple(
            ProcessProjection(**dict(item))
            for item in _mapping_items(value.get("processes"), "processes")
        ),
        usage=tuple(
            UsageMetric(**dict(item))
            for item in _mapping_items(value.get("usage"), "usage")
        ),
        preferences=preference_snapshot_from_dict(_mapping(value.get("preferences"))),
        inventory=tuple(
            InventoryProjection(**dict(item))
            for item in _mapping_items(value.get("inventory"), "inventory")
        ),
    )


def preference_snapshot_to_dict(snapshot: PreferenceSnapshot) -> dict[str, Any]:
    """Serialize private preference state without native settings."""
    return {
        "schema_version": snapshot.schema_version,
        "revision": snapshot.revision,
        "notification_policy": snapshot.notification_policy,
        "values": _preferences_to_dict(snapshot.values),
    }


def preference_snapshot_from_dict(value: Mapping[str, Any]) -> PreferenceSnapshot:
    """Parse the strict preference attach contract."""
    if value.get("schema_version") != WORKBENCH_PREFERENCES_SCHEMA_VERSION:
        raise WorkbenchResourceError("unsupported Workbench preference schema")
    return PreferenceSnapshot(
        _preferences_from_mapping(value.get("values")),
        _required_text(value.get("revision"), "preference revision"),
        notification_policy=_required_text(
            value.get("notification_policy"), "notification policy"
        ),
    )


def task_binding(task: TaskProjection) -> dict[str, Any]:
    """Return every exact owner field needed for cancellation."""
    return {
        "id": task.id,
        "child_id": task.child_id,
        "session_id": task.session_id,
        "generation": task.generation,
        "version": task.version,
        "lease_owner": task.lease_owner,
        "leased_until": task.leased_until,
    }


def process_binding(process: ProcessProjection) -> dict[str, Any]:
    """Return every exact owner field needed before stopping a process."""
    return {
        "id": process.id,
        "session_id": process.session_id,
        "run_id": process.run_id,
        "owner": process.owner,
        "version": process.version,
        "leased_until": process.leased_until,
    }


def _preferences_from_mapping(value: Any) -> WorkbenchPreferences:
    if not isinstance(value, Mapping):
        raise WorkbenchResourceError("Workbench preferences must be an object")
    allowed = set(WorkbenchPreferences.__dataclass_fields__)
    if set(value) - allowed:
        raise WorkbenchResourceError("unknown Workbench preference")
    defaults = WorkbenchPreferences()
    theme = str(value.get("theme", defaults.theme))
    keymap = str(value.get("keymap", defaults.keymap))
    screen_mode = str(value.get("screen_mode", defaults.screen_mode))
    if theme not in {"system", "dark", "light"}:
        raise WorkbenchResourceError("theme is invalid")
    if keymap not in {"default", "vim"}:
        raise WorkbenchResourceError("keymap is invalid")
    if screen_mode not in {"fullscreen", "inline"}:
        raise WorkbenchResourceError("screen mode is invalid")
    raw_fields = value.get("status_fields", defaults.status_fields)
    if not isinstance(raw_fields, (list, tuple)):
        raise WorkbenchResourceError("status fields are invalid")
    status_fields = tuple(str(item) for item in raw_fields)
    if len(status_fields) > len(_ALLOWED_STATUS_FIELDS) or not set(
        status_fields
    ).issubset(_ALLOWED_STATUS_FIELDS):
        raise WorkbenchResourceError("status fields are invalid")
    booleans: dict[str, bool] = {}
    for name in ("mouse", "reduced_motion", "screen_reader", "notifications"):
        item = value.get(name, getattr(defaults, name))
        if not isinstance(item, bool):
            raise WorkbenchResourceError(f"{name} must be boolean")
        booleans[name] = item
    return WorkbenchPreferences(
        theme=theme,
        keymap=keymap,
        screen_mode=screen_mode,
        status_fields=status_fields,
        **booleans,
    )


def _preferences_to_dict(value: WorkbenchPreferences) -> dict[str, Any]:
    result = asdict(value)
    result["status_fields"] = list(value.status_fields)
    return result


def _preference_revision(value: WorkbenchPreferences) -> str:
    return hashlib.sha256(
        json.dumps(
            _preferences_to_dict(value), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _duration_seconds(started_at: str | None, finished_at: str | None) -> float:
    if not started_at or not finished_at:
        return 0.0
    try:
        return max(
            (
                datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
            ).total_seconds(),
            0.0,
        )
    except ValueError:
        return 0.0


def _neutralize(value: str) -> str:
    value = _TERMINAL_RE.sub("⟦terminal-control⟧", value)
    value = _BIDI_RE.sub("�", value)
    return _CONTROL_RE.sub("�", value)


def _mapping_items(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or len(value) > MAX_RESOURCE_ITEMS:
        raise WorkbenchResourceError(f"{field_name} are invalid")
    if not all(isinstance(item, Mapping) for item in value):
        raise WorkbenchResourceError(f"{field_name} are invalid")
    return tuple(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkbenchResourceError("expected an object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 512:
        raise WorkbenchResourceError(f"{field_name} is invalid")
    return text


def _required_identity(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not all(character.isalnum() or character in "._:@+~-" for character in text):
        raise WorkbenchResourceError(f"{field_name} is invalid")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
