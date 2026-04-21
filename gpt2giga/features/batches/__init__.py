"""Batches capability."""

from gpt2giga.features.batches.service import (
    BatchesService,
    get_batches_service_from_state,
)
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
