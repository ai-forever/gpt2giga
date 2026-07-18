"""Tests for provider-neutral backend secret resolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging

import pytest

from gpt2giga_harness.secrets import (
    CompositeSecretResolver,
    EnvironmentSecretResolver,
    KeychainSecretResolver,
    MemorySecretResolver,
    SecretReference,
    SecretReferenceKind,
    SecretResolutionError,
    SecretResolutionErrorCode,
    SecretResolutionService,
    SecretResolutionState,
    secret_reference_from_dict,
    secret_reference_to_dict,
    secret_resolution_evidence_to_dict,
)
from gpt2giga_harness.sessions.redaction import redact_for_storage


class _Clock:
    def __init__(self) -> None:
        self.monotonic = 100.0
        self.now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self.monotonic += seconds
        self.now += timedelta(seconds=seconds)


class _KeychainReader:
    def __init__(
        self, value: str | None = None, error: Exception | None = None
    ) -> None:
        self.value = value
        self.error = error

    def read(self, reference: SecretReference) -> str | None:
        if self.error is not None:
            raise self.error
        return self.value


def test_reference_schema_reads_legacy_and_round_trips_versioned_metadata() -> None:
    legacy = {
        "kind": "environment",
        "name": "PROVIDER_TOKEN",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    reference = secret_reference_from_dict(legacy)
    payload = secret_reference_to_dict(reference)

    assert payload == {
        "schema_version": 1,
        "kind": "environment",
        "name": "PROVIDER_TOKEN",
        "service": None,
        "account": None,
        "expires_at": "2099-01-01T00:00:00Z",
        "cache_ttl_seconds": 0,
    }
    assert secret_reference_from_dict(payload) == reference
    assert "value" not in json.dumps(payload)


@pytest.mark.parametrize(
    "payload",
    (
        {"kind": "environment", "name": "bad-name"},
        {"kind": "environment", "name": "TOKEN", "value": "plaintext"},
        {"kind": "test", "name": "TOKEN", "cache_ttl_seconds": 301},
        {"schema_version": 2, "kind": "environment", "name": "TOKEN"},
    ),
)
def test_reference_schema_rejects_invalid_or_value_bearing_sources(payload) -> None:
    with pytest.raises(ValueError):
        secret_reference_from_dict(payload)


def test_resolution_is_owner_bound_and_all_public_evidence_is_content_free(
    caplog,
) -> None:
    canary = "n1-02-secret-canary-value"
    reference = SecretReference(SecretReferenceKind.ENVIRONMENT, "PROVIDER_TOKEN")
    service = SecretResolutionService(
        EnvironmentSecretResolver({"PROVIDER_TOKEN": canary})
    )

    resolved = service.resolve(reference, owner="provider-spawn:test")
    with pytest.raises(ValueError, match="does not match"):
        resolved.reveal_for("other-owner")
    assert resolved.reveal_for("provider-spawn:test") == canary

    caplog.set_level(logging.INFO)
    logging.getLogger(__name__).info("resolved=%s", resolved)
    public_outputs = (
        str(resolved),
        repr(resolved),
        json.dumps(secret_reference_to_dict(reference), sort_keys=True),
        json.dumps(
            secret_resolution_evidence_to_dict(resolved.evidence), sort_keys=True
        ),
        json.dumps(redact_for_storage({"resolved": resolved}), sort_keys=True),
        caplog.text,
    )
    assert resolved.evidence.state is SecretResolutionState.RESOLVED
    assert resolved.evidence.reference_id == reference.identity
    assert resolved.evidence.backend_id == "environment"
    assert resolved.evidence.provenance is not None
    assert resolved.evidence.provenance.backend_id == "environment"
    assert all(canary not in output for output in public_outputs)
    assert redact_for_storage({"resolved": resolved}) == {"resolved": "<redacted>"}


def test_cache_is_owner_scoped_bounded_and_rotation_invalidates() -> None:
    clock = _Clock()
    backend = MemorySecretResolver({"TOKEN": "first-value"})
    reference = SecretReference(
        SecretReferenceKind.TEST,
        "TOKEN",
        cache_ttl_seconds=10,
    )
    service = SecretResolutionService(
        CompositeSecretResolver((backend,)),
        monotonic=lambda: clock.monotonic,
        now=lambda: clock.now,
    )

    first = service.resolve(reference, owner="provider:one")
    backend.set("TOKEN", "second-value")
    cached = service.resolve(reference, owner="provider:one")
    separate_owner = service.resolve(reference, owner="provider:two")

    assert first.reveal_for("provider:one") == "first-value"
    assert cached.reveal_for("provider:one") == "first-value"
    assert cached.evidence.cache_hit is True
    assert separate_owner.reveal_for("provider:two") == "second-value"
    assert service.rotate(reference, owner="provider:one") == 1
    rotated = service.resolve(reference, owner="provider:one")
    assert rotated.reveal_for("provider:one") == "second-value"
    assert rotated.evidence.cache_hit is False

    backend.set("TOKEN", "third-value")
    clock.advance(11)
    expired = service.resolve(reference, owner="provider:one")
    assert expired.reveal_for("provider:one") == "third-value"


def test_unavailable_missing_denied_expired_and_keychain_states_are_safe() -> None:
    environment = SecretReference(SecretReferenceKind.ENVIRONMENT, "TOKEN")
    unavailable_keychain = SecretReference(
        SecretReferenceKind.KEYCHAIN,
        "provider-token",
        service="agent-workbench",
    )
    expired = SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        "OLD_TOKEN",
        expires_at="2000-01-01T00:00:00Z",
    )
    cases = (
        (
            SecretResolutionService(CompositeSecretResolver()),
            unavailable_keychain,
            SecretResolutionErrorCode.UNAVAILABLE,
        ),
        (
            SecretResolutionService(EnvironmentSecretResolver({})),
            environment,
            SecretResolutionErrorCode.MISSING,
        ),
        (
            SecretResolutionService(
                EnvironmentSecretResolver(
                    {"TOKEN": "must-not-leak"}, allowed_names=frozenset()
                )
            ),
            environment,
            SecretResolutionErrorCode.DENIED,
        ),
        (
            SecretResolutionService(EnvironmentSecretResolver({"OLD_TOKEN": "old"})),
            expired,
            SecretResolutionErrorCode.EXPIRED,
        ),
    )

    for service, reference, expected_code in cases:
        with pytest.raises(SecretResolutionError) as raised:
            service.resolve(reference, owner="provider:test")
        assert raised.value.code is expected_code
        serialized = json.dumps(redact_for_storage(raised.value), sort_keys=True)
        assert "must-not-leak" not in serialized
        assert "old" not in serialized
        assert raised.value.evidence is not None

    optional_keychain = KeychainSecretResolver()
    assert optional_keychain.supports(SecretReferenceKind.KEYCHAIN) is False
    injected = KeychainSecretResolver(_KeychainReader("keychain-canary"))
    resolved = injected.resolve(unavailable_keychain, owner="provider:test")
    assert resolved.reveal_for("provider:test") == "keychain-canary"
    denied = KeychainSecretResolver(_KeychainReader(error=PermissionError("raw")))
    with pytest.raises(SecretResolutionError) as raised:
        denied.resolve(unavailable_keychain, owner="provider:test")
    assert raised.value.code is SecretResolutionErrorCode.DENIED
    assert "raw" not in str(raised.value)


def test_inspection_never_reads_the_source() -> None:
    reference = SecretReference(SecretReferenceKind.KEYCHAIN, "token", service="app")
    reader = _KeychainReader(error=AssertionError("must not read"))
    service = SecretResolutionService(KeychainSecretResolver(reader))

    evidence = service.inspect(reference)

    assert evidence.state is SecretResolutionState.AVAILABLE
    assert evidence.backend_id is None
