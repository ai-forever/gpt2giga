"""Startup-owned provider adapter composition for normalized bridge routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from gpt2giga.capabilities import (
    capability_predicates_for_semantics,
    resolve_gigachat_route_capabilities,
)
from gpt2giga.capabilities.models import CapabilityKey
from gpt2giga.common.tools import normalize_gigachat_builtin_tool_type
from gpt2giga.core.context import update_request_context
from gpt2giga.protocols.normalized import (
    BridgeSemantic,
    NormalizedChatRequest,
    NormalizedToolKind,
    PublicProtocol,
    UpstreamProvider,
    admit_bridge_route,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.network import ProviderNetworkAuthorizer
from gpt2giga.providers.profiles import ProviderKind, ProviderRegistry


class BridgeProviderRuntime:
    """Resolve immutable aliases to adapters constructed once at startup."""

    def __init__(self, state: Any) -> None:
        self.registry: ProviderRegistry = state.provider_registry
        self._adapters: dict[tuple[str, str], Any] = {}
        self._network_authorizers = {
            profile.profile_id: ProviderNetworkAuthorizer(profile)
            for profile in self.registry.config.profiles
        }
        self._builtin_tools_enabled = not getattr(
            state.config.proxy_settings,
            "disable_builtin_tool_mapping",
            False,
        )
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
        requested_semantics = _requested_semantics(request)
        capability_predicates: frozenset[str] = frozenset()
        capability_predicate_reasons: Mapping[str, str] = {}
        capability_metadata: dict[str, str] = {}
        if route.provider_kind is ProviderKind.GIGACHAT:
            effective = resolve_gigachat_route_capabilities(
                model_id=route.upstream_model,
                public_protocol=PublicProtocol.OPENAI_RESPONSES.value,
                api_mode=api_mode,
                route_id=route.profile_id,
                builtin_tools_enabled=self._builtin_tools_enabled,
            )
            predicate_admission = capability_predicates_for_semantics(
                effective,
                requested_semantics,
                capability_requirements=_capability_requirements(request),
            )
            capability_predicates = predicate_admission.supported
            capability_predicate_reasons = predicate_admission.failure_reasons
            capability_metadata = {
                "effective_capability_revision": (
                    predicate_admission.capability_revision
                )
            }
        admission = admit_bridge_route(
            public_protocol=PublicProtocol.OPENAI_RESPONSES,
            public_alias=route.public_alias,
            upstream_provider=UpstreamProvider(route.provider_kind.value),
            profile_id=route.profile_id,
            config_revision=route.config_revision,
            capability_profile_revision=route.capability_profile,
            requested_semantics=requested_semantics,
            capability_predicates=capability_predicates,
            capability_predicate_reasons=capability_predicate_reasons,
        )
        update_request_context(
            model_requested=route.public_alias,
            model_effective=route.upstream_model,
            bridge_route=route.execution_context(),
            metadata={
                **capability_metadata,
                "selected_model_id": route.upstream_model,
                "admission_schema_version": admission.schema_version,
                "admission_loss_matrix_revision": admission.loss_matrix_revision,
            },
        )
        return self._adapters[(route.public_alias, api_mode)]

    async def aclose(self) -> None:
        """Close each independently owned adapter client exactly once."""
        closed: set[int] = set()
        for adapter in self._adapters.values():
            identity = id(adapter)
            close = getattr(adapter, "aclose", None)
            if identity in closed or not callable(close):
                continue
            closed.add(identity)
            await close()


def _requested_semantics(
    request: NormalizedChatRequest,
) -> dict[BridgeSemantic, str]:
    semantics = {BridgeSemantic.ROLES: "input"}
    if request.tools:
        semantics[BridgeSemantic.TOOL_DEFINITIONS_AND_CALL_IDS] = "tools"
    hosted_tool_index = next(
        (
            index
            for index, tool in enumerate(request.tools)
            if tool.kind is NormalizedToolKind.HOSTED
        ),
        None,
    )
    if hosted_tool_index is not None:
        semantics[BridgeSemantic.HOSTED_AND_PROVIDER_NATIVE_TOOLS] = (
            f"tools[{hosted_tool_index}].type"
        )
    if request.tool_choice is not None:
        semantics[BridgeSemantic.TOOL_CHOICE] = "tool_choice"
    if any(message.role == "tool" for message in request.messages):
        semantics[BridgeSemantic.TOOL_RESULTS] = "input"
    if request.parallel_tool_calls is not None:
        semantics[BridgeSemantic.PARALLEL_TOOL_CALLS] = "parallel_tool_calls"
    if request.response_format is not None:
        semantics[BridgeSemantic.STRUCTURED_OUTPUT_JSON_SCHEMA] = "text.format"
    if request.reasoning is not None:
        semantics[BridgeSemantic.REASONING_CONTROLS_AND_SUMMARIES] = "reasoning"
    if request.response_state is not None:
        if request.response_state.previous_response_id is not None:
            state_field = "previous_response_id"
        elif request.response_state.conversation_id is not None:
            state_field = "conversation"
        elif request.response_state.include:
            state_field = "include"
        elif request.response_state.store is not None:
            state_field = "store"
        else:
            state_field = "background"
        semantics[BridgeSemantic.PREVIOUS_RESPONSE_STATE] = state_field
    if any(
        part.image_reference is not None or part.type == "image_url"
        for message in request.messages
        if isinstance(message.content, list)
        for part in message.content
    ):
        semantics[BridgeSemantic.MULTIMODAL_INPUTS] = "input"
        semantics[BridgeSemantic.FILES_AND_IMAGES] = "input"
    elif any(
        part.type == "file"
        for message in request.messages
        if isinstance(message.content, list)
        for part in message.content
    ):
        semantics[BridgeSemantic.FILES_AND_IMAGES] = "input"
    if request.stream:
        semantics[BridgeSemantic.STREAM_LIFECYCLE] = "stream"
        semantics[BridgeSemantic.DISCONNECT] = "stream"
    return semantics


_HOSTED_TOOL_CAPABILITIES = {
    "web_search": CapabilityKey.HOSTED_WEB_SEARCH,
    "url_content_extraction": CapabilityKey.HOSTED_URL_EXTRACTION,
    "code_interpreter": CapabilityKey.HOSTED_CODE_INTERPRETER,
    "image_generate": CapabilityKey.HOSTED_IMAGE_GENERATION,
    "model_3d_generate": CapabilityKey.HOSTED_3D_GENERATION,
}


def _capability_requirements(
    request: NormalizedChatRequest,
) -> dict[BridgeSemantic, tuple[CapabilityKey, ...]]:
    hosted_tools = [
        tool for tool in request.tools if tool.kind is NormalizedToolKind.HOSTED
    ]
    if not hosted_tools:
        return {}

    requirements: list[CapabilityKey] = []
    for tool in hosted_tools:
        provider_type = normalize_gigachat_builtin_tool_type(tool.type)
        capability = _HOSTED_TOOL_CAPABILITIES.get(provider_type or "")
        if capability is None:
            return {BridgeSemantic.HOSTED_AND_PROVIDER_NATIVE_TOOLS: ()}
        if capability not in requirements:
            requirements.append(capability)
    return {
        BridgeSemantic.HOSTED_AND_PROVIDER_NATIVE_TOOLS: tuple(requirements),
    }
