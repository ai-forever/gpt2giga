from dataclasses import replace

import pytest

from gpt2giga_harness.sessions.conversation import (
    active_conversation_messages,
    edited_message_metadata,
    history_before_edited_message,
)
from gpt2giga_harness.sessions.models import HarnessMessage


def test_active_conversation_replaces_the_latest_user_turn_append_only():
    first_user = _message("user-1", "user", "first")
    first_assistant = _message("assistant-1", "assistant", "first answer")
    edited_user = _message("user-2", "user", "old prompt")
    deleted_assistant = _message("assistant-2", "assistant", "old answer")
    replacement = replace(
        _message("user-3", "user", "new prompt"),
        metadata=edited_message_metadata(edited_user.id),
    )
    new_assistant = _message("assistant-3", "assistant", "new answer")

    retained = (
        first_user,
        first_assistant,
        edited_user,
        deleted_assistant,
        replacement,
        new_assistant,
    )

    assert [message.id for message in active_conversation_messages(retained)] == [
        "user-1",
        "assistant-1",
        "user-3",
        "assistant-3",
    ]
    assert history_before_edited_message(retained, replacement.id) == (
        first_user,
        first_assistant,
    )


def test_only_latest_active_user_message_can_be_edited():
    retained = (
        _message("user-1", "user", "first"),
        _message("assistant-1", "assistant", "answer"),
        _message("user-2", "user", "second"),
    )

    with pytest.raises(ValueError, match="Only the latest user message"):
        history_before_edited_message(retained, "user-1")


def _message(message_id: str, role: str, content: str) -> HarnessMessage:
    return HarnessMessage(
        id=message_id,
        session_id="session-1",
        run_id=f"run-{message_id}",
        role=role,
        content=content,
        created_at="2026-07-18T00:00:00Z",
    )
