"""Tests for shared tool, policy, and secret-reference contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

from gpt2giga.harness.sessions.redaction import redact_for_storage
from gpt2giga.harness.runtime.policy import PolicyDecision as HarnessPolicyDecision
from gpt2giga.tools import (
    CompositeSecretResolver,
    EnvironmentSecretResolver,
    PolicyDecision,
    ResolvedSecret,
    SecretReference,
    SecretReferenceKind,
    SecretResolutionError,
    SecretResolutionErrorCode,
    ToolDescriptor,
    ToolExecutionPolicy,
    ToolProvider,
    ToolRisk,
    secret_reference_to_dict,
)


@dataclass(frozen=True)
class FakeProvider:
    id: str = "fake"

    def list_tools(self) -> tuple[ToolDescriptor, ...]:
        return (
            ToolDescriptor(
                id="fake.read",
                provider_id=self.id,
                title="Read",
                risk=ToolRisk.LOW,
            ),
        )


class FakeKeychainResolver:
    def supports(self, kind: SecretReferenceKind) -> bool:
        return kind is SecretReferenceKind.KEYCHAIN

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        if not owner:
            raise ValueError("owner required")
        return ResolvedSecret(reference, "fake-keychain-value", owner=owner)


def test_tool_provider_and_descriptor_contract() -> None:
    provider = FakeProvider()

    assert isinstance(provider, ToolProvider)
    assert provider.list_tools()[0].provider_id == "fake"
    with pytest.raises(ValueError, match="id must not be empty"):
        ToolDescriptor(id="", provider_id="fake", title="Bad")


def test_tool_policy_prefers_tool_then_risk_then_default() -> None:
    policy = ToolExecutionPolicy(
        id="project",
        tool_rules={"danger.delete": PolicyDecision.DENY},
        risk_rules={ToolRisk.HIGH: PolicyDecision.ASK},
        default=PolicyDecision.ALLOW,
    )

    denied = policy.resolve(
        ToolDescriptor(
            id="danger.delete",
            provider_id="fake",
            title="Delete",
            risk=ToolRisk.HIGH,
        )
    )
    asked = policy.resolve(
        ToolDescriptor(
            id="danger.other",
            provider_id="fake",
            title="Other",
            risk=ToolRisk.HIGH,
        )
    )
    allowed = policy.resolve(
        ToolDescriptor(id="safe.read", provider_id="fake", title="Read")
    )

    assert (denied.decision, denied.source) == (
        PolicyDecision.DENY,
        "tool:danger.delete",
    )
    assert (asked.decision, asked.source) == (PolicyDecision.ASK, "risk:high")
    assert (allowed.decision, allowed.source) == (PolicyDecision.ALLOW, "default")
    assert HarnessPolicyDecision is PolicyDecision


def test_environment_secret_resolution_requires_named_boundary_and_is_opaque() -> None:
    reference = SecretReference(
        kind=SecretReferenceKind.ENVIRONMENT,
        name="EXAMPLE_TOKEN",
    )
    resolver = EnvironmentSecretResolver(
        {"EXAMPLE_TOKEN": "do-not-persist-this-value"},
        allowed_names=frozenset({"EXAMPLE_TOKEN"}),
    )

    with pytest.raises(ValueError, match="owning boundary"):
        resolver.resolve(reference, owner="")
    resolved = resolver.resolve(reference, owner="mcp:example")

    with pytest.raises(ValueError, match="does not match"):
        resolved.reveal_for("request:other")
    assert resolved.reveal_for("mcp:example") == "do-not-persist-this-value"
    assert str(resolved) == "<redacted>"
    assert "do-not-persist-this-value" not in repr(resolved)
    assert redact_for_storage({"result": resolved}) == {"result": "<redacted>"}
    assert "do-not-persist-this-value" not in json.dumps(
        redact_for_storage({"result": resolved})
    )


@pytest.mark.parametrize(
    ("resolver", "reference", "code"),
    (
        (
            EnvironmentSecretResolver({}, allowed_names=frozenset({"MISSING"})),
            SecretReference(SecretReferenceKind.ENVIRONMENT, "MISSING"),
            SecretResolutionErrorCode.MISSING,
        ),
        (
            EnvironmentSecretResolver({"DENIED": "hidden"}, allowed_names=frozenset()),
            SecretReference(SecretReferenceKind.ENVIRONMENT, "DENIED"),
            SecretResolutionErrorCode.DENIED,
        ),
        (
            EnvironmentSecretResolver({"OLD": "hidden"}),
            SecretReference(
                SecretReferenceKind.ENVIRONMENT,
                "OLD",
                expires_at="2000-01-01T00:00:00Z",
            ),
            SecretResolutionErrorCode.EXPIRED,
        ),
    ),
)
def test_environment_secret_failures_are_typed(
    resolver: EnvironmentSecretResolver,
    reference: SecretReference,
    code: SecretResolutionErrorCode,
) -> None:
    with pytest.raises(SecretResolutionError) as raised:
        resolver.resolve(reference, owner="request:test")

    assert raised.value.code is code
    assert "hidden" not in str(raised.value)


def test_keychain_requires_an_installed_available_resolver() -> None:
    reference = SecretReference(
        SecretReferenceKind.KEYCHAIN,
        "github-token",
        service="gpt2giga",
        account="octocat",
    )
    resolver = CompositeSecretResolver((EnvironmentSecretResolver({}),))

    assert resolver.supports(SecretReferenceKind.KEYCHAIN) is False
    with pytest.raises(SecretResolutionError) as raised:
        resolver.resolve(reference, owner="mcp:github")
    assert raised.value.code is SecretResolutionErrorCode.UNAVAILABLE

    fake_resolver = CompositeSecretResolver((FakeKeychainResolver(),))
    assert fake_resolver.supports(SecretReferenceKind.KEYCHAIN) is True
    assert (
        fake_resolver.resolve(reference, owner="mcp:github").reveal_for("mcp:github")
        == "fake-keychain-value"
    )


def test_reference_serialization_contains_only_pointer_metadata() -> None:
    reference = SecretReference(
        SecretReferenceKind.KEYCHAIN,
        "github-token",
        service="gpt2giga",
        account="octocat",
        expires_at="2099-01-01T00:00:00+00:00",
    )

    payload = secret_reference_to_dict(reference)

    assert payload == {
        "kind": "keychain",
        "name": "github-token",
        "service": "gpt2giga",
        "account": "octocat",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    assert "value" not in json.dumps(payload)
