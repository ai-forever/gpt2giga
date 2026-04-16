"""Public compatibility facade for Responses streaming."""

from gpt2giga.features.responses._streaming import (
    ResponsesStreamEventSequencer,
    stream_responses_generator,
)

__all__ = ["ResponsesStreamEventSequencer", "stream_responses_generator"]
