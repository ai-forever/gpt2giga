"""Structured request-side helpers for the GigaChat Responses pipeline."""

from gpt2giga.providers.gigachat.responses.backend_request import (
    ResponsesV2BackendRequestMixin,
)
from gpt2giga.providers.gigachat.responses.input_normalizer import (
    ResponsesV2InputNormalizerMixin,
)
from gpt2giga.providers.gigachat.responses.model_options import (
    ResponsesV2ModelOptionsMixin,
)
from gpt2giga.providers.gigachat.responses.threading import (
    ResponsesV2ThreadingMixin,
)
from gpt2giga.providers.gigachat.responses.tool_mapping import (
    ResponsesV2ToolMappingMixin,
)


class RequestTransformerResponsesV2Mixin(
    ResponsesV2BackendRequestMixin,
    ResponsesV2ModelOptionsMixin,
    ResponsesV2InputNormalizerMixin,
    ResponsesV2ThreadingMixin,
    ResponsesV2ToolMappingMixin,
):
    """Helpers for native Responses API v2 payload assembly."""
