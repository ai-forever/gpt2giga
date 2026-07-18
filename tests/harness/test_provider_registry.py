from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import stat

import pytest

from gpt2giga_harness.provider_profiles import (
    ModelPurposeDefault,
    ProviderOwnership,
    migrate_legacy_provider_route,
)
from gpt2giga_harness.provider_registry import (
    LayeredProviderRegistry,
    ProviderAuthenticationFailure,
    ProviderCompatibilityFailure,
    ProviderDiscoveryStatus,
    ProviderFailureKind,
    ProviderHealthFailure,
    ProviderHealthService,
    ProviderHealthStatus,
    ProviderHealthStore,
    ProviderModelSource,
    ProviderNetworkPolicyDecision,
    ProviderProbeResponse,
    ProviderRegistryConflict,
    ProviderRegistryEntry,
    ProviderRegistryOwnershipError,
    ProviderRegistryStore,
    ProviderTransportFailure,
)


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
TIMESTAMP = "2026-07-18T12:00:00Z"


def test_registry_crud_is_private_reference_only_and_round_trips(tmp_path):
    profile, route = _profile_route(ownership=ProviderOwnership.USER)
    store = ProviderRegistryStore(tmp_path, ProviderOwnership.USER, now=lambda: NOW)

    created = store.create(profile, routes=(route,))

    assert store.get(profile.id) == created
    assert store.list() == (created,)
    assert created.revision == 1
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["ownership"] == "user"
    assert (
        payload["providers"][0]["profile"]["authentication"]["secret_reference"]["name"]
        == "GPT2GIGA_HARNESS_API_KEY"
    )
    assert "secret-value-canary" not in serialized
    assert "api_key" not in serialized
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

    replacement = replace(profile, revision="profile-r2", display_name="Updated")
    replacement_route = replace(
        route,
        revision="route-r2",
        provider=replacement.ref,
    )
    updated = store.replace(
        replacement,
        routes=(replacement_route,),
        enabled=False,
        expected_revision=created.revision,
    )

    assert updated.revision == 2
    assert updated.profile.display_name == "Updated"
    assert updated.enabled is False
    store.delete(profile.id, expected_revision=updated.revision)
    assert store.list() == ()


def test_registry_stale_writes_and_foreign_ownership_fail_closed(tmp_path):
    profile, route = _profile_route(ownership=ProviderOwnership.PROJECT)
    store = ProviderRegistryStore(tmp_path, ProviderOwnership.PROJECT, now=lambda: NOW)
    created = store.create(profile, routes=(route,))
    disabled = store.set_enabled(
        profile.id,
        False,
        expected_revision=created.revision,
    )

    assert disabled.revision == 2
    with pytest.raises(ProviderRegistryConflict, match="revision changed"):
        store.set_enabled(profile.id, True, expected_revision=created.revision)
    with pytest.raises(ProviderRegistryConflict, match="revision changed"):
        store.delete(profile.id, expected_revision=created.revision)

    user_profile, user_route = _profile_route(ownership=ProviderOwnership.USER)
    with pytest.raises(ProviderRegistryOwnershipError, match="ownership"):
        store.create(user_profile, routes=(user_route,))


def test_changed_profile_and_route_content_require_semantic_revisions(tmp_path):
    profile, route = _profile_route(ownership=ProviderOwnership.USER)
    store = ProviderRegistryStore(tmp_path, ProviderOwnership.USER, now=lambda: NOW)
    created = store.create(profile, routes=(route,))

    with pytest.raises(ProviderRegistryConflict, match="profile revision"):
        store.replace(
            replace(profile, display_name="Changed without revision"),
            routes=(route,),
            enabled=True,
            expected_revision=created.revision,
        )
    with pytest.raises(ProviderRegistryConflict, match="route revision"):
        store.replace(
            profile,
            routes=(replace(route, model="changed-without-revision"),),
            enabled=True,
            expected_revision=created.revision,
        )


