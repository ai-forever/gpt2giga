from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.reviewed_evidence import reviewed_evidence_manifest
from gpt2giga_harness.runtime.models import ApprovalStatus, JobStatus
from gpt2giga_harness.runtime.policy import (
    ApprovalDecision,
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    REVIEWED_PROMOTION_APPLY_OWNER,
    REVIEW_EVERY_ACTION_PROFILE,
    approval_binding_digest,
    approval_request_to_dict,
    permission_profile,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobWorker
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.ui.app import create_app


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


def test_session_grant_is_distinct_from_run_and_project_scope(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    engine = PolicyEngine(store)
    context = PolicyContext(
        project_id="project_scope",
        session_id="session_scope",
        run_id="run_scope",
        reason="Start a reviewed process.",
    )
    resolution = engine.resolve(
        PermissionAction.PROCESS_SPAWN,
        profile=permission_profile("review_every_action"),
        context=context,
    )
    request = store.create_approval_request(resolution, context)

    store.decide_approval_request(request.id, ApprovalDecision.ALLOW_SESSION)

    assert store.consume_matching_approval_grant(
        action=PermissionAction.PROCESS_SPAWN,
        project_id="project_scope",
        session_id="session_scope",
        run_id="another_run",
        job_id=None,
    )
    assert not store.consume_matching_approval_grant(
        action=PermissionAction.PROCESS_SPAWN,
        project_id="project_scope",
        session_id="other_session",
        run_id="another_run",
        job_id=None,
    )


def test_hash_bound_approval_cannot_be_broadened_or_rebound(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    binding = "reviewed-source-and-patch"
    context = PolicyContext(
        project_id="project_bound",
        session_id="sess_bound",
        run_id="run_bound",
        reason="Apply the reviewed patch.",
        preview={"source_sha": "a" * 40, "patch_sha256": "b" * 64},
        approval_binding=binding,
    )
    resolution = PolicyEngine(store).resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=context,
    )
    approval = store.create_approval_request(resolution, context)
    duplicate = store.create_approval_request(resolution, context)
    rebound_context = replace(
        context,
        approval_binding="different-source-or-patch",
    )
    rebound_resolution = PolicyEngine(store).resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=rebound_context,
    )
    rebound = store.create_approval_request(rebound_resolution, rebound_context)

    assert duplicate.id == approval.id
    assert rebound.id != approval.id
    assert store.find_approval_request_by_binding(binding) == approval
    assert store.find_approval_request_by_binding("missing-binding") is None
    assert approval.preview["approval_binding_sha256"] == approval_binding_digest(
        binding
    )
    with pytest.raises(ValueError, match="only be allowed once"):
        store.decide_approval_request(approval.id, ApprovalDecision.ALLOW_RUN)

    decided = store.decide_approval_request(approval.id, ApprovalDecision.ALLOW_ONCE)
    assert store.find_approval_request_by_binding(binding) == decided
    assert not store.consume_matching_approval_grant(
        action=PermissionAction.GIT_APPLY,
        project_id="project_bound",
        run_id="run_bound",
        job_id=None,
        approval_binding="different-source-or-patch",
    )
    assert store.consume_matching_approval_grant(
        action=PermissionAction.GIT_APPLY,
        project_id="project_bound",
        run_id="run_bound",
        job_id=None,
        approval_binding=binding,
    )
    assert not store.consume_matching_approval_grant(
        action=PermissionAction.GIT_APPLY,
        project_id="project_bound",
        run_id="run_bound",
        job_id=None,
        approval_binding=binding,
    )


def test_reviewed_promotion_records_immutable_hash_chained_policy_audit(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    binding = "raw-reviewed-source-and-patch-binding"
    context = PolicyContext(
        project_id="project_audit",
        session_id="sess_audit",
        run_id="run_audit",
        reason="Apply the reviewed patch.",
        preview={
            "source_sha": "a" * 40,
            "patch_sha256": "b" * 64,
            "api_key": "secret-value",
        },
        approval_binding=binding,
        enforcement_owner=REVIEWED_PROMOTION_APPLY_OWNER,
    )
    engine = PolicyEngine(store)
    resolution = engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=context,
    )
    approval = store.create_approval_request(resolution, context)
    store.decide_approval_request(approval.id, ApprovalDecision.ALLOW_ONCE)

    wrong_owner = engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=replace(context, enforcement_owner="reviewed_promotion.other"),
    )
    wrong_binding = engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=replace(context, approval_binding="different-reviewed-binding"),
    )
    assert store.list_policy_audit_events(operation_id=approval.id)[-1].phase.value == (
        "decision"
    )
    authorized = engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=context,
    )

    assert wrong_owner.decision is PolicyDecision.ASK
    assert wrong_binding.decision is PolicyDecision.ASK
    assert authorized.decision is PolicyDecision.ALLOW
    events = store.list_policy_audit_events(operation_id=approval.id)
    assert [event.phase.value for event in events] == [
        "resolution",
        "decision",
        "enforcement",
    ]
    assert [event.decision for event in events] == ["ask", "allow_once", "allow"]
    assert {event.enforcement_owner for event in events} == {
        REVIEWED_PROMOTION_APPLY_OWNER
    }
    assert all(
        event.approval_binding_sha256 == approval_binding_digest(binding)
        for event in events
    )
    assert events[0].previous_event_sha256 is None
    assert events[1].previous_event_sha256 == events[0].event_sha256
    assert events[2].previous_event_sha256 == events[1].event_sha256
    reviewed_evidence = reviewed_evidence_manifest("run_audit", events)
    assert reviewed_evidence is not None
    assert reviewed_evidence["source_run_id"] == "run_audit"
    assert reviewed_evidence["operations"] == [
        {
            "operation_id": approval.id,
            "action": "git.apply",
            "enforcement_owner": REVIEWED_PROMOTION_APPLY_OWNER,
            "approval_binding_sha256": approval_binding_digest(binding),
            "audit_head_sha256": events[-1].event_sha256,
            "event_count": 3,
        }
    ]
    exported = store.export()
    assert exported["reviewed_evidence"] == [reviewed_evidence]
    assert binding not in str(exported)
    assert "secret-value" not in str(exported)

    with pytest.raises(ValueError, match="event hash is invalid"):
        reviewed_evidence_manifest(
            "run_audit",
            (*events[:-1], replace(events[-1], event_sha256="0" * 64)),
        )

    with closing(sqlite3.connect(store.path)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE policy_audit_events SET decision = 'deny' WHERE id = ?",
                (events[0].id,),
            )
    with closing(sqlite3.connect(store.path)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM policy_audit_events WHERE id = ?", (events[0].id,)
            )


def test_reviewed_promotion_denial_has_no_enforcement_event(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    context = PolicyContext(
        project_id="project_denied_audit",
        run_id="run_denied_audit",
        reason="Apply the reviewed patch.",
        preview={"source_sha": "a" * 40, "patch_sha256": "b" * 64},
        approval_binding="denied-binding",
        enforcement_owner=REVIEWED_PROMOTION_APPLY_OWNER,
    )
    resolution = PolicyEngine(store).resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=context,
    )
    approval = store.create_approval_request(resolution, context)

    store.decide_approval_request(approval.id, ApprovalDecision.DENY)

    events = store.list_policy_audit_events(operation_id=approval.id)
    assert [event.phase.value for event in events] == ["resolution", "decision"]
    assert events[-1].decision == "deny"


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
    assert approval["ux"]["target"]["kind"] == "subprocess"
    assert approval["ux"]["risk"] == "medium"
    assert approval["ux"]["side_effect_free"] is True
    assert approval["ux"]["grant_created"] is False

    decided = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "allow_once"},
    )

    assert decided.status_code == 200
    assert decided.json()["job_status"] == "queued"
    assert worker.run_once() is True
    assert runtime.get_job(started.json()["job"]["id"]).status is JobStatus.SUCCEEDED
