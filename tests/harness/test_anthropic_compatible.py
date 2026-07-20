from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from gpt2giga_harness.anthropic_compatible import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_BEDROCK_DIALECT,
    ANTHROPIC_FOUNDRY_DIALECT,
    ANTHROPIC_MESSAGES_DIALECT,
    ANTHROPIC_MODELS_DISCOVERY_STRATEGY,
    ANTHROPIC_PLATFORM_DISCOVERY_STRATEGY,
    ANTHROPIC_PROBE_OWNER,
    ANTHROPIC_VERTEX_DIALECT,
    AnthropicCompatibleProbeBackend,
    AnthropicPlatform,
    AnthropicProbeAuthenticationError,
    AnthropicProbeCompatibilityError,
    AnthropicProbeProviderHealthError,
    AnthropicProbeTransportError,
    AnthropicTransportResponse,
    anthropic_cloud_profile,
    anthropic_compatible_route,
    claude_agent_sdk_provider_decision,
    claude_code_anthropic_api_compatibility,
    claude_code_anthropic_cloud_compatibility,
    custom_anthropic_compatible_profile,
    official_anthropic_profile,
    parse_anthropic_models_response,
)
from gpt2giga_harness.claude_agent_sdk_poc import ClaudeSdkAuthMode
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.provider_profiles import (
    AuthenticationOwnership,
    ModelPurpose,
    ModelPurposeDefault,
    ProviderAuthentication,
    ProviderCompatibilityRegistry,
    ProviderOwnership,
    ProviderProtocol,
    RouteCompatibilityError,
    provider_profile_to_dict,
    route_profile_to_dict,
)
from gpt2giga_harness.provider_registry import (
    ProviderAuthenticationFailure,
    ProviderCompatibilityFailure,
    ProviderDiscoveryStatus,
    ProviderHealthFailure,
    ProviderHealthService,
    ProviderHealthStatus,
    ProviderHealthStore,
    ProviderModelSource,
    ProviderProbeRequest,
    ProviderRegistryEntry,
    ProviderTransportFailure,
)
from gpt2giga_harness.secrets import (
    EnvironmentSecretResolver,
    SecretReference,
    SecretReferenceKind,
    SecretResolutionService,
)


def test_official_template_is_reference_only_and_messages_specific():
    profile = official_anthropic_profile()

    assert profile.id == "anthropic"
    assert profile.protocol is ProviderProtocol.ANTHROPIC_COMPATIBLE
    assert profile.dialect == ANTHROPIC_MESSAGES_DIALECT
    assert profile.base_url == "https://api.anthropic.com"
    assert profile.route_prefix == "/v1"
    assert profile.effective_base_url == "https://api.anthropic.com/v1"
    assert profile.discovery_strategy == ANTHROPIC_MODELS_DISCOVERY_STRATEGY
    assert profile.ownership is ProviderOwnership.BUILT_IN
    assert profile.authentication.secret_reference == SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        "ANTHROPIC_API_KEY",
    )
    statuses = {item.id: item.status for item in profile.capability_evidence}
    assert statuses == {
        "chat": "supported",
        "images": "model-dependent",
        "reasoning": "model-dependent",
        "streaming": "supported",
        "structured-output": "model-dependent",
        "tools": "model-dependent",
        "usage": "supported",
    }
    serialized = json.dumps(provider_profile_to_dict(profile), sort_keys=True)
    assert "secret-value-canary" not in serialized
    assert "ANTHROPIC_API_KEY" in serialized


