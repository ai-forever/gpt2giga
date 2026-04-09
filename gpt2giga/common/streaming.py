"""Compatibility wrappers over feature-owned streaming helpers."""

from typing import Any, AsyncGenerator, Optional

from gigachat import GigaChat
from gigachat.models import Chat
from starlette.requests import Request

from gpt2giga.app.dependencies import (
    get_response_processor_from_state,
    get_runtime_providers,
    set_runtime_provider,
)
from gpt2giga.features.chat.stream import (
    stream_chat_completion_generator as _stream_chat_completion_generator,
)
from gpt2giga.features.responses.stream import (
    stream_responses_generator as _stream_responses_generator,
)
from gpt2giga.providers.gigachat.chat_mapper import GigaChatChatMapper


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
) -> AsyncGenerator[str, None]:
    app_state = request.app.state
    mapper = get_runtime_providers(app_state).chat_mapper
    if mapper is None:
        mapper = GigaChatChatMapper(
            response_processor=get_response_processor_from_state(app_state),
        )
        set_runtime_provider(app_state, "chat_mapper", mapper)

    async for line in _stream_chat_completion_generator(
        request,
        model,
        chat_messages,
        response_id,
        giga_client,
        mapper=mapper,
    ):
        yield line


async def stream_responses_generator(
    request: Request,
    chat_messages: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
    response_store: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    async for line in _stream_responses_generator(
        request,
        chat_messages,
        response_id=response_id,
        giga_client=giga_client,
        request_data=request_data,
        response_store=response_store,
    ):
        yield line
