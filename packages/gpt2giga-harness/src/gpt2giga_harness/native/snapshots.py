"""Durable binding of managed native sessions to immutable execution snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from gpt2giga_harness.native.base import NativeCommandPlan
from gpt2giga_harness.native.models import (
    NativeExecutionSnapshot,
    NativeSessionRef,
    NativeSessionStatus,
    execution_snapshot_from_dict,
    execution_snapshot_to_dict,
)
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import new_id

SNAPSHOT_INDEX_FILE = "execution-snapshots.json"
SNAPSHOT_BINDING_MAX_DELAY_SECONDS = 300.0
SNAPSHOT_BINDING_CLOCK_SKEW_SECONDS = 5.0


class NativeExecutionSnapshotStore:
    """Persist and conservatively reconcile successful native start snapshots."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir).expanduser() / "native" / SNAPSHOT_INDEX_FILE
        self.lock_path = self.path

    def record_start(
        self,
        plan: NativeCommandPlan,
        *,
        native_session_id: str | None = None,
    ) -> None:
        """Record one start only after its process has been spawned successfully."""
        snapshot = plan.execution_snapshot
        if snapshot is None:
            raise ValueError("Native start plan is missing an execution snapshot")
        with exclusive_file_lock(self.lock_path):
            records = {
                str(item.get("snapshot", {}).get("id")): dict(item)
                for item in self._read_records()
                if isinstance(item.get("snapshot"), Mapping)
            }
            records[snapshot.id] = {
                "snapshot": execution_snapshot_to_dict(snapshot),
                "native_session_id": _optional_text(native_session_id),
                "known_sources": sorted(set(plan.snapshot_known_sources)),
                "bound_source": None,
            }
            self._write_records(records.values())

    def reconcile(
        self,
        refs: Iterable[NativeSessionRef],
        *,
        harness_id: str,
    ) -> tuple[NativeSessionRef, ...]:
        """Attach snapshots only when identity or a new source is unambiguous."""
        with exclusive_file_lock(self.lock_path):
            return self._reconcile_locked(refs, harness_id=harness_id)

    def _reconcile_locked(
        self,
        refs: Iterable[NativeSessionRef],
        *,
        harness_id: str,
    ) -> tuple[NativeSessionRef, ...]:
        refs_list = list(refs)
        records = [
            item
            for item in self._read_records()
            if _snapshot(item) is not None and _snapshot(item).harness_id == harness_id
        ]
        attached: dict[str, NativeExecutionSnapshot] = {}
        changed = False

        for record in records:
            snapshot = _snapshot(record)
            if snapshot is None:
                continue
            bound_source = _optional_text(record.get("bound_source"))
            native_session_id = _optional_text(record.get("native_session_id"))
            for ref in refs_list:
                if bound_source is not None and ref.source == bound_source:
                    attached[ref.id] = snapshot
                elif native_session_id is not None and (
                    ref.native_session_id == native_session_id
                    and _snapshot_matches_ref(snapshot, ref)
                ):
                    attached[ref.id] = snapshot
                    if bound_source != ref.source:
                        record["bound_source"] = ref.source
                        changed = True

        pending = [
            record
            for record in records
            if _optional_text(record.get("bound_source")) is None
            and _optional_text(record.get("native_session_id")) is None
        ]
        candidates_by_record: dict[str, list[NativeSessionRef]] = {}
        records_by_ref: dict[str, list[str]] = {}
        for record in pending:
            snapshot = _snapshot(record)
            if snapshot is None:
                continue
            known_sources = {str(item) for item in record.get("known_sources", ())}
            candidates = [
                ref
                for ref in refs_list
                if ref.id not in attached
                and ref.source not in known_sources
                and _snapshot_matches_ref(snapshot, ref)
            ]
            candidates_by_record[snapshot.id] = candidates
            for ref in candidates:
                records_by_ref.setdefault(ref.id, []).append(snapshot.id)

        records_by_id = {
            snapshot.id: record
            for record in pending
            if (snapshot := _snapshot(record)) is not None
        }
        temporal_pairs, temporally_scoped_records, temporally_scoped_refs = (
            _temporal_binding_pairs(records_by_id, candidates_by_record)
        )
        for snapshot_id, ref in temporal_pairs.items():
            snapshot = _snapshot(records_by_id[snapshot_id])
            if snapshot is None:
                continue
            records_by_id[snapshot_id]["bound_source"] = ref.source
            records_by_id[snapshot_id]["native_session_id"] = ref.native_session_id
            attached[ref.id] = snapshot
            changed = True

        for snapshot_id, candidates in candidates_by_record.items():
            if snapshot_id in temporally_scoped_records:
                continue
            candidates = [
                ref
                for ref in candidates
                if ref.id not in attached and ref.id not in temporally_scoped_refs
            ]
            if len(candidates) != 1:
                continue
            ref = candidates[0]
            if len(records_by_ref.get(ref.id, ())) != 1:
                continue
            snapshot = _snapshot(records_by_id[snapshot_id])
            if snapshot is None:
                continue
            records_by_id[snapshot_id]["bound_source"] = ref.source
            records_by_id[snapshot_id]["native_session_id"] = ref.native_session_id
            attached[ref.id] = snapshot
            changed = True

        if changed:
            all_records = {
                str(item.get("snapshot", {}).get("id")): item
                for item in self._read_records()
                if isinstance(item.get("snapshot"), Mapping)
            }
            for record in records:
                snapshot = _snapshot(record)
                if snapshot is not None:
                    all_records[snapshot.id] = record
            self._write_records(all_records.values())

        return tuple(
            replace(ref, execution_snapshot=attached.get(ref.id))
            if ref.status is NativeSessionStatus.MANAGED_NATIVE
            else ref
            for ref in refs_list
        )

    def _read_records(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        raw = data.get("records", ()) if isinstance(data, Mapping) else ()
        return [dict(item) for item in raw if isinstance(item, Mapping)]

    def _write_records(self, records: Iterable[Mapping[str, Any]]) -> None:
        payload = redact_for_storage(
            {
                "records": sorted(
                    (dict(item) for item in records),
                    key=lambda item: str(item.get("snapshot", {}).get("id", "")),
                )
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{new_id('tmp')}")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)


def validate_resume_snapshot(
    ref: NativeSessionRef,
    *,
    harness_id: str,
) -> NativeExecutionSnapshot:
    """Validate that a ref still matches the execution identity it will resume."""
    snapshot = ref.execution_snapshot
    if snapshot is None:
        raise ValueError(
            "route_unknown: legacy native ref requires an explicit reviewed API mode"
        )
    if snapshot.harness_id != harness_id or ref.harness_id != harness_id:
        raise ValueError("Native resume harness identity contradicts its snapshot")
    snapshot_workspaces = {
        value
        for value in (
            snapshot.workspace,
            snapshot.source_workspace,
            snapshot.effective_workspace,
        )
        if value
    }
    if (
        ref.workspace
        and snapshot_workspaces
        and ref.workspace not in snapshot_workspaces
    ):
        raise ValueError("Native resume workspace contradicts its snapshot")
    project_id = _optional_text(ref.metadata.get("project_id"))
    if project_id and project_id != snapshot.project_id:
        raise ValueError("Native resume project identity contradicts its snapshot")
    native_home = _optional_text(ref.metadata.get("native_home"))
    if native_home and snapshot.native_home and native_home != snapshot.native_home:
        raise ValueError("Native resume home contradicts its snapshot")
    return snapshot


def _snapshot(record: Mapping[str, Any]) -> NativeExecutionSnapshot | None:
    value = record.get("snapshot")
    return execution_snapshot_from_dict(value if isinstance(value, Mapping) else None)


def _snapshot_matches_ref(
    snapshot: NativeExecutionSnapshot,
    ref: NativeSessionRef,
) -> bool:
    if ref.status is not NativeSessionStatus.MANAGED_NATIVE:
        return False
    if snapshot.harness_id != ref.harness_id:
        return False
    snapshot_workspaces = {
        value
        for value in (
            snapshot.workspace,
            snapshot.source_workspace,
            snapshot.effective_workspace,
        )
        if value
    }
    if (
        ref.workspace
        and snapshot_workspaces
        and ref.workspace not in snapshot_workspaces
    ):
        return False
    project_id = _optional_text(ref.metadata.get("project_id"))
    if project_id and snapshot.project_id != project_id:
        return False
    native_home = _optional_text(ref.metadata.get("native_home"))
    return not (
        native_home and snapshot.native_home and native_home != snapshot.native_home
    )


def _temporal_binding_pairs(
    records_by_id: Mapping[str, Mapping[str, Any]],
    candidates_by_record: Mapping[str, list[NativeSessionRef]],
) -> tuple[dict[str, NativeSessionRef], set[str], set[str]]:
    distances_by_record: dict[str, list[tuple[NativeSessionRef, float]]] = {}
    distances_by_ref: dict[str, list[tuple[str, float]]] = {}
    refs_by_id: dict[str, NativeSessionRef] = {}
    temporally_scoped_records: set[str] = set()
    temporally_scoped_refs: set[str] = set()
    for snapshot_id, candidates in candidates_by_record.items():
        snapshot = _snapshot(records_by_id[snapshot_id])
        if snapshot is None:
            continue
        for ref in candidates:
            if (
                _timestamp(snapshot.created_at) is not None
                and _timestamp(ref.created_at) is not None
            ):
                temporally_scoped_records.add(snapshot_id)
                temporally_scoped_refs.add(ref.id)
            distance = _snapshot_ref_delay(snapshot, ref)
            if distance is None:
                continue
            distances_by_record.setdefault(snapshot_id, []).append((ref, distance))
            distances_by_ref.setdefault(ref.id, []).append((snapshot_id, distance))
            refs_by_id[ref.id] = ref

    record_choices = {
        snapshot_id: ref.id
        for snapshot_id, values in distances_by_record.items()
        if (ref := _unique_nearest_ref(values)) is not None
    }
    ref_choices = {
        ref_id: snapshot_id
        for ref_id, values in distances_by_ref.items()
        if (snapshot_id := _unique_nearest_snapshot(values)) is not None
    }
    pairs = {
        snapshot_id: refs_by_id[ref_id]
        for snapshot_id, ref_id in record_choices.items()
        if ref_choices.get(ref_id) == snapshot_id
    }
    return pairs, temporally_scoped_records, temporally_scoped_refs


def _snapshot_ref_delay(
    snapshot: NativeExecutionSnapshot,
    ref: NativeSessionRef,
) -> float | None:
    snapshot_time = _timestamp(snapshot.created_at)
    ref_time = _timestamp(ref.created_at)
    if snapshot_time is None or ref_time is None:
        return None
    delay = (ref_time - snapshot_time).total_seconds()
    if delay < -SNAPSHOT_BINDING_CLOCK_SKEW_SECONDS:
        return None
    if delay > SNAPSHOT_BINDING_MAX_DELAY_SECONDS:
        return None
    return abs(delay)


def _unique_nearest_ref(
    values: list[tuple[NativeSessionRef, float]],
) -> NativeSessionRef | None:
    nearest = min(distance for _, distance in values)
    matches = [ref for ref, distance in values if distance == nearest]
    return matches[0] if len(matches) == 1 else None


def _unique_nearest_snapshot(values: list[tuple[str, float]]) -> str | None:
    nearest = min(distance for _, distance in values)
    matches = [snapshot_id for snapshot_id, distance in values if distance == nearest]
    return matches[0] if len(matches) == 1 else None


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
