"""Content-free capability evidence for the Anthropic upstream lane."""

from __future__ import annotations

from typing import Any

from gpt2giga.providers.anthropic.adapter import (
    ANTHROPIC_IMPLEMENTED_FEATURES_V1,
)


ANTHROPIC_CAPABILITY_EVIDENCE_SCHEMA_VERSION = (
    "gpt2giga.anthropic-capability-evidence.v1"
)

_BLOCKED_SEMANTICS = {
    "citations": "anthropic_citations_not_normalized_v1",
    "computer_and_code_execution": "anthropic_execution_tools_not_admitted_v1",
    "files_and_documents": "anthropic_files_not_admitted_v1",
    "hosted_provider_tools": "anthropic_hosted_tools_not_admitted_v1",
    "image_inputs": "anthropic_images_not_admitted_v1",
    "reasoning_controls_and_summaries": "anthropic_reasoning_not_admitted_v1",
    "structured_output": "anthropic_structured_output_not_admitted_v1",
}


def anthropic_capability_evidence() -> dict[str, Any]:
    """Return deterministic provider facts for the bridge-matrix owner."""
    return {
        "schema_version": ANTHROPIC_CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        "provider_kind": "anthropic",
        "support_status": "technical_preview",
        "exact_normalized_features": sorted(
            feature.value for feature in ANTHROPIC_IMPLEMENTED_FEATURES_V1
        ),
        "blocked_semantics": [
            {
                "semantic": semantic,
                "status": "blocked",
                "reason_id": reason_id,
            }
            for semantic, reason_id in sorted(_BLOCKED_SEMANTICS.items())
        ],
        "evidence_ids": ["ANT-01", "ANT-02", "ANT-03"],
    }
