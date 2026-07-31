from typing import Dict, List, Set

from gigachat.models import Messages

VALID_ROLES: Set[str] = {"system", "user", "assistant", "function"}

ROLE_MAPPING: Dict[str, str] = {
    "developer": "system",
    "tool": "function",
}


def map_role(role: str, is_first: bool, logger=None) -> str:
    """
    Maps a role to a valid GigaChat role.

    GigaChat only supports: system, user, assistant, function
    - system must be the first message only
    - developer -> system (if first) or user (if not first)
    - tool -> function
    - unknown roles -> user

    Args:
        role: Original role from OpenAI format
        is_first: Whether this is the first message (system allowed only here)
        logger: Optional logger for debug messages

    Returns:
        Valid GigaChat role
    """
    mapped_role = ROLE_MAPPING.get(role, role)

    if mapped_role == "system" and not is_first:
        return "user"

    if mapped_role not in VALID_ROLES:
        if logger:
            logger.debug(f"Unknown role '{role}' mapped to 'user'")
        return "user"

    return mapped_role


def merge_consecutive_messages(messages: List[Dict]) -> List[Dict]:
    """
    Merges consecutive messages with the same role.

    GigaChat works better when consecutive same-role messages are concatenated.
    This also helps avoid issues with message ordering.

    Args:
        messages: List of message dictionaries

    Returns:
        List of messages with consecutive same-role messages merged
    """
    if not messages:
        return messages

    merged: List[Dict] = []
    for message in messages:
        if not merged:
            merged.append(message)
            continue

        last = merged[-1]
        if (
            last["role"] == message["role"]
            and "function_call" not in last
            and "function_call" not in message
            and isinstance(last.get("content", ""), str)
            and isinstance(message.get("content", ""), str)
        ):
            last["content"] = (
                last.get("content", "") + "\n" + message.get("content", "")
            ).strip()
            if "attachments" in message:
                if "attachments" not in last:
                    last["attachments"] = []
                last["attachments"].extend(message["attachments"])
        else:
            merged.append(message)

    return merged


def collapse_user_messages(messages: List[Messages]) -> List[Messages]:
    """
    Collapses consecutive user messages into one.

    Args:
        messages: List of Messages objects

    Returns:
        List of Messages with consecutive user messages collapsed
    """
    collapsed_messages: List[Messages] = []
    prev_user_message = None
    content_parts: List[str] = []

    for message in messages:
        if message.role == "user" and prev_user_message is not None:
            content_parts.append(message.content)
        else:
            if content_parts:
                prev_user_message.content = "\n".join(
                    [prev_user_message.content] + content_parts
                )
                content_parts = []
            collapsed_messages.append(message)
            prev_user_message = message if message.role == "user" else None

    if content_parts and prev_user_message is not None:
        prev_user_message.content = "\n".join(
            [prev_user_message.content] + content_parts
        )

    return collapsed_messages


def ensure_system_first(messages: List[Dict]) -> List[Dict]:
    """
    Ensures system message is first in the list (if present).

    Args:
        messages: List of message dictionaries

    Returns:
        Messages with system message moved to front if needed
    """
    if not messages or messages[0].get("role") == "system":
        return messages

    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            system_msg = messages.pop(i)
            messages.insert(0, system_msg)
            break

    return messages


def limit_attachments(messages: List[Dict], max_total: int = 10, logger=None) -> None:
    """
    Limits the total number of attachments across all messages.

    Processes messages in reverse order (newest first) to preserve
    the most recent attachments.

    Args:
        messages: List of message dictionaries (modified in place)
        max_total: Maximum total attachments allowed
        logger: Optional logger for warnings
    """
    cur_attachment_count = 0
    for message in reversed(messages):
        message_attachments = len(message.get("attachments", []))
        if cur_attachment_count + message_attachments > max_total:
            allowed = max_total - cur_attachment_count
            message["attachments"] = message["attachments"][:allowed]
            if logger:
                logger.warning(f"Limited attachments in message to {allowed}")
            break
        cur_attachment_count += message_attachments
