from typing import Dict, List, Set

from gigachat.models import Messages

VALID_ROLES: Set[str] = {"system", "user", "assistant", "function"}

ROLE_MAPPING: Dict[str, str] = {
    "developer": "system",
    "tool": "function",
}


def map_role(role: str, is_first: bool, logger=None) -> str:
    """Map an external role to a valid GigaChat role."""
    mapped_role = ROLE_MAPPING.get(role, role)

    if mapped_role == "system" and not is_first:
        return "user"

    if mapped_role not in VALID_ROLES:
        if logger:
            logger.debug(f"Unknown role '{role}' mapped to 'user'")
        return "user"

    return mapped_role


def merge_consecutive_messages(messages: List[Dict]) -> List[Dict]:
    """Merge adjacent messages with the same role."""
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
    """Collapse consecutive user messages into one."""
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
    """Move the first system message to the front when needed."""
    if not messages or messages[0].get("role") == "system":
        return messages

    for index, message in enumerate(messages):
        if message.get("role") == "system":
            system_message = messages.pop(index)
            messages.insert(0, system_message)
            break

    return messages


def limit_attachments(messages: List[Dict], max_total: int = 10, logger=None) -> None:
    """Trim attachments from oldest messages once the total limit is exceeded."""
    current_attachment_count = 0
    for message in reversed(messages):
        message_attachments = len(message.get("attachments", []))
        if current_attachment_count + message_attachments > max_total:
            allowed = max_total - current_attachment_count
            message["attachments"] = message["attachments"][:allowed]
            if logger:
                logger.warning(f"Limited attachments in message to {allowed}")
            break
        current_attachment_count += message_attachments
