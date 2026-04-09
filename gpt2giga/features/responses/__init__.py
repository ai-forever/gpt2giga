"""Responses capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gpt2giga.features.responses.service import (
        ResponsesService,
        get_responses_service_from_state,
    )

__all__ = ["ResponsesService", "get_responses_service_from_state"]


def __getattr__(name: str) -> Any:
    """Lazily expose the responses service surface."""
    if name == "ResponsesService":
        from gpt2giga.features.responses.service import ResponsesService

        return ResponsesService
    if name == "get_responses_service_from_state":
        from gpt2giga.features.responses.service import get_responses_service_from_state

        return get_responses_service_from_state
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