def test_custom_template_preserves_endpoint_auth_policy_and_semantic_revision():
    reference = SecretReference(
        SecretReferenceKind.KEYCHAIN,
        "anthropic-token",
        service="agent-workbench",
        account="team-a",
    )
    authentication = ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        reference,
    )
    first = custom_anthropic_compatible_profile(
        provider_id="custom-anthropic",
        display_name="Custom Anthropic",
        base_url="https://compatible.example/root/",
        route_prefix="/v1/",
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca",
        egress_policy_ref="egress:approved",
    )
    repeated = custom_anthropic_compatible_profile(
        provider_id="custom-anthropic",
        display_name="Custom Anthropic",
        base_url="https://compatible.example/root",
        route_prefix="/v1",
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca",
        egress_policy_ref="egress:approved",
    )
    changed = custom_anthropic_compatible_profile(
        provider_id="custom-anthropic",
        display_name="Custom Anthropic",
        base_url="https://other.example",
        route_prefix="/v1",
        authentication=authentication,
    )

    assert first == repeated
    assert first.effective_base_url == "https://compatible.example/root/v1"
    assert first.authentication.secret_reference == reference
    assert first.revision != changed.revision
    assert first.proxy_policy_ref == "proxy:corp"

    unauthenticated = custom_anthropic_compatible_profile(
        provider_id="local-anthropic",
        display_name="Local Anthropic",
        base_url="http://127.0.0.1:8080/v1",
        route_prefix=None,
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )
    assert unauthenticated.authentication.secret_reference is None

    with pytest.raises(ValueError, match="authentication ownership"):
        custom_anthropic_compatible_profile(
            provider_id="native-invalid",
            display_name="Native Invalid",
            base_url="https://compatible.example/v1",
            route_prefix=None,
            authentication=ProviderAuthentication(
                AuthenticationOwnership.PROVIDER_NATIVE
            ),
        )


@pytest.mark.parametrize(
    ("platform", "dialect"),
    [
        (AnthropicPlatform.AMAZON_BEDROCK, ANTHROPIC_BEDROCK_DIALECT),
        (AnthropicPlatform.GOOGLE_VERTEX, ANTHROPIC_VERTEX_DIALECT),
        (AnthropicPlatform.MICROSOFT_FOUNDRY, ANTHROPIC_FOUNDRY_DIALECT),
    ],
)
def test_cloud_templates_keep_platform_dialects_and_provider_auth_distinct(
    platform,
    dialect,
):
    profile = anthropic_cloud_profile(
        platform,
        provider_id=f"fixture-{platform.value}",
        display_name=platform.value,
        base_url="https://platform.example/anthropic",
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
    )

    assert profile.dialect == dialect
    assert profile.authentication.ownership is AuthenticationOwnership.PROVIDER_NATIVE
    assert profile.discovery_strategy == ANTHROPIC_PLATFORM_DISCOVERY_STRATEGY
    assert profile.discovery_cache_ttl_seconds == 0
    assert profile.route_prefix is None


def test_cloud_auth_matrix_allows_foundry_key_without_crossing_platforms():
    foundry_key = ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        SecretReference(
            SecretReferenceKind.ENVIRONMENT,
            "ANTHROPIC_FOUNDRY_API_KEY",
        ),
    )
    profile = anthropic_cloud_profile(
        AnthropicPlatform.MICROSOFT_FOUNDRY,
        provider_id="foundry",
        display_name="Foundry",
        base_url="https://resource.services.ai.azure.com/anthropic",
        authentication=foundry_key,
    )
    assert profile.authentication == foundry_key

    for platform in (
        AnthropicPlatform.AMAZON_BEDROCK,
        AnthropicPlatform.GOOGLE_VERTEX,
    ):
        with pytest.raises(ValueError, match="authentication ownership"):
            anthropic_cloud_profile(
                platform,
                provider_id="invalid",
                display_name="Invalid",
                base_url="https://platform.example",
                authentication=foundry_key,
            )

    with pytest.raises(ValueError, match="cloud platform"):
        anthropic_cloud_profile(
            AnthropicPlatform.ANTHROPIC_API,
            provider_id="invalid",
            display_name="Invalid",
            base_url="https://api.anthropic.com/v1",
        )