def test_registry_clone_requires_current_source_and_new_identity(tmp_path):
    source, source_route = _profile_route(ownership=ProviderOwnership.USER)
    clone, clone_route = _profile_route(
        provider_id="provider-clone",
        profile_revision="clone-r1",
        route_id="route-clone",
        ownership=ProviderOwnership.USER,
    )
    store = ProviderRegistryStore(tmp_path, ProviderOwnership.USER, now=lambda: NOW)
    created = store.create(source, routes=(source_route,))

    cloned = store.clone(
        source.id,
        clone,
        routes=(clone_route,),
        expected_source_revision=created.revision,
    )

    assert cloned.profile.id == "provider-clone"
    assert cloned.revision == 1
    assert [item.profile.id for item in store.list()] == [
        "provider-a",
        "provider-clone",
    ]
    with pytest.raises(ValueError, match="must differ"):
        store.clone(
            source.id,
            source,
            routes=(source_route,),
            expected_source_revision=created.revision,
        )
    with pytest.raises(ProviderRegistryConflict, match="revision changed"):
        store.clone(
            source.id,
            replace(clone, id="another-clone"),
            routes=(),
            expected_source_revision=99,
        )


def test_layered_registry_uses_explicit_precedence_and_disabled_shadowing():
    user = _entry(ProviderOwnership.USER, display_name="User", enabled=True)
    project = _entry(ProviderOwnership.PROJECT, display_name="Project", enabled=True)
    environment = _entry(
        ProviderOwnership.ENVIRONMENT,
        display_name="Environment",
        enabled=True,
    )
    managed = _entry(
        ProviderOwnership.MANAGED_POLICY,
        display_name="Managed",
        enabled=False,
    )

    resolved = LayeredProviderRegistry(
        {
            ProviderOwnership.USER: (user,),
            ProviderOwnership.PROJECT: (project,),
            ProviderOwnership.ENVIRONMENT: (environment,),
            ProviderOwnership.MANAGED_POLICY: (managed,),
        }
    ).get("provider-a")

    assert resolved is not None
    assert resolved.source is ProviderOwnership.MANAGED_POLICY
    assert resolved.entry.profile.display_name == "Managed"
    assert resolved.entry.enabled is False
    assert resolved.shadowed_sources == (
        ProviderOwnership.ENVIRONMENT,
        ProviderOwnership.PROJECT,
        ProviderOwnership.USER,
    )


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (
            ProviderAuthenticationFailure("credentials_rejected"),
            ProviderFailureKind.AUTHENTICATION,
        ),
        (
            ProviderCompatibilityFailure("dialect_rejected"),
            ProviderFailureKind.COMPATIBILITY,
        ),
        (ProviderHealthFailure("maintenance"), ProviderFailureKind.PROVIDER_HEALTH),
        (ProviderTransportFailure("connection_timeout"), ProviderFailureKind.TRANSPORT),
    ],
)
def test_health_failures_preserve_independent_failure_axes(tmp_path, failure, kind):
    entry = _entry(ProviderOwnership.USER)
    backend = _Backend(failure=failure)
    service = ProviderHealthService(
        backend,
        ProviderHealthStore(tmp_path),
        now=lambda: NOW,
        monotonic=_monotonic(),
    )

    result = service.check(entry, force=True)

    assert result.status is ProviderHealthStatus.UNHEALTHY
    assert result.failure_kind is kind
    assert result.reason_code == failure.reason_code
    assert result.discovery_status is ProviderDiscoveryStatus.FAILED
    assert {item.source for item in result.models} == {
        ProviderModelSource.CONFIGURED_FALLBACK
    }


def test_offline_disabled_and_unresolved_egress_block_before_backend(tmp_path):
    backend = _Backend(response=ProviderProbeResponse(models=("discovered",)))
    store = ProviderHealthStore(tmp_path)
    service = ProviderHealthService(
        backend,
        store,
        now=lambda: NOW,
        monotonic=_monotonic(),
    )
    disabled = replace(_entry(ProviderOwnership.USER), enabled=False)
    offline = _entry(ProviderOwnership.USER, provider_id="offline", offline=True)
    egress = _entry(
        ProviderOwnership.USER,
        provider_id="egress",
        egress_policy_ref="egress:restricted",
    )

    disabled_result = service.check(disabled, force=True)
    offline_result = service.check(offline, force=True)
    egress_result = service.check(egress, force=True)

    assert backend.requests == []
    assert disabled_result.reason_code == "provider_disabled"
    assert offline_result.reason_code == "offline_mode"
    assert egress_result.reason_code == "egress_policy_unresolved"
    for result in (disabled_result, offline_result, egress_result):
        assert result.status is ProviderHealthStatus.BLOCKED
        assert result.failure_kind is ProviderFailureKind.NETWORK_POLICY


