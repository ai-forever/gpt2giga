import asyncio

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
from gpt2giga_harness.ui.routers.runs import (
    _runs_center_resnapshot_sse,
    _runs_center_revision,
    _runs_center_update_sse,
    _stream_runs_center_updates,
)
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
    explanations = {item["key"]: item for item in body["runs"][0]["explanations"]}
    assert list(explanations) == [
        "policy",
        "worktree",
        "provenance",
        "recovery",
        "promotion",
    ]
    assert explanations["policy"]["status"] == "attention"
    assert "awaits an operator decision" in explanations["policy"]["summary"]
    assert explanations["worktree"]["status"] == "attention"
    assert "awaits explicit review" in explanations["worktree"]["summary"]
    assert explanations["provenance"]["status"] == "attention"
    assert explanations["recovery"]["status"] == "ready"
    assert "Safe retry is available" in explanations["recovery"]["summary"]
    assert explanations["promotion"]["status"] == "blocked"
    assert "failed run" in explanations["promotion"]["summary"]
    assert "prompt" not in body["runs"][0]["job"]
    assert "prompt" not in body["runs"][0]["run"]
    assert "metadata" not in body["runs"][0]["run"]
    assert "/tmp/demo-worktree" not in response.text
    assert summary.status_code == 200
    assert summary.json()["run"]["run_id"] == run_id
    assert client.get("/api/runs?status=unknown").status_code == 400
    assert runtime.get_job(job_id).status.value == "failed"


def test_runs_center_stream_contract_is_global_content_free_and_routable(tmp_path):
    client, runtime, sessions, _run_id, _job_id, _event_id = _failed_run(tmp_path)
    revision = _runs_center_revision(runtime, sessions)
    update = _runs_center_update_sse(revision)
    resnapshot = _runs_center_resnapshot_sse(revision)

    assert "/api/runs/updates/stream" in client.get("/openapi.json").json()["paths"]
    assert update == (
        f'id: {revision}\ndata: {{"revision":"{revision}","type":"runs.updated"}}\n\n'
    )
    assert resnapshot == (f'event: resnapshot\ndata: {{"revision":"{revision}"}}\n\n')
    assert "run_id" not in update
    assert "session_id" not in update


async def test_runs_center_stream_emits_revision_and_cleans_up_subscription(tmp_path):
    _client, runtime, sessions, run_id, _job_id, _event_id = _failed_run(tmp_path)
    subscription = sessions.event_broker.subscribe_runs_center()
    initial = _runs_center_revision(runtime, sessions)
    stream = _stream_runs_center_updates(
        runtime,
        sessions,
        subscription,
        initial_revision=initial,
        last_event_id=None,
    )
    try:
        assert await anext(stream) == ": connected\n\n"
        session_id = sessions.get_run(run_id).session_id
        sessions.update_session(session_id, title="Updated from another task")
        frame = await asyncio.wait_for(anext(stream), timeout=1)
        assert '"type":"runs.updated"' in frame
        assert initial not in frame
    finally:
        await stream.aclose()

    assert sessions.event_broker.runs_center_subscriber_count() == 0


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


def test_runs_center_explains_complete_provenance_and_promotion_eligibility(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    workspace = tmp_path / "repo"
    workspace.mkdir()
    session = sessions.create_session(title="Reusable run", workspace=str(workspace))
    run = sessions.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="summarize the project",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=str(workspace),
        status="succeeded",
    )
    run = sessions.update_run(
        run.id,
        metadata={
            "workspace_execution": {"policy": "current"},
            "provenance": {
                key: {}
                for key in (
                    "project",
                    "git",
                    "harness",
                    "request",
                    "execution",
                    "records",
                    "replay_request",
                )
            },
        },
    )
    job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_reuse",
        initial_run_id=run.id,
        idempotency_key="reuse",
        required_harness_id="echo",
    ).job
    attempt = runtime.create_attempt(job.id, run_id=run.id, status="running")
    runtime.finish_attempt(attempt.id, "succeeded")
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
        store=sessions,
        runtime_store=runtime,
    )

    response = TestClient(app).get(f"/api/runs/{run.id}/summary")

    assert response.status_code == 200
    explanations = {
        item["key"]: item for item in response.json()["run"]["explanations"]
    }
    assert explanations["policy"]["status"] == "neutral"
    assert explanations["worktree"]["status"] == "neutral"
    assert explanations["provenance"]["status"] == "ready"
    assert "7 of 7" in explanations["provenance"]["summary"]
    assert explanations["recovery"]["status"] == "ready"
    assert explanations["promotion"]["status"] == "ready"
    assert "reviewed promotion preview" in explanations["promotion"]["summary"]
    assert str(workspace) not in str(explanations)


