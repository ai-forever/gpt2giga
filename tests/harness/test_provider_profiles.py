from dataclasses import replace
import json

import pytest

from gpt2giga_harness import provider_profiles as provider_module
from gpt2giga_harness.execution import (
    ExecutionTransport,
    ProviderRef,
    SnapshotEvidenceRef,
)
from gpt2giga_harness.provider_profiles import (
    NEUTRAL_PROVIDER_ENTRY_POINT_GROUP,
    PROVIDER_ADAPTER_ENTRY_POINTS,
    AdapterProtocolCompatibility,
    AuthenticationOwnership,
    ModelPurpose,
    ProviderAuthentication,
    ProviderCompatibilityRegistry,
    ProviderOwnership,
    ProviderProfile,
    ProviderProtocol,
    RouteCompatibilityError,
    RouteProfile,
    codex_legacy_compatibility,
    migrate_legacy_provider_route,
    provider_profile_from_dict,
    provider_profile_to_dict,
    route_profile_from_dict,
    route_profile_to_dict,
)
from gpt2giga_harness.registries import RegistryCollisionError
from gpt2giga_harness.secrets import SecretReference, SecretReferenceKind


def test_profiles_round_trip_without_secret_values_and_keep_refs_separate():
    provider, route = migrate_legacy_provider_route(
        proxy_url="http://127.0.0.1:8090/root/",
        api_mode="v2",
        harness_id="codex-cli",
        model="coding-model",
    )

    provider_payload = provider_profile_to_dict(provider)
    route_payload = route_profile_to_dict(route)
    serialized = json.dumps(
        {"provider": provider_payload, "route": route_payload},
        sort_keys=True,
    )

    assert provider_profile_from_dict(provider_payload) == provider
    assert route_profile_from_dict(route_payload) == route
    assert provider.ref == ProviderRef(provider.id, provider.revision)
    assert route.ref.provider == provider.ref
    assert provider.effective_base_url == "http://127.0.0.1:8090/root/v2"
    assert route.effective_base_url == provider.effective_base_url
    assert provider_payload["authentication"]["secret_reference"]["name"] == (
        "GPT2GIGA_HARNESS_API_KEY"
    )
    assert "secret-value-canary" not in serialized
    assert "api_key" not in serialized


def test_profile_parsers_are_strict_and_reject_value_bearing_or_future_data():
    provider, route = migrate_legacy_provider_route(
        proxy_url="https://proxy.example/base",
        api_mode="v1",
        harness_id="direct-chat",
        model="model-a",
    )
    provider_payload = provider_profile_to_dict(provider)
    route_payload = route_profile_to_dict(route)

    future = dict(provider_payload, schema_version=2)
    with pytest.raises(ValueError, match="schema_version"):
        provider_profile_from_dict(future)

    value_bearing = dict(provider_payload, api_key="secret-value-canary")
    with pytest.raises(ValueError, match="unknown provider profile fields"):
        provider_profile_from_dict(value_bearing)

    route_unknown = dict(route_payload, prompt="must-not-persist")
    with pytest.raises(ValueError, match="unknown route profile fields"):
        route_profile_from_dict(route_unknown)

    with pytest.raises(ValueError, match="credentials"):
        replace(provider, base_url="https://user:password@proxy.example")


def test_provider_authentication_retains_only_persistable_secret_refs():
    with pytest.raises(ValueError, match="requires SecretRef"):
        ProviderAuthentication(AuthenticationOwnership.SECRET_REFERENCE)

    with pytest.raises(ValueError, match="test SecretRef"):
        ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            SecretReference(SecretReferenceKind.TEST, "TEST_PROVIDER_KEY"),
        )

    with pytest.raises(ValueError, match="cannot retain SecretRef"):
        ProviderAuthentication(
            AuthenticationOwnership.PROVIDER_NATIVE,
            SecretReference(SecretReferenceKind.ENVIRONMENT, "PROVIDER_KEY"),
        )


def test_legacy_migration_preserves_api_mode_endpoint_and_protocol_family():
    cases = (
        ("direct-chat", ProviderProtocol.OPENAI_COMPATIBLE),
        ("codex-cli", ProviderProtocol.OPENAI_COMPATIBLE),
        ("claude-code", ProviderProtocol.ANTHROPIC_COMPATIBLE),
        ("gemini-cli", ProviderProtocol.GEMINI_COMPATIBLE),
    )
    for harness_id, protocol in cases:
        provider, route = migrate_legacy_provider_route(
            proxy_url="https://proxy.example/root/",
            api_mode="V1",
            harness_id=harness_id,
            model="legacy-model",
        )

        assert provider.protocol is protocol
        assert route.protocol is protocol
        assert provider.dialect == "gpt2giga-v1"
        assert route.effective_base_url == "https://proxy.example/root/v1"
        assert provider.ownership is ProviderOwnership.MIGRATED_LEGACY
        assert route.purpose is ModelPurpose.CODING

    with pytest.raises(ValueError, match="v1 or v2"):
        migrate_legacy_provider_route(
            proxy_url="https://proxy.example",
            api_mode="v3",
            harness_id="codex-cli",
            model="legacy-model",
        )

    with pytest.raises(ValueError, match="no reviewed provider protocol"):
        migrate_legacy_provider_route(
            proxy_url="https://proxy.example",
            api_mode="v2",
            harness_id="unknown-adapter",
            model="legacy-model",
        )