def test_policy_refs_reach_backend_only_after_explicit_egress_admission(tmp_path):
    entry = _entry(
        ProviderOwnership.USER,
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca-mtls",
        egress_policy_ref="egress:provider-api",
    )
    backend = _Backend(response=ProviderProbeResponse(models=("model-discovered",)))
    evaluated = []

    def allow(request):
        evaluated.append(request)
        return ProviderNetworkPolicyDecision(True)

    service = ProviderHealthService(
        backend,
        ProviderHealthStore(tmp_path),
        network_policy=allow,
        now=lambda: NOW,
        monotonic=_monotonic(),
    )

    result = service.check(entry, timeout_seconds=3.5, force=True)

    assert result.status is ProviderHealthStatus.READY
    assert len(evaluated) == len(backend.requests) == 1
    request = backend.requests[0]
    assert request.timeout_seconds == 3.5
    assert request.proxy_policy_ref == "proxy:corp"
    assert request.tls_policy_ref == "tls:custom-ca-mtls"
    assert request.egress_policy_ref == "egress:provider-api"
    with pytest.raises(ValueError, match="bounded range"):
        service.check(entry, timeout_seconds=31, force=True)


def test_discovery_failure_keeps_configured_fallback_truthful(tmp_path):
    entry = _entry(ProviderOwnership.USER)
    backend = _Backend(
        response=ProviderProbeResponse(
            models=("must-not-be-used",),
            discovery_succeeded=False,
            discovery_reason_code="models_unavailable",
        )
    )
    service = ProviderHealthService(
        backend,
        ProviderHealthStore(tmp_path),
        now=lambda: NOW,
        monotonic=_monotonic(),
    )

    result = service.check(entry, force=True)

    assert result.status is ProviderHealthStatus.READY
    assert result.discovery_status is ProviderDiscoveryStatus.FAILED
    assert result.discovery_reason_code == "models_unavailable"
    assert [(item.model, item.source.value) for item in result.models] == [
        ("configured-model", "configured_fallback")
    ]


def test_successful_discovery_keeps_unseen_default_as_configured_fallback(tmp_path):
    entry = _entry(ProviderOwnership.USER)
    backend = _Backend(
        response=ProviderProbeResponse(models=("configured-model", "other-model"))
    )
    service = ProviderHealthService(
        backend,
        ProviderHealthStore(tmp_path),
        now=lambda: NOW,
        monotonic=_monotonic(),
    )

    result = service.check(entry, force=True)

    assert result.discovery_status is ProviderDiscoveryStatus.SUCCEEDED
    assert [(item.model, item.source.value) for item in result.models] == [
        ("configured-model", "discovered"),
        ("other-model", "discovered"),
    ]


def test_health_cache_is_ttl_and_provider_revision_bound(tmp_path):
    clock = _Clock(NOW)
    entry = _entry(ProviderOwnership.USER, cache_ttl_seconds=60)
    backend = _Backend(response=ProviderProbeResponse(models=("discovered",)))
    service = ProviderHealthService(
        backend,
        ProviderHealthStore(tmp_path),
        now=clock.now,
        monotonic=_monotonic(),
    )

    first = service.check(entry)
    clock.advance(seconds=30)
    cached = service.check(entry)
    changed_profile = replace(entry.profile, revision="profile-r2")
    changed = replace(
        entry,
        profile=changed_profile,
        routes=tuple(
            replace(route, provider=changed_profile.ref) for route in entry.routes
        ),
        revision=2,
    )
    refreshed = service.check(changed)

    assert first.cached is False
    assert cached.cached is True
    assert refreshed.cached is False
    assert refreshed.provider.revision == "profile-r2"
    assert len(backend.requests) == 2


