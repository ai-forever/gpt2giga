"""Best-effort normalized shadow-mode hooks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request

from gpt2giga.core.context import get_request_context
from gpt2giga.models.config import ProxySettings
from gpt2giga.protocols.normalized.diagnostics import (
    NormalizationDiagnosticEvent,
    build_normalization_diagnostic,
)
from gpt2giga.protocols.normalized.models import NormalizedChatRequest

_MAX_SHADOW_DIAGNOSTIC_EVENTS = 100


def is_shadow_normalization_enabled(settings: ProxySettings) -> bool:
    """Return whether normalized shadow translation should run."""
    return settings.normalization_mode == "shadow"


async def run_openai_chat_shadow_normalization(
    request: Request,
    payload: Mapping[str, Any],
) -> NormalizedChatRequest | None:
    """Run OpenAI chat normalization in shadow mode without breaking requests."""
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if settings is None or not is_shadow_normalization_enabled(settings):
        return None

    adapter = getattr(state, "openai_protocol_adapter", None)
    if adapter is None:
        from gpt2giga.protocols.openai import OpenAIProtocolAdapter

        adapter = OpenAIProtocolAdapter()

    try:
        normalized = await adapter.to_normalized(
            payload,
            context=get_request_context(),
        )
        _record_shadow_diagnostic(
            state,
            build_normalization_diagnostic(
                request_id=_request_id(),
                route=request.url.path,
                normalization_status="ok",
                normalized_payload=normalized,
            ),
        )
        return normalized
    except Exception as exc:  # pragma: no cover - no-raise branch covered by route test
        _record_shadow_diagnostic(
            state,
            build_normalization_diagnostic(
                request_id=_request_id(),
                route=request.url.path,
                normalization_status="error",
                errors=[type(exc).__name__],
            ),
        )
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.warning(
                "OpenAI normalized shadow translation failed: {}",
                type(exc).__name__,
            )
        return None


def _request_id() -> str | None:
    context = get_request_context()
    return context.request_id if context is not None else None


def _record_shadow_diagnostic(
    state: Any,
    event: NormalizationDiagnosticEvent,
) -> None:
    events = getattr(state, "normalization_shadow_events", None)
    if not isinstance(events, list):
        events = []
        state.normalization_shadow_events = events
    events.append(event)
    if len(events) > _MAX_SHADOW_DIAGNOSTIC_EVENTS:
        del events[: len(events) - _MAX_SHADOW_DIAGNOSTIC_EVENTS]

    logger = getattr(state, "logger", None)
    if logger is not None:
        logger.bind(normalization=event.to_json_dict()).debug(
            "Normalized shadow diagnostic"
        )
