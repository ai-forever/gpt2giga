"""Startup-owned provider adapter composition for normalized bridge routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
import hashlib
from typing import Any, Literal

import httpx

from gpt2giga.capabilities import (
    capability_predicates_for_semantics,
    resolve_gigachat_route_capabilities,
)
from gpt2giga.capabilities.models import CapabilityKey
from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.tools import (
    map_namespaced_tool_name_to_gigachat,
    normalize_gigachat_builtin_tool_type,
)
from gpt2giga.core.context import update_request_context
from gpt2giga.protocols.normalized import (
    BridgeFeature,
    BridgeMatrixAdmissionError,
    BridgeSemantic,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedStreamEvent,
    NormalizedTokenLimits,
    NormalizedTool,
    NormalizedToolKind,
    PublicProtocol,
    UnsupportedSemanticLossError,
    UpstreamProvider,
    admit_bridge_route,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.network import ProviderNetworkAuthorizer
from gpt2giga.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    openai_compatible_profile,
)
from gpt2giga.providers.profiles import (
    ProviderKind,
    ProviderProfileError,
    ProviderRegistry,
)


_DOWNSTREAM_PROTOCOLS = {
    PublicProtocol.OPENAI_RESPONSES: DownstreamProtocol.OPENAI,
    PublicProtocol.OPENAI_CHAT_COMPLETIONS: DownstreamProtocol.OPENAI,
    PublicProtocol.ANTHROPIC_MESSAGES: DownstreamProtocol.ANTHROPIC,
    PublicProtocol.GEMINI_GENERATE_CONTENT: DownstreamProtocol.GEMINI,
}
_PROVIDER_LABELS = {
    PublicProtocol.OPENAI_RESPONSES: "openai",
    PublicProtocol.OPENAI_CHAT_COMPLETIONS: "openai",
    PublicProtocol.ANTHROPIC_MESSAGES: "anthropic",
    PublicProtocol.GEMINI_GENERATE_CONTENT: "gemini",
}
_CONDITIONAL_FEATURES = {
    BridgeSemantic.MULTIMODAL_INPUTS: BridgeFeature.IMAGE_REFERENCES,
    BridgeSemantic.FILES_AND_IMAGES: BridgeFeature.IMAGE_REFERENCES,
    BridgeSemantic.PARALLEL_TOOL_CALLS: BridgeFeature.PARALLEL_TOOL_CALLS,
    BridgeSemantic.STRUCTURED_OUTPUT_JSON_SCHEMA: BridgeFeature.JSON_SCHEMA_OUTPUT,
}


class _BoundOpenAICompatibleAdapter:
    """Bind one upstream alias to one public protocol projection."""

    def __init__(
        self,
        adapter: OpenAICompatibleProviderAdapter,
        *,
        public_alias: str,
        upstream_model: str,
        public_protocol: PublicProtocol,
        downstream_capabilities: frozenset[BridgeFeature],
        model_limiter: Any,
    ) -> None:
        self._adapter = adapter
        self._public_alias = public_alias
        self._upstream_model = upstream_model
        self._public_protocol = public_protocol
        self._downstream = _DOWNSTREAM_PROTOCOLS[public_protocol]
        self._downstream_capabilities = downstream_capabilities
        self._model_limiter = model_limiter

    async def complete(
        self,
        request: NormalizedChatRequest,
        *,
        context: Any | None = None,
    ) -> Any:
        """Execute one non-streaming request through the bound upstream."""
        del context
        prepared = self._prepare_request(request)
        async with self._model_limiter.limit(
            self._upstream_model,
            provider=_PROVIDER_LABELS[self._public_protocol],
        ):
            return await self._adapter.complete(
                prepared,
                downstream=self._downstream,
                downstream_capabilities=self._downstream_capabilities,
            )

    async def chat(
        self,
        request: NormalizedChatRequest,
        *,
        context: Any | None = None,
    ) -> Any:
        """Keep the normalized provider interface used by existing routers."""
        return await self.complete(request, context=context)

    async def stream_chat(
        self,
        request: NormalizedChatRequest,
        *,
        context: Any | None = None,
        is_disconnected: Any | None = None,
        logger: Any | None = None,
    ) -> AsyncIterator[NormalizedStreamEvent]:
        """Execute one streaming request through the bound upstream."""
        del context, logger
        prepared = self._prepare_request(request)
        async with self._model_limiter.limit(
            self._upstream_model,
            provider=_PROVIDER_LABELS[self._public_protocol],
        ):
            async for event in self._adapter.stream_chat(
                prepared,
                downstream=self._downstream,
                downstream_capabilities=self._downstream_capabilities,
                is_disconnected=is_disconnected,
            ):
                yield event

    async def count_tokens(self, *_args: Any, **_kwargs: Any) -> Any:
        """Reject token counting that Chat Completions cannot implement exactly."""
        raise ClientCompatibilityError(
            "The selected Chat Completions upstream has no exact token-count API.",
            provider=(
                "anthropic"
                if self._public_protocol is PublicProtocol.ANTHROPIC_MESSAGES
                else "openai"
            ),
            param="model",
            code="unsupported_semantic",
        )

    def preflight(self, request: NormalizedChatRequest) -> None:
        """Run protocol-loss admission before a public stream may start."""
        self._adapter.admit(
            self._prepare_request(request),
            downstream=self._downstream,
            downstream_capabilities=self._downstream_capabilities,
        )

    def _prepare_request(self, request: NormalizedChatRequest) -> NormalizedChatRequest:
        if request.model != self._public_alias:
            raise ValueError("normalized request model does not match the public alias")
        return request.model_copy(
            update={
                "model": self._upstream_model,
                "messages": [
                    _openai_compatible_message(message) for message in request.messages
                ],
                "tools": _openai_compatible_tools(request.tools),
            }
        )


class BridgeProviderRuntime:
    """Resolve immutable aliases to adapters constructed once at startup."""

    def __init__(self, state: Any) -> None:
        self.registry: ProviderRegistry = state.provider_registry
        self._adapters: dict[tuple[str, str], Any] = {}
        self._external_adapters: dict[str, OpenAICompatibleProviderAdapter] = {}
        self._bound_external_adapters: dict[
            tuple[str, PublicProtocol], _BoundOpenAICompatibleAdapter
        ] = {}
        self._http_clients: dict[str, httpx.AsyncClient] = {}
        authorizer_factory = getattr(
            state,
            "openai_compatible_network_authorizer_factory",
            ProviderNetworkAuthorizer,
        )
        self._network_authorizers = {
            profile.profile_id: authorizer_factory(profile)
            for profile in self.registry.config.profiles
        }
        self._model_limiter = state.model_concurrency_limiter
        for public_alias in self.registry.public_aliases():
            route = self.registry.resolve(public_alias)
            if route.provider_kind is ProviderKind.GIGACHAT:
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
            elif route.provider_kind is ProviderKind.OPENAI_COMPATIBLE:
                self._external_adapters[public_alias] = (
                    self._build_openai_compatible_adapter(state, route)
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
            if (
                route.provider_kind is ProviderKind.OPENAI_COMPATIBLE
                and alias not in self._external_adapters
            ):
                return False
        return True

    def adapter_for(
        self,
        request: NormalizedChatRequest,
        *,
        api_mode: Literal["v1", "v2"],
        public_protocol: PublicProtocol = PublicProtocol.OPENAI_RESPONSES,
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
                public_protocol=public_protocol.value,
                api_mode=api_mode,
                route_id=route.profile_id,
                builtin_tools_enabled=True,
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
        elif route.provider_kind is ProviderKind.OPENAI_COMPATIBLE:
            capabilities = self.registry.model_alias_for(route).capabilities
            if capabilities is None:
                raise ProviderProfileError(
                    "invalid_profile_schema",
                    "OpenAI-compatible execution requires provider-profiles.v3 "
                    "model capabilities.",
                )
            capability_predicates = frozenset(
                f"capability.{semantic.value}"
                for semantic, feature in _CONDITIONAL_FEATURES.items()
                if feature in capabilities.features
            )
        admission = admit_bridge_route(
            public_protocol=public_protocol,
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
        if route.provider_kind is ProviderKind.OPENAI_COMPATIBLE:
            bound = self._bound_openai_compatible_adapter(route, public_protocol)
            try:
                bound.preflight(request)
            except UnsupportedSemanticLossError as exc:
                raise BridgeMatrixAdmissionError(
                    public_protocol=public_protocol,
                    upstream_provider=UpstreamProvider.OPENAI_COMPATIBLE,
                    public_alias=route.public_alias,
                    public_field_path={
                        PublicProtocol.OPENAI_RESPONSES: "input",
                        PublicProtocol.OPENAI_CHAT_COMPLETIONS: "messages",
                        PublicProtocol.ANTHROPIC_MESSAGES: "messages",
                        PublicProtocol.GEMINI_GENERATE_CONTENT: "contents",
                    }[public_protocol],
                    reason_id="protocol_loss_rejected",
                ) from exc
            return bound
        return self._adapters[(route.public_alias, api_mode)]

    def _build_openai_compatible_adapter(
        self,
        state: Any,
        route: Any,
    ) -> OpenAICompatibleProviderAdapter:
        profile = self.registry.profile_for(route)
        model = self.registry.model_alias_for(route)
        capabilities = model.capabilities
        if capabilities is None:
            raise ProviderProfileError(
                "invalid_profile_schema",
                "OpenAI-compatible execution requires provider-profiles.v3 model "
                "capabilities.",
            )
        credential = self.registry.credential_for(route)
        credential_reference_id = (
            hashlib.sha256(
                f"{profile.profile_id}:{profile.credential_env}".encode("utf-8")
            ).hexdigest()
            if profile.credential_env is not None
            else None
        )
        upstream_profile = openai_compatible_profile(
            profile_id=route.profile_id,
            revision=route.profile_revision,
            config_revision=route.config_revision,
            public_alias=route.public_alias,
            base_url=profile.base_url,
            model=route.upstream_model,
            capability_profile=route.capability_profile,
            loss_matrix_revision=route.loss_matrix_revision,
            features=capabilities.features,
            limits=NormalizedTokenLimits(
                **capabilities.limits.model_dump(mode="python", exclude_none=True)
            ),
            network_policy_ref=profile.network_policy_ref,
            credential_reference_id=credential_reference_id,
            tls_policy_ref=profile.tls_policy_ref,
        )
        http_client = self._http_clients.get(profile.profile_id)
        if http_client is None:
            client_factory = getattr(
                state,
                "openai_compatible_http_client_factory",
                None,
            )
            if callable(client_factory):
                http_client = client_factory(upstream_profile)
            else:
                http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(upstream_profile.timeout_seconds),
                    verify=True,
                    follow_redirects=False,
                    trust_env=False,
                )
            self._http_clients[profile.profile_id] = http_client
        return OpenAICompatibleProviderAdapter(
            upstream_profile,
            credential=credential,
            authorize_network=self._network_authorizers[profile.profile_id],
            http_client=http_client,
        )

    def _bound_openai_compatible_adapter(
        self,
        route: Any,
        public_protocol: PublicProtocol,
    ) -> _BoundOpenAICompatibleAdapter:
        key = (route.public_alias, public_protocol)
        bound = self._bound_external_adapters.get(key)
        if bound is not None:
            return bound
        capabilities = self.registry.model_alias_for(route).capabilities
        if capabilities is None:  # pragma: no cover - guarded at composition
            raise RuntimeError("OpenAI-compatible capabilities are unavailable")
        bound = _BoundOpenAICompatibleAdapter(
            self._external_adapters[route.public_alias],
            public_alias=route.public_alias,
            upstream_model=route.upstream_model,
            public_protocol=public_protocol,
            downstream_capabilities=capabilities.features,
            model_limiter=self._model_limiter,
        )
        self._bound_external_adapters[key] = bound
        return bound

    async def aclose(self) -> None:
        """Close each independently owned adapter client exactly once."""
        closed: set[int] = set()
        for adapter in (*self._adapters.values(), *self._external_adapters.values()):
            identity = id(adapter)
            close = getattr(adapter, "aclose", None)
            if identity in closed or not callable(close):
                continue
            closed.add(identity)
            await close()
        for client in self._http_clients.values():
            identity = id(client)
            if identity in closed:
                continue
            closed.add(identity)
            await client.aclose()


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


def _openai_compatible_message(message: NormalizedMessage) -> NormalizedMessage:
    if message.role != "developer":
        return message
    return message.model_copy(update={"role": "system"})


def _openai_compatible_tools(
    tools: list[NormalizedTool],
) -> list[NormalizedTool]:
    flattened: list[NormalizedTool] = []
    names: set[str] = set()
    for tool in tools:
        if tool.kind is not NormalizedToolKind.NAMESPACE:
            candidates = [_strip_default_function_strict(tool)]
        else:
            nested = tool.configuration.get("tools")
            if not isinstance(nested, list) or not tool.name:
                raise ClientCompatibilityError(
                    "The Responses namespace tool is invalid.",
                    param="tools",
                    code="invalid_request",
                )
            candidates = []
            for raw_nested in nested:
                nested_tool = NormalizedTool.model_validate(raw_nested)
                if (
                    nested_tool.kind is not NormalizedToolKind.FUNCTION
                    or not nested_tool.name
                ):
                    raise ClientCompatibilityError(
                        "The Responses namespace contains a non-function tool.",
                        param="tools",
                        code="unsupported_semantic",
                    )
                candidates.append(
                    _strip_default_function_strict(
                        nested_tool.model_copy(
                            update={
                                "kind": NormalizedToolKind.FUNCTION,
                                "type": "function",
                                "name": map_namespaced_tool_name_to_gigachat(
                                    tool.name,
                                    nested_tool.name,
                                ),
                            }
                        )
                    )
                )
        for candidate in candidates:
            if candidate.name is not None:
                if candidate.name in names:
                    raise ClientCompatibilityError(
                        "Responses tools collide after namespace flattening.",
                        param="tools",
                        code="invalid_request",
                    )
                names.add(candidate.name)
            flattened.append(candidate)
    return flattened


def _strip_default_function_strict(tool: NormalizedTool) -> NormalizedTool:
    if tool.raw_extensions != {"function": {"strict": False}}:
        return tool
    return tool.model_copy(update={"raw_extensions": {}})
