"""Chat feature orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from gpt2giga.app.dependencies import (
    get_runtime_providers,
    get_runtime_services,
    set_runtime_provider,
    set_runtime_service,
)
from gpt2giga.features.chat.contracts import (
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

    async def prepare_request(
        self,
        data: ChatRequestData,
        *,
        giga_client: ChatUpstreamClient | None = None,
    ) -> PreparedChatRequest:
        """Prepare a provider request for chat completions."""
        return await self.mapper.prepare_request(data, giga_client)

    async def create_completion(
        self,
        data: ChatRequestData,
        *,
        giga_client: ChatUpstreamClient,
        response_id: str,
    ) -> ChatResponseData:
        """Execute a non-streaming chat completion."""
        prepared_request = await self.prepare_request(data, giga_client=giga_client)
        response = await giga_client.achat(prepared_request)
        return self.mapper.process_response(
            response,
            data["model"],
            response_id,
            request_data=data,
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
            data["model"],
            prepared_request,
            response_id=response_id,
            giga_client=giga_client,
            mapper=self.mapper,
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
        mapper = GigaChatChatMapper(
            request_transformer=providers.request_transformer,
            response_processor=providers.response_processor,
        )
        set_runtime_provider(state, "chat_mapper", mapper)

    service = ChatService(mapper)
    return set_runtime_service(state, "chat", service)
