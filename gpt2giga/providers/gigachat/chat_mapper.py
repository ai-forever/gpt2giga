"""GigaChat chat-completions mapping entry point."""

from __future__ import annotations

import inspect
from typing import Any, Optional

from gigachat import GigaChat


class GigaChatChatMapper:
    """Wrap chat-specific request/response mapping for the GigaChat provider."""

    def __init__(self, *, request_transformer=None, response_processor=None):
        self.request_transformer = request_transformer
        self.response_processor = response_processor

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
        data: dict[str, Any],
        giga_client: Optional[GigaChat] = None,
    ) -> dict[str, Any]:
        """Prepare a GigaChat chat request."""
        request_transformer = self._require_request_transformer()
        prepare_request = request_transformer.prepare_chat_completion
        if giga_client is None or not self._accepts_giga_client(prepare_request):
            return await prepare_request(data)
        return await prepare_request(data, giga_client)

    def process_response(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Convert a non-streaming GigaChat chat response."""
        response_processor = self._require_response_processor()
        return response_processor.process_response(
            giga_resp,
            gpt_model,
            response_id,
            request_data=request_data,
        )

    def process_stream_chunk(
        self,
        giga_resp: Any,
        gpt_model: str,
        response_id: str,
        request_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Convert a streaming GigaChat chat chunk."""
        response_processor = self._require_response_processor()
        return response_processor.process_stream_chunk(
            giga_resp,
            gpt_model,
            response_id,
            request_data=request_data,
        )
