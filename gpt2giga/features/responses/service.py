"""Responses feature orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from starlette.requests import Request

from gpt2giga.app.dependencies import (
    get_response_processor_from_state,
    get_request_transformer_from_state,
    get_runtime_services,
    set_runtime_service,
)
from gpt2giga.core.contracts import get_request_model, to_backend_payload
from gpt2giga.features.responses.contracts import (
    PreparedResponsesRequest,
    ResponsesBackendMode,
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
        *,
        backend_mode: ResponsesBackendMode = "v1",
    ):
        self.request_preparer = request_preparer
        self.response_processor = response_processor
        self.backend_mode = backend_mode

    @property
    def uses_v2_backend(self) -> bool:
        """Return ``True`` when Responses should use the v2 backend path."""
        return self.backend_mode == "v2"

    async def prepare_request(
        self,
        data: ResponsesRequestData,
        *,
        giga_client: ResponsesUpstreamClient | None = None,
        response_store: ResponsesMetadataStore | None = None,
    ) -> PreparedResponsesRequest:
        """Prepare a provider request for the Responses API."""
        if self.uses_v2_backend:
            return await self.request_preparer.prepare_response_v2(
                data,
                giga_client,
                response_store=response_store,
            )
        return await self.request_preparer.prepare_response(data, giga_client)

    async def create_response(
        self,
        data: ResponsesRequestData,
        *,
        giga_client: ResponsesUpstreamClient,
        response_id: str,
        response_store: ResponsesMetadataStore | None = None,
    ) -> ResponsesResponseData:
        """Execute a non-streaming Responses API request."""
        request_payload = to_backend_payload(data)
        prepared_request = await self.prepare_request(
            data,
            giga_client=giga_client,
            response_store=response_store,
        )
        if self.uses_v2_backend:
            response = await giga_client.achat_v2(prepared_request)
            return self.response_processor.process_response_api_v2(
                request_payload,
                response,
                get_request_model(data),
                response_id,
                response_store=response_store,
            )
        response = await giga_client.achat(prepared_request)
        return self.response_processor.process_response_api(
            request_payload,
            response,
            get_request_model(data),
            response_id,
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
        request_payload = to_backend_payload(data)
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
            request_data=request_payload,
            response_store=resolved_store,
            response_processor=self.response_processor,
            api_mode=self.backend_mode,
        ):
            yield line


def get_responses_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped responses service, creating it lazily if needed."""
    services = get_runtime_services(state)
    service = services.responses
    if service is not None:
        return service

    request_preparer = get_request_transformer_from_state(state)
    response_processor = get_response_processor_from_state(state)
    config = getattr(state, "config", None)
    proxy_settings = getattr(config, "proxy_settings", None)
    backend_mode = getattr(proxy_settings, "responses_backend_mode", "v1")
    service = ResponsesService(
        request_preparer,
        response_processor,
        backend_mode=backend_mode,
    )
    return set_runtime_service(state, "responses", service)