def test_route_revision_binds_model_purpose_provider_and_capability_evidence():
    provider = official_anthropic_profile(
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
    )
    route = anthropic_compatible_route(
        provider,
        route_id="anthropic-coding",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )
    repeated = anthropic_compatible_route(
        provider,
        route_id="anthropic-coding",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )

    assert route == repeated
    assert route.provider == provider.ref
    assert route.effective_base_url == "https://api.anthropic.com/v1"
    assert route.capability_evidence == provider.capability_evidence
    assert route_profile_to_dict(route)["model"] == "model-a"
    changed = anthropic_compatible_route(
        provider,
        route_id="anthropic-coding",
        model="model-b",
        purpose=ModelPurpose.CODING,
    )
    assert route.revision != changed.revision


def test_models_parser_is_strict_bounded_and_rejects_partial_pages():
    payload = {
        "data": [
            {"id": "model-b", "type": "model", "display_name": "B"},
            {"id": "model-a", "type": "model", "display_name": "A"},
            {"id": "model-a", "type": "model", "display_name": "A"},
        ],
        "first_id": "model-b",
        "has_more": False,
        "last_id": "model-a",
    }

    assert parse_anthropic_models_response(payload) == ("model-a", "model-b")
    with pytest.raises(ValueError, match="data"):
        parse_anthropic_models_response({"data": {}})
    with pytest.raises(ValueError, match="another page"):
        parse_anthropic_models_response({"data": [], "has_more": True})
    with pytest.raises(ValueError, match="model id"):
        parse_anthropic_models_response({"data": [{"id": "", "type": "model"}]})
    with pytest.raises(ValueError, match="model type"):
        parse_anthropic_models_response(
            {"data": [{"id": "model", "type": "not-model"}]}
        )


def test_direct_probe_resolves_auth_only_at_transport_boundary_and_discovers_models():
    canary = "secret-value-canary"
    profile = custom_anthropic_compatible_profile(
        provider_id="compatible-anthropic",
        display_name="Compatible Anthropic",
        base_url="https://compatible.example",
        route_prefix="/v1",
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca-mtls",
        egress_policy_ref="egress:approved",
    )
    transport = _Transport(
        AnthropicTransportResponse(
            payload={
                "data": [{"id": "model-a", "type": "model"}],
                "has_more": False,
            }
        ),
        expected_secret=canary,
    )
    backend = AnthropicCompatibleProbeBackend(
        transport,
        SecretResolutionService(
            EnvironmentSecretResolver({"ANTHROPIC_API_KEY": canary})
        ),
    )

    response = backend.check(_probe_request(profile))

    assert response.models == ("model-a",)
    request = transport.requests[0]
    assert request.platform is AnthropicPlatform.ANTHROPIC_API
    assert request.probe_url == "https://compatible.example/v1/models"
    assert request.api_version == ANTHROPIC_API_VERSION
    assert request.proxy_policy_ref == "proxy:corp"
    assert request.tls_policy_ref == "tls:custom-ca-mtls"
    assert request.egress_policy_ref == "egress:approved"
    assert canary not in repr(request)
    assert canary not in json.dumps(provider_profile_to_dict(profile))


@pytest.mark.parametrize(
    "platform",
    [
        AnthropicPlatform.AMAZON_BEDROCK,
        AnthropicPlatform.GOOGLE_VERTEX,
        AnthropicPlatform.MICROSOFT_FOUNDRY,
    ],
)
def test_cloud_probe_leaves_provider_native_credentials_with_transport(platform):
    profile = anthropic_cloud_profile(
        platform,
        provider_id=platform.value,
        display_name=platform.value,
        base_url="https://platform.example/anthropic",
    )
    transport = _Transport(AnthropicTransportResponse(models=("model-a",)))

    response = AnthropicCompatibleProbeBackend(transport).check(_probe_request(profile))

    assert response.models == ("model-a",)
    request = transport.requests[0]
    assert request.platform is platform
    assert request.credential is None
    assert request.api_version is None
    assert request.probe_url == "https://platform.example/anthropic"


