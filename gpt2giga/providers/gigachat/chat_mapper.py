"""GigaChat chat-completions mapping entry point."""

from __future__ import annotations

import inspect
from typing import Any

from gpt2giga.features.chat.contracts import ChatRequestData


class GigaChatChatMapper:
    """Wrap chat-specific request/response mapping for the GigaChat provider."""

    def __init__(
        self,
        *,
        request_transformer=None,
        response_processor=None,
        backend_mode: str = "v1",
    ):
        self.request_transformer = request_transformer
        self.response_processor = response_processor
        self.backend_mode = backend_mode

    @property
    def uses_v2_backend(self) -> bool:
        """Return ``True`` when chat-like routes should use the v2 backend."""
        return self.backend_mode == "v2"

    @staticmethod
    def _accepts_giga_client(prepare_request) -> bool:
        parameters = tuple(inspect.signature(prepare_request).parameters.values())
        return (
            any(
                parameter.kind
                in {
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                }
                for parameter in parameters
            )
            or len(parameters) >= 2
        )

    def _require_request_transformer(self):
        if self.request_transformer is None:
            raise RuntimeError("Chat request transformer is not configured.")
        return self.request_transformer

    def _require_response_processor(self):
        if self.response_processor is None:
            raise RuntimeError("Chat response processor is not configured.")
        return self.response_processor

    async def prepare_request(
        self,
        data: ChatRequestData,
        giga_client: Any = None,
    ) -> dict[str, Any]:
        """Prepare a GigaChat chat request."""
        request_transformer = self._require_request_transformer()
        prepare_request = (
            request_transformer.prepare_chat_completion_v2
            if self.uses_v2_backend
            else request_transformer.prepare_chat_completion
        )
        if giga_client is None or not self._accepts_giga_client(prepare_request):
            return await prepare_request(data)
        return await prepare_request(data, giga_client)

    def process_response(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Any = None,
    ) -> dict[str, Any]:
        """Convert a non-streaming GigaChat chat response."""
        response_processor = self._require_response_processor()
        if self.uses_v2_backend:
            return response_processor.process_response_v2(
                giga_resp,
                gpt_model,
                response_id,
                request_data=request_data,
            )
        return response_processor.process_response(
            giga_resp,
            gpt_model,
            response_id,
            request_data=request_data,
        )

    def normalize_provider_response(self, giga_resp: Any) -> dict[str, Any]:
        """Normalize a raw GigaChat response for provider-owned adapters."""
        response_processor = self._require_response_processor()
        if self.uses_v2_backend:
            return response_processor.normalize_chat_v2_response(giga_resp)
        return giga_resp.model_dump()

    def process_stream_chunk(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Any = None,
    ) -> dict[str, Any]:
        """Convert a streaming GigaChat chat chunk."""
        response_processor = self._require_response_processor()
        if self.uses_v2_backend:
            return response_processor.process_stream_chunk_v2(
                giga_resp,
                gpt_model,
                response_id,
                request_data=request_data,
            )
        return response_processor.process_stream_chunk(
            giga_resp,
            gpt_model,
            response_id,
            request_data=request_data,
        )
