"""GigaChat provider client helpers."""

from typing import Any

from gigachat import GigaChat

from gpt2giga.providers.gigachat.types import SupportsAclose


def create_gigachat_client(settings: Any) -> GigaChat:
    """Create a GigaChat SDK client from settings."""
    return GigaChat(**settings.model_dump())


async def close_gigachat_client(client: SupportsAclose | None, logger: Any) -> None:
    """Close a GigaChat SDK client without failing application shutdown."""
    if client is None:
        return
    try:
        await client.aclose()
        logger.info("GigaChat client closed")
    except Exception as exc:
        logger.warning(f"Error closing GigaChat client: {exc}")
