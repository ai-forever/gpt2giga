"""Responses feature orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from starlette.requests import Request

from gpt2giga.features.responses.contracts import (
    PreparedResponsesRequest,
    ResponsesMetadataStore,
    ResponsesRequestData,
    ResponsesRequestPreparer,
    ResponsesResponseData,
    ResponsesResultProcessor,
    ResponsesUpstreamClient,
)
from gpt2giga.features.responses.store import get_response_store
from gpt2giga.features.responses.stream import stream_responses_generator


class ResponsesService:
    """Coordinate the internal Responses API flow."""

    def __init__(
        self,
        request_preparer: ResponsesRequestPreparer,
        response_processor: ResponsesResultProcessor,
    ):
        self.request_preparer = request_preparer
        self.response_processor = response_processor

    async def prepare_request(
        self,
        data: ResponsesRequestData,
        *,
        giga_client: ResponsesUpstreamClient | None = None,
        response_store: ResponsesMetadataStore | None = None,
    ) -> PreparedResponsesRequest:
        """Prepare a provider request for the Responses API."""
        return await self.request_preparer.prepare_response_v2(
            data,
            giga_client,
            response_store=response_store,
        )

    async def create_response(
        self,
        data: ResponsesRequestData,
        *,
        giga_client: ResponsesUpstreamClient,
        response_id: str,
        response_store: ResponsesMetadataStore | None = None,
    ) -> ResponsesResponseData:
        """Execute a non-streaming Responses API request."""
        prepared_request = await self.prepare_request(
            data,
            giga_client=giga_client,
            response_store=response_store,
        )
        response = await giga_client.achat_v2(prepared_request)
        return self.response_processor.process_response_api_v2(
            data,
            response,
            data["model"],
            response_id,
            response_store=response_store,
        )

    async def stream_response(
        self,
        request: Request,
        data: ResponsesRequestData,
        *,
        giga_client: ResponsesUpstreamClient,
        response_id: str,
        response_store: ResponsesMetadataStore | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute a streaming Responses API request."""
        resolved_store = (
            response_store
            if response_store is not None
            else get_response_store(request)
        )
        prepared_request = await self.prepare_request(
            data,
            giga_client=giga_client,
            response_store=resolved_store,
        )
        async for line in stream_responses_generator(
            request,
            prepared_request,
            response_id=response_id,
            giga_client=giga_client,
            request_data=data,
            response_store=resolved_store,
            response_processor=self.response_processor,
        ):
            yield line


def get_responses_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped responses service, creating it lazily if needed."""
    service = getattr(state, "responses_service", None)
    if service is not None:
        return service

    request_preparer = getattr(state, "request_transformer", None)
    if request_preparer is None:
        raise RuntimeError("Responses request transformer is not configured.")

    response_processor = getattr(state, "response_processor", None)
    if response_processor is None:
        raise RuntimeError("Responses response processor is not configured.")

    service = ResponsesService(request_preparer, response_processor)
    state.responses_service = service
    return service
