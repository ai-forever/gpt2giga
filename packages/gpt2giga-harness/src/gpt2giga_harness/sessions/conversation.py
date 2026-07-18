"""Active conversation projections over append-only retained messages."""

from __future__ import annotations

from collections.abc import Iterable

from gpt2giga_harness.sessions.models import HarnessMessage


EDITED_FROM_MESSAGE_ID = "edited_from_message_id"


def active_conversation_messages(
    messages: Iterable[HarnessMessage],
) -> tuple[HarnessMessage, ...]:
    """Project the latest edited branch without deleting retained run evidence."""
    active: list[HarnessMessage] = []
    for message in messages:
        edited_from = _edited_from_message_id(message)
        if edited_from is not None:
            source_index = next(
                (
                    index
                    for index, candidate in enumerate(active)
                    if candidate.id == edited_from
                ),
                None,
            )
            if source_index is not None:
                del active[source_index:]
        active.append(message)
    return tuple(active)


def history_before_edited_message(
    messages: Iterable[HarnessMessage],
    message_id: str,
) -> tuple[HarnessMessage, ...]:
    """Return history preceding the latest editable user message."""
    active = active_conversation_messages(messages)
    latest_user = next(
        (message for message in reversed(active) if message.role == "user"),
        None,
    )
    if latest_user is None or latest_user.id != message_id:
        raise ValueError("Only the latest user message can be edited")
    source_index = next(
        index for index, message in enumerate(active) if message.id == message_id
    )
    return active[:source_index]


def edited_message_metadata(message_id: str | None) -> dict[str, str]:
    """Build the content-free branch marker for a replacement user message."""
    return {EDITED_FROM_MESSAGE_ID: message_id} if message_id is not None else {}


def _edited_from_message_id(message: HarnessMessage) -> str | None:
    value = message.metadata.get(EDITED_FROM_MESSAGE_ID)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
