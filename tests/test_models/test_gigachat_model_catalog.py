import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from gpt2giga.models.catalog import (
    CatalogSource,
    ModelCatalogSnapshot,
    ModelDescriptor,
    ModelDiscoveryContext,
)
from gpt2giga.providers.gigachat.model_catalog import (
    CredentialScopeDigester,
    GigaChatModelCatalog,
    ModelCatalogBoundsError,
)

_REVISION = "sha256:" + "b" * 64
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self):
        self.now = _NOW

    def __call__(self):
        return self.now


class FakeClient:
    def __init__(
        self,
        *,
        credentials: str | None = "credential-a",
        scope: str = "scope-a",
        model: str | None = None,
    ):
        self._settings = SimpleNamespace(
            credentials=credentials,
            scope=scope,
            user=None,
            password=None,
            access_token=None,
            model=model,
        )


class FakeDiscovery:
    def __init__(self, clock: MutableClock):
        self.clock = clock
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.error: Exception | None = None
        self.model_count = 1
        self.metadata: dict = {}

    async def discover(self, client, context: ModelDiscoveryContext):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        models = tuple(
            ModelDescriptor(
                id=f"model-{index}",
                provider_kind="gigachat",
                provider_profile_id=context.provider_profile_id,
                discovered_at=self.clock(),
                inventory_revision=_REVISION,
                provider_metadata=self.metadata,
            )
            for index in range(self.model_count)
        )
        return ModelCatalogSnapshot(
            provider_profile_id=context.provider_profile_id,
            credential_scope_digest=context.credential_scope_digest,
            models=models,
            inventory_revision=_REVISION,
            discovered_at=self.clock(),
            expires_at=self.clock() + timedelta(seconds=10),
            source=CatalogSource.PROVIDER_API,
        )


def _catalog(discovery: FakeDiscovery, clock: MutableClock, **kwargs):
    return GigaChatModelCatalog(
        discovery=discovery,
        scope_digester=CredentialScopeDigester(salt=b"s" * 32),
        clock=clock,
        **kwargs,
    )


async def test_cache_is_single_flight_and_refresh_is_explicit():
    clock = MutableClock()
    discovery = FakeDiscovery(clock)
    catalog = _catalog(discovery, clock)
    client = FakeClient()

    first = asyncio.create_task(catalog.list_models(client))
    second = asyncio.create_task(catalog.list_models(client))
    await discovery.started.wait()
    assert discovery.calls == 1
    discovery.release.set()

    first_snapshot, second_snapshot = await asyncio.gather(first, second)
    assert first_snapshot is second_snapshot
    assert await catalog.list_models(client) is first_snapshot

    discovery.started.clear()
    discovery.release.clear()
    explicit_refresh = asyncio.create_task(catalog.refresh(client))
    await discovery.started.wait()
    assert discovery.calls == 2
    discovery.release.set()
    await explicit_refresh


async def test_cache_isolated_by_credential_scope_and_not_configured_model():
    clock = MutableClock()
    discovery = FakeDiscovery(clock)
    discovery.release.set()
    catalog = _catalog(discovery, clock)

    first = FakeClient(credentials="credential-a", scope="scope-a", model="first")
    same_scope = FakeClient(
        credentials="credential-a",
        scope="scope-a",
        model="another-default",
    )
    another_scope = FakeClient(credentials="credential-a", scope="scope-b")
    another_credential = FakeClient(credentials="credential-b", scope="scope-a")

    first_snapshot = await catalog.list_models(first)
    assert await catalog.list_models(same_scope) is first_snapshot
    await catalog.list_models(another_scope)
    await catalog.list_models(another_credential)

    assert discovery.calls == 3
    serialized = first_snapshot.model_dump_json()
    assert "credential-a" not in serialized
    assert "scope-a" not in serialized


async def test_cache_evicts_oldest_credential_scope_at_bound():
    clock = MutableClock()
    discovery = FakeDiscovery(clock)
    discovery.release.set()
    catalog = _catalog(discovery, clock, max_scopes=1)
    first = FakeClient(credentials="credential-a")
    second = FakeClient(credentials="credential-b")

    await catalog.list_models(first)
    await catalog.list_models(second)
    await catalog.list_models(first)

    assert discovery.calls == 3


async def test_expired_refresh_failure_returns_explicit_stale_snapshot():
    clock = MutableClock()
    discovery = FakeDiscovery(clock)
    discovery.release.set()
    catalog = _catalog(discovery, clock)
    client = FakeClient()
    fresh = await catalog.list_models(client)

    clock.now += timedelta(seconds=11)
    discovery.error = RuntimeError("provider unavailable")
    stale = await catalog.list_models(client)

    assert fresh.stale is False
    assert stale.stale is True
    assert stale.source is CatalogSource.STALE_CACHE
    assert all(model.stale for model in stale.models)
    assert discovery.calls == 2


async def test_initial_discovery_failure_does_not_fabricate_a_model():
    clock = MutableClock()
    discovery = FakeDiscovery(clock)
    discovery.error = RuntimeError("provider unavailable")
    discovery.release.set()
    catalog = _catalog(discovery, clock)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await catalog.list_models(FakeClient())


@pytest.mark.parametrize(
    ("model_count", "metadata", "kwargs"),
    [
        (2, {}, {"max_models": 1}),
        (1, {"large": "x" * 2_000}, {"max_payload_bytes": 1_000}),
    ],
)
async def test_cache_rejects_inventory_outside_bounds(
    model_count,
    metadata,
    kwargs,
):
    clock = MutableClock()
    discovery = FakeDiscovery(clock)
    discovery.model_count = model_count
    discovery.metadata = metadata
    discovery.release.set()
    catalog = _catalog(discovery, clock, **kwargs)

    with pytest.raises(ModelCatalogBoundsError):
        await catalog.list_models(FakeClient())


def test_scope_digest_is_non_reversible_and_profile_scoped():
    digester = CredentialScopeDigester(salt=b"s" * 32)
    client = FakeClient(credentials="credential-a", scope="scope-a")

    first = digester.digest(client, provider_profile_id="profile-a")
    repeated = digester.digest(client, provider_profile_id="profile-a")
    another_profile = digester.digest(client, provider_profile_id="profile-b")

    assert first == repeated
    assert first != another_profile
    assert first.startswith("sha256:")
    assert "credential-a" not in first
    assert "scope-a" not in first
