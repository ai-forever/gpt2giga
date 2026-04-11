"""GigaChat Responses API v2 request mapping helpers."""

from gpt2giga.providers.gigachat.responses_backend_request import (
    ResponsesV2BackendRequestMixin,
)
from gpt2giga.providers.gigachat.responses_input_normalizer import (
    ResponsesV2InputNormalizerMixin,
)
from gpt2giga.providers.gigachat.responses_options import (
    ResponsesV2ModelOptionsMixin,
)
from gpt2giga.providers.gigachat.responses_threading import (
    ResponsesV2ThreadingMixin,
)
from gpt2giga.providers.gigachat.responses_tool_mapping import (
    ResponsesV2ToolMappingMixin,
)


class RequestTransformerResponsesV2Mixin(
    ResponsesV2BackendRequestMixin,
    ResponsesV2ModelOptionsMixin,
    ResponsesV2InputNormalizerMixin,
    ResponsesV2ThreadingMixin,
    ResponsesV2ToolMappingMixin,
):
    """Helpers for native Responses API v2 payloads."""
