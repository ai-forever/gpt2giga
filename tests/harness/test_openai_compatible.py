from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.openai_compatible import (
    OPENAI_CHAT_COMPLETIONS_DIALECT,
    OPENAI_MODELS_DISCOVERY_STRATEGY,
    OPENAI_PROBE_OWNER,
    OPENAI_RESPONSES_DIALECT,
    OpenAICompatibleProbeBackend,
    OpenAIProbeAuthenticationError,
    OpenAIProbeCompatibilityError,
    OpenAIProbeProviderHealthError,
    OpenAIProbeTransportError,
    OpenAITransportResponse,
    OpenAIWireAPI,
    codex_openai_compatibility,
    custom_openai_compatible_profile,
    direct_chat_openai_compatibility,
    official_openai_profile,
    openai_compatible_route,
    parse_openai_models_response,
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
    route_profile_to_dict,
)
from gpt2giga_harness.provider_registry import (
    ProviderAuthenticationFailure,
    ProviderCompatibilityFailure,
    ProviderDiscoveryStatus,
    ProviderHealthService,
    ProviderHealthStatus,
    ProviderHealthStore,
    ProviderHealthFailure,
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


def test_official_templates_are_reference_only_and_wire_api_specific():
    responses = official_openai_profile(OpenAIWireAPI.RESPONSES)
    chat = official_openai_profile(OpenAIWireAPI.CHAT_COMPLETIONS)

    assert responses.id == "openai"
    assert responses.protocol is ProviderProtocol.OPENAI_COMPATIBLE
    assert responses.dialect == OPENAI_RESPONSES_DIALECT
    assert responses.base_url == "https://api.openai.com"
    assert responses.route_prefix == "/v1"
    assert responses.effective_base_url == "https://api.openai.com/v1"
    assert responses.discovery_strategy == OPENAI_MODELS_DISCOVERY_STRATEGY
    assert responses.ownership is ProviderOwnership.BUILT_IN
    assert responses.authentication.secret_reference == SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        "OPENAI_API_KEY",
    )
    assert responses.default_models == ()
    assert chat.id == "openai-chat-completions"
    assert chat.dialect == OPENAI_CHAT_COMPLETIONS_DIALECT
    assert chat.revision != responses.revision

    statuses = {item.id: item.status for item in responses.capability_evidence}
    assert statuses == {
        "chat": "supported",
        "images": "model-dependent",
        "reasoning": "model-dependent",
        "streaming": "supported",
        "structured-output": "model-dependent",
        "tools": "model-dependent",
        "usage": "supported",
    }
    serialized = json.dumps(provider_profile_to_dict(responses), sort_keys=True)
    assert "secret-value-canary" not in serialized
    assert "OPENAI_API_KEY" in serialized


def test_custom_template_preserves_explicit_endpoint_auth_and_semantic_revision():
    reference = SecretReference(
        SecretReferenceKind.KEYCHAIN,
        "provider-token",
        service="agent-workbench",
        account="team-a",
    )
    authentication = ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        reference,
    )
    first = custom_openai_compatible_profile(
        provider_id="custom-provider",
        display_name="Custom Provider",
        base_url="https://compatible.example/root/",
        route_prefix="/v1/",
        wire_api=OpenAIWireAPI.CHAT_COMPLETIONS,
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca",
        egress_policy_ref="egress:approved",
    )
    repeated = custom_openai_compatible_profile(
        provider_id="custom-provider",
        display_name="Custom Provider",
        base_url="https://compatible.example/root",
        route_prefix="/v1",
        wire_api=OpenAIWireAPI.CHAT_COMPLETIONS,
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca",
        egress_policy_ref="egress:approved",
    )
    changed = custom_openai_compatible_profile(
        provider_id="custom-provider",
        display_name="Custom Provider",
        base_url="https://compatible.example/root",
        route_prefix="/v1",
        wire_api=OpenAIWireAPI.RESPONSES,
        authentication=authentication,
        ownership=ProviderOwnership.PROJECT,
    )

    assert first == repeated
    assert first.effective_base_url == "https://compatible.example/root/v1"
    assert first.authentication.secret_reference == reference
    assert first.revision != changed.revision
    assert changed.dialect == OPENAI_RESPONSES_DIALECT

    unauthenticated = custom_openai_compatible_profile(
        provider_id="local-compatible",
        display_name="Local Compatible",
        base_url="http://127.0.0.1:8080/v1",
        route_prefix=None,
        wire_api=OpenAIWireAPI.CHAT_COMPLETIONS,
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )
    assert unauthenticated.authentication.secret_reference is None

    with pytest.raises(ValueError, match="SecretRef or no authentication"):
        custom_openai_compatible_profile(
            provider_id="native-auth-invalid",
            display_name="Native Auth Invalid",
            base_url="https://compatible.example/v1",
            route_prefix=None,
            wire_api=OpenAIWireAPI.RESPONSES,
            authentication=ProviderAuthentication(
                AuthenticationOwnership.PROVIDER_NATIVE
            ),
        )


