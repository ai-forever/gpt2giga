from dataclasses import replace

import pytest

from gpt2giga_harness.runtime.authority import (
    AuthorityGrant,
    AuthorityLifetime,
    ReviewerKind,
)
from gpt2giga_harness.runtime.network_access import (
    NetworkAccessDenied,
    ReviewedDomainProxyPolicy,
    ReviewedDomainRule,
    ScopedNetworkRequest,
    authorize_scoped_network_access,
    network_access_manifest,
)
from gpt2giga_harness.runtime.policy import EnforcementLevel


SHA_A = "a" * 64


def _request(**changes) -> ScopedNetworkRequest:
    values = {
        "url": "https://api.example.com/v1/models",
        "method": "GET",
        "purpose": "provider.metadata",
    }
    values.update(changes)
    return ScopedNetworkRequest(**values)


def _grant(request: ScopedNetworkRequest, **changes) -> AuthorityGrant:
    values = {
        "id": "network_grant_1",
        "scope": request.scope,
        "lifetime": AuthorityLifetime.OPERATION,
        "preview_sha256": request.preview_sha256,
        "policy_source": "approval.network",
        "reviewer_kind": ReviewerKind.HUMAN,
        "reviewer_id": "operator_1",
        "enforcement": EnforcementLevel.ENFORCED_BY_HARNESS,
        "created_at": "2026-07-27T10:00:00+00:00",
        "expires_at": "2026-07-27T10:15:00+00:00",
        "operation_id": "operation_1",
    }
    values.update(changes)
    return AuthorityGrant(**values)


def _authorize(
    request: ScopedNetworkRequest,
    grant: AuthorityGrant,
    **changes,
):
    values = {
        "resolved_addresses": ("8.8.8.8", "2606:4700:4700::1111"),
        "now": "2026-07-27T10:05:00+00:00",
        "sandbox_network_enabled": True,
    }
    values.update(changes)
    return authorize_scoped_network_access(request, grant, **values)


def test_network_access_is_default_deny_and_requires_harness_enforcement():
    request = _request()
    grant = _grant(request)

    with pytest.raises(
        NetworkAccessDenied,
        match="sandbox_network_access_is_disabled",
    ):
        authorize_scoped_network_access(
            request,
            grant,
            resolved_addresses=("8.8.8.8",),
            now="2026-07-27T10:05:00+00:00",
        )

    delegated = replace(
        grant,
        enforcement=EnforcementLevel.DELEGATED_TO_CLI_SANDBOX,
    )
    with pytest.raises(
        NetworkAccessDenied,
        match="network_grant_is_not_harness_enforced",
    ):
        _authorize(request, delegated)


def test_exact_scope_preview_expiry_and_revocation_are_fail_closed():
    request = _request()
    grant = _grant(request)

    ticket = _authorize(request, grant)
    assert ticket.host == "api.example.com"
    assert ticket.port == 443
    assert ticket.protocol == "https"
    assert ticket.method_class.value == "safe"
    assert ticket.purpose == "provider.metadata"
    assert ticket.pinned_addresses == ("2606:4700:4700::1111", "8.8.8.8")

    changed_method = _request(method="POST")
    with pytest.raises(
        NetworkAccessDenied,
        match="network_scope_does_not_match_grant",
    ):
        _authorize(changed_method, grant)

    changed_purpose = _request(purpose="provider.execute")
    with pytest.raises(
        NetworkAccessDenied,
        match="network_preview_does_not_match_grant",
    ):
        _authorize(changed_purpose, grant)

    with pytest.raises(NetworkAccessDenied, match="network_grant_is_expired"):
        _authorize(
            request,
            grant,
            now="2026-07-27T10:16:00+00:00",
        )
    with pytest.raises(NetworkAccessDenied, match="network_grant_is_revoked"):
        _authorize(
            request,
            replace(grant, revoked_at="2026-07-27T10:04:00+00:00"),
        )
    with pytest.raises(NetworkAccessDenied, match="network_grant_requires_expiry"):
        _authorize(request, replace(grant, expires_at=None))