def test_compatibility_admission_keeps_axes_separate_and_returns_evidence():
    provider, route = migrate_legacy_provider_route(
        proxy_url="http://127.0.0.1:8090",
        api_mode="v2",
        harness_id="codex-cli",
        model="coding-model",
    )
    compatibility = codex_legacy_compatibility()
    registry = ProviderCompatibilityRegistry.with_builtins()

    admission = registry.admit(
        provider,
        route,
        harness_id="codex-cli",
        adapter_version=compatibility.adapter_version,
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        required_capabilities=("chat", "tools"),
    )

    assert admission.provider == provider.ref
    assert admission.route == route.ref
    assert admission.compatibility_id == "legacy-gpt2giga-codex-cli"
    assert admission.evidence == compatibility.evidence


@pytest.mark.parametrize(
    ("mutation", "kwargs", "code"),
    [
        (
            lambda provider, route: (
                provider,
                replace(route, provider=ProviderRef(provider.id, "stale")),
            ),
            {},
            "provider_revision_mismatch",
        ),
        (
            lambda provider, route: (
                provider,
                replace(route, protocol=ProviderProtocol.ANTHROPIC_COMPATIBLE),
            ),
            {},
            "protocol_mismatch",
        ),
        (
            lambda provider, route: (
                provider,
                replace(route, effective_base_url="https://other.example/v2"),
            ),
            {},
            "endpoint_mismatch",
        ),
        (
            lambda provider, route: (
                provider,
                replace(route, authentication_ownership=AuthenticationOwnership.NONE),
            ),
            {},
            "authentication_mismatch",
        ),
        (
            lambda provider, route: (
                provider,
                replace(route, model="different-model"),
            ),
            {},
            "model_purpose_mismatch",
        ),
        (
            lambda provider, route: (provider, route),
            {"harness_id": "claude-code"},
            "adapter_protocol_incompatible",
        ),
        (
            lambda provider, route: (provider, route),
            {"required_capabilities": ("images",)},
            "capability_incompatible",
        ),
    ],
)
def test_invalid_combinations_fail_closed_before_spawn(mutation, kwargs, code):
    provider, route = migrate_legacy_provider_route(
        proxy_url="http://127.0.0.1:8090",
        api_mode="v2",
        harness_id="codex-cli",
        model="coding-model",
    )
    provider, route = mutation(provider, route)
    compatibility = codex_legacy_compatibility()
    registry = ProviderCompatibilityRegistry.with_builtins()
    arguments = {
        "harness_id": "codex-cli",
        "adapter_version": compatibility.adapter_version,
        "transport": ExecutionTransport.NATIVE_STRUCTURED,
        **kwargs,
    }
    spawned = False

    with pytest.raises(RouteCompatibilityError) as caught:
        registry.admit(provider, route, **arguments)
        spawned = True

    assert caught.value.code == code
    assert spawned is False


def test_transport_compatibility_is_independent_from_protocol_support():
    provider, route = migrate_legacy_provider_route(
        proxy_url="http://127.0.0.1:8090",
        api_mode="v2",
        harness_id="direct-chat",
        model="coding-model",
    )
    compatibility = provider_module.direct_chat_legacy_compatibility()

    with pytest.raises(RouteCompatibilityError) as caught:
        ProviderCompatibilityRegistry.with_builtins().admit(
            provider,
            route,
            harness_id="direct-chat",
            adapter_version=compatibility.adapter_version,
            transport=ExecutionTransport.NATIVE_STRUCTURED,
        )

    assert caught.value.code == "transport_incompatible"


