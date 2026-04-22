"""Responses API v2 input normalization helpers."""

from gpt2giga.providers.gigachat.responses.input_messages import (
    ResponsesV2MessageBuilderMixin,
)


class ResponsesV2InputNormalizerMixin(ResponsesV2MessageBuilderMixin):
    """Normalize Responses API inputs into GigaChat v2 messages."""
