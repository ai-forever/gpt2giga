from gpt2giga_harness.runtime.approval_ux import approval_ux_projection
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import (
    ApprovalRequest,
    EnforcementLevel,
    PermissionAction,
)


def _request(**changes) -> ApprovalRequest:
    values = {
        "id": "approval_1",
        "action": PermissionAction.PROCESS_SPAWN,
        "status": ApprovalStatus.PENDING,
        "enforcement": EnforcementLevel.ENFORCED_BY_HARNESS,
        "policy_source": "profile:review_every_action",
        "enforcement_owner": "durable_worker",
        "reason": "Start the reviewed process.",
        "preview": {"harness_id": "echo", "mode": "plan"},
        "created_at": "2026-07-27T12:00:00+00:00",
        "project_id": "project_1",
        "session_id": "session_1",
        "run_id": "run_1",
        "job_id": "job_1",
    }
    values.update(changes)
    return ApprovalRequest(**values)


def test_approval_projection_explains_target_risk_scope_and_choices():
    payload = approval_ux_projection(_request())

    assert payload["schema_version"] == 1
    assert payload["target"] == {
        "kind": "subprocess",
        "fields": {"harness_id": "echo"},
    }
    assert payload["scope"] == {
        "operation_id": "job_1",
        "session_id": "session_1",
        "project_id": "project_1",
    }
    assert payload["risk"] == "medium"
    assert payload["consequence"] == "start_a_local_process"
    assert payload["side_effect_free"] is True
    assert payload["grant_created"] is False
    assert len(payload["preview_sha256"]) == 64
    choices = {option["decision"]: option for option in payload["decision_options"]}
    assert choices["allow_once"]["enabled"] is True
    assert choices["allow_session"]["enabled"] is True
    assert choices["allow_project"]["enabled"] is False


def test_hash_bound_or_protected_requests_fail_closed():
    bound = approval_ux_projection(
        _request(preview={"approval_binding": "exact-preview", "harness_id": "echo"})
    )
    assert bound["preview_bound"] is True
    assert (
        next(
            option
            for option in bound["decision_options"]
            if option["decision"] == "allow_session"
        )["enabled"]
        is False
    )

    protected = approval_ux_projection(
        _request(
            action=PermissionAction.WORKSPACE_WRITE,
            preview={"workspace": ".git/config"},
        )
    )
    assert protected["protected"] is True
    assert protected["risk"] == "blocked"
    assert [item["decision"] for item in protected["decision_options"]] == ["deny"]


def test_network_projection_retains_the_exact_redacted_target():
    payload = approval_ux_projection(
        _request(
            action=PermissionAction.NETWORK_CONNECT,
            preview={
                "url": "https://api.example.test/v1",
                "operation": "POST metadata only",
            },
        )
    )

    assert payload["target"] == {
        "kind": "network",
        "fields": {
            "url": "https://api.example.test/v1",
            "operation": "POST metadata only",
        },
    }


def test_network_projection_exposes_scoped_grant_fields_without_body_content():
    payload = approval_ux_projection(
        _request(
            action=PermissionAction.NETWORK_CONNECT,
            preview={
                "host": "api.example.test",
                "port": 443,
                "protocol": "https",
                "method": "POST",
                "method_class": "write",
                "redirect_policy": "deny",
                "purpose": "provider.metadata",
                "max_request_body_bytes": 65536,
                "max_response_body_bytes": 1048576,
                "request_body_sha256": "a" * 64,
            },
        )
    )

    assert payload["target"]["kind"] == "network"
    assert payload["target"]["fields"] == {
        "host": "api.example.test",
        "port": 443,
        "protocol": "https",
        "method": "POST",
        "method_class": "write",
        "redirect_policy": "deny",
        "purpose": "provider.metadata",
        "max_request_body_bytes": 65536,
        "max_response_body_bytes": 1048576,
    }
    assert "request_body_sha256" not in payload["target"]["fields"]
