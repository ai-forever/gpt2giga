"""Files and batches normalization feature."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gpt2giga.features.files_batches.service import (
        FilesBatchesService,
        get_files_batches_service_from_state,
    )

__all__ = ["FilesBatchesService", "get_files_batches_service_from_state"]


def __getattr__(name: str) -> Any:
    """Lazily expose the files-batches service surface."""
    if name == "FilesBatchesService":
        from gpt2giga.features.files_batches.service import FilesBatchesService

        return FilesBatchesService
    if name == "get_files_batches_service_from_state":
        from gpt2giga.features.files_batches.service import (
            get_files_batches_service_from_state,
        )

        return get_files_batches_service_from_state
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
