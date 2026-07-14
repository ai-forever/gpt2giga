from dataclasses import replace

import pytest

from gpt2giga_harness.native.base import NativeCommandPlan
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    create_execution_snapshot,
)
from gpt2giga_harness.native.snapshots import (
    NativeExecutionSnapshotStore,
    validate_resume_snapshot,
)


def test_snapshot_store_binds_only_new_unambiguous_managed_source(tmp_path):
    store = NativeExecutionSnapshotStore(tmp_path)
    snapshot = _snapshot()
    store.record_start(
        NativeCommandPlan(
            command=("codex",),
            execution_snapshot=snapshot,
            snapshot_known_sources=("/managed/old.jsonl",),
        )
    )
    old = _ref("old", source="/managed/old.jsonl")
    new = _ref("new", source="/managed/new.jsonl")

    reconciled = store.reconcile((old, new), harness_id="codex-cli")
    reopened = NativeExecutionSnapshotStore(tmp_path).reconcile(
        (old, new), harness_id="codex-cli"
    )

    assert reconciled[0].execution_snapshot is None
    assert reconciled[1].execution_snapshot == snapshot
    assert reopened[1].execution_snapshot == snapshot


def test_snapshot_store_refuses_ambiguous_pending_binding(tmp_path):
    store = NativeExecutionSnapshotStore(tmp_path)
    first = _snapshot(model="first")
    second = _snapshot(model="second")
    for snapshot in (first, second):
        store.record_start(
            NativeCommandPlan(command=("codex",), execution_snapshot=snapshot)
        )

    (ref,) = store.reconcile(
        (_ref("new", source="/managed/new.jsonl"),),
        harness_id="codex-cli",
    )

    assert ref.execution_snapshot is None


def test_snapshot_store_binds_sequential_pending_runs_by_nearest_start_time(tmp_path):
    store = NativeExecutionSnapshotStore(tmp_path)
    first = replace(
        _snapshot(model="first"),
        created_at="2026-07-13T18:37:48Z",
    )
    second = replace(
        _snapshot(model="second"),
        created_at="2026-07-13T18:38:27Z",
    )
    store.record_start(NativeCommandPlan(command=("codex",), execution_snapshot=first))
    store.record_start(
        NativeCommandPlan(
            command=("codex",),
            execution_snapshot=second,
            snapshot_known_sources=("/managed/first.jsonl",),
        )
    )
    refs = (
        _ref(
            "first",
            source="/managed/first.jsonl",
            created_at="2026-07-13T18:37:51Z",
        ),
        _ref(
            "second",
            source="/managed/second.jsonl",
            created_at="2026-07-13T18:38:29Z",
        ),
    )

    reconciled = store.reconcile(refs, harness_id="codex-cli")

    assert reconciled[0].execution_snapshot == first
    assert reconciled[1].execution_snapshot == second


def test_snapshot_store_does_not_bind_stale_snapshot_by_time(tmp_path):
    store = NativeExecutionSnapshotStore(tmp_path)
    snapshot = replace(
        _snapshot(),
        created_at="2026-07-13T10:00:00Z",
    )
    store.record_start(
        NativeCommandPlan(command=("codex",), execution_snapshot=snapshot)
    )

    (ref,) = store.reconcile(
        (
            _ref(
                "late",
                source="/managed/late.jsonl",
                created_at="2026-07-13T11:00:00Z",
            ),
        ),
        harness_id="codex-cli",
    )

    assert ref.execution_snapshot is None


def test_snapshot_store_refuses_temporally_tied_pending_binding(tmp_path):
    store = NativeExecutionSnapshotStore(tmp_path)
    snapshots = tuple(
        replace(
            _snapshot(model=model),
            created_at="2026-07-13T18:40:20Z",
        )
        for model in ("first", "second")
    )
    for snapshot in snapshots:
        store.record_start(
            NativeCommandPlan(command=("codex",), execution_snapshot=snapshot)
        )

    (ref,) = store.reconcile(
        (
            _ref(
                "tied",
                source="/managed/tied.jsonl",
                created_at="2026-07-13T18:40:22Z",
            ),
        ),
        harness_id="codex-cli",
    )

    assert ref.execution_snapshot is None


def test_validate_resume_snapshot_rejects_contradictory_project_identity():
    snapshot = _snapshot()
    ref = replace(
        _ref("managed", source="/managed/session.jsonl"),
        execution_snapshot=snapshot,
        metadata={
            "project_id": "proj_other",
            "native_home": "/managed/codex",
        },
    )

    with pytest.raises(ValueError, match="project identity"):
        validate_resume_snapshot(ref, harness_id="codex-cli")


def test_validate_resume_snapshot_accepts_effective_worktree_identity():
    snapshot = replace(
        _snapshot(),
        source_workspace="/repo",
        effective_workspace="/worktrees/run-1",
    )
    ref = replace(
        _ref("managed", source="/managed/session.jsonl"),
        workspace="/worktrees/run-1",
        execution_snapshot=snapshot,
        metadata={
            "project_id": "proj_repo",
            "native_home": "/managed/codex",
        },
    )

    assert validate_resume_snapshot(ref, harness_id="codex-cli") == snapshot


def _snapshot(*, model: str = "GigaChat-2-Max"):
    return create_execution_snapshot(
        harness_id="codex-cli",
        api_mode="v1",
        model=model,
        native_home="/managed/codex",
        workspace="/repo",
        project_id="proj_repo",
        permission_mode="plan",
        tool_config_hash="config-hash",
    )


def _ref(
    ref_id: str,
    *,
    source: str,
    created_at: str | None = None,
) -> NativeSessionRef:
    return NativeSessionRef(
        id=ref_id,
        harness_id="codex-cli",
        native_session_id=f"session-{ref_id}",
        title=ref_id,
        workspace="/repo",
        source=source,
        status=NativeSessionStatus.MANAGED_NATIVE,
        created_at=created_at,
        updated_at=None,
        message_count=1,
        can_preview=True,
        can_import=True,
        can_resume=True,
        metadata={
            "project_id": "proj_repo",
            "native_home": "/managed/codex",
        },
    )
