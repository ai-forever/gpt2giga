"""GigaChat Responses API output mapping helpers."""

from gpt2giga.providers.gigachat.responses_output_items import (
    ResponsesOutputItemsMixin,
)
from gpt2giga.providers.gigachat.responses_result_builder import (
    ResponsesResultBuilderMixin,
)


class ResponseProcessorResponsesMixin(
    ResponsesResultBuilderMixin,
    ResponsesOutputItemsMixin,
):
    """Helpers specific to the Responses API output shape."""