def test_health_cache_rechecks_policy_enablement_and_discovery_intent(tmp_path):
    clock = _Clock(NOW)
    entry = _entry(ProviderOwnership.USER, cache_ttl_seconds=60)
    backend = _Backend(response=ProviderProbeResponse(models=("discovered",)))
    policy_allowed = True

    def policy(_request):
        if policy_allowed:
            return ProviderNetworkPolicyDecision(True)
        return ProviderNetworkPolicyDecision(False, "egress_revoked")

    service = ProviderHealthService(
        backend,
        ProviderHealthStore(tmp_path),
        network_policy=policy,
        now=clock.now,
        monotonic=_monotonic(),
    )

    without_discovery = service.check(entry, discover_models=False)
    with_discovery = service.check(entry, discover_models=True)
    disabled = service.check(replace(entry, enabled=False))
    policy_allowed = False
    denied = service.check(entry)

    assert without_discovery.discovery_status is ProviderDiscoveryStatus.NOT_REQUESTED
    assert with_discovery.discovery_status is ProviderDiscoveryStatus.SUCCEEDED
    assert disabled.reason_code == "provider_disabled"
    assert disabled.cached is False
    assert denied.reason_code == "egress_revoked"
    assert denied.cached is False
    assert len(backend.requests) == 2


def test_health_snapshot_is_strict_private_and_contains_no_runtime_values(tmp_path):
    entry = _entry(ProviderOwnership.USER)
    store = ProviderHealthStore(tmp_path)
    service = ProviderHealthService(
        _Backend(response=ProviderProbeResponse(models=("model-a",))),
        store,
        now=lambda: NOW,
        monotonic=_monotonic(),
    )

    result = service.check(entry, force=True)
    path = store._path(entry.profile.id)
    serialized = path.read_text(encoding="utf-8")

    assert store.load(entry.profile.id) == result
    assert "secret-value-canary" not in serialized
    assert "proxy:corp" not in serialized
    assert "tls:custom-ca-mtls" not in serialized
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


class _Backend:
    def __init__(self, *, response=None, failure=None):
        self.response = response or ProviderProbeResponse()
        self.failure = failure
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return self.response


class _Clock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value

    def advance(self, *, seconds):
        self.value += timedelta(seconds=seconds)


def _monotonic():
    values = iter(index / 100 for index in range(1000))
    return lambda: next(values)


def _entry(
    ownership,
    *,
    provider_id="provider-a",
    display_name="Provider A",
    enabled=True,
    offline=False,
    cache_ttl_seconds=0,
    proxy_policy_ref=None,
    tls_policy_ref=None,
    egress_policy_ref=None,
):
    profile, route = _profile_route(
        provider_id=provider_id,
        ownership=ownership,
        display_name=display_name,
        offline=offline,
        cache_ttl_seconds=cache_ttl_seconds,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
    )
    return ProviderRegistryEntry(
        profile=profile,
        routes=(route,),
        enabled=enabled,
        revision=1,
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )


def _profile_route(
    *,
    provider_id="provider-a",
    profile_revision="profile-r1",
    route_id="route-a",
    route_revision="route-r1",
    ownership=ProviderOwnership.USER,
    display_name="Provider A",
    offline=False,
    cache_ttl_seconds=0,
    proxy_policy_ref=None,
    tls_policy_ref=None,
    egress_policy_ref=None,
):
    legacy_profile, legacy_route = migrate_legacy_provider_route(
        proxy_url="https://provider.example/base",
        api_mode="v2",
        harness_id="direct-chat",
        model="configured-model",
    )
    profile = replace(
        legacy_profile,
        id=provider_id,
        revision=profile_revision,
        display_name=display_name,
        ownership=ownership,
        offline=offline,
        discovery_cache_ttl_seconds=cache_ttl_seconds,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        default_models=(
            ModelPurposeDefault(
                legacy_route.purpose,
                "configured-model",
            ),
        ),
    )
    route = replace(
        legacy_route,
        id=route_id,
        revision=route_revision,
        provider=profile.ref,
    )
    return profile, route
