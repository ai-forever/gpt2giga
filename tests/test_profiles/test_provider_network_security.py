"""Security contracts for request-scoped provider network authorization."""

from __future__ import annotations

from dataclasses import dataclass
import json

from pydantic import ValidationError
import pytest

from gpt2giga.providers.network import (
    ProviderNetworkAuthorizationError,
    ProviderNetworkAuthorizer,
)
from gpt2giga.providers.profiles import ProviderProfile


@dataclass(frozen=True)
class _Intent:
    url: str = "https://api.example.com/v1/messages"
    method: str = "POST"
    purpose: str = "provider.fixture.messages"
    request_body_bytes: int = 17
    request_body_sha256: str | None = "a" * 64
    max_response_bytes: int = 1024


def _profile(**overrides: object) -> ProviderProfile:
    payload: dict[str, object] = {
        "profile_id": "fixture-provider",
        "provider_kind": "anthropic",
        "base_url": "https://api.example.com/v1",
        "credential_env": "FIXTURE_API_KEY",
        "network_policy_ref": "public-fixture",
        "tls_policy_ref": "system-default",
        "models": [
            {
                "public_alias": "fixture/model",
                "upstream_model": "exact-model",
                "capability_profile": "fixture-v1",
                "support_status": "technical_preview",
            }
        ],
    }
    payload.update(overrides)
    return ProviderProfile.model_validate(payload)


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "::",
        "::1",
        "fe80::1",
    ],
)
def test_production_authorization_rejects_non_public_dns_results(address: str) -> None:
    authorizer = ProviderNetworkAuthorizer(
        _profile(),
        resolver=lambda _host, _port: [address],
    )

    with pytest.raises(ProviderNetworkAuthorizationError) as raised:
        authorizer(_Intent())

    assert raised.value.code == "destination_mismatch"
    assert address not in str(raised.value)


def test_ticket_binds_exact_destination_body_peer_and_expiry() -> None:
    now = [100.0]
    authorizer = ProviderNetworkAuthorizer(
        _profile(),
        resolver=lambda host, port: ["93.184.216.34"],
        clock=lambda: now[0],
        ticket_ttl_seconds=5.0,
    )

    ticket = authorizer(_Intent())
    assert ticket.peer_validation_required is True
    assert ticket.host == "api.example.com"
    assert ticket.port == 443
    ticket.validate_request_body(body_bytes=17, body_sha256="a" * 64)
    ticket.validate_connected_peer("93.184.216.34")
    ticket.validate_response_body(body_bytes=1024)

    with pytest.raises(ProviderNetworkAuthorizationError) as peer_error:
        ticket.validate_connected_peer("93.184.216.35")
    assert peer_error.value.code == "destination_mismatch"

    with pytest.raises(ProviderNetworkAuthorizationError) as body_error:
        ticket.validate_request_body(body_bytes=18, body_sha256="a" * 64)
    assert body_error.value.code == "request_mismatch"

    now[0] = 106.0
    with pytest.raises(ProviderNetworkAuthorizationError) as expired:
        ticket.validate_connected_peer("93.184.216.34")
    assert expired.value.code == "destination_mismatch"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1/messages",
        "https://alternate.example.com/v1/messages",
        "https://api.example.com:444/v1/messages",
        "https://api.example.com/v1-escape/messages",
        "https://user:password@api.example.com/v1/messages",
        "https://api.example.com/v1/messages#fragment",
    ],
)
def test_authorizer_rejects_transport_and_base_path_overrides(url: str) -> None:
    calls = []

    def resolver(host: str, port: int) -> list[str]:
        calls.append((host, port))
        return ["93.184.216.34"]

    authorizer = ProviderNetworkAuthorizer(_profile(), resolver=resolver)
    with pytest.raises(ProviderNetworkAuthorizationError) as raised:
        authorizer(_Intent(url=url))

    assert raised.value.code == "destination_mismatch"
    assert calls == []


def test_loopback_development_ticket_cannot_rebind_to_public_or_private_lan() -> None:
    profile = _profile(
        base_url="http://127.0.0.1:8080/v1",
        allow_loopback=True,
        network_policy_ref="loopback-development",
    )
    public = ProviderNetworkAuthorizer(
        profile,
        resolver=lambda _host, _port: ["93.184.216.34"],
    )
    private = ProviderNetworkAuthorizer(
        profile,
        resolver=lambda _host, _port: ["192.168.1.2"],
    )
    loopback = ProviderNetworkAuthorizer(
        profile,
        resolver=lambda _host, _port: ["127.0.0.1", "::1"],
    )

    intent = _Intent(url="http://127.0.0.1:8080/v1/messages")
    for authorizer in (public, private):
        with pytest.raises(ProviderNetworkAuthorizationError):
            authorizer(intent)
    assert loopback(intent).addresses == frozenset({"127.0.0.1", "::1"})


@pytest.mark.parametrize("field", ["api_key", "authorization", "headers", "token"])
def test_profile_schema_has_no_arbitrary_auth_or_header_override(field: str) -> None:
    payload = _profile().model_dump(mode="json")
    payload[field] = "fixture-secret"

    with pytest.raises(ValidationError):
        ProviderProfile.model_validate(payload)
    assert "fixture-secret" not in json.dumps(_profile().model_dump(mode="json"))