def test_route_revision_binds_model_purpose_provider_and_capability_evidence():
    provider = official_openai_profile(
        OpenAIWireAPI.RESPONSES,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "model-a"),),
    )
    route = openai_compatible_route(
        provider,
        route_id="openai-coding",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )
    repeated = openai_compatible_route(
        provider,
        route_id="openai-coding",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )

    assert route == repeated
    assert route.provider == provider.ref
    assert route.effective_base_url == "https://api.openai.com/v1"
    assert route.capability_evidence == provider.capability_evidence
    assert route_profile_to_dict(route)["model"] == "model-a"
    changed = openai_compatible_route(
        provider,
        route_id="openai-coding",
        model="model-b",
        purpose=ModelPurpose.CODING,
    )
    assert route.revision != changed.revision


def test_models_parser_is_strict_bounded_and_does_not_infer_capabilities():
    payload = {
        "object": "list",
        "data": [
            {"id": "model-b", "object": "model", "owned_by": "fixture"},
            {"id": "model-a", "object": "model", "owned_by": "fixture"},
            {"id": "model-a", "object": "model", "owned_by": "fixture"},
        ],
    }

    assert parse_openai_models_response(payload) == ("model-a", "model-b")
    with pytest.raises(ValueError, match="object"):
        parse_openai_models_response({"object": "not-a-list", "data": []})
    with pytest.raises(ValueError, match="data"):
        parse_openai_models_response({"object": "list", "data": {}})
    with pytest.raises(ValueError, match="model id"):
        parse_openai_models_response(
            {"object": "list", "data": [{"id": "", "object": "model"}]}
        )


def test_probe_backend_resolves_auth_only_at_transport_boundary_and_discovers_models():
    canary = "secret-value-canary"
    profile = custom_openai_compatible_profile(
        provider_id="compatible-provider",
        display_name="Compatible Provider",
        base_url="https://compatible.example",
        route_prefix="/v1",
        wire_api=OpenAIWireAPI.RESPONSES,
        authentication=ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            SecretReference(SecretReferenceKind.ENVIRONMENT, "OPENAI_API_KEY"),
        ),
        proxy_policy_ref="proxy:corp",
        tls_policy_ref="tls:custom-ca-mtls",
        egress_policy_ref="egress:approved",
    )
    transport = _Transport(
        OpenAITransportResponse(
            payload={
                "object": "list",
                "data": [{"id": "model-a", "object": "model"}],
            }
        ),
        expected_secret=canary,
    )
    backend = OpenAICompatibleProbeBackend(
        transport,
        SecretResolutionService(EnvironmentSecretResolver({"OPENAI_API_KEY": canary})),
    )
    request = _probe_request(profile)

    response = backend.check(request)

    assert response.models == ("model-a",)
    assert response.discovery_succeeded is True
    assert len(transport.requests) == 1
    transport_request = transport.requests[0]
    assert transport_request.models_url == "https://compatible.example/v1/models"
    assert transport_request.proxy_policy_ref == "proxy:corp"
    assert transport_request.tls_policy_ref == "tls:custom-ca-mtls"
    assert transport_request.egress_policy_ref == "egress:approved"
    assert canary not in repr(transport_request)
    assert canary not in json.dumps(provider_profile_to_dict(profile))


