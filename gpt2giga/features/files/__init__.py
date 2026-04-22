"""Files capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gpt2giga.features.files.service import (
        FilesService,
        get_files_service_from_state,
    )

__all__ = ["FilesService", "get_files_service_from_state"]


def __getattr__(name: str) -> Any:
    """Lazily expose the files service surface."""
    if name == "FilesService":
        from gpt2giga.features.files.service import FilesService

        return FilesService
    if name == "get_files_service_from_state":
        from gpt2giga.features.files.service import get_files_service_from_state

        return get_files_service_from_state
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
