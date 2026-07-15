from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyResolution,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.static import INDEX_HTML, load_text_asset
from gpt2giga_harness.tools.policy import PolicyDecision


def test_runs_center_lists_filters_and_resolves_lightweight_summary(tmp_path):
    client, runtime, _sessions, run_id, job_id, _event_id = _failed_run(tmp_path)

    response = client.get("/api/runs?status=failed&limit=1")
    summary = client.get(f"/api/runs/{run_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    assert body["runs"][0]["job"]["id"] == job_id
    assert body["runs"][0]["status_group"] == "failed"
    assert body["runs"][0]["retry_count"] == 0
    assert body["runs"][0]["actions"]["retry"].endswith("/retry")
    assert body["runs"][0]["actions"]["open_worktree"].endswith("/open-worktree")
    assert body["runs"][0]["actions"]["inspect_artifact"].endswith("/pr")
    ownership = body["runs"][0]["ownership"]
    assert ownership["job_id"] == job_id
    assert ownership["job_status"] == "failed"
    assert ownership["attempt_number"] == 1
    assert ownership["attempt_status"] == "failed"
    assert ownership["worker_id"] == "worker_review"
    assert ownership["leased_until"] is None
    assert body["runs"][0]["approvals"][0]["action"] == "workspace.write"
    assert body["runs"][0]["approvals"][0]["status"] == "pending"
    assert "preview" not in body["runs"][0]["approvals"][0]
    assert "/tmp/private-worktree" not in response.text
    assert body["runs"][0]["artifact_inventory"] == [
        {"type": "worktree", "source": "run"},
        {"type": "diff", "source": "run"},
        {"type": "pr", "source": "run"},
    ]
    assert "prompt" not in body["runs"][0]["job"]
    assert "prompt" not in body["runs"][0]["run"]
    assert "metadata" not in body["runs"][0]["run"]
    assert summary.status_code == 200
    assert summary.json()["run"]["run_id"] == run_id
    assert client.get("/api/runs?status=unknown").status_code == 400
    assert runtime.get_job(job_id).status.value == "failed"


def test_runs_center_projects_active_attempt_lease_without_process_details(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    session = sessions.create_session(title="Owned run")
    run = sessions.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="inspect ownership",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
    )
    job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_owned",
        initial_run_id=run.id,
        idempotency_key="owned",
        required_harness_id="echo",
    ).job
    attempt = runtime.create_attempt(
        job.id,
        run_id=run.id,
        status="running",
        lease_owner="worker_active",
        leased_until="2099-01-01T00:00:00+00:00",
    )
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
        store=sessions,
        runtime_store=runtime,
    )

    ownership = (
        TestClient(app).get(f"/api/runs/{run.id}/summary").json()["run"]["ownership"]
    )

    assert ownership["attempt_id"] == attempt.id
    assert ownership["worker_id"] == "worker_active"
    assert ownership["leased_until"] == "2099-01-01T00:00:00+00:00"
    assert "process_id" not in ownership


def test_runs_center_trace_is_bounded_lazy_and_hides_reasoning(tmp_path):
    client, _runtime, _sessions, run_id, _job_id, event_id = _failed_run(tmp_path)

    trace = client.get(f"/api/runs/{run_id}/trace?limit=3")
    payload = client.get(f"/api/runs/{run_id}/events/{event_id}")

    assert trace.status_code == 200
    nodes = trace.json()["nodes"]
    assert len(nodes) <= 3
    assert any(node["kind"] == "agent" and node["depth"] == 0 for node in nodes)
    assert any(node["kind"] == "tool" and node["depth"] == 2 for node in nodes)
    assert all("reasoning" not in node["title"].lower() for node in nodes)
    assert all("payload" not in node for node in nodes)
    assert payload.status_code == 200
    assert payload.json()["payload"] == {"result": "visible"}


