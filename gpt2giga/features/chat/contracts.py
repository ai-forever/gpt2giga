"""Internal contracts for the chat feature."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Protocol, TypeAlias, runtime_checkable

from gigachat import GigaChat

ChatRequestData: TypeAlias = dict[str, Any]
PreparedChatRequest: TypeAlias = Any
ChatResponseData: TypeAlias = dict[str, Any]
ChatStreamChunk: TypeAlias = dict[str, Any]


@runtime_checkable
class ChatUpstreamClient(Protocol):
    """Minimal upstream client surface required by the chat feature."""

    async def achat(self, chat: PreparedChatRequest) -> Any:
        """Run a non-streaming chat request."""

    async def achat_v2(self, chat: PreparedChatRequest) -> Any:
        """Run a non-streaming v2 chat request."""

    def astream(self, chat: Any) -> AsyncIterator[Any]:
        """Run a streaming chat request."""

    def astream_v2(self, chat: Any) -> AsyncIterator[Any]:
        """Run a streaming v2 chat request."""


@runtime_checkable
class ChatProviderMapper(Protocol):
    """Provider-specific chat request/response mapping surface."""

    async def prepare_request(
        self,
        data: ChatRequestData,
        giga_client: Optional[GigaChat] = None,
    ) -> PreparedChatRequest:
        """Map the feature request into a provider-specific payload."""

    def process_response(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Optional[ChatRequestData] = None,
    ) -> ChatResponseData:
        """Map a provider response into the external chat-completions contract."""

    def process_stream_chunk(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Optional[ChatRequestData] = None,
    ) -> ChatStreamChunk:
        """Map a provider stream chunk into the external chat-completions contract."""
