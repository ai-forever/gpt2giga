from dataclasses import replace

import pytest

from gpt2giga_harness.runtime.authority import (
    ApprovalPolicy,
    ApprovalPreset,
    AuthorityDecision,
    AuthorityGrant,
    AuthorityLifetime,
    AuthorityResourceKind,
    AuthorityScope,
    BrowserTarget,
    ChildAgentTarget,
    FilesystemTarget,
    GitHubTarget,
    IntegrationTarget,
    McpTarget,
    NetworkTarget,
    RevalidationReason,
    ReviewerKind,
    SubprocessTarget,
    authority_schema_manifest,
    child_scope_within_ceiling,
    compile_approval_preset,
    revalidation_reasons,
)
from gpt2giga_harness.runtime.policy import EnforcementLevel


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _scope(target, *operations: str) -> AuthorityScope:
    return AuthorityScope(target=target, operations=operations)


def _policy(
    preset: ApprovalPreset,
    reviewer: ReviewerKind = ReviewerKind.HUMAN,
) -> ApprovalPolicy:
    return ApprovalPolicy(
        preset=preset,
        reviewer_kind=reviewer,
        reviewer_id="operator_1" if reviewer is ReviewerKind.HUMAN else "reviewer_v1",
        policy_source="settings.default",
        enforcement=EnforcementLevel.DELEGATED_TO_CLI_SANDBOX,
    )


def _grant(scope: AuthorityScope, **changes) -> AuthorityGrant:
    values = {
        "id": "grant_1",
        "scope": scope,
        "lifetime": AuthorityLifetime.OPERATION,
        "preview_sha256": SHA_A,
        "policy_source": "settings.default",
        "reviewer_kind": ReviewerKind.HUMAN,
        "reviewer_id": "operator_1",
        "enforcement": EnforcementLevel.ENFORCED_BY_HARNESS,
        "created_at": "2026-07-27T10:00:00+00:00",
        "operation_id": "operation_1",
    }
    values.update(changes)
    return AuthorityGrant(**values)


def test_schema_models_each_authority_resource_separately():
    scopes = (
        _scope(FilesystemTarget("workspace_1", "src/app.py"), "read", "write"),
        _scope(SubprocessTarget("pytest", SHA_A, SHA_B), "execute"),
        _scope(NetworkTarget("api.example.com", 443, "https"), "connect", "post"),
        _scope(GitHubTarget("openai/codex"), "pull_request.create"),
        _scope(BrowserTarget("https://example.com"), "navigate"),
        _scope(McpTarget("docs", "search"), "call"),
        _scope(IntegrationTarget("plugin_1", SHA_C), "disable"),
        _scope(ChildAgentTarget("reviewer", SHA_B), "delegate"),
    )

    assert [scope.resource_kind for scope in scopes] == list(AuthorityResourceKind)
    assert len({scope.scope_sha256 for scope in scopes}) == len(scopes)
    assert all(scope.to_dict()["schema_version"] == 1 for scope in scopes)


def test_network_target_canonicalizes_ipv6_without_confusing_port_separator():
    target = NetworkTarget("2606:4700:4700::1111", 443, "https")

    assert target.to_dict()["host"] == "2606:4700:4700::1111"


def test_presets_compile_to_explicit_rules_without_changing_enforcement():
    read = _scope(FilesystemTarget("workspace_1", "src"), "read")
    write = _scope(FilesystemTarget("workspace_1", "src"), "write")

    previews = {read.scope_sha256: SHA_A, write.scope_sha256: SHA_B}
    always = compile_approval_preset(
        _policy(ApprovalPreset.ALWAYS_ASK),
        (read, write),
        preview_sha256=previews,
    )
    ask_writes = compile_approval_preset(
        _policy(ApprovalPreset.ASK_ON_WRITES),
        (read, write),
        preview_sha256=previews,
    )
    auto_reviewed = compile_approval_preset(
        _policy(ApprovalPreset.ALLOW_REVIEWED, ReviewerKind.AUTO_REVIEW),
        (read, write),
        preview_sha256=previews,
        reviewed_preview_sha256={write.scope_sha256: SHA_B},
    )

    assert {item.decision for item in always} == {AuthorityDecision.ASK}
    assert {item.scope_sha256: item.decision for item in ask_writes} == {
        read.scope_sha256: AuthorityDecision.ALLOW,
        write.scope_sha256: AuthorityDecision.ASK,
    }
    assert {item.scope_sha256: item.decision for item in auto_reviewed} == {
        read.scope_sha256: AuthorityDecision.ASK,
        write.scope_sha256: AuthorityDecision.ALLOW,
    }
    assert {item.reviewer_kind for item in auto_reviewed} == {ReviewerKind.AUTO_REVIEW}
    assert {item.enforcement for item in auto_reviewed} == {
        EnforcementLevel.DELEGATED_TO_CLI_SANDBOX
    }
    changed_preview = compile_approval_preset(
        _policy(ApprovalPreset.ALLOW_REVIEWED, ReviewerKind.AUTO_REVIEW),
        (write,),
        preview_sha256={write.scope_sha256: SHA_C},
        reviewed_preview_sha256={write.scope_sha256: SHA_B},
    )
    assert changed_preview[0].decision is AuthorityDecision.ASK


