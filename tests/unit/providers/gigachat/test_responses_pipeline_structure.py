"""Regression coverage for the structured Responses pipeline layout."""

from gpt2giga.providers.gigachat.responses.backend_request import (
    ResponsesV2BackendRequestMixin as StructuredResponsesV2BackendRequestMixin,
)
from gpt2giga.providers.gigachat.responses.input_normalizer import (
    ResponsesV2InputNormalizerMixin as StructuredResponsesV2InputNormalizerMixin,
)
from gpt2giga.providers.gigachat.responses.model_options import (
    ResponsesV2ModelOptionsMixin as StructuredResponsesV2ModelOptionsMixin,
)
from gpt2giga.providers.gigachat.responses.output_items import (
    ResponsesOutputItemsMixin as StructuredResponsesOutputItemsMixin,
)
from gpt2giga.providers.gigachat.responses.request_mapper import (
    RequestTransformerResponsesV2Mixin as StructuredRequestTransformerResponsesV2Mixin,
)
from gpt2giga.providers.gigachat.responses.response_mapper import (
    ResponseProcessorResponsesMixin as StructuredResponseProcessorResponsesMixin,
)
from gpt2giga.providers.gigachat.responses.result_builder import (
    ResponsesResultBuilderMixin as StructuredResponsesResultBuilderMixin,
)
from gpt2giga.providers.gigachat.responses.threading import (
    ResponsesV2ThreadingMixin as StructuredResponsesV2ThreadingMixin,
)
from gpt2giga.providers.gigachat.responses.tool_mapping import (
    ResponsesV2ToolMappingMixin as StructuredResponsesV2ToolMappingMixin,
)
from gpt2giga.providers.gigachat.responses_backend_request import (
    ResponsesV2BackendRequestMixin,
)
from gpt2giga.providers.gigachat.responses_input_normalizer import (
    ResponsesV2InputNormalizerMixin,
)
from gpt2giga.providers.gigachat.responses_options import ResponsesV2ModelOptionsMixin
from gpt2giga.providers.gigachat.responses_output_items import ResponsesOutputItemsMixin
from gpt2giga.providers.gigachat.responses_request_mapper import (
    RequestTransformerResponsesV2Mixin,
)
from gpt2giga.providers.gigachat.responses_response_mapper import (
    ResponseProcessorResponsesMixin,
)
from gpt2giga.providers.gigachat.responses_result_builder import (
    ResponsesResultBuilderMixin,
)
from gpt2giga.providers.gigachat.responses_threading import ResponsesV2ThreadingMixin
from gpt2giga.providers.gigachat.responses_tool_mapping import (
    ResponsesV2ToolMappingMixin,
)


def test_legacy_responses_import_paths_reexport_structured_pipeline() -> None:
    """Keep the old Responses helper imports aligned with the new package layout."""
    assert ResponsesV2BackendRequestMixin is StructuredResponsesV2BackendRequestMixin
    assert ResponsesV2InputNormalizerMixin is StructuredResponsesV2InputNormalizerMixin
    assert ResponsesV2ModelOptionsMixin is StructuredResponsesV2ModelOptionsMixin
    assert ResponsesV2ThreadingMixin is StructuredResponsesV2ThreadingMixin
    assert ResponsesV2ToolMappingMixin is StructuredResponsesV2ToolMappingMixin
    assert (
        RequestTransformerResponsesV2Mixin
        is StructuredRequestTransformerResponsesV2Mixin
    )
    assert ResponsesOutputItemsMixin is StructuredResponsesOutputItemsMixin
    assert ResponsesResultBuilderMixin is StructuredResponsesResultBuilderMixin
    assert ResponseProcessorResponsesMixin is StructuredResponseProcessorResponsesMixin
