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


def test_structured_responses_pipeline_exports_expected_mixins() -> None:
    """Keep the structured Responses helper package layout explicit."""
    assert (
        StructuredResponsesV2BackendRequestMixin.__name__
        == "ResponsesV2BackendRequestMixin"
    )
    assert (
        StructuredResponsesV2InputNormalizerMixin.__name__
        == "ResponsesV2InputNormalizerMixin"
    )
    assert (
        StructuredResponsesV2ModelOptionsMixin.__name__
        == "ResponsesV2ModelOptionsMixin"
    )
    assert StructuredResponsesV2ThreadingMixin.__name__ == "ResponsesV2ThreadingMixin"
    assert (
        StructuredResponsesV2ToolMappingMixin.__name__ == "ResponsesV2ToolMappingMixin"
    )
    assert (
        StructuredRequestTransformerResponsesV2Mixin.__name__
        == "RequestTransformerResponsesV2Mixin"
    )
    assert StructuredResponsesOutputItemsMixin.__name__ == "ResponsesOutputItemsMixin"
    assert (
        StructuredResponsesResultBuilderMixin.__name__ == "ResponsesResultBuilderMixin"
    )
    assert (
        StructuredResponseProcessorResponsesMixin.__name__
        == "ResponseProcessorResponsesMixin"
    )
