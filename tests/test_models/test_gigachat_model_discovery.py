from datetime import datetime, timezone

import pytest

from gpt2giga.models.catalog import CatalogSource, ModelDiscoveryContext
from gpt2giga.providers.gigachat.model_discovery import (
    GigaChatModelDiscovery,
    GigaChatModelDiscoveryError,
)

_DIGEST = "sha256:" + "a" * 64
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class FakeModelsResponse:
    def __init__(self, data):
        self.data = data


class FakeGigaChat:
    def __init__(self, models):
        self.models = models
        self.calls = 0

    async def aget_models(self):
        self.calls += 1
        return FakeModelsResponse(self.models)


def _context() -> ModelDiscoveryContext:
    return ModelDiscoveryContext(
        provider_profile_id="gigachat-primary",
        credential_scope_digest=_DIGEST,
    )


async def test_discovery_uses_authenticated_client_and_preserves_safe_extensions():
    client = FakeGigaChat(
        [
            {
                "id": "GigaChat-3-Pro",
                "object": "model",
                "owned_by": "sber",
                "type": "chat",
                "context_window": 128_000,
                "capabilities": {"vision": True, "access_token": "secret"},
                "x_headers": {"authorization": "Bearer secret"},
            },
            {
                "id": "Embeddings-2",
                "object": "model",
                "owned_by": "sber",
                "type": "embedder",
                "future_extension": ["one", {"nested": 2}],
            },
        ]
    )
    discovery = GigaChatModelDiscovery(ttl_seconds=15, clock=lambda: _NOW)

    snapshot = await discovery.discover(client, _context())

    assert client.calls == 1
    assert snapshot.source is CatalogSource.PROVIDER_API
    assert snapshot.expires_at.timestamp() - snapshot.discovered_at.timestamp() == 15
    assert [model.id for model in snapshot.models] == [
        "GigaChat-3-Pro",
        "Embeddings-2",
    ]
    assert snapshot.models[0].provider_metadata == {
        "object": "model",
        "context_window": 128_000,
        "capabilities": {"vision": True},
    }
    assert snapshot.models[1].provider_metadata["future_extension"] == [
        "one",
        {"nested": 2},
    ]
    assert "secret" not in snapshot.model_dump_json()


async def test_inventory_revision_is_stable_across_provider_order_and_time():
    first = GigaChatModelDiscovery(clock=lambda: _NOW)
    later = GigaChatModelDiscovery(
        clock=lambda: datetime(2026, 8, 3, 13, 0, tzinfo=timezone.utc)
    )
    models = [
        {"id": "GigaChat-3-Pro", "object": "model", "owned_by": "sber"},
        {"id": "Embeddings-2", "object": "model", "owned_by": "sber"},
    ]

    first_snapshot = await first.discover(FakeGigaChat(models), _context())
    later_snapshot = await later.discover(
        FakeGigaChat(list(reversed(models))),
        _context(),
    )

    assert first_snapshot.inventory_revision == later_snapshot.inventory_revision
    assert first_snapshot.discovered_at != later_snapshot.discovered_at


async def test_discovery_keeps_an_empty_inventory_honest():
    snapshot = await GigaChatModelDiscovery(clock=lambda: _NOW).discover(
        FakeGigaChat([]),
        _context(),
    )

    assert snapshot.models == ()


@pytest.mark.parametrize(
    "models",
    [
        [{"object": "model", "owned_by": "sber"}],
        [
            {"id": "duplicate", "object": "model", "owned_by": "sber"},
            {"id": "duplicate", "object": "model", "owned_by": "sber"},
        ],
    ],
)
async def test_discovery_rejects_malformed_or_ambiguous_inventory(models):
    with pytest.raises(GigaChatModelDiscoveryError):
        await GigaChatModelDiscovery(clock=lambda: _NOW).discover(
            FakeGigaChat(models),
            _context(),
        )