def test_foundry_secret_is_resolved_without_becoming_provider_state():
    canary = "foundry-secret-canary"
    profile = anthropic_cloud_profile(
        AnthropicPlatform.MICROSOFT_FOUNDRY,
        provider_id="foundry",
        display_name="Foundry",
        base_url="https://resource.services.ai.azure.com/anthropic",
        authentication=ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            SecretReference(
                SecretReferenceKind.ENVIRONMENT,
                "ANTHROPIC_FOUNDRY_API_KEY",
            ),
        ),
    )
    transport = _Transport(
        AnthropicTransportResponse(
            discovery_succeeded=False,
            discovery_reason_code="models_unsupported",
        ),
        expected_secret=canary,
    )
    backend = AnthropicCompatibleProbeBackend(
        transport,
        SecretResolutionService(
            EnvironmentSecretResolver({"ANTHROPIC_FOUNDRY_API_KEY": canary})
        ),
    )

    response = backend.check(_probe_request(profile))

    assert response.discovery_succeeded is False
    assert response.discovery_reason_code == "models_unsupported"
    assert canary not in repr(transport.requests[0])
    assert canary not in json.dumps(provider_profile_to_dict(profile))


def test_probe_keeps_discovery_failure_separate_from_connection_health():
    profile = official_anthropic_profile(
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "configured"),),
    )
    backend = AnthropicCompatibleProbeBackend(
        _Transport(
            AnthropicTransportResponse(
                discovery_succeeded=False,
                discovery_reason_code="models_unsupported",
            )
        ),
        SecretResolutionService(
            EnvironmentSecretResolver({"ANTHROPIC_API_KEY": "fixture-token"})
        ),
    )

    response = backend.check(_probe_request(profile))

    assert response.models == ()
    assert response.discovery_succeeded is False
    assert response.discovery_reason_code == "models_unsupported"

    invalid = AnthropicCompatibleProbeBackend(
        _Transport(AnthropicTransportResponse(payload={"data": {}})),
        SecretResolutionService(
            EnvironmentSecretResolver({"ANTHROPIC_API_KEY": "fixture-token"})
        ),
    ).check(_probe_request(profile))
    assert invalid.discovery_succeeded is False
    assert invalid.discovery_reason_code == "invalid_models_response"


def test_probe_composes_with_health_store_without_persisting_runtime_values(tmp_path):
    canary = "secret-value-canary"
    profile = official_anthropic_profile(
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "configured"),),
    )
    route = anthropic_compatible_route(
        profile,
        route_id="anthropic-coding",
        model="configured",
        purpose=ModelPurpose.CODING,
    )
    entry = ProviderRegistryEntry(
        profile=profile,
        routes=(route,),
        enabled=True,
        revision=1,
        created_at="2026-07-19T00:00:00Z",
        updated_at="2026-07-19T00:00:00Z",
    )
    transport = _Transport(
        AnthropicTransportResponse(
            payload={
                "data": [{"id": "discovered", "type": "model"}],
                "has_more": False,
            }
        ),
        expected_secret=canary,
    )
    service = ProviderHealthService(
        AnthropicCompatibleProbeBackend(
            transport,
            SecretResolutionService(
                EnvironmentSecretResolver({"ANTHROPIC_API_KEY": canary})
            ),
        ),
        ProviderHealthStore(tmp_path),
        now=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
        monotonic=_Clock(),
    )

    snapshot = service.check(entry)

    assert snapshot.status is ProviderHealthStatus.READY
    assert snapshot.discovery_status is ProviderDiscoveryStatus.SUCCEEDED
    assert {(item.model, item.source) for item in snapshot.models} == {
        ("configured", ProviderModelSource.CONFIGURED_FALLBACK),
        ("discovered", ProviderModelSource.DISCOVERED),
    }
    persisted = next((tmp_path / "providers" / "health").glob("*.json"))
    assert canary not in persisted.read_text()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            AnthropicProbeAuthenticationError("invalid_key"),
            ProviderAuthenticationFailure,
        ),
        (AnthropicProbeCompatibilityError("bad_dialect"), ProviderCompatibilityFailure),
        (AnthropicProbeProviderHealthError("overloaded"), ProviderHealthFailure),
        (AnthropicProbeTransportError("timeout"), ProviderTransportFailure),
    ],
)
def test_probe_failure_axes_remain_independent(error, expected):
    backend = AnthropicCompatibleProbeBackend(
        _Transport(error),
        SecretResolutionService(
            EnvironmentSecretResolver({"ANTHROPIC_API_KEY": "fixture-token"})
        ),
    )

    with pytest.raises(expected):
        backend.check(_probe_request(official_anthropic_profile()))


