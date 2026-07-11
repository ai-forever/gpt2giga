"""GigaChat provider protocol types."""

from typing import Any, Protocol


class SupportsAclose(Protocol):
    """Represent GigaChat-like clients with async close support."""

    async def aclose(self) -> Any:
        """Close the client."""
