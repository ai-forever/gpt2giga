"""Internal contracts for the responses feature."""

from __future__ import annotations

from typing import (
    Any,
    AsyncIterator,
    Literal,
    MutableMapping,
    Protocol,
    TypeAlias,
)

from gpt2giga.core.contracts import NormalizedResponsesRequest

ResponsesRequestData: TypeAlias = NormalizedResponsesRequest | dict[str, Any]
PreparedResponsesRequest: TypeAlias = Any
ResponsesResponseData: TypeAlias = dict[str, Any]
ResponsesMetadataStore: TypeAlias = MutableMapping[str, Any]
ResponsesBackendMode: TypeAlias = Literal["v1", "v2"]


class ResponsesUpstreamClient(Protocol):
    """Minimal upstream client surface required by the responses feature."""

    async def achat(self, chat: PreparedResponsesRequest) -> Any:
        """Run a non-streaming legacy Responses API request."""

    async def achat_v2(self, chat: PreparedResponsesRequest) -> Any:
        """Run a non-streaming Responses API request."""

    async def aget_file_content(self, file_id: str) -> Any:
        """Return provider file contents as a base64 payload."""

    def astream(self, chat: PreparedResponsesRequest) -> AsyncIterator[Any]:
        """Run a streaming legacy Responses API request."""

    def astream_v2(self, chat: PreparedResponsesRequest) -> AsyncIterator[Any]:
        """Run a streaming Responses API request."""


class ResponsesRequestPreparer(Protocol):
    """Provider request-mapping surface for Responses API requests."""

    async def prepare_response(
        self,
        data: ResponsesRequestData,
        giga_client: Any = None,
    ) -> PreparedResponsesRequest:
        """Map the feature request into a legacy provider payload."""

    async def prepare_response_v2(
        self,
        data: ResponsesRequestData,
        giga_client: Any = None,
        response_store: ResponsesMetadataStore | None = None,
    ) -> PreparedResponsesRequest:
        """Map the feature request into a provider-specific payload."""


class ResponsesResultProcessor(Protocol):
    """Provider response-mapping surface for Responses API responses."""

    def process_response_api(
        self,
        data: ResponsesRequestData,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
    ) -> ResponsesResponseData:
        """Map a legacy provider response into the external Responses contract."""

    def process_response_api_v2(
        self,
        data: ResponsesRequestData,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        response_store: ResponsesMetadataStore | None = None,
    ) -> ResponsesResponseData:
        """Map a provider response into the external Responses API contract."""
