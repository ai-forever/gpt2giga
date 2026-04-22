"""Responses API v2 input normalization helpers."""

from gpt2giga.providers.gigachat.responses.input_content import (
    ResponsesV2ContentPartsMixin,
)
from gpt2giga.providers.gigachat.responses.input_history import (
    ResponsesV2HistoryRepairMixin,
)
from gpt2giga.providers.gigachat.responses.input_messages import (
    ResponsesV2MessageBuilderMixin,
)


class ResponsesV2InputNormalizerMixin(
    ResponsesV2MessageBuilderMixin,
    ResponsesV2HistoryRepairMixin,
    ResponsesV2ContentPartsMixin,
):
    """Normalize Responses API inputs into GigaChat v2 messages."""
