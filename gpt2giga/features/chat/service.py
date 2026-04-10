"""Chat feature orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from gpt2giga.app.dependencies import (
    get_runtime_providers,
    get_runtime_services,
    set_runtime_provider,
    set_runtime_service,
)
from gpt2giga.core.contracts import get_request_model, to_backend_payload
from gpt2giga.features.chat.contracts import (
    ChatBackendMode,
    ChatProviderMapper,
    ChatRequestData,
    ChatResponseData,
    ChatUpstreamClient,
    PreparedChatRequest,
)
from gpt2giga.features.chat.stream import stream_chat_completion_generator
from gpt2giga.providers.gigachat.chat_mapper import GigaChatChatMapper


class ChatService:
    """Coordinate the internal chat-completions flow."""

    def __init__(self, mapper: ChatProviderMapper):
        self.mapper = mapper

    @property
    def backend_mode(self) -> ChatBackendMode:
        """Return the configured backend mode for chat-like requests."""
        backend_mode = getattr(self.mapper, "backend_mode", None)
        if backend_mode in {"v1", "v2"}:
            return backend_mode
        if getattr(self.mapper, "uses_v2_backend", False):
            return "v2"
        return "v1"

    @property
    def uses_v2_backend(self) -> bool:
        """Return ``True`` when the service is configured for v2 calls."""
        return self.backend_mode == "v2"

    @property
    def response_processor(self) -> Any:
        """Expose the provider response processor for provider adapters."""
        return getattr(self.mapper, "response_processor", None)

    async def prepare_request(
        self,
        data: ChatRequestData,
        *,
        giga_client: ChatUpstreamClient | None = None,
    ) -> PreparedChatRequest:
        """Prepare a provider request for chat completions."""
        return await self.mapper.prepare_request(data, giga_client)

    async def execute_prepared_request(
        self,
        prepared_request: PreparedChatRequest,
        *,
        giga_client: ChatUpstreamClient,
    ) -> Any:
        """Execute an already prepared chat-like request against GigaChat."""
        if self.uses_v2_backend:
            return await giga_client.achat_v2(prepared_request)
        return await giga_client.achat(prepared_request)

    def normalize_provider_response(self, giga_resp: Any) -> dict[str, Any]:
        """Normalize a raw backend response for provider-specific adapters."""
        normalize_response = getattr(self.mapper, "normalize_provider_response", None)
        if callable(normalize_response):
            return normalize_response(giga_resp)
        if hasattr(giga_resp, "model_dump"):
            return giga_resp.model_dump()
        if isinstance(giga_resp, dict):
            return giga_resp
        raise TypeError("Unsupported provider response payload.")

    async def create_completion(
        self,
        data: ChatRequestData,
        *,
        giga_client: ChatUpstreamClient,
        response_id: str,
    ) -> ChatResponseData:
        """Execute a non-streaming chat completion."""
        prepared_request = await self.prepare_request(data, giga_client=giga_client)
        response = await self.execute_prepared_request(
            prepared_request,
            giga_client=giga_client,
        )
        return self.mapper.process_response(
            response,
            get_request_model(data),
            response_id,
            request_data=to_backend_payload(data),
        )

    async def stream_completion(
        self,
        request,
        data: ChatRequestData,
        *,
        giga_client: ChatUpstreamClient,
        response_id: str,
    ) -> AsyncGenerator[str, None]:
        """Execute a streaming chat completion."""
        prepared_request = await self.prepare_request(data, giga_client=giga_client)
        async for line in stream_chat_completion_generator(
            request,
            get_request_model(data),
            prepared_request,
            response_id=response_id,
            giga_client=giga_client,
            mapper=self.mapper,
            api_mode=self.backend_mode,
        ):
            yield line


def get_chat_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped chat service, creating it lazily if needed."""
    services = get_runtime_services(state)
    service = services.chat
    if service is not None:
        return service

    providers = get_runtime_providers(state)
    mapper = providers.chat_mapper
    if mapper is None:
        config = getattr(state, "config", None)
        proxy_settings = getattr(config, "proxy_settings", None)
        backend_mode = getattr(proxy_settings, "chat_backend_mode", "v1")
        mapper = GigaChatChatMapper(
            request_transformer=providers.request_transformer,
            response_processor=providers.response_processor,
            backend_mode=backend_mode,
        )
        set_runtime_provider(state, "chat_mapper", mapper)

    service = ChatService(mapper)
    return set_runtime_service(state, "chat", service)
