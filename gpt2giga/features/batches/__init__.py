"""Batches capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gpt2giga.features.batches.validation import (
    BatchInputValidator,
    detect_batch_input_format,
    parse_jsonl_with_diagnostics,
    validate_batch_input_bytes,
    validate_batch_input_rows,
)
from gpt2giga.features.batches.validation_contracts import (
    BatchValidationIssue,
    BatchValidationReport,
    BatchValidationSeverity,
    BatchValidationSummary,
)

__all__ = [
    "BatchValidationIssue",
    "BatchValidationReport",
    "BatchValidationSeverity",
    "BatchValidationSummary",
    "BatchInputValidator",
    "BatchesService",
    "detect_batch_input_format",
    "get_batches_service_from_state",
    "parse_jsonl_with_diagnostics",
    "validate_batch_input_bytes",
    "validate_batch_input_rows",
]

if TYPE_CHECKING:
    from gpt2giga.features.batches.service import (
        BatchesService,
        get_batches_service_from_state,
    )


def __getattr__(name: str) -> Any:
    """Lazily expose the batches service surface."""
    if name == "BatchesService":
        from gpt2giga.features.batches.service import BatchesService

        return BatchesService
    if name == "get_batches_service_from_state":
        from gpt2giga.features.batches.service import get_batches_service_from_state

        return get_batches_service_from_state
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
