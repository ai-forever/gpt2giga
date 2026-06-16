"""Helpers for selecting the upstream GigaChat API contract."""

from collections.abc import Callable
from typing import Literal

from starlette.requests import Request

GigaChatAPIMode = Literal["v1", "v2"]

_STATE_ATTR = "gigachat_api_mode_override"


def force_gigachat_api_mode(mode: GigaChatAPIMode) -> Callable[[Request], None]:
    """Set a per-request GigaChat API mode override."""

    def dependency(request: Request) -> None:
        setattr(request.state, _STATE_ATTR, mode)

    return dependency


def get_gigachat_api_mode_override(request: Request) -> GigaChatAPIMode | None:
    """Return the per-request API mode override, when a versioned route set it."""
    mode = getattr(request.state, _STATE_ATTR, None)
    if mode in {"v1", "v2"}:
        return mode
    return None


def resolve_gigachat_api_mode(request: Request) -> GigaChatAPIMode:
    """Resolve the GigaChat chat API mode for this request."""
    override = get_gigachat_api_mode_override(request)
    if override is not None:
        return override
    return getattr(request.app.state.config.proxy_settings, "gigachat_api_mode", "v1")
