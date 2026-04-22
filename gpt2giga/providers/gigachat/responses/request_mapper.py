"""Structured request-side helpers for the GigaChat Responses pipeline."""

from gpt2giga.providers.gigachat.responses.backend_request import (
    ResponsesV2BackendRequestMixin,
)


class RequestTransformerResponsesV2Mixin(ResponsesV2BackendRequestMixin):
    """Helpers for native Responses API v2 payload assembly."""
