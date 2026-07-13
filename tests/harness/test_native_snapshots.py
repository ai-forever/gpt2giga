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


def _ref(ref_id: str, *, source: str) -> NativeSessionRef:
    return NativeSessionRef(
        id=ref_id,
        harness_id="codex-cli",
        native_session_id=f"session-{ref_id}",
        title=ref_id,
        workspace="/repo",
        source=source,
        status=NativeSessionStatus.MANAGED_NATIVE,
        created_at=None,
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
