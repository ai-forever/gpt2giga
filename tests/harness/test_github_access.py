from dataclasses import replace
import json

import pytest

from gpt2giga_harness.runtime.authority import (
    AuthorityGrant,
    AuthorityLifetime,
    ReviewerKind,
)
from gpt2giga_harness.runtime.github_access import (
    GitHubAccessDenied,
    GitHubAuthoritySurface,
    GitHubCapabilityRequest,
    GitHubCredentialBinding,
    GitHubCredentialSource,
    GitHubOperationClass,
    authorize_github_capability,
    github_access_manifest,
)
from gpt2giga_harness.runtime.policy import EnforcementLevel


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _credential(**changes) -> GitHubCredentialBinding:
    values = {
        "source": GitHubCredentialSource.GH_CLI_ACTIVE_ACCOUNT,
        "host": "github.com",
        "principal_sha256": SHA_A,
        "permission_set_sha256": SHA_B,
        "expires_at": "2026-07-27T11:00:00+00:00",
    }
    values.update(changes)
    return GitHubCredentialBinding(**values)


def _request(**changes) -> GitHubCapabilityRequest:
    values = {
        "repository": "OpenAI/Codex",
        "operation": GitHubOperationClass.PULL_REQUEST_WRITE,
        "surface": GitHubAuthoritySurface.GITHUB_API,
        "credential": _credential(),
        "resource_id": "new",
        "payload_bytes": 256,
        "payload_sha256": SHA_C,
        "preview_created_at": "2026-07-27T10:00:00+00:00",
        "preview_expires_at": "2026-07-27T10:05:00+00:00",
    }
    values.update(changes)
    return GitHubCapabilityRequest(**values)


def _grant(request: GitHubCapabilityRequest, **changes) -> AuthorityGrant:
    values = {
        "id": "github_grant_1",
        "scope": request.scope,
        "lifetime": AuthorityLifetime.OPERATION,
        "preview_sha256": request.preview_sha256,
        "policy_source": "approval.github",
        "reviewer_kind": ReviewerKind.HUMAN,
        "reviewer_id": "operator_1",
        "enforcement": EnforcementLevel.ENFORCED_BY_HARNESS,
        "created_at": "2026-07-27T10:00:00+00:00",
        "expires_at": "2026-07-27T10:10:00+00:00",
        "operation_id": "operation_1",
    }
    values.update(changes)
    return AuthorityGrant(**values)


def _authorize(
    request: GitHubCapabilityRequest,
    grant: AuthorityGrant | None,
    **changes,
):
    values = {
        "current_credential_binding_sha256": request.credential.binding_sha256,
        "now": "2026-07-27T10:03:00+00:00",
    }
    values.update(changes)
    return authorize_github_capability(request, grant, **values)


def test_local_git_is_not_github_authority_and_manifest_freezes_the_boundary():
    with pytest.raises(
        ValueError,
        match="local Git must use local Git authority",
    ):
        _request(surface=GitHubAuthoritySurface.LOCAL_GIT)

    manifest = github_access_manifest()
    assert manifest["authority_surfaces"] == {
        "local_git": "separate_non_github_authority",
        "github_api": "github_capability",
        "github_cli": "github_capability",
    }
    assert manifest["orientation"]["mutation_grant_required"] is False
    assert manifest["orientation"]["network_authority_required"] is True
    assert manifest["write_operation_classes"] == [
        "issue.write",
        "comment.write",
        "pull_request.write",
        "release.write",
    ]
    assert manifest["write_grant"]["lifetime"] == "operation"
    assert manifest["write_grant"]["fresh_preview_required"] is True
    assert manifest["live_github_side_effect"] is False


def test_read_only_orientation_is_independent_of_mutation_grants():
    request = GitHubCapabilityRequest(
        repository="OpenAI/Codex",
        operation=GitHubOperationClass.ORIENTATION_READ,
        surface=GitHubAuthoritySurface.GITHUB_CLI,
        credential=_credential(),
    )

    ticket = _authorize(request, None)

    assert request.repository == "openai/codex"
    assert request.approval_binding is None
    assert ticket.grant_id is None
    assert ticket.operation is GitHubOperationClass.ORIENTATION_READ
    assert ticket.policy_source == "github.orientation.read_only"
    assert ticket.audit_receipt()["network_authority_required"] is True
    with pytest.raises(
        GitHubAccessDenied,
        match="github_orientation_is_independent_of_mutation_grants",
    ):
        _authorize(request, _grant(_request()))