def test_probe_fails_closed_for_wrong_protocol_dialect_strategy_and_response():
    profile = official_anthropic_profile()
    backend = AnthropicCompatibleProbeBackend(
        _Transport(AnthropicTransportResponse(payload={"data": []})),
        SecretResolutionService(
            EnvironmentSecretResolver({"ANTHROPIC_API_KEY": "fixture-token"})
        ),
    )
    with pytest.raises(ProviderCompatibilityFailure, match="protocol_incompatible"):
        backend.check(
            _probe_request(
                replace(profile, protocol=ProviderProtocol.OPENAI_COMPATIBLE)
            )
        )
    with pytest.raises(ProviderCompatibilityFailure, match="dialect_incompatible"):
        backend.check(_probe_request(replace(profile, dialect="unknown")))
    with pytest.raises(
        ProviderCompatibilityFailure,
        match="discovery_strategy_incompatible",
    ):
        backend.check(_probe_request(replace(profile, discovery_strategy="none")))
    with pytest.raises(
        ProviderCompatibilityFailure,
        match="authentication_ownership_incompatible",
    ):
        backend.check(
            _probe_request(
                replace(
                    profile,
                    authentication=ProviderAuthentication(
                        AuthenticationOwnership.PROVIDER_NATIVE
                    ),
                )
            )
        )

    cloud = anthropic_cloud_profile(
        AnthropicPlatform.AMAZON_BEDROCK,
        provider_id="bedrock",
        display_name="Bedrock",
        base_url="https://bedrock.example",
    )
    invalid_cloud = AnthropicCompatibleProbeBackend(
        _Transport(AnthropicTransportResponse(payload={"data": []}))
    )
    with pytest.raises(
        ProviderCompatibilityFailure,
        match="invalid_platform_probe_response",
    ):
        invalid_cloud.check(_probe_request(cloud))


@pytest.mark.parametrize(
    ("platform", "auth_mode"),
    [
        (AnthropicPlatform.ANTHROPIC_API, ClaudeSdkAuthMode.API_KEY),
        (AnthropicPlatform.AMAZON_BEDROCK, ClaudeSdkAuthMode.BEDROCK),
        (AnthropicPlatform.GOOGLE_VERTEX, ClaudeSdkAuthMode.VERTEX),
        (AnthropicPlatform.MICROSOFT_FOUNDRY, ClaudeSdkAuthMode.FOUNDRY),
    ],
)
def test_sdk_provider_mapping_preserves_negative_embedded_exit(platform, auth_mode):
    profile = (
        official_anthropic_profile()
        if platform is AnthropicPlatform.ANTHROPIC_API
        else anthropic_cloud_profile(
            platform,
            provider_id=platform.value,
            display_name=platform.value,
            base_url="https://platform.example/anthropic",
        )
    )

    decision = claude_agent_sdk_provider_decision(profile)

    assert decision.platform is platform
    assert decision.auth_mode is auth_mode
    assert decision.protocol_compatible is True
    assert decision.structured_transport_ready is False
    assert decision.subscription_embedding_allowed is False
    assert decision.blockers == ("n2_04_embedded_driver_blocked",)


def test_sdk_mapping_does_not_relabel_unauthenticated_custom_route():
    profile = custom_anthropic_compatible_profile(
        provider_id="local",
        display_name="Local",
        base_url="http://127.0.0.1:8080/v1",
        route_prefix=None,
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )

    decision = claude_agent_sdk_provider_decision(profile)

    assert decision.auth_mode is None
    assert decision.protocol_compatible is False
    assert decision.blockers == (
        "n2_04_embedded_driver_blocked",
        "sdk_authentication_incompatible",
    )


