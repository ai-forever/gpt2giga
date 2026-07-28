"""Harness-owned boundary for the normalized OpenAI-compatible adapter."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
import ssl
from typing import Any

from gpt2giga_harness.openai_compatible import openai_compatible_route
from gpt2giga_harness.provider_profiles import (
    AuthenticationOwnership,
    ProviderProfile,
    ProviderProtocol,
    RouteProfile,
)
from gpt2giga_harness.runtime.network_access import (
    NetworkAccessTicket,
    ScopedNetworkRequest,
)
from gpt2giga_harness.secrets import SecretResolutionService


OPENAI_UPSTREAM_EXECUTION_OWNER = "provider-execution:openai-compatible"


@dataclass(frozen=True)
class HarnessOpenAICompatibleNetworkAuthorization:
    """Adapt one scoped Harness ticket to the gateway transport contract."""

    ticket: NetworkAccessTicket
    now: Callable[[], datetime]

    @property
    def max_response_bytes(self) -> int:
        """Return the exact reviewed response ceiling."""
        return self.ticket.max_response_bytes

    @property
    def peer_validation_required(self) -> bool:
        """Require transport-layer peer evidence for live network requests."""
        return True

    def validate_request_body(
        self,
        *,
        body_bytes: int,
        body_sha256: str | None,
    ) -> None:
        """Revalidate the exact serialized body before transport."""
        self.ticket.validate_request_body(
            body_bytes=body_bytes,
            body_sha256=body_sha256,
            now=_timestamp(self.now()),
        )

    def validate_connected_peer(self, address: str) -> None:
        """Revalidate the connected address against pre-connect resolution."""
        self.ticket.validate_connected_peer(address, now=_timestamp(self.now()))

    def validate_response_body(self, *, body_bytes: int) -> None:
        """Revalidate the received body against the reviewed ceiling."""
        self.ticket.validate_response_body(body_bytes=body_bytes)

    def __gpt2giga_redacted__(self) -> dict[str, Any]:
        """Return content-free ticket evidence only."""
        return self.ticket.audit_receipt()


class HarnessOpenAICompatibleNetworkAuthorizer:
    """Map adapter intents to exact scoped-network ticket requests."""

    def __init__(
        self,
        ticket_factory: Callable[[ScopedNetworkRequest], NetworkAccessTicket],
        *,
        policy_ref: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(ticket_factory):
            raise TypeError("OpenAI-compatible ticket factory is required")
        if not isinstance(policy_ref, str) or not policy_ref.strip():
            raise ValueError("OpenAI-compatible network policy ref is required")
        self.ticket_factory = ticket_factory
        self.policy_ref = policy_ref.strip()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def __call__(self, intent: Any) -> HarnessOpenAICompatibleNetworkAuthorization:
        request = ScopedNetworkRequest(
            url=intent.url,
            method=intent.method,
            purpose=intent.purpose,
            request_body_bytes=intent.request_body_bytes,
            request_body_sha256=intent.request_body_sha256,
            max_response_bytes=intent.max_response_bytes,
        )
        ticket = self.ticket_factory(request)
        if not isinstance(ticket, NetworkAccessTicket):
            raise TypeError("ticket factory must return NetworkAccessTicket")
        if (
            ticket.scope_sha256 != request.scope.scope_sha256
            or ticket.preview_sha256 != request.preview_sha256
        ):
            raise ValueError("network ticket does not match adapter request")
        return HarnessOpenAICompatibleNetworkAuthorization(ticket, self.now)


def build_openai_compatible_upstream_adapter(
    provider: ProviderProfile,
    route: RouteProfile,
    *,
    capabilities: Any,
    secrets: SecretResolutionService | None,
    authorize_network: HarnessOpenAICompatibleNetworkAuthorizer,
    timeout_seconds: float = 30.0,
    max_response_bytes: int = 1024 * 1024,
    http_client: Any = None,
    ssl_context: ssl.SSLContext | bool | None = None,
) -> Any:
    """Resolve exact Harness ownership into the gateway adapter at runtime."""
    _validate_execution_profile(provider, route, capabilities=capabilities)
    credential: str | None = None
    credential_reference_id: str | None = None
    authentication = provider.authentication
    if authentication.ownership is AuthenticationOwnership.SECRET_REFERENCE:
        reference = authentication.secret_reference
        if reference is None:
            raise ValueError("OpenAI-compatible SecretRef is missing")
        if secrets is None:
            raise ValueError("OpenAI-compatible secret resolver is unavailable")
        resolved = secrets.resolve(reference, owner=OPENAI_UPSTREAM_EXECUTION_OWNER)
        credential = resolved.reveal_for(OPENAI_UPSTREAM_EXECUTION_OWNER)
        credential_reference_id = reference.identity
    elif authentication.ownership is not AuthenticationOwnership.NONE:
        raise ValueError(
            "OpenAI-compatible upstream requires SecretRef or no authentication"
        )
    if not provider.egress_policy_ref:
        raise ValueError("OpenAI-compatible upstream requires a network policy ref")
    if authorize_network.policy_ref != provider.egress_policy_ref:
        raise ValueError("OpenAI-compatible network policy ref changed")

    try:
        adapter_module = import_module("gpt2giga.providers.openai_compatible")
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "gpt2giga is required for OpenAI-compatible upstream execution"
        ) from exc

    profile = adapter_module.OpenAICompatibleUpstreamProfile(
        id=provider.id,
        revision=provider.revision,
        base_url=route.effective_base_url,
        model=route.model,
        capabilities=capabilities,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        credential_reference_id=credential_reference_id,
        network_policy_ref=provider.egress_policy_ref,
        tls_policy_ref=provider.tls_policy_ref,
        proxy_policy_ref=provider.proxy_policy_ref,
    )
    return adapter_module.OpenAICompatibleProviderAdapter(
        profile,
        credential=credential,
        authorize_network=authorize_network,
        http_client=http_client,
        ssl_context=ssl_context,
    )


def _validate_execution_profile(
    provider: ProviderProfile,
    route: RouteProfile,
    *,
    capabilities: Any,
) -> None:
    if not isinstance(provider, ProviderProfile) or not isinstance(route, RouteProfile):
        raise TypeError("OpenAI-compatible provider and route are required")
    if provider.offline:
        raise ValueError("offline provider cannot execute upstream requests")
    if provider.protocol is not ProviderProtocol.OPENAI_COMPATIBLE:
        raise ValueError("provider is not OpenAI-compatible")
    if provider.dialect != "openai-chat-completions-v1":
        raise ValueError("G7-01 admits only OpenAI Chat Completions upstream")
    if (
        route.provider != provider.ref
        or route.protocol is not provider.protocol
        or route.dialect != provider.dialect
        or route.effective_base_url != provider.effective_base_url
        or route.authentication_ownership is not provider.authentication.ownership
    ):
        raise ValueError("OpenAI-compatible route changed after profile review")
    expected_route = openai_compatible_route(
        provider,
        route_id=route.id,
        model=route.model,
        purpose=route.purpose,
        capability_evidence=route.capability_evidence,
    )
    if route != expected_route:
        raise ValueError("OpenAI-compatible route changed after profile review")
    expected_profile = f"{provider.id}@{provider.revision}"
    if getattr(capabilities, "profile", None) != expected_profile:
        raise ValueError("normalized capabilities do not bind the provider revision")
    features = getattr(capabilities, "features", None)
    if not isinstance(features, Collection) or not features:
        raise ValueError("normalized capabilities are missing")
    if getattr(capabilities, "limits", None) is None:
        raise ValueError("normalized token limits are missing")


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("network authorization clock must return datetime")
    if value.tzinfo is None:
        raise ValueError("network authorization clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