@pytest.mark.parametrize(
    "operation",
    (
        GitHubOperationClass.ISSUE_WRITE,
        GitHubOperationClass.COMMENT_WRITE,
        GitHubOperationClass.PULL_REQUEST_WRITE,
        GitHubOperationClass.RELEASE_WRITE,
    ),
)
def test_each_hosted_write_class_requires_an_exact_fresh_operation_grant(operation):
    request = _request(operation=operation)

    with pytest.raises(GitHubAccessDenied, match="github_write_requires_grant"):
        _authorize(request, None)

    ticket = _authorize(request, _grant(request))
    assert ticket.operation is operation
    assert ticket.expires_at == "2026-07-27T10:05:00+00:00"
    assert (
        ticket.validate_before_dispatch(
            request,
            current_credential_binding_sha256=request.credential.binding_sha256,
            now="2026-07-27T10:04:00+00:00",
        )["outcome"]
        == "dispatch_validated"
    )


def test_changed_preview_credential_expiry_revocation_and_retry_fail_closed():
    request = _request()
    grant = _grant(request)

    changed_payload = _request(payload_sha256=SHA_B)
    with pytest.raises(
        GitHubAccessDenied,
        match="github_preview_does_not_match_grant",
    ):
        _authorize(changed_payload, grant)
    with pytest.raises(GitHubAccessDenied, match="github_credential_changed"):
        _authorize(
            request,
            grant,
            current_credential_binding_sha256=SHA_C,
        )
    with pytest.raises(GitHubAccessDenied, match="github_grant_is_revoked"):
        _authorize(
            request,
            replace(grant, revoked_at="2026-07-27T10:02:00+00:00"),
        )
    with pytest.raises(GitHubAccessDenied, match="github_write_preview_is_expired"):
        _authorize(request, grant, now="2026-07-27T10:05:00+00:00")
    with pytest.raises(
        GitHubAccessDenied,
        match="github_write_retry_requires_fresh_preview",
    ):
        _authorize(request, grant, retry=True)
    with pytest.raises(
        GitHubAccessDenied,
        match="github_write_requires_operation_grant",
    ):
        _authorize(
            request,
            replace(
                grant,
                lifetime=AuthorityLifetime.SESSION,
                operation_id=None,
                session_id="session_1",
            ),
        )


def test_approval_and_audit_receipts_are_content_free_and_privacy_safe():
    request = _request()
    approval = request.approval_preview()
    ticket = _authorize(request, _grant(request))
    receipt = ticket.audit_receipt()
    encoded = json.dumps({"approval": approval, "receipt": receipt})

    assert approval["repository"]["name_with_owner"] == "openai/codex"
    assert approval["credential_source"] == "gh_cli_active_account"
    assert approval["resource_id_sha256"] != "new"
    assert "body" not in approval
    assert "credential" not in receipt
    assert "principal" not in receipt
    assert receipt["reviewer_id_sha256"] != "operator_1"
    assert receipt["payload_sha256"] == SHA_C
    for canary in (
        "TOKEN=canary",
        "person@example.com",
        "+1-555-0100",
        "4111111111111111",
    ):
        assert canary not in encoded


def test_invalid_write_preview_and_expired_credential_are_rejected():
    with pytest.raises(ValueError, match="fresh preview window"):
        _request(preview_created_at=None)
    with pytest.raises(ValueError, match="preview window is invalid"):
        _request(preview_expires_at="2026-07-27T10:05:01+00:00")

    request = _request(credential=_credential(expires_at="2026-07-27T10:02:00+00:00"))
    with pytest.raises(GitHubAccessDenied, match="github_credential_is_expired"):
        _authorize(request, _grant(request))