def test_claude_compatibility_admits_reviewed_transports_and_blocks_structured():
    registry = ProviderCompatibilityRegistry.with_builtins()
    direct_compatibility = claude_code_anthropic_api_compatibility()
    direct = official_anthropic_profile()
    direct_route = anthropic_compatible_route(
        direct,
        route_id="direct",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )
    admission = registry.admit(
        direct,
        direct_route,
        harness_id="claude-code",
        adapter_version=direct_compatibility.adapter_version,
        transport=ExecutionTransport.ONE_SHOT,
        required_capabilities=("chat", "streaming"),
    )
    assert admission.compatibility_id == "anthropic-compatible-claude-code"
    with pytest.raises(RouteCompatibilityError) as caught:
        registry.admit(
            direct,
            direct_route,
            harness_id="claude-code",
            adapter_version=direct_compatibility.adapter_version,
            transport=ExecutionTransport.NATIVE_STRUCTURED,
        )
    assert caught.value.code == "transport_incompatible"

    cloud_compatibility = claude_code_anthropic_cloud_compatibility()
    cloud = anthropic_cloud_profile(
        AnthropicPlatform.GOOGLE_VERTEX,
        provider_id="vertex",
        display_name="Vertex",
        base_url="https://vertex.example",
    )
    cloud_route = anthropic_compatible_route(
        cloud,
        route_id="vertex",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )
    admission = registry.admit(
        cloud,
        cloud_route,
        harness_id="claude-code",
        adapter_version=cloud_compatibility.adapter_version,
        transport=ExecutionTransport.NATIVE_TERMINAL,
        required_capabilities=("chat",),
    )
    assert admission.compatibility_id == "anthropic-cloud-claude-code"


def test_compatibility_fixtures_keep_direct_and_cloud_auth_separate():
    direct = claude_code_anthropic_api_compatibility()
    cloud = claude_code_anthropic_cloud_compatibility()

    assert direct.dialects == (ANTHROPIC_MESSAGES_DIALECT,)
    assert direct.native_auth is False
    assert cloud.dialects == tuple(
        sorted(
            (
                ANTHROPIC_BEDROCK_DIALECT,
                ANTHROPIC_VERTEX_DIALECT,
                ANTHROPIC_FOUNDRY_DIALECT,
            )
        )
    )
    assert cloud.native_auth is True
    assert ExecutionTransport.NATIVE_STRUCTURED not in direct.transports
    assert ExecutionTransport.NATIVE_STRUCTURED not in cloud.transports


def test_probe_owner_is_stable_and_request_repr_is_content_free():
    assert ANTHROPIC_PROBE_OWNER == "provider-probe:anthropic-compatible"
    transport = _Transport(
        AnthropicTransportResponse(
            discovery_succeeded=False,
            discovery_reason_code="models_unsupported",
        )
    )
    profile = custom_anthropic_compatible_profile(
        provider_id="local",
        display_name="Local",
        base_url="http://127.0.0.1:8080/v1",
        route_prefix=None,
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )

    AnthropicCompatibleProbeBackend(transport).check(_probe_request(profile))

    assert "credential=None" in repr(transport.requests[0])


class _Transport:
    def __init__(self, outcome, *, expected_secret=None):
        self.outcome = outcome
        self.expected_secret = expected_secret
        self.requests = []

    def probe(self, request):
        if self.expected_secret is not None:
            assert request.credential is not None
            assert request.credential.reveal_for(ANTHROPIC_PROBE_OWNER) == (
                self.expected_secret
            )
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        value = self.value
        self.value += 0.01
        return value


def _probe_request(profile, *, discover_models=True):
    return ProviderProbeRequest(
        profile=profile,
        timeout_seconds=5.0,
        discover_models=discover_models,
        proxy_policy_ref=profile.proxy_policy_ref,
        tls_policy_ref=profile.tls_policy_ref,
        egress_policy_ref=profile.egress_policy_ref,
    )
