"""Deterministic execution-mode selection for OpenAI Responses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from gpt2giga.core.context import update_request_context
from gpt2giga.providers.profiles import ProviderAliasError, ProviderKind


class ResponsesExecutionMode(str, Enum):
    """Name the only supported Responses execution owners."""

    NATIVE_GIGACHAT = "native_gigachat"
    NORMALIZED_BRIDGE = "normalized_bridge"


@dataclass(frozen=True)
class ResponsesExecutionSelection:
    """Record the immutable pre-dispatch execution decision."""

    mode: ResponsesExecutionMode
    reason: str
    route: Any | None = None


def select_responses_execution(
    state: Any,
    *,
    requested_model: Any,
) -> ResponsesExecutionSelection:
    """Select one execution owner from the startup-owned provider registry."""
    registry = getattr(state, "provider_registry", None)
    if registry is None:
        injected_adapter = getattr(state, "responses_provider_adapter", None)
        selection = ResponsesExecutionSelection(
            mode=(
                ResponsesExecutionMode.NORMALIZED_BRIDGE
                if injected_adapter is not None
                else ResponsesExecutionMode.NATIVE_GIGACHAT
            ),
            reason=(
                "injected_normalized_adapter"
                if injected_adapter is not None
                else "native_gigachat_default"
            ),
        )
        _record_selection(selection, requested_model=requested_model)
        return selection

    try:
        route = registry.resolve(requested_model)
    except ProviderAliasError:
        if not _is_config_free_gigachat_registry(registry):
            raise
        selection = ResponsesExecutionSelection(
            mode=ResponsesExecutionMode.NATIVE_GIGACHAT,
            reason="config_free_gigachat_model",
        )
        _record_selection(selection, requested_model=requested_model)
        return selection

    mode = (
        ResponsesExecutionMode.NATIVE_GIGACHAT
        if route.provider_kind is ProviderKind.GIGACHAT
        else ResponsesExecutionMode.NORMALIZED_BRIDGE
    )
    selection = ResponsesExecutionSelection(
        mode=mode,
        reason=(
            "gigachat_provider_route"
            if mode is ResponsesExecutionMode.NATIVE_GIGACHAT
            else "cross_provider_route"
        ),
        route=route,
    )
    _record_selection(selection, requested_model=requested_model)
    return selection


def _is_config_free_gigachat_registry(registry: Any) -> bool:
    """Recognize the config-free dynamic GigaChat route owner."""
    profiles = tuple(getattr(getattr(registry, "config", None), "profiles", ()))
    return len(profiles) == 1 and (
        profiles[0].profile_id == "native-gigachat"
        and profiles[0].provider_kind is ProviderKind.GIGACHAT
    )


def _record_selection(
    selection: ResponsesExecutionSelection,
    *,
    requested_model: Any,
) -> None:
    route = selection.route
    update_request_context(
        model_requested=requested_model,
        metadata={
            "responses_execution_mode": selection.mode.value,
            "responses_execution_reason": selection.reason,
        },
        bridge_route=route.execution_context() if route is not None else None,
    )