def test_probe_backend_keeps_discovery_failure_separate_from_connection_health():
    profile = official_openai_profile(
        OpenAIWireAPI.CHAT_COMPLETIONS,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "configured"),),
    )
    backend = OpenAICompatibleProbeBackend(
        _Transport(
            OpenAITransportResponse(
                discovery_succeeded=False,
                discovery_reason_code="models_unsupported",
            )
        ),
        SecretResolutionService(
            EnvironmentSecretResolver({"OPENAI_API_KEY": "fixture-token"})
        ),
    )

    response = backend.check(_probe_request(profile))

    assert response.models == ()
    assert response.discovery_succeeded is False
    assert response.discovery_reason_code == "models_unsupported"

    invalid = OpenAICompatibleProbeBackend(
        _Transport(OpenAITransportResponse(payload={"object": "list", "data": {}})),
        SecretResolutionService(
            EnvironmentSecretResolver({"OPENAI_API_KEY": "fixture-token"})
        ),
    ).check(_probe_request(profile))
    assert invalid.discovery_succeeded is False
    assert invalid.discovery_reason_code == "invalid_models_response"


def test_probe_backend_composes_with_health_store_without_persisting_runtime_values(
    tmp_path,
):
    canary = "secret-value-canary"
    profile = official_openai_profile(
        OpenAIWireAPI.RESPONSES,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, "configured"),),
    )
    route = openai_compatible_route(
        profile,
        route_id="openai-coding",
        model="configured",
        purpose=ModelPurpose.CODING,
    )
    entry = ProviderRegistryEntry(
        profile=profile,
        routes=(route,),
        enabled=True,
        revision=1,
        created_at="2026-07-18T20:00:00Z",
        updated_at="2026-07-18T20:00:00Z",
    )
    transport = _Transport(
        OpenAITransportResponse(
            payload={
                "object": "list",
                "data": [{"id": "discovered", "object": "model"}],
            }
        ),
        expected_secret=canary,
    )
    backend = OpenAICompatibleProbeBackend(
        transport,
        SecretResolutionService(EnvironmentSecretResolver({"OPENAI_API_KEY": canary})),
    )
    store = ProviderHealthStore(tmp_path)
    monotonic_values = iter((1.0, 1.01))
    service = ProviderHealthService(
        backend,
        store,
        now=lambda: datetime(2026, 7, 18, 20, tzinfo=timezone.utc),
        monotonic=lambda: next(monotonic_values),
    )

    result = service.check(entry, force=True)

    assert result.status is ProviderHealthStatus.READY
    assert result.discovery_status is ProviderDiscoveryStatus.SUCCEEDED
    assert [(item.model, item.source) for item in result.models] == [
        ("configured", ProviderModelSource.CONFIGURED_FALLBACK),
        ("discovered", ProviderModelSource.DISCOVERED),
    ]
    serialized = store._path(profile.id).read_text(encoding="utf-8")
    assert canary not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "discovered" in serialized


def test_connection_only_probe_still_reaches_transport_without_model_evidence():
    profile = custom_openai_compatible_profile(
        provider_id="local-compatible",
        display_name="Local Compatible",
        base_url="http://127.0.0.1:8080/v1",
        route_prefix=None,
        wire_api=OpenAIWireAPI.CHAT_COMPLETIONS,
        authentication=ProviderAuthentication(AuthenticationOwnership.NONE),
    )
    transport = _Transport(OpenAITransportResponse(payload=None))
    backend = OpenAICompatibleProbeBackend(transport)

    response = backend.check(_probe_request(profile, discover_models=False))

    assert response.models == ()
    assert len(transport.requests) == 1
    assert transport.requests[0].discover_models is False


@pytest.mark.parametrize(
    ("transport_error", "expected"),
    [
        (
            OpenAIProbeAuthenticationError("invalid_api_key"),
            ProviderAuthenticationFailure,
        ),
        (
            OpenAIProbeCompatibilityError("unsupported_wire_api"),
            ProviderCompatibilityFailure,
        ),
        (OpenAIProbeProviderHealthError("rate_limited"), ProviderHealthFailure),
        (OpenAIProbeTransportError("connection_failed"), ProviderTransportFailure),
    ],
)
def test_probe_backend_maps_provider_failures_without_error_detail(
    transport_error,
    expected,
):
    profile = official_openai_profile(OpenAIWireAPI.RESPONSES)
    backend = OpenAICompatibleProbeBackend(
        _Transport(error=transport_error),
        SecretResolutionService(
            EnvironmentSecretResolver({"OPENAI_API_KEY": "secret-value-canary"})
        ),
    )

    with pytest.raises(expected) as caught:
        backend.check(_probe_request(profile))

    assert caught.value.reason_code == transport_error.reason_code
    assert "secret-value-canary" not in repr(caught.value)


