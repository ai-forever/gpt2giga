from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.gemini_compatible import (
    GEMINI_GENERATE_CONTENT_DIALECT,
    GEMINI_MODELS_DISCOVERY_STRATEGY,
    GEMINI_PROBE_OWNER,
    GEMINI_VERTEX_DIALECT,
    GEMINI_VERTEX_DISCOVERY_STRATEGY,
    GeminiCliAuthMode,
    GeminiCompatibleProbeBackend,
    GeminiPlatform,
    GeminiProbeAuthenticationError,
    GeminiProbeCompatibilityError,
    GeminiProbeProviderHealthError,
    GeminiProbeTransportError,
    GeminiTransportResponse,
    custom_gemini_compatible_profile,
    gemini_cli_api_compatibility,
    gemini_cli_configuration_evidence,
    gemini_cli_vertex_compatibility,
    gemini_compatible_route,
    official_gemini_profile,
    parse_gemini_models_response,
    vertex_ai_gemini_profile,
)
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


def test_official_template_is_reference_only_and_generate_content_specific():
    profile = official_gemini_profile()

    assert profile.id == "gemini"
    assert profile.protocol is ProviderProtocol.GEMINI_COMPATIBLE
    assert profile.dialect == GEMINI_GENERATE_CONTENT_DIALECT
    assert profile.base_url == "https://generativelanguage.googleapis.com"
    assert profile.route_prefix == "/v1beta"
    assert profile.effective_base_url == (
        "https://generativelanguage.googleapis.com/v1beta"
    )
    assert profile.discovery_strategy == GEMINI_MODELS_DISCOVERY_STRATEGY
    assert profile.ownership is ProviderOwnership.BUILT_IN
    assert profile.authentication.secret_reference == SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        "GEMINI_API_KEY",
    )
    assert {item.id: item.status for item in profile.capability_evidence} == {
        "chat": "supported",
        "images": "model-dependent",
        "reasoning": "model-dependent",
        "streaming": "supported",
        "structured-output": "model-dependent",
        "tools": "model-dependent",
        "usage": "supported",
    }
    serialized = json.dumps(provider_profile_to_dict(profile), sort_keys=True)
    assert "GEMINI_API_KEY" in serialized
    assert "secret-value-canary" not in serialized


def test_custom_template_preserves_auth_policy_and_semantic_revision():
    authentication = ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        SecretReference(
            SecretReferenceKind.KEYCHAIN,
            "gemini-token",
            service="agent-workbench",
            account="team-a",
        ),
    )
    first = custom_gemini_compatible_profile(
        provider_id="custom-gemini",
        display_name="Custom Gemini",
        base_url="https://compatible.example/root/",
        route_prefix="/v1beta/",
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca",
        egress_policy_ref="egress:approved",
    )
    repeated = custom_gemini_compatible_profile(
        provider_id="custom-gemini",
        display_name="Custom Gemini",
        base_url="https://compatible.example/root",
        route_prefix="/v1beta",
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca",
        egress_policy_ref="egress:approved",
    )

    assert first == repeated
    assert first.authentication == authentication
    assert first.effective_base_url == "https://compatible.example/root/v1beta"
    assert first.proxy_policy_ref == "proxy:corp"
    assert first.tls_policy_ref == "tls:custom-ca"
    assert first.egress_policy_ref == "egress:approved"
    changed = custom_gemini_compatible_profile(
        provider_id="custom-gemini",
        display_name="Custom Gemini",
        base_url="https://compatible.example/root",
        route_prefix="/v1",
        authentication=authentication,
    )
    assert first.revision != changed.revision


def test_direct_and_vertex_templates_keep_auth_ownership_distinct():
    unauthenticated = custom_gemini_compatible_profile(
        provider_id="local",
        display_name="Local",
        base_url="http://127.0.0.1:8080",
        route_prefix="/v1beta",
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )
    vertex = vertex_ai_gemini_profile()

    assert unauthenticated.authentication.ownership is AuthenticationOwnership.NONE
    assert vertex.dialect == GEMINI_VERTEX_DIALECT
    assert vertex.discovery_strategy == GEMINI_VERTEX_DISCOVERY_STRATEGY
    assert vertex.discovery_cache_ttl_seconds == 0
    assert vertex.authentication.ownership is AuthenticationOwnership.PROVIDER_NATIVE
    assert vertex.base_url == "https://aiplatform.googleapis.com"

    native = ProviderAuthentication(AuthenticationOwnership.PROVIDER_NATIVE)
    with pytest.raises(ValueError, match="authentication ownership"):
        custom_gemini_compatible_profile(
            provider_id="invalid",
            display_name="Invalid",
            base_url="https://compatible.example",
            route_prefix="/v1beta",
            authentication=native,
        )


