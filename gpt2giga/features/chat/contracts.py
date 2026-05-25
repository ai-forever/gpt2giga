"""Internal contracts for the chat feature."""

from __future__ import annotations

from typing import (
    Any,
    AsyncIterator,
    Literal,
    Protocol,
    TypeAlias,
    runtime_checkable,
)

from gpt2giga.core.contracts import NormalizedChatRequest

ChatRequestData: TypeAlias = NormalizedChatRequest | dict[str, Any]
PreparedChatRequest: TypeAlias = Any
ChatResponseData: TypeAlias = dict[str, Any]
ChatStreamChunk: TypeAlias = dict[str, Any]
ChatBackendMode: TypeAlias = Literal["v1", "v2"]


@runtime_checkable
class PrimaryChatResource(Protocol):
    """GigaChat primary-chat resource surface used by v2 chat calls."""

    async def create(self, chat: PreparedChatRequest) -> Any:
        """Run a non-streaming primary chat request."""

    def stream(self, chat: Any) -> AsyncIterator[Any]:
        """Run a streaming primary chat request."""

    async def __call__(self, chat: PreparedChatRequest) -> Any:
        """Run a legacy chat request through the callable namespace shim."""


@runtime_checkable
class ChatUpstreamClient(Protocol):
    """Minimal upstream client surface required by the chat feature."""

    achat: PrimaryChatResource

    def astream(self, chat: Any) -> AsyncIterator[Any]:
        """Run a streaming chat request."""


@runtime_checkable
class ChatProviderMapper(Protocol):
    """Provider-specific chat request/response mapping surface."""

    async def prepare_request(
        self,
        data: ChatRequestData,
        giga_client: Any = None,
    ) -> PreparedChatRequest:
        """Map the feature request into a provider-specific payload."""

    def process_response(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Any = None,
    ) -> ChatResponseData:
        """Map a provider response into the external chat-completions contract."""

    def process_stream_chunk(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Any = None,
    ) -> ChatStreamChunk:
        """Map a provider stream chunk into the external chat-completions contract."""