def test_runs_center_cursor_and_blocked_filter_do_not_repeat_jobs(tmp_path):
    client, runtime, sessions, _run_id, first_job_id, _event_id = _failed_run(tmp_path)
    session = sessions.create_session(title="Waiting for input")
    run = sessions.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="wait",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
    )
    blocked_job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_wait",
        initial_run_id=run.id,
        idempotency_key="wait",
        required_harness_id="echo",
        initial_status="waiting_input",
    ).job

    first_page = client.get("/api/runs?limit=1").json()
    second_page = client.get(
        "/api/runs?limit=1", params={"cursor": first_page["next_cursor"]}
    ).json()
    blocked = client.get("/api/runs?status=blocked").json()

    assert first_page["runs"][0]["job"]["id"] == blocked_job.id
    assert second_page["runs"][0]["job"]["id"] == first_job_id
    assert first_page["runs"][0]["job"]["id"] != second_page["runs"][0]["job"]["id"]
    assert [item["job"]["id"] for item in blocked["runs"]] == [blocked_job.id]


def test_runs_center_retry_requeues_only_safe_failed_attempt(tmp_path):
    client, runtime, _sessions, run_id, job_id, _event_id = _failed_run(tmp_path)

    retried = client.post(f"/api/runs/{run_id}/retry")
    duplicate = client.post(f"/api/runs/{run_id}/retry")

    assert retried.status_code == 200
    assert retried.json()["job"]["status"] == "queued"
    assert retried.json()["job"]["max_attempts"] == 2
    assert runtime.get_job(job_id).status.value == "queued"
    assert duplicate.status_code == 409


def test_runs_center_assets_expose_bounded_live_routable_surface():
    script = load_text_asset("app.js")

    for fragment in (
        'id="runs-center"',
        'data-run-status="approval-needed"',
        'id="runs-trace-list"',
        'id="runs-retry-button"',
        'id="runs-inspect-artifact-button"',
        'id="runs-ownership-panel"',
        'id="runs-ownership-grid"',
        'id="runs-team-tree"',
        'data-tab="team"',
    ):
        assert fragment in INDEX_HTML
    for fragment in (
        "RUNS_TRACE_DOM_LIMIT = 200",
        "function loadRunsCenter",
        "function loadRunsTrace",
        "function appendRunsLiveEvent",
        "function openRunsCenterEventStream",
        "function renderRunsOwnership",
        "function renderAgentTeam",
        "function loadWorkAgentTeam",
        "/events/stream",
    ):
        assert fragment in script


def _failed_run(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    session = sessions.create_session(title="Durable review")
    run = sessions.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="review this",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="failed",
    )
    run = sessions.update_run(
        run.id,
        metadata={
            "workspace_execution": {
                "worktree_path": "/tmp/demo-worktree",
                "patch": "diff --git a/demo b/demo",
            },
            "pr_artifact": {"title": "Fix parser"},
        },
    )
    submission = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_review",
        initial_run_id=run.id,
        idempotency_key="review",
        required_harness_id="echo",
    )
    attempt = runtime.create_attempt(
        submission.job.id,
        run_id=run.id,
        status="running",
        lease_owner="worker_review",
    )
    runtime.set_attempt_idempotency_class(attempt.id, "read_only")
    runtime.finish_attempt(attempt.id, "failed", error_summary="expected failure")
    runtime.create_approval_request(
        PolicyResolution(
            action=PermissionAction.WORKSPACE_WRITE,
            decision=PolicyDecision.ASK,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
            policy_source="test-policy",
        ),
        PolicyContext(
            session_id=session.id,
            run_id=run.id,
            job_id=submission.job.id,
            reason="Review the retained change",
            preview={"path": "/tmp/private-worktree"},
        ),
    )
    sessions.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=session.id,
            run_id=run.id,
            type="model_reasoning",
            message="Hidden reasoning must not render",
            payload={"thought": "secret"},
            created_at=utc_now(),
            attempt_id=attempt.id,
            span_kind="reasoning",
        )
    )
    event_id = new_id("evt")
    sessions.append_event(
        HarnessStoredEvent(
            id=event_id,
            session_id=session.id,
            run_id=run.id,
            type="tool_finished",
            message="Tool completed",
            payload={"result": "visible", "reasoning": "hidden"},
            created_at=utc_now(),
            attempt_id=attempt.id,
            span_id="tool_1",
            parent_span_id="agent_1",
            span_kind="tool",
            span_status="succeeded",
        )
    )
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
        store=sessions,
        runtime_store=runtime,
    )
    client = TestClient(app)
    assert client.get("/").status_code == 200
    return client, runtime, sessions, run.id, submission.job.id, event_id
