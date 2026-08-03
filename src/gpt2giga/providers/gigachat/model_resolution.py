"""Resolve GigaChat models without inventing an upstream default."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from gpt2giga.common.model_concurrency import ProviderName
from gpt2giga.models.catalog import ModelSelectionPolicy

ModelSource = Literal["forced", "payload", "settings", "assistant", "thread"]
GigaChatApiMode = Literal["v1", "v2"]


@dataclass(frozen=True)
class ResolvedUpstreamModel:
    """Separate the optional upstream model from the required limiter identity."""

    model: str | None
    limiter_key: str
    source: ModelSource


class UpstreamModelRequiredError(Exception):
    """Signal that a request cannot select a GigaChat model safely."""

    message = (
        "An upstream GigaChat model is required. Forward a request model or "
        "configure GIGACHAT_MODEL."
    )

    def __init__(self, *, provider: ProviderName = "openai") -> None:
        self.provider = provider
        super().__init__(self.message)


def resolve_upstream_model(
    payload: Any,
    config: Any,
    *,
    forced_model: Any = None,
    api_mode: GigaChatApiMode = "v1",
    provider: ProviderName = "openai",
) -> ResolvedUpstreamModel:
    """Resolve model precedence used by every GigaChat chat-like call."""
    settings = getattr(config, "gigachat_settings", None)
    selection = ModelSelectionPolicy(
        default_model=_non_blank_string(getattr(settings, "model", None)),
        forced_model=_non_blank_string(forced_model),
    ).select(_field(payload, "model"))
    if selection.model is not None:
        source: ModelSource
        if selection.source == "requested":
            source = "payload"
        elif selection.source == "default":
            source = "settings"
        else:
            source = "forced"
        return ResolvedUpstreamModel(selection.model, selection.model, source)

    if api_mode == "v2":
        assistant_id = _non_blank_string(_field(payload, "assistant_id"))
        if assistant_id is not None:
            return ResolvedUpstreamModel(
                model=None,
                limiter_key=f"assistant:{assistant_id}",
                source="assistant",
            )

        storage = _field(payload, "storage")
        thread_id = _non_blank_string(_field(storage, "thread_id"))
        if thread_id is not None:
            return ResolvedUpstreamModel(
                model=None,
                limiter_key=f"thread:{thread_id}",
                source="thread",
            )

    raise UpstreamModelRequiredError(provider=provider)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _non_blank_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value
