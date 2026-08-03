from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from gpt2giga.models.catalog import (
    MODEL_CATALOG_SCHEMA_VERSION,
    CatalogSource,
    ModelCatalogSnapshot,
    ModelDescriptor,
    ModelDiscoveryContext,
)

_DIGEST = "sha256:" + "a" * 64
_REVISION = "sha256:" + "b" * 64


def _descriptor(*, stale: bool = False) -> ModelDescriptor:
    return ModelDescriptor(
        id="GigaChat-3-Pro",
        provider_kind="gigachat",
        provider_profile_id="gigachat-primary",
        owned_by="sber",
        discovered_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        stale=stale,
        inventory_revision=_REVISION,
        provider_metadata={"object": "model", "context_window": 128_000},
    )


def test_catalog_contracts_are_frozen_and_serialize_required_fields():
    discovered_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    context = ModelDiscoveryContext(
        provider_profile_id="gigachat-primary",
        credential_scope_digest=_DIGEST,
    )
    snapshot = ModelCatalogSnapshot(
        provider_profile_id=context.provider_profile_id,
        credential_scope_digest=context.credential_scope_digest,
        models=(_descriptor(),),
        inventory_revision=_REVISION,
        discovered_at=discovered_at,
        expires_at=discovered_at + timedelta(seconds=30),
        source=CatalogSource.PROVIDER_API,
    )

    assert snapshot.schema_version == MODEL_CATALOG_SCHEMA_VERSION
    assert snapshot.model_dump(mode="json")["models"][0]["id"] == "GigaChat-3-Pro"
    with pytest.raises(ValidationError):
        snapshot.stale = True
    with pytest.raises(ValidationError):
        snapshot.models[0].available = False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("credential_scope_digest", "raw-credential-value"),
        ("inventory_revision", "not-a-revision"),
    ],
)
def test_snapshot_rejects_non_digest_scope_and_revision(field: str, value: str):
    discovered_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    values = {
        "provider_profile_id": "gigachat-primary",
        "credential_scope_digest": _DIGEST,
        "models": (_descriptor(),),
        "inventory_revision": _REVISION,
        "discovered_at": discovered_at,
        "expires_at": discovered_at + timedelta(seconds=30),
        "source": CatalogSource.PROVIDER_API,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        ModelCatalogSnapshot(**values)


def test_snapshot_rejects_mismatched_model_identity_and_stale_state():
    discovered_at = datetime(2026, 8, 3, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="snapshot stale state"):
        ModelCatalogSnapshot(
            provider_profile_id="gigachat-primary",
            credential_scope_digest=_DIGEST,
            models=(_descriptor(stale=True),),
            inventory_revision=_REVISION,
            discovered_at=discovered_at,
            expires_at=discovered_at + timedelta(seconds=30),
            source=CatalogSource.PROVIDER_API,
        )


def test_snapshot_requires_timezone_aware_bounded_lifetime():
    discovered_at = datetime(2026, 8, 3, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="must not precede"):
        ModelCatalogSnapshot(
            provider_profile_id="gigachat-primary",
            credential_scope_digest=_DIGEST,
            models=(_descriptor(),),
            inventory_revision=_REVISION,
            discovered_at=discovered_at,
            expires_at=discovered_at - timedelta(seconds=1),
            source=CatalogSource.PROVIDER_API,
        )