def test_grant_lifetimes_are_distinct_and_persisted_policy_expires():
    scope = _scope(GitHubTarget("openai/codex"), "issue.create")

    operation = _grant(scope)
    session = _grant(
        scope,
        id="grant_2",
        lifetime=AuthorityLifetime.SESSION,
        operation_id=None,
        session_id="session_1",
    )
    persisted = _grant(
        scope,
        id="grant_3",
        lifetime=AuthorityLifetime.PERSISTED_POLICY,
        operation_id=None,
        policy_id="policy_1",
        expires_at="2026-07-27T11:00:00+00:00",
    )

    assert {item.lifetime for item in (operation, session, persisted)} == set(
        AuthorityLifetime
    )
    with pytest.raises(ValueError, match="requires expires_at"):
        replace(persisted, expires_at=None)


def test_child_scope_can_only_preserve_or_narrow_parent_ceiling():
    parent = _scope(
        FilesystemTarget("workspace_1", "src", recursive=True),
        "read",
        "write",
    )
    narrowed = _scope(
        FilesystemTarget("workspace_1", "src", recursive=True),
        "read",
    )
    broader = _scope(
        FilesystemTarget("workspace_1", "src", recursive=True),
        "delete",
        "read",
        "write",
    )
    different_target = _scope(
        FilesystemTarget("workspace_1", "tests", recursive=True),
        "read",
    )

    assert child_scope_within_ceiling(narrowed, parent)
    assert not child_scope_within_ceiling(broader, parent)
    assert not child_scope_within_ceiling(different_target, parent)


def test_stale_preview_target_redirect_and_retry_force_revalidation():
    original = _scope(NetworkTarget("api.example.com", 443, "https"), "post")
    changed = _scope(NetworkTarget("other.example.com", 443, "https"), "post")
    grant = _grant(
        original,
        revoked_at="2026-07-27T10:10:00+00:00",
        expires_at="2026-07-27T10:20:00+00:00",
    )

    reasons = revalidation_reasons(
        grant,
        current_scope=changed,
        current_preview_sha256=SHA_B,
        now="2026-07-27T10:30:00+00:00",
        redirected=True,
        retry=True,
    )

    assert reasons == (
        RevalidationReason.REVOKED,
        RevalidationReason.EXPIRED,
        RevalidationReason.STALE_PREVIEW,
        RevalidationReason.TARGET_CHANGED,
        RevalidationReason.REDIRECT,
        RevalidationReason.RETRY,
    )


def test_manifest_freezes_required_g4_00_invariants():
    assert authority_schema_manifest() == {
        "schema_version": 1,
        "resource_kinds": [
            "filesystem",
            "subprocess",
            "network",
            "github",
            "browser",
            "mcp",
            "integration",
            "child_agent",
        ],
        "lifetimes": ["operation", "session", "persisted_policy"],
        "approval_presets": ["always_ask", "ask_on_writes", "allow_reviewed"],
        "reviewer_kinds": ["human", "auto_review"],
        "decisions": ["ask", "allow", "deny"],
        "revalidation_reasons": [
            "expired",
            "revoked",
            "stale_preview",
            "target_changed",
            "redirect",
            "retry",
        ],
        "child_authority_rule": "same_target_and_subset_operations",
        "auto_review_changes_enforcement": False,
        "content_free_preview_binding": "sha256",
    }