def test_provider_native_auth_requires_separate_adapter_evidence():
    provider, route = _provider_native_route()
    registry = ProviderCompatibilityRegistry()
    compatibility = _compatibility(native_auth=False)
    registry.register(compatibility)

    with pytest.raises(RouteCompatibilityError) as caught:
        registry.admit(
            provider,
            route,
            harness_id="adapter-a",
            adapter_version="1",
            transport=ExecutionTransport.NATIVE_STRUCTURED,
        )

    assert caught.value.code == "native_auth_incompatible"

    registry = ProviderCompatibilityRegistry()
    registry.register(replace(compatibility, native_auth=True))
    admitted = registry.admit(
        provider,
        route,
        harness_id="adapter-a",
        adapter_version="1",
        transport=ExecutionTransport.NATIVE_STRUCTURED,
    )
    assert admitted.compatibility_id == compatibility.id


def test_provider_entry_points_use_neutral_family_and_registry_kernel(monkeypatch):
    compatibility = _compatibility()

    class FakeEntryPoint:
        name = "provider-a"
        value = f"{__name__}:_compatibility"

        def load(self):
            return lambda: compatibility

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == NEUTRAL_PROVIDER_ENTRY_POINT_GROUP
            return (FakeEntryPoint(),)

    monkeypatch.setattr(provider_module, "entry_points", lambda: FakeEntryPoints())
    registry = ProviderCompatibilityRegistry()

    registry.load_entry_points()

    assert [item.id for item in registry.list()] == [compatibility.id]
    assert registry.discovery_errors == []


def test_installed_builtin_provider_entry_points_deduplicate():
    registry = ProviderCompatibilityRegistry.with_builtins()

    registry.load_entry_points()

    assert PROVIDER_ADAPTER_ENTRY_POINTS.registry_id == "provider_adapter"
    assert PROVIDER_ADAPTER_ENTRY_POINTS.groups == (NEUTRAL_PROVIDER_ENTRY_POINT_GROUP,)
    assert [item.id for item in registry.list()] == [
        "anthropic-cloud-claude-code",
        "anthropic-compatible-claude-code",
        "legacy-gpt2giga-claude-code",
        "legacy-gpt2giga-codex-cli",
        "legacy-gpt2giga-direct-chat",
        "legacy-gpt2giga-gemini-cli",
        "openai-compatible-codex-cli",
        "openai-compatible-direct-chat",
    ]
    assert registry.discovery_errors == []


def test_provider_registry_rejects_collisions_and_bounds_redacted_failures(monkeypatch):
    registry = ProviderCompatibilityRegistry()
    registry.register(_compatibility())
    with pytest.raises(RegistryCollisionError):
        registry.register(replace(_compatibility(), revision="other"))

    class BrokenEntryPoint:
        value = "provider_plugin:factory"

        def __init__(self, index):
            self.name = f"broken-{index}"

        def load(self):
            raise ValueError("api_key=secret-value-canary")

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == NEUTRAL_PROVIDER_ENTRY_POINT_GROUP
            return tuple(BrokenEntryPoint(index) for index in range(25))

    monkeypatch.setattr(provider_module, "entry_points", lambda: FakeEntryPoints())
    failed = ProviderCompatibilityRegistry()
    failed.load_entry_points()

    assert len(failed.discovery_errors) == provider_module.MAX_DISCOVERY_ERRORS
    assert all("secret-value-canary" not in item for item in failed.discovery_errors)
    assert all("details omitted" in item for item in failed.discovery_errors)


def _provider_native_route():
    evidence = (SnapshotEvidenceRef("chat", "1", "supported", "fixture"),)
    provider = ProviderProfile(
        id="provider-a",
        revision="1",
        display_name="Provider A",
        protocol=ProviderProtocol.GEMINI_COMPATIBLE,
        dialect="gemini-v1",
        base_url="https://provider.example",
        route_prefix="/v1",
        authentication=ProviderAuthentication(AuthenticationOwnership.PROVIDER_NATIVE),
        ownership=ProviderOwnership.USER,
        capability_evidence=evidence,
    )
    route = RouteProfile(
        id="route-a",
        revision="1",
        provider=provider.ref,
        protocol=provider.protocol,
        dialect=provider.dialect,
        effective_base_url=provider.effective_base_url,
        purpose=ModelPurpose.CODING,
        model="model-a",
        authentication_ownership=AuthenticationOwnership.PROVIDER_NATIVE,
        capability_evidence=evidence,
    )
    return provider, route


def _compatibility(*, native_auth=True):
    return AdapterProtocolCompatibility(
        id="provider-a-adapter-a",
        revision="1",
        harness_id="adapter-a",
        adapter_version="1",
        protocol=ProviderProtocol.GEMINI_COMPATIBLE,
        dialects=("gemini-v1",),
        transports=(ExecutionTransport.NATIVE_STRUCTURED,),
        capabilities=("chat",),
        native_auth=native_auth,
        evidence=(
            SnapshotEvidenceRef(
                "adapter-a-gemini",
                "1",
                "supported",
                "fixture",
            ),
        ),
    )
