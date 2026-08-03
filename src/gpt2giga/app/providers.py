"""Startup-owned provider adapter composition for normalized bridge routes."""

from __future__ import annotations

from typing import Any, Literal

from gpt2giga.core.context import update_request_context
from gpt2giga.protocols.normalized import (
    BridgeSemantic,
    NormalizedChatRequest,
    PublicProtocol,
    UpstreamProvider,
    admit_bridge_route,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.profiles import ProviderKind, ProviderRegistry


class BridgeProviderRuntime:
    """Resolve immutable aliases to adapters constructed once at startup."""

    def __init__(self, state: Any) -> None:
        self.registry: ProviderRegistry = state.provider_registry
        self._adapters: dict[tuple[str, str], Any] = {}
        for public_alias in self.registry.public_aliases():
            route = self.registry.resolve(public_alias)
            if route.provider_kind is not ProviderKind.GIGACHAT:
                continue
            for api_mode in ("v1", "v2"):
                self._adapters[(public_alias, api_mode)] = GigaChatProviderAdapter(
                    config=state.config,
                    request_transformer=state.request_transformer,
                    giga_client=state.gigachat_client,
                    model_limiter=state.model_concurrency_limiter,
                    response_processor=state.response_processor,
                    api_mode=api_mode,
                    forced_model=route.upstream_model,
                )

    @property
    def adapters_ready(self) -> bool:
        """Return whether every currently executable alias has its adapter."""
        for alias in self.registry.public_aliases():
            route = self.registry.resolve(alias)
            if route.provider_kind is ProviderKind.GIGACHAT and not all(
                (alias, mode) in self._adapters for mode in ("v1", "v2")
            ):
                return False
        return True

    def adapter_for(
        self,
        request: NormalizedChatRequest,
        *,
        api_mode: Literal["v1", "v2"],
    ) -> Any:
        """Admit and return the exact startup-owned adapter for one request."""
        route = self.registry.resolve(request.model)
        admit_bridge_route(
            public_protocol=PublicProtocol.OPENAI_RESPONSES,
            public_alias=route.public_alias,
            upstream_provider=UpstreamProvider(route.provider_kind.value),
            profile_id=route.profile_id,
            config_revision=route.config_revision,
            capability_profile_revision=route.capability_profile,
            requested_semantics=_requested_semantics(request),
        )
        update_request_context(
            model_requested=route.public_alias,
            model_effective=route.upstream_model,
            bridge_route=route.execution_context(),
        )
        return self._adapters[(route.public_alias, api_mode)]


def _requested_semantics(
    request: NormalizedChatRequest,
) -> dict[BridgeSemantic, str]:
    semantics = {BridgeSemantic.ROLES: "input"}
    if request.tools:
        semantics[BridgeSemantic.TOOL_DEFINITIONS_AND_CALL_IDS] = "tools"
    if request.tool_choice is not None:
        semantics[BridgeSemantic.TOOL_CHOICE] = "tool_choice"
    if any(message.role == "tool" for message in request.messages):
        semantics[BridgeSemantic.TOOL_RESULTS] = "input"
    if request.parallel_tool_calls is not None:
        semantics[BridgeSemantic.PARALLEL_TOOL_CALLS] = "parallel_tool_calls"
    if request.response_format is not None:
        semantics[BridgeSemantic.STRUCTURED_OUTPUT_JSON_SCHEMA] = "text.format"
    if request.stream:
        semantics[BridgeSemantic.STREAM_LIFECYCLE] = "stream"
        semantics[BridgeSemantic.DISCONNECT] = "stream"
    return semantics
