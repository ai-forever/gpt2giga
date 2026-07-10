from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.runtime.models import ApprovalStatus, JobStatus
from gpt2giga.harness.runtime.policy import (
    ApprovalDecision,
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    REVIEW_EVERY_ACTION_PROFILE,
    approval_request_to_dict,
    permission_profile,
)
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.harness.runtime.worker import DurableJobWorker
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.ui.app import create_app


def test_policy_profiles_are_named_and_record_enforcement_boundary():
    profile = permission_profile("review-every-action")
    resolution = PolicyEngine().resolve(
        PermissionAction.PROCESS_SPAWN,
        profile=profile,
        context=PolicyContext(reason="test"),
        enforcement=EnforcementLevel.DELEGATED_TO_CLI_SANDBOX,
    )

    assert profile is REVIEW_EVERY_ACTION_PROFILE
    assert resolution.decision is PolicyDecision.ASK
    assert resolution.policy_source == "profile:review_every_action"
    assert resolution.enforcement is EnforcementLevel.DELEGATED_TO_CLI_SANDBOX


def test_approval_allow_once_requeues_pre_spawn_job_and_is_consumed(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    job = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        initial_run_id="run_1",
        idempotency_key="approval-job",
        initial_status=JobStatus.WAITING_APPROVAL,
    ).job
    context = PolicyContext(
        project_id="project_1",
        session_id=job.session_id,
        run_id=job.initial_run_id,
        job_id=job.id,
        reason="Start a process.",
        preview={"api_key": "secret-value", "command": "tool --safe"},
    )
    resolution = PolicyEngine(store).resolve(
        PermissionAction.PROCESS_SPAWN,
        profile=REVIEW_EVERY_ACTION_PROFILE,
        context=context,
    )

    approval = store.create_approval_request(resolution, context)
    duplicate = store.create_approval_request(resolution, context)

    assert approval.id == duplicate.id
    assert store.get_job(job.id).approval_request_id == approval.id
    assert (
        store.claim_next_job(
            worker_id="worker_1", capability_fingerprint={}, lease_seconds=5
        )
        is None
    )
    decided = store.decide_approval_request(approval.id, ApprovalDecision.ALLOW_ONCE)
    assert decided.status is ApprovalStatus.APPROVED
    assert store.get_job(job.id).status is JobStatus.QUEUED
    assert store.consume_matching_approval_grant(
        action=PermissionAction.PROCESS_SPAWN,
        project_id=context.project_id,
        run_id=context.run_id,
        job_id=context.job_id,
    )
    assert not store.consume_matching_approval_grant(
        action=PermissionAction.PROCESS_SPAWN,
        project_id=context.project_id,
        run_id=context.run_id,
        job_id=context.job_id,
    )
    exported = approval_request_to_dict(decided)
    assert "secret-value" not in str(exported)
    assert exported["enforcement"] == "enforced_by_harness"


def test_denied_pre_spawn_approval_cancels_without_attempt(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    job = store.submit_job(
        session_id="sess_denied",
        user_message_id="msg_denied",
        initial_run_id="run_denied",
        idempotency_key="denied",
        initial_status=JobStatus.WAITING_APPROVAL,
    ).job
    context = PolicyContext(
        session_id=job.session_id,
        run_id=job.initial_run_id,
        job_id=job.id,
        reason="Start a process.",
    )
    resolution = PolicyEngine(store).resolve(
        PermissionAction.PROCESS_SPAWN,
        profile=REVIEW_EVERY_ACTION_PROFILE,
        context=context,
    )
    approval = store.create_approval_request(resolution, context)

    decided = store.decide_approval_request(approval.id, ApprovalDecision.DENY)

    assert decided.status is ApprovalStatus.DENIED
    assert store.get_job(job.id).status is JobStatus.CANCELED
    assert store.list_attempts(job.id) == ()
    assert store.inspect()["counts"]["approval_requests"] == 1


def test_run_and_expiring_project_grants_stay_in_scope(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    engine = PolicyEngine(store)
    run_context = PolicyContext(
        project_id="project_scope",
        session_id="sess_scope",
        run_id="run_scope",
        reason="Create a branch.",
    )
    branch_resolution = engine.resolve(
        PermissionAction.GIT_BRANCH_CREATE,
        profile=permission_profile("interactive"),
        context=run_context,
    )
    branch_request = store.create_approval_request(branch_resolution, run_context)
    store.decide_approval_request(branch_request.id, ApprovalDecision.ALLOW_RUN)

    assert store.consume_matching_approval_grant(
        action=PermissionAction.GIT_BRANCH_CREATE,
        project_id="project_scope",
        run_id="run_scope",
        job_id=None,
    )
    assert not store.consume_matching_approval_grant(
        action=PermissionAction.GIT_BRANCH_CREATE,
        project_id="other_project",
        run_id="other_run",
        job_id=None,
    )

    apply_resolution = engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=run_context,
    )
    apply_request = store.create_approval_request(apply_resolution, run_context)
    store.decide_approval_request(
        apply_request.id,
        ApprovalDecision.ALLOW_PROJECT,
        project_expiry_seconds=3600,
    )

    assert store.consume_matching_approval_grant(
        action=PermissionAction.GIT_APPLY,
        project_id="project_scope",
        run_id="another_run",
        job_id=None,
    )
    assert not store.consume_matching_approval_grant(
        action=PermissionAction.GIT_APPLY,
        project_id="other_project",
        run_id="another_run",
        job_id=None,
    )


def test_approval_center_requeues_strict_profile_job_for_worker(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = create_default_registry(include_entry_points=False)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    client = TestClient(
        create_app(
            config,
            registry=registry,
            store=sessions,
            runtime_store=runtime,
        )
    )

    started = client.post(
        "/api/sessions/run/start",
        json={
            "harness_id": "echo",
            "prompt": "approval gate",
            "permission_profile": "review_every_action",
        },
    )

    assert started.status_code == 200
    assert started.json()["job"]["status"] == "waiting_approval"
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_policy")
    assert worker.run_once() is False
    inbox = client.get("/api/approvals?status=pending").json()
    assert inbox["pending_count"] == 1
    approval = inbox["approvals"][0]
    assert approval["action"] == "process.spawn"

    decided = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "allow_once"},
    )

    assert decided.status_code == 200
    assert decided.json()["job_status"] == "queued"
    assert worker.run_once() is True
    assert runtime.get_job(started.json()["job"]["id"]).status is JobStatus.SUCCEEDED
