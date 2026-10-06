"""Read effective settings from prepared GigaChat requests."""

from collections.abc import Mapping
from typing import Any


def parallel_tool_calls_enabled(request: Any) -> bool:
    """Return the prepared v2 setting, or the GigaChat default of false."""
    options = (
        request.get("model_options")
        if isinstance(request, Mapping)
        else getattr(request, "model_options", None)
    )
    value = (
        options.get("parallel_tool_calls")
        if isinstance(options, Mapping)
        else getattr(options, "parallel_tool_calls", None)
    )
    return value is True