@pytest.mark.parametrize(
    "address",
    (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "::ffff:127.0.0.1",
    ),
)
def test_ssrf_destinations_and_metadata_ranges_are_denied(address):
    request = _request()

    with pytest.raises(
        NetworkAccessDenied,
        match="network_resolution_contains_non_public_address",
    ):
        _authorize(request, _grant(request), resolved_addresses=(address,))


def test_dns_resolution_is_pinned_and_connected_peer_must_match():
    request = _request()
    ticket = _authorize(
        request,
        _grant(request),
        resolved_addresses=("8.8.8.8",),
    )

    receipt = ticket.validate_connected_peer(
        "8.8.8.8",
        now="2026-07-27T10:06:00+00:00",
    )
    assert receipt["outcome"] == "peer_validated"
    assert receipt["peer_address_sha256"] != "8.8.8.8"
    with pytest.raises(
        NetworkAccessDenied,
        match="network_peer_changed_after_resolution",
    ):
        ticket.validate_connected_peer(
            "1.1.1.1",
            now="2026-07-27T10:06:00+00:00",
        )
    with pytest.raises(NetworkAccessDenied, match="network_ticket_is_expired"):
        ticket.validate_connected_peer(
            "8.8.8.8",
            now="2026-07-27T10:16:00+00:00",
        )

    with pytest.raises(
        NetworkAccessDenied,
        match="network_dns_resolution_is_empty",
    ):
        _authorize(request, _grant(request), resolved_addresses=())
    with pytest.raises(
        NetworkAccessDenied,
        match="network_resolution_has_too_many_addresses",
    ):
        _authorize(
            request,
            _grant(request),
            resolved_addresses=("8.8.8.8" for _ in range(33)),
        )


def test_ip_literal_cannot_be_rebound_to_a_different_address():
    request = _request(url="https://8.8.8.8/")
    grant = _grant(request)

    ticket = _authorize(request, grant, resolved_addresses=("8.8.8.8",))
    assert ticket.host == "8.8.8.8"
    with pytest.raises(
        NetworkAccessDenied,
        match="network_literal_resolution_changed_target",
    ):
        _authorize(request, grant, resolved_addresses=("1.1.1.1",))


def test_redirects_require_same_origin_policy_and_full_revalidation():
    original = _request(redirect_policy="same_origin")
    grant = _grant(original)
    redirected = original.with_redirect("https://api.example.com/v2/models")

    ticket = _authorize(
        redirected,
        grant,
        redirect_from=original,
        resolved_addresses=("8.8.8.8",),
    )
    assert ticket.redirect_revalidated is True

    denied_request = _request()
    with pytest.raises(NetworkAccessDenied, match="network_redirect_is_not_allowed"):
        _authorize(
            denied_request.with_redirect("https://api.example.com/v2/models"),
            _grant(denied_request),
            redirect_from=denied_request,
        )

    escaped = original.with_redirect("https://other.example.com/v2/models")
    escaped_grant = _grant(escaped)
    with pytest.raises(NetworkAccessDenied, match="network_redirect_changed_origin"):
        _authorize(escaped, escaped_grant, redirect_from=original)

    with pytest.raises(
        NetworkAccessDenied,
        match="network_retry_requires_fresh_authorization",
    ):
        _authorize(original, grant, retry=True)
    with pytest.raises(ValueError, match="network redirect hops size is invalid"):
        replace(original, redirect_hops=5).with_redirect(
            "https://api.example.com/v3/models"
        )


