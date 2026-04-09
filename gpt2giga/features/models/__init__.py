"""Models capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gpt2giga.features.models.service import (
        ModelsService,
        get_models_service_from_state,
    )

__all__ = ["ModelsService", "get_models_service_from_state"]


def __getattr__(name: str) -> Any:
    """Lazily expose the models service surface."""
    if name == "ModelsService":
        from gpt2giga.features.models.service import ModelsService

        return ModelsService
    if name == "get_models_service_from_state":
        from gpt2giga.features.models.service import get_models_service_from_state

        return get_models_service_from_state
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