def test_vertex_template_allows_explicit_google_api_key_reference():
    authentication = ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        SecretReference(SecretReferenceKind.ENVIRONMENT, "GOOGLE_API_KEY"),
    )
    profile = vertex_ai_gemini_profile(authentication=authentication)

    assert profile.authentication == authentication


def test_route_revision_binds_model_purpose_provider_and_evidence():
    provider = official_gemini_profile(
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "gemini-a"),),
    )
    route = gemini_compatible_route(
        provider,
        route_id="gemini-coding",
        model="gemini-a",
        purpose=ModelPurpose.CODING,
    )
    repeated = gemini_compatible_route(
        provider,
        route_id="gemini-coding",
        model="gemini-a",
        purpose=ModelPurpose.CODING,
    )

    assert route == repeated
    assert route.provider == provider.ref
    assert route.capability_evidence == provider.capability_evidence
    changed = gemini_compatible_route(
        provider,
        route_id="gemini-coding",
        model="gemini-b",
        purpose=ModelPurpose.CODING,
    )
    assert route.revision != changed.revision


def test_models_parser_is_strict_bounded_and_rejects_partial_pages():
    payload = {
        "models": [
            {"name": "models/gemini-b", "baseModelId": "gemini-b"},
            {"name": "models/gemini-a-001", "baseModelId": "gemini-a"},
            {"name": "models/gemini-a-002", "baseModelId": "gemini-a"},
        ]
    }

    assert parse_gemini_models_response(payload) == ("gemini-a", "gemini-b")
    with pytest.raises(ValueError, match="models"):
        parse_gemini_models_response({"models": {}})
    with pytest.raises(ValueError, match="another page"):
        parse_gemini_models_response({"models": [], "nextPageToken": "next"})
    with pytest.raises(ValueError, match="resource name"):
        parse_gemini_models_response({"models": [{"name": "gemini-a"}]})
    with pytest.raises(ValueError, match="model id"):
        parse_gemini_models_response(
            {"models": [{"name": "models/gemini-a", "baseModelId": ""}]}
        )


def test_direct_probe_resolves_auth_at_transport_boundary_and_discovers_models():
    canary = "secret-value-canary"
    profile = custom_gemini_compatible_profile(
        provider_id="compatible-gemini",
        display_name="Compatible Gemini",
        base_url="https://compatible.example",
        route_prefix="/v1beta",
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca-mtls",
        egress_policy_ref="egress:approved",
    )
    transport = _Transport(
        GeminiTransportResponse(payload={"models": [{"name": "models/gemini-a"}]}),
        expected_secret=canary,
    )
    backend = GeminiCompatibleProbeBackend(
        transport,
        SecretResolutionService(EnvironmentSecretResolver({"GEMINI_API_KEY": canary})),
    )

    response = backend.check(_probe_request(profile))

    assert response.models == ("gemini-a",)
    request = transport.requests[0]
    assert request.platform is GeminiPlatform.GEMINI_API
    assert request.probe_url == "https://compatible.example/v1beta/models"
    assert request.proxy_policy_ref == "proxy:corp"
    assert request.tls_policy_ref == "tls:custom-ca-mtls"
    assert request.egress_policy_ref == "egress:approved"
    assert canary not in repr(request)
    assert canary not in json.dumps(provider_profile_to_dict(profile))


def test_vertex_probe_leaves_native_credentials_with_transport():
    profile = vertex_ai_gemini_profile()
    transport = _Transport(GeminiTransportResponse(models=("gemini-a",)))

    response = GeminiCompatibleProbeBackend(transport).check(_probe_request(profile))

    assert response.models == ("gemini-a",)
    request = transport.requests[0]
    assert request.platform is GeminiPlatform.VERTEX_AI
    assert request.credential is None
    assert request.probe_url == "https://aiplatform.googleapis.com"


def test_vertex_api_key_is_resolved_without_becoming_provider_state():
    canary = "vertex-key-canary"
    profile = vertex_ai_gemini_profile(
        authentication=ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            SecretReference(SecretReferenceKind.ENVIRONMENT, "GOOGLE_API_KEY"),
        )
    )
    transport = _Transport(
        GeminiTransportResponse(
            discovery_succeeded=False,
            discovery_reason_code="models_unsupported",
        ),
        expected_secret=canary,
    )
    backend = GeminiCompatibleProbeBackend(
        transport,
        SecretResolutionService(EnvironmentSecretResolver({"GOOGLE_API_KEY": canary})),
    )

    response = backend.check(_probe_request(profile))

    assert response.discovery_succeeded is False
    assert canary not in repr(transport.requests[0])
    assert canary not in json.dumps(provider_profile_to_dict(profile))


