"""Explicit opt-in smoke for a reviewed remote vLLM-compatible endpoint."""

from datetime import datetime, timedelta, timezone
import os
import socket
from urllib.parse import urlsplit

import pytest

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedProtocolCapabilities,
    NormalizedTokenLimits,
)
from gpt2giga_harness.openai_compatible import (
    openai_compatible_route,
    vllm_openai_compatible_profile,
)
from gpt2giga_harness.openai_upstream import (
    HarnessOpenAICompatibleNetworkAuthorizer,
    build_openai_compatible_upstream_adapter,
)
from gpt2giga_harness.provider_profiles import ModelPurpose
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


pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.slow]
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _configured(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip() or "REPLACE_WITH" in value:
        return None
    return value.strip()


@pytest.fixture(scope="module", autouse=True)
def require_remote_vllm() -> None:
    if os.getenv("GPT2GIGA_RUN_VLLM_SMOKE", "").lower() not in _TRUE_VALUES:
        pytest.skip("set GPT2GIGA_RUN_VLLM_SMOKE=1 for the live vLLM smoke")
    base_url = _configured("GPT2GIGA_VLLM_BASE_URL")
    model = _configured("GPT2GIGA_VLLM_MODEL")
    if base_url is None or model is None:
        pytest.skip("set GPT2GIGA_VLLM_BASE_URL and GPT2GIGA_VLLM_MODEL")
    if urlsplit(base_url).scheme != "https":
        pytest.skip("live vLLM smoke requires a reviewed remote HTTPS endpoint")


def _authorizer():
    def ticket_factory(request):
        now = datetime.now(timezone.utc)
        addresses = tuple(
            sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(
                        request.target.host,
                        request.target.port,
                        type=socket.SOCK_STREAM,
                    )
                }
            )
        )
        grant = AuthorityGrant(
            id=f"vllm_smoke_{request.preview_sha256[:16]}",
            scope=request.scope,
            lifetime=AuthorityLifetime.OPERATION,
            preview_sha256=request.preview_sha256,
            policy_source="live-smoke.explicit-opt-in",
            reviewer_kind=ReviewerKind.HUMAN,
            reviewer_id="live-smoke-operator",
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
            operation_id=f"vllm_smoke_{request.preview_sha256[:16]}",
        )
        return authorize_scoped_network_access(
            request,
            grant,
            resolved_addresses=addresses,
            now=now.isoformat(),
            sandbox_network_enabled=True,
        )

    return HarnessOpenAICompatibleNetworkAuthorizer(
        ticket_factory,
        policy_ref="egress:live-vllm-smoke",
    )


async def test_remote_vllm_text_completion_smoke():
    base_url = _configured("GPT2GIGA_VLLM_BASE_URL")
    model = _configured("GPT2GIGA_VLLM_MODEL")
    assert base_url is not None
    assert model is not None
    api_key = _configured("GPT2GIGA_VLLM_API_KEY")
    secret_reference = (
        SecretReference(SecretReferenceKind.ENVIRONMENT, "GPT2GIGA_VLLM_API_KEY")
        if api_key is not None
        else None
    )
    normalized_base = base_url.rstrip("/")
    route_prefix = None if normalized_base.endswith("/v1") else "/v1"
    provider = vllm_openai_compatible_profile(
        provider_id="live-vllm-smoke",
        base_url=normalized_base,
        route_prefix=route_prefix,
        model=model,
        secret_reference=secret_reference,
        egress_policy_ref="egress:live-vllm-smoke",
    )
    route = openai_compatible_route(
        provider,
        route_id="live-vllm-smoke",
        model=model,
        purpose=ModelPurpose.CODING,
    )
    capabilities = NormalizedProtocolCapabilities(
        profile=f"{provider.id}@{provider.revision}",
        features=frozenset(
            {
                BridgeFeature.ROLES,
                BridgeFeature.ORDERED_CONTENT_PARTS,
                BridgeFeature.TEXT,
                BridgeFeature.GENERATION_CONTROLS,
                BridgeFeature.STOP_REASON,
                BridgeFeature.USAGE,
                BridgeFeature.MODEL_IDENTITY,
                BridgeFeature.REQUEST_ERROR_CLASSES,
                BridgeFeature.CANCELLATION,
                BridgeFeature.CONTEXT_TOKEN_LIMITS,
            }
        ),
        limits=NormalizedTokenLimits(
            context_window=int(os.getenv("GPT2GIGA_VLLM_CONTEXT_WINDOW", "32768")),
            max_output_tokens=1024,
        ),
    )
    secrets = (
        SecretResolutionService(
            EnvironmentSecretResolver(
                allowed_names=frozenset({"GPT2GIGA_VLLM_API_KEY"})
            )
        )
        if secret_reference is not None
        else None
    )
    adapter = build_openai_compatible_upstream_adapter(
        provider,
        route,
        capabilities=capabilities,
        secrets=secrets,
        authorize_network=_authorizer(),
        timeout_seconds=30.0,
    )
    try:
        response = await adapter.complete(
            NormalizedChatRequest(
                model=model,
                messages=[
                    NormalizedMessage(
                        role="user",
                        content="Reply with the single word OK.",
                    )
                ],
                generation_config=NormalizedGenerationConfig(max_tokens=8),
            ),
            downstream=DownstreamProtocol.OPENAI,
            downstream_capabilities={
                BridgeFeature.GENERATION_CONTROLS,
                BridgeFeature.CONTEXT_TOKEN_LIMITS,
            },
        )
    finally:
        await adapter.aclose()

    assert response.choices
    assert response.choices[0].message is not None
    assert response.choices[0].message.content
