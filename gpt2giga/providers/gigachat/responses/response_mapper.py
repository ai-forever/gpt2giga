"""Structured response-side helpers for the GigaChat Responses pipeline."""

from gpt2giga.providers.gigachat.responses.result_builder import (
    ResponsesResultBuilderMixin,
)


class ResponseProcessorResponsesMixin(ResponsesResultBuilderMixin):
    """Helpers specific to the Responses API output shape."""