def test_probe_keeps_discovery_failure_separate_from_connection_health():
    profile = official_gemini_profile()
    secrets = SecretResolutionService(
        EnvironmentSecretResolver({"GEMINI_API_KEY": "fixture-token"})
    )
    unavailable = GeminiCompatibleProbeBackend(
        _Transport(
            GeminiTransportResponse(
                discovery_succeeded=False,
                discovery_reason_code="models_unsupported",
            )
        ),
        secrets,
    ).check(_probe_request(profile))
    invalid = GeminiCompatibleProbeBackend(
        _Transport(GeminiTransportResponse(payload={"models": {}})),
        secrets,
    ).check(_probe_request(profile))

    assert unavailable.discovery_succeeded is False
    assert unavailable.discovery_reason_code == "models_unsupported"
    assert invalid.discovery_succeeded is False
    assert invalid.discovery_reason_code == "invalid_models_response"


def test_probe_composes_with_health_store_without_persisting_runtime_values(tmp_path):
    canary = "secret-value-canary"
    profile = official_gemini_profile(
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "configured"),),
    )
    route = gemini_compatible_route(
        profile,
        route_id="gemini-coding",
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
    service = ProviderHealthService(
        GeminiCompatibleProbeBackend(
            _Transport(
                GeminiTransportResponse(
                    payload={"models": [{"name": "models/discovered"}]}
                ),
                expected_secret=canary,
            ),
            SecretResolutionService(
                EnvironmentSecretResolver({"GEMINI_API_KEY": canary})
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
        (GeminiProbeAuthenticationError("invalid_key"), ProviderAuthenticationFailure),
        (GeminiProbeCompatibilityError("bad_dialect"), ProviderCompatibilityFailure),
        (GeminiProbeProviderHealthError("overloaded"), ProviderHealthFailure),
        (GeminiProbeTransportError("timeout"), ProviderTransportFailure),
    ],
)
def test_probe_failure_axes_remain_independent(error, expected):
    backend = GeminiCompatibleProbeBackend(
        _Transport(error),
        SecretResolutionService(
            EnvironmentSecretResolver({"GEMINI_API_KEY": "fixture-token"})
        ),
    )

    with pytest.raises(expected):
        backend.check(_probe_request(official_gemini_profile()))


def test_probe_fails_closed_for_profile_drift_and_invalid_platform_response():
    profile = official_gemini_profile()
    backend = GeminiCompatibleProbeBackend(
        _Transport(GeminiTransportResponse(payload={"models": []})),
        SecretResolutionService(
            EnvironmentSecretResolver({"GEMINI_API_KEY": "fixture-token"})
        ),
    )
    with pytest.raises(ProviderCompatibilityFailure, match="protocol_incompatible"):
        backend.check(
            _probe_request(
                replace(profile, protocol=ProviderProtocol.ANTHROPIC_COMPATIBLE)
            )
        )
    with pytest.raises(ProviderCompatibilityFailure, match="dialect_incompatible"):
        backend.check(_probe_request(replace(profile, dialect="unknown")))
    with pytest.raises(
        ProviderCompatibilityFailure,
        match="discovery_strategy_incompatible",
    ):
        backend.check(_probe_request(replace(profile, discovery_strategy="none")))

    invalid_vertex = GeminiCompatibleProbeBackend(
        _Transport(GeminiTransportResponse(payload={"models": []}))
    )
    with pytest.raises(
        ProviderCompatibilityFailure,
        match="invalid_platform_probe_response",
    ):
        invalid_vertex.check(_probe_request(vertex_ai_gemini_profile()))


def test_native_client_google_login_evidence_never_reads_or_copies_oauth():
    evidence = gemini_cli_configuration_evidence(
        GeminiCliAuthMode.GOOGLE_LOGIN,
        cli_version="0.46.0",
    )

    assert evidence.provider is None
    assert evidence.authentication_ownership is AuthenticationOwnership.PROVIDER_NATIVE
    assert evidence.settings_auth_type == "oauth-personal"
    assert evidence.oauth_token_access is False
    assert evidence.endpoint_override is False
    assert evidence.environment_variables == ("GOOGLE_CLOUD_PROJECT",)
    assert "secret-value-canary" not in repr(evidence)
    with pytest.raises(ValueError, match="cannot be attached"):
        gemini_cli_configuration_evidence(
            GeminiCliAuthMode.GOOGLE_LOGIN,
            official_gemini_profile(),
            cli_version="0.46.0",
        )


def test_native_client_api_gateway_and_vertex_configuration_are_reference_only():
    direct = official_gemini_profile()
    gateway = custom_gemini_compatible_profile(
        provider_id="gateway",
        display_name="Gateway",
        base_url="https://gateway.example",
        route_prefix="/v1beta",
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )
    vertex = vertex_ai_gemini_profile()

    api_key = gemini_cli_configuration_evidence(
        GeminiCliAuthMode.GEMINI_API_KEY,
        direct,
        cli_version="0.46.0",
    )
    gateway_config = gemini_cli_configuration_evidence(
        GeminiCliAuthMode.GATEWAY,
        gateway,
        cli_version="0.46.0",
    )
    vertex_config = gemini_cli_configuration_evidence(
        GeminiCliAuthMode.VERTEX_AI,
        vertex,
        cli_version="0.46.0",
    )

    assert api_key.environment_variables == ("GEMINI_API_KEY",)
    assert gateway_config.environment_variables == ("GOOGLE_GEMINI_BASE_URL",)
    assert gateway_config.endpoint_override is True
    assert vertex_config.environment_variables == (
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_GENAI_USE_VERTEXAI",
    )
    assert all(
        not item.oauth_token_access for item in (api_key, gateway_config, vertex_config)
    )


def test_native_client_configuration_rejects_crossed_auth_modes():
    with pytest.raises(ValueError, match="requires a SecretRef"):
        gemini_cli_configuration_evidence(
            GeminiCliAuthMode.GEMINI_API_KEY,
            custom_gemini_compatible_profile(
                provider_id="local",
                display_name="Local",
                base_url="http://127.0.0.1:8080",
                route_prefix="/v1beta",
                authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
            ),
            cli_version="0.46.0",
        )
    with pytest.raises(ValueError, match="Vertex mode"):
        gemini_cli_configuration_evidence(
            GeminiCliAuthMode.VERTEX_AI,
            official_gemini_profile(),
            cli_version="0.46.0",
        )


def test_gemini_compatibility_admits_reviewed_dialects_and_transports():
    registry = ProviderCompatibilityRegistry.with_builtins()
    direct_compatibility = gemini_cli_api_compatibility()
    direct = official_gemini_profile()
    direct_route = gemini_compatible_route(
        direct,
        route_id="direct",
        model="gemini-a",
        purpose=ModelPurpose.CODING,
    )
    admission = registry.admit(
        direct,
        direct_route,
        harness_id="gemini-cli",
        adapter_version=direct_compatibility.adapter_version,
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        required_capabilities=("chat", "streaming"),
    )
    assert admission.compatibility_id == "gemini-compatible-gemini-cli"

    vertex_compatibility = gemini_cli_vertex_compatibility()
    vertex = vertex_ai_gemini_profile()
    vertex_route = gemini_compatible_route(
        vertex,
        route_id="vertex",
        model="gemini-a",
        purpose=ModelPurpose.CODING,
    )
    admission = registry.admit(
        vertex,
        vertex_route,
        harness_id="gemini-cli",
        adapter_version=vertex_compatibility.adapter_version,
        transport=ExecutionTransport.NATIVE_TERMINAL,
        required_capabilities=("chat",),
    )
    assert admission.compatibility_id == "gemini-vertex-gemini-cli"

    with pytest.raises(RouteCompatibilityError) as caught:
        registry.admit(
            direct,
            direct_route,
            harness_id="gemini-cli",
            adapter_version=direct_compatibility.adapter_version,
            transport=ExecutionTransport.ONE_SHOT,
            required_capabilities=("tools",),
        )
    assert caught.value.code == "capability_incompatible"


def test_probe_owner_is_stable_and_request_repr_is_content_free():
    assert GEMINI_PROBE_OWNER == "provider-probe:gemini-compatible"
    transport = _Transport(
        GeminiTransportResponse(
            discovery_succeeded=False,
            discovery_reason_code="models_unsupported",
        )
    )
    profile = custom_gemini_compatible_profile(
        provider_id="local",
        display_name="Local",
        base_url="http://127.0.0.1:8080",
        route_prefix="/v1beta",
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )

    GeminiCompatibleProbeBackend(transport).check(_probe_request(profile))

    assert "credential=None" in repr(transport.requests[0])


class _Transport:
    def __init__(self, outcome, *, expected_secret=None):
        self.outcome = outcome
        self.expected_secret = expected_secret
        self.requests = []

    def probe(self, request):
        if self.expected_secret is not None:
            assert request.credential is not None
            assert request.credential.reveal_for(GEMINI_PROBE_OWNER) == (
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
