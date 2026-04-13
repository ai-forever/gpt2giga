"""Responses feature orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from fastapi import HTTPException
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

    @staticmethod
    def _invalid_request(
        message: str,
        *,
        param: str | None = None,
        code: str | None = None,
    ) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": message,
                    "type": "invalid_request_error",
                    "param": param,
                    "code": code,
                }
            },
        )

    def resolve_request_model(
        self,
        data: ResponsesRequestData,
        *,
        response_store: ResponsesMetadataStore | None = None,
    ) -> str | None:
        """Resolve the effective request model for audit and response shaping."""
        explicit_model = get_request_model(data, default="")
        if explicit_model:
            return explicit_model

        request_payload = to_backend_payload(data)
        previous_response_id = request_payload.get("previous_response_id")
        if not isinstance(previous_response_id, str) or not previous_response_id:
            return None

        metadata = response_store.get(previous_response_id) if response_store else None
        if not isinstance(metadata, dict):
            return None

        stored_model = metadata.get("model")
        return stored_model if isinstance(stored_model, str) and stored_model else None

    def _validate_request_context(
        self,
        data: ResponsesRequestData,
        *,
        response_store: ResponsesMetadataStore | None = None,
    ) -> None:
        """Ensure the request carries enough state to execute safely."""
        if self.resolve_request_model(data, response_store=response_store):
            return

        if not self.uses_v2_backend:
            raise self._invalid_request("`model` is required.", param="model")

        request_payload = to_backend_payload(data)
        conversation = request_payload.get("conversation")
        if (
            isinstance(conversation, dict)
            and isinstance(conversation.get("id"), str)
            and conversation["id"]
        ):
            return

        if request_payload.get("previous_response_id") is not None:
            return

        raise self._invalid_request(
            "`model` is required unless continuing via `conversation.id` or `previous_response_id`.",
            param="model",
        )

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
        self._validate_request_context(data, response_store=response_store)
        request_model = self.resolve_request_model(data, response_store=response_store)
        request_payload = to_backend_payload(data)
        if request_model and not request_payload.get("model"):
            request_payload["model"] = request_model
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
                request_model or "unknown",
                response_id,
                response_store=response_store,
            )
        response = await giga_client.achat(prepared_request)
        return self.response_processor.process_response_api(
            request_payload,
            response,
            request_model or "unknown",
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
        self._validate_request_context(data, response_store=resolved_store)
        request_model = self.resolve_request_model(data, response_store=resolved_store)
        request_payload = to_backend_payload(data)
        if request_model and not request_payload.get("model"):
            request_payload["model"] = request_model
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
