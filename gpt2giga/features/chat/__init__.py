"""Chat-completions capability."""

from __future__ import annotations

from typing import Any

_chat_service_exports: tuple[Any, Any] | None = None


def __getattr__(name: str):
    if name not in {"ChatService", "get_chat_service_from_state"}:
        raise AttributeError(name)

    global _chat_service_exports
    if _chat_service_exports is None:
        from gpt2giga.features.chat.service import (
            ChatService,
            get_chat_service_from_state,
        )

        _chat_service_exports = (ChatService, get_chat_service_from_state)

    chat_service, get_chat_service = _chat_service_exports
    return chat_service if name == "ChatService" else get_chat_service


__all__ = ["ChatService", "get_chat_service_from_state"]