def test_runs_center_exports_content_free_redacted_support_bundle(tmp_path):
    client, _runtime, sessions, run_id, job_id, _event_id = _failed_run(tmp_path)
    secret = "support-secret-value-123456"
    run = sessions.get_run(run_id)
    sessions.update_run(
        run_id,
        metadata={
            **dict(run.metadata),
            "preflight": {
                "ok": True,
                "hard_block": False,
                "max_severity": "warning",
                "findings": [
                    {
                        "severity": "warning",
                        "code": "credential-like-content",
                        "message": f"password={secret}",
                        "workspace_path": "/tmp/private-source/.env",
                    }
                ],
                "readiness": {
                    "schema_version": 1,
                    "ok": True,
                    "blocked": False,
                    "summary": {"ready": 2, "degraded": 1, "blocked": 0},
                    "plan": {
                        "harness_id": "echo",
                        "invocation_mode": "headless",
                        "api_mode": "v2",
                        "model": None,
                        "mode": "plan",
                        "workspace_configured": False,
                        "workspace_policy": "current",
                        "delivery": "durable",
                        "dry_run": False,
                    },
                    "findings": [
                        {
                            "id": "delivery",
                            "category": "execution-plan",
                            "status": "ready",
                            "required": True,
                            "summary": (
                                "Run delivery uses the durable worker path at "
                                "/var/private-worker/state.json."
                            ),
                            "evidence": {"private_path": "/tmp/private-worker"},
                            "remediation": [],
                        }
                    ],
                },
            },
        },
    )

    response = client.get(f"/api/runs/{run_id}/support-bundle")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="gpt2giga-support-{run_id}.json"'
    )
    bundle = response.json()
    assert bundle["schema_version"] == 1
    assert bundle["run"]["job_id"] == job_id
    assert bundle["capability_snapshot"]["harness_id"] == "echo"
    assert bundle["execution_plan"]["delivery"] == "durable"
    assert bundle["diagnostics"]["preflight"]["finding_codes"] == [
        "credential-like-content"
    ]
    assert bundle["diagnostics"]["readiness"]["findings"][0]["id"] == "delivery"
    assert (
        "<internal-path>"
        in (bundle["diagnostics"]["readiness"]["findings"][0]["summary"])
    )
    assert bundle["artifacts"] == [
        {"type": "worktree", "source": "run"},
        {"type": "diff", "source": "run"},
        {"type": "pr", "source": "run"},
    ]
    assert any(
        transition.get("event_type") == "tool_finished"
        for transition in bundle["state_transitions"]
    )
    assert all(
        "message" not in item and "payload" not in item
        for item in bundle["state_transitions"]
    )
    assert bundle["safety"] == {
        "approval_context_included": False,
        "artifact_content_included": False,
        "commands_included": False,
        "content_capture_included": False,
        "errors_included": False,
        "event_payloads_included": False,
        "messages_included": False,
        "prompt_included": False,
        "workspace_paths_included": False,
    }
    serialized = response.text
    for forbidden in (
        secret,
        "review this",
        "Tool completed",
        "visible",
        "diff --git",
        "Review the retained change",
        "/tmp/demo-worktree",
        "/tmp/private-worktree",
        "/tmp/private-source",
        "/tmp/private-worker",
    ):
        assert forbidden not in serialized


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
