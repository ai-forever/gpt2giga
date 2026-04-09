"""Shared helpers for OpenAI-compatible API routes."""

from gpt2giga.common.tools import convert_tool_to_giga_functions


def populate_giga_functions(data: dict, logger) -> None:
    """Populate GigaChat-compatible function definitions when tools are present."""
    if "tools" not in data and "functions" not in data:
        return
    data["functions"] = convert_tool_to_giga_functions(data)
    if logger:
        logger.debug(f"Functions count: {len(data['functions'])}")
