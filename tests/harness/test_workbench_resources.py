from __future__ import annotations

from dataclasses import replace
import os

import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.runtime.models import (
    NativeProcessOutputRecord,
    NativeProcessRecord,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.workbench_resources import (
    WorkbenchPreferenceStore,
    WorkbenchResourceError,
    WorkbenchResourceService,
    process_binding,
    resource_snapshot_from_dict,
    resource_snapshot_to_dict,
    task_binding,
)


def _service(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    return (
        WorkbenchResourceService(
            session_store=sessions,
            runtime_store=runtime,
            preference_store=WorkbenchPreferenceStore(tmp_path),
            integration_service=IntegrationFlowService(tmp_path),
        ),
        sessions,
        runtime,
    )


def test_private_preferences_are_versioned_atomic_and_native_config_free(tmp_path):
    store = WorkbenchPreferenceStore(tmp_path)
    initial = store.load()

    saved = store.save(
        {
            **initial.values.__dict__,
            "theme": "dark",
            "reduced_motion": True,
            "status_fields": ["provider", "usage"],
        },
        expected_revision=initial.revision,
    )

    assert saved.values.theme == "dark"
    assert saved.values.reduced_motion is True
    assert saved.notification_policy == "content_free"
    assert saved.revision != initial.revision
    assert os.stat(store.path).st_mode & 0o777 == 0o600
    assert not any(tmp_path.rglob("config.toml"))
    with pytest.raises(WorkbenchResourceError, match="revision changed"):
        store.save(saved.values.__dict__, expected_revision=initial.revision)


def test_resource_snapshot_binds_task_process_usage_and_inventory(tmp_path):
    service, sessions, runtime = _service(tmp_path)
    session = sessions.create_session(title="Bounded resources")
    job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_1",
        idempotency_key="resource-job",
        agent_id="reviewer",
        workflow_id="flow_parent",
    ).job
    attempt = runtime.create_attempt(job.id, run_id=job.initial_run_id)
    now = utc_now()
    runtime.create_native_process(
        NativeProcessRecord(
            id="proc_1",
            owner_id="server_1",
            owner_process_id=123,
            session_id=session.id,
            run_id=job.initial_run_id,
            harness_id="codex-cli",
            status="running",
            process_id=456,
            process_group_id=456,
            transport="pty",
            ref={"exit_code": None},
            started_at=now,
            updated_at=now,
            heartbeat_at=now,
            leased_until="2099-01-01T00:00:00+00:00",
        )
    )
    runtime.append_native_process_output(
        NativeProcessOutputRecord("proc_1", 1, "pty", "safe\x1b]52;c;blocked\x07", now),
        owner_id="server_1",
        max_chunks=8,
    )
    sessions.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=session.id,
            run_id=job.initial_run_id,
            type="usage",
            message="Usage retained.",
            payload={"total_tokens": 42, "cost_usd": 0.25, "source": "codex"},
            created_at=now,
        )
    )
    sessions.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=session.id,
            run_id=job.initial_run_id,
            type="tool_call_completed",
            message="Subagent completed.",
            payload={
                "subagent_id": "child_1",
                "parent_tool_call_id": "spawn_1",
                "status": "completed",
            },
            created_at=now,
        )
    )

    snapshot = service.snapshot(session.id)
    round_trip = resource_snapshot_from_dict(resource_snapshot_to_dict(snapshot))

    task = next(item for item in snapshot.tasks if item.id == job.id)
    child = next(item for item in snapshot.tasks if item.child_id == "child_1")
    process = snapshot.processes[0]
    assert task.child_id == "reviewer"
    assert task.generation == attempt.attempt_number
    assert child.parent_id == "spawn_1"
    assert child.cancelable is False
    assert process_binding(process)["owner"] == "server_1"
    assert "blocked" not in process.output
    assert "terminal-control" in process.output
    assert {(item.id, item.source) for item in snapshot.usage} >= {
        ("total_tokens", "codex"),
        ("provider_cost", "codex"),
    }
    assert {item.kind for item in snapshot.inventory} >= {"mcp", "plugin"}
    assert round_trip == snapshot


def test_task_cancellation_rejects_stale_owner_binding(tmp_path):
    service, sessions, runtime = _service(tmp_path)
    session = sessions.create_session(title="Cancelable")
    job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_1",
        idempotency_key="cancel-job",
        agent_id="worker",
    ).job
    runtime.create_attempt(job.id, run_id=job.initial_run_id)
    task = next(
        item for item in service.snapshot(session.id).tasks if item.id == job.id
    )

    stale = {**task_binding(task), "child_id": "another-child"}
    with pytest.raises(WorkbenchResourceError, match="binding changed"):
        service.cancel_task(stale)

    canceled = service.cancel_task(task_binding(task))
    assert canceled.cancel_requested is True
    assert runtime.get_job(job.id).cancel_requested_at is not None

    terminal = replace(canceled, status="succeeded", cancelable=False)
    assert task_binding(terminal)["id"] == job.id


def test_workbench_resources_api_shares_snapshot_and_private_preference_contract(
    tmp_path,
):
    data_dir = tmp_path / "state"
    app = create_app(config=HarnessConfig(data_dir=data_dir))

    with TestClient(app) as client:
        response = client.get("/api/workbench/resources")
        assert response.status_code == 200
        initial = response.json()
        preferences = initial["preferences"]
        values = {**preferences["values"], "screen_reader": True}
        saved = client.put(
            "/api/workbench/preferences",
            json={
                "expected_revision": preferences["revision"],
                "values": values,
            },
        )
        stale = client.put(
            "/api/workbench/preferences",
            json={
                "expected_revision": preferences["revision"],
                "values": values,
            },
        )

    assert saved.status_code == 200
    assert saved.json()["preferences"]["values"]["screen_reader"] is True
    assert stale.status_code == 409
    assert initial["inventory"]
    assert all(item["action"] == "provider_handoff" for item in initial["inventory"])
    assert os.stat(data_dir / "settings" / "workbench.json").st_mode & 0o777 == 0o600