def test_probe_backend_fails_closed_before_transport_for_auth_and_profile_drift():
    missing_transport = _Transport(
        OpenAITransportResponse(payload={"object": "list", "data": []})
    )
    missing = OpenAICompatibleProbeBackend(
        missing_transport,
        SecretResolutionService(EnvironmentSecretResolver({})),
    )
    profile = official_openai_profile(OpenAIWireAPI.RESPONSES)

    with pytest.raises(ProviderAuthenticationFailure) as caught:
        missing.check(_probe_request(profile))
    assert caught.value.reason_code == "secret_missing"
    assert missing_transport.requests == []

    incompatible = replace(
        profile,
        protocol=ProviderProtocol.ANTHROPIC_COMPATIBLE,
    )
    with pytest.raises(ProviderCompatibilityFailure) as caught:
        missing.check(_probe_request(incompatible))
    assert caught.value.reason_code == "protocol_incompatible"
    assert missing_transport.requests == []


def test_codex_and_direct_chat_fixtures_admit_only_reviewed_dialects_and_transports():
    registry = ProviderCompatibilityRegistry.with_builtins()
    compatibility_ids = {item.id for item in registry.list()}
    assert {
        "openai-compatible-codex-cli",
        "openai-compatible-direct-chat",
    } <= compatibility_ids

    codex_profile = official_openai_profile(OpenAIWireAPI.RESPONSES)
    codex_route = openai_compatible_route(
        codex_profile,
        route_id="openai-codex",
        model="fixture-model",
        purpose=ModelPurpose.CODING,
    )
    codex = codex_openai_compatibility()
    admission = registry.admit(
        codex_profile,
        codex_route,
        harness_id="codex-cli",
        adapter_version=codex.adapter_version,
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        required_capabilities=("chat", "streaming", "usage"),
    )
    assert admission.compatibility_id == codex.id

    chat_profile = official_openai_profile(OpenAIWireAPI.CHAT_COMPLETIONS)
    chat_route = openai_compatible_route(
        chat_profile,
        route_id="openai-direct-chat",
        model="fixture-model",
        purpose=ModelPurpose.CODING,
    )
    direct = direct_chat_openai_compatibility()
    admission = registry.admit(
        chat_profile,
        chat_route,
        harness_id="direct-chat",
        adapter_version=direct.adapter_version,
        transport=ExecutionTransport.ONE_SHOT,
        required_capabilities=("chat", "streaming", "usage"),
    )
    assert admission.compatibility_id == direct.id

    with pytest.raises(RouteCompatibilityError) as crossed:
        registry.admit(
            codex_profile,
            codex_route,
            harness_id="direct-chat",
            adapter_version=direct.adapter_version,
            transport=ExecutionTransport.ONE_SHOT,
        )
    assert crossed.value.code == "adapter_protocol_incompatible"

    with pytest.raises(RouteCompatibilityError) as native_direct:
        registry.admit(
            chat_profile,
            chat_route,
            harness_id="direct-chat",
            adapter_version=direct.adapter_version,
            transport=ExecutionTransport.NATIVE_STRUCTURED,
        )
    assert native_direct.value.code == "transport_incompatible"

    with pytest.raises(RouteCompatibilityError) as unprobed_model_capability:
        registry.admit(
            codex_profile,
            codex_route,
            harness_id="codex-cli",
            adapter_version=codex.adapter_version,
            transport=ExecutionTransport.NATIVE_STRUCTURED,
            required_capabilities=("tools",),
        )
    assert unprobed_model_capability.value.code == "capability_incompatible"


class _Transport:
    def __init__(self, response=None, *, error=None, expected_secret=None):
        self.response = response
        self.error = error
        self.expected_secret = expected_secret
        self.requests = []

    def probe(self, request):
        self.requests.append(request)
        if self.expected_secret is not None:
            assert request.credential is not None
            assert request.credential.reveal_for(OPENAI_PROBE_OWNER) == (
                self.expected_secret
            )
        if self.error is not None:
            raise self.error
        return self.response


def _probe_request(profile, *, discover_models=True):
    return ProviderProbeRequest(
        profile=profile,
        timeout_seconds=3.0,
        discover_models=discover_models,
        proxy_policy_ref=profile.proxy_policy_ref,
        tls_policy_ref=profile.tls_policy_ref,
        egress_policy_ref=profile.egress_policy_ref,
    )
