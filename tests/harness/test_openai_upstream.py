from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

pytest.importorskip(
    "gpt2giga",
    reason="optional gateway integration is exercised by the candidate smoke",
)

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedProtocolCapabilities,
    NormalizedTokenLimits,
)
from gpt2giga.providers.openai_compatible import OPENAI_CHAT_EXECUTION_OWNER
from gpt2giga_harness.openai_compatible import (
    VLLM_OPENAI_COMPATIBLE_PROFILE_VERSION,
    openai_compatible_route,
    vllm_openai_compatible_profile,
)
from gpt2giga_harness.openai_upstream import (
    OPENAI_UPSTREAM_EXECUTION_OWNER,
    HarnessOpenAICompatibleNetworkAuthorizer,
    build_openai_compatible_upstream_adapter,
)
from gpt2giga_harness.provider_profiles import ModelPurpose, ProviderOwnership
from gpt2giga_harness.runtime.authority import (
    AuthorityGrant,
    AuthorityLifetime,
    ReviewerKind,
)
from gpt2giga_harness.runtime.network_access import authorize_scoped_network_access
from gpt2giga_harness.runtime.policy import EnforcementLevel
from gpt2giga_harness.secrets import (
    EnvironmentSecretResolver,
    SecretReference,
    SecretReferenceKind,
    SecretResolutionService,
)

NOW = datetime(2026, 7, 27, 10, 5, tzinfo=timezone.utc)


def _provider_and_route(*, egress_policy_ref="egress:vllm"):
    reference = SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        "VLLM_API_KEY",
    )
    provider = vllm_openai_compatible_profile(
        provider_id="vllm-team",
        display_name="Team vLLM",
        base_url="https://vllm.example",
        model="model-a",
        secret_reference=reference,
        ownership=ProviderOwnership.PROJECT,
        tls_policy_ref="tls:system",
        egress_policy_ref=egress_policy_ref,
    )
    route = openai_compatible_route(
        provider,
        route_id="vllm-team-coding",
        model="model-a",
        purpose=ModelPurpose.CODING,
    )
    return provider, route, reference


def _capabilities(provider):
    return NormalizedProtocolCapabilities(
        profile=f"{provider.id}@{provider.revision}",
        features=frozenset(BridgeFeature),
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
    )


def _network_authorizer():
    def ticket_factory(request):
        grant = AuthorityGrant(
            id=f"grant_{request.preview_sha256[:12]}",
            scope=request.scope,
            lifetime=AuthorityLifetime.OPERATION,
            preview_sha256=request.preview_sha256,
            policy_source="approval.network",
            reviewer_kind=ReviewerKind.HUMAN,
            reviewer_id="operator_1",
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
            created_at="2026-07-27T10:00:00+00:00",
            expires_at="2026-07-27T10:15:00+00:00",
            operation_id=f"operation_{request.preview_sha256[:12]}",
        )
        return authorize_scoped_network_access(
            request,
            grant,
            resolved_addresses=("8.8.8.8",),
            now=NOW.isoformat(),
            sandbox_network_enabled=True,
        )

    return HarnessOpenAICompatibleNetworkAuthorizer(
        ticket_factory,
        policy_ref="egress:vllm",
        now=lambda: NOW,
    )


class _NetworkStream:
    def get_extra_info(self, name):
        if name == "server_addr":
            return ("8.8.8.8", 443)
        return None


async def test_vllm_profile_and_harness_boundary_own_refs_grants_and_execution():
    provider, route, reference = _provider_and_route()
    observed = []

    async def handler(request):
        observed.append(request)
        assert request.headers["authorization"] == "Bearer secret-value-canary"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-harness",
                "created": 1_700_000_000,
                "model": "model-a",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
            extensions={"network_stream": _NetworkStream()},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    secrets = SecretResolutionService(
        EnvironmentSecretResolver(
            {"VLLM_API_KEY": "secret-value-canary"},
            allowed_names=frozenset({"VLLM_API_KEY"}),
        )
    )
    adapter = build_openai_compatible_upstream_adapter(
        provider,
        route,
        capabilities=_capabilities(provider),
        secrets=secrets,
        authorize_network=_network_authorizer(),
        http_client=client,
    )

    response = await adapter.complete(
        NormalizedChatRequest(
            model="model-a",
            messages=[NormalizedMessage(role="user", content="hello")],
        ),
        downstream=DownstreamProtocol.OPENAI,
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=1,
    )
    await client.aclose()

    assert response.id == "chatcmpl-harness"
    assert response.choices[0].message.content == "ok"
    assert response.choices[0].stop_reason == "stop"
    assert observed[0].url == "https://vllm.example/v1/chat/completions"
    assert adapter.profile.credential_reference_id == reference.identity
    assert adapter.profile.network_policy_ref == "egress:vllm"
    assert adapter.profile.tls_policy_ref == "tls:system"
    assert OPENAI_UPSTREAM_EXECUTION_OWNER == ("provider-execution:openai-compatible")
    assert OPENAI_UPSTREAM_EXECUTION_OWNER == OPENAI_CHAT_EXECUTION_OWNER
    assert "secret-value-canary" not in repr(adapter)
    assert all(
        evidence.source == VLLM_OPENAI_COMPATIBLE_PROFILE_VERSION
        for evidence in provider.capability_evidence
    )


def test_harness_boundary_rejects_unbound_or_unowned_execution():
    provider, route, _reference = _provider_and_route(egress_policy_ref=None)
    secrets = SecretResolutionService(
        EnvironmentSecretResolver({"VLLM_API_KEY": "secret-value-canary"})
    )

    with pytest.raises(ValueError, match="network policy ref"):
        build_openai_compatible_upstream_adapter(
            provider,
            route,
            capabilities=_capabilities(provider),
            secrets=secrets,
            authorize_network=_network_authorizer(),
        )

    admitted, admitted_route, _reference = _provider_and_route()
    with pytest.raises(ValueError, match="route changed"):
        build_openai_compatible_upstream_adapter(
            admitted,
            replace(admitted_route, model="model-b"),
            capabilities=_capabilities(admitted),
            secrets=secrets,
            authorize_network=_network_authorizer(),
        )

    with pytest.raises(ValueError, match="bind the provider revision"):
        build_openai_compatible_upstream_adapter(
            admitted,
            admitted_route,
            capabilities=_capabilities(admitted).model_copy(
                update={"profile": "vllm-team@stale"},
            ),
            secrets=secrets,
            authorize_network=_network_authorizer(),
        )