def test_reviewed_proxy_is_loopback_only_allowlist_first_and_purpose_bound():
    rule = ReviewedDomainRule(
        pattern="*.example.com",
        purposes=("provider.metadata",),
        reviewed_by="operator_1",
        expires_at="2026-07-27T11:00:00+00:00",
    )
    policy = ReviewedDomainProxyPolicy(enabled=True, rules=(rule,))
    request = _request()

    ticket = _authorize(request, _grant(request), proxy_policy=policy)
    assert ticket.proxy_policy_sha256 == policy.policy_sha256
    assert policy.to_dict()["listener_host"] == "127.0.0.1"

    apex = _request(url="https://example.com/")
    with pytest.raises(
        NetworkAccessDenied,
        match="network_destination_is_not_reviewed",
    ):
        _authorize(apex, _grant(apex), proxy_policy=policy)

    wrong_purpose = _request(purpose="provider.execute")
    with pytest.raises(
        NetworkAccessDenied,
        match="network_destination_is_not_reviewed",
    ):
        _authorize(wrong_purpose, _grant(wrong_purpose), proxy_policy=policy)

    with pytest.raises(ValueError, match="global network wildcard"):
        ReviewedDomainRule(
            pattern="*",
            purposes=("provider.metadata",),
            reviewed_by="operator_1",
            expires_at="2026-07-27T11:00:00+00:00",
        )
    with pytest.raises(ValueError, match="loopback-only"):
        ReviewedDomainProxyPolicy(listener_host="0.0.0.0")
    with pytest.raises(ValueError, match="reviewed allowlist"):
        ReviewedDomainProxyPolicy(enabled=True)
    with pytest.raises(ValueError, match="duplicate patterns"):
        ReviewedDomainProxyPolicy(enabled=True, rules=(rule, rule))


def test_body_response_and_url_channels_are_bounded_and_content_addressed():
    request = _request(
        method="POST",
        request_body_bytes=32,
        request_body_sha256=SHA_A,
        max_response_bytes=128,
    )
    policy = ReviewedDomainProxyPolicy(
        max_request_body_bytes=16,
        max_response_body_bytes=64,
    )

    with pytest.raises(
        NetworkAccessDenied,
        match="network_request_body_exceeds_reviewed_limit",
    ):
        _authorize(request, _grant(request), proxy_policy=policy)

    response_only = _request(max_response_bytes=128)
    with pytest.raises(
        NetworkAccessDenied,
        match="network_response_body_exceeds_reviewed_limit",
    ):
        _authorize(response_only, _grant(response_only), proxy_policy=policy)

    with pytest.raises(ValueError, match="body sha256 must match"):
        _request(method="POST", request_body_bytes=1)
    with pytest.raises(ValueError, match="safe network methods"):
        _request(request_body_bytes=1, request_body_sha256=SHA_A)
    with pytest.raises(ValueError, match="canonical HTTPS"):
        _request(url="http://api.example.com/")
    with pytest.raises(ValueError, match="without credentials"):
        _request(url="https://user@example.com/")


def test_ticket_revalidates_actual_request_and_bounded_response_sizes():
    request = _request(
        method="POST",
        request_body_bytes=32,
        request_body_sha256=SHA_A,
        max_response_bytes=128,
    )
    ticket = _authorize(request, _grant(request))

    assert (
        ticket.validate_request_body(
            body_bytes=32,
            body_sha256=SHA_A,
            now="2026-07-27T10:06:00+00:00",
        )["outcome"]
        == "request_body_validated"
    )
    assert ticket.validate_response_body(body_bytes=128)["outcome"] == (
        "response_body_validated"
    )
    with pytest.raises(
        NetworkAccessDenied,
        match="network_request_body_changed_after_review",
    ):
        ticket.validate_request_body(
            body_bytes=31,
            body_sha256=SHA_A,
            now="2026-07-27T10:06:00+00:00",
        )
    with pytest.raises(
        NetworkAccessDenied,
        match="network_response_body_exceeds_reviewed_limit",
    ):
        ticket.validate_response_body(body_bytes=129)
    with pytest.raises(
        NetworkAccessDenied,
        match="network_response_body_size_is_invalid",
    ):
        ticket.validate_response_body(body_bytes=1.5)


def test_manifest_and_receipt_do_not_claim_live_or_blanket_internet_access():
    request = _request()
    ticket = _authorize(request, _grant(request))
    receipt = ticket.audit_receipt()
    manifest = network_access_manifest()

    assert manifest["default_sandbox_network_access"] == "deny"
    assert manifest["blanket_internet_switch"] is False
    assert manifest["live_network_side_effect"] is False
    assert manifest["reviewed_proxy"]["global_wildcard_allowed"] is False
    assert receipt["peer_validation_required"] is True
    assert receipt["address_count"] == 2
    assert "8.8.8.8" not in str(receipt)
    assert "/v1/models" not in str(receipt)
