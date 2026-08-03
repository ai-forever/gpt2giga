"""Explicit default and forced model selection semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ModelSelectionSource = Literal["forced", "requested", "default", "omitted"]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """Record the effective model and the policy input that selected it."""

    model: str | None
    source: ModelSelectionSource


@dataclass(frozen=True, slots=True)
class ModelSelectionPolicy:
    """Keep deployment defaults distinct from explicit forced overrides."""

    default_model: str | None = None
    forced_model: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "default_model", _non_blank(self.default_model))
        object.__setattr__(self, "forced_model", _non_blank(self.forced_model))

    def select(self, requested_model: Any = None) -> ModelSelection:
        """Resolve forced, requested, then default model precedence."""
        if self.forced_model is not None:
            return ModelSelection(self.forced_model, "forced")

        requested = _non_blank(requested_model)
        if requested is not None:
            return ModelSelection(requested, "requested")

        if self.default_model is not None:
            return ModelSelection(self.default_model, "default")

        return ModelSelection(None, "omitted")


def _non_blank(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value
