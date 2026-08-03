"""Contract tests for model-aware tri-state capabilities."""

import json

import pytest
from pydantic import ValidationError

from gpt2giga.capabilities import (
    CapabilityDecision,
    CapabilityKey,
    CapabilityLayer,
    CapabilityScope,
    CapabilitySource,
    CapabilityState,
    capability_revision,
)


def _revision(label: str) -> str:
    return capability_revision({"label": label})


def _decision(
    key: CapabilityKey,
    state: CapabilityState = CapabilityState.UNKNOWN,
) -> CapabilityDecision:
    return CapabilityDecision(
        state=state,
        reason_id=f"{key.value}_not_resolved",
        source=CapabilitySource.UNRESOLVED,
        evidence_ids=("CAP-CONTRACT-01", "CAP-CONTRACT-01"),
        revision=_revision(key.value),
    )


def test_capability_vocabulary_is_complete_and_tri_state() -> None:
    assert {item.value for item in CapabilityState} == {
        "supported",
        "unsupported",
        "unknown",
    }
    assert {item.value for item in CapabilityKey} == {
        "text_input",
        "streaming",
        "function_tools",
        "hosted_web_search",
        "hosted_url_extraction",
        "hosted_code_interpreter",
        "hosted_image_generation",
        "hosted_3d_generation",
        "parallel_tool_calls",
        "json_schema_output",
        "reasoning_controls",
        "reasoning_summary",
        "previous_response_state",
        "conversation_state",
        "file_input",
        "image_input",
        "usage_tokens",
        "cancellation",
        "disconnect",
    }


def test_decision_canonicalizes_evidence_and_forbids_unknown_fields() -> None:
    decision = _decision(CapabilityKey.TEXT_INPUT)

    assert decision.evidence_ids == ("CAP-CONTRACT-01",)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapabilityDecision.model_validate(
            {
                **decision.model_dump(mode="json"),
                "provider_response": "must-not-be-retained",
            }
        )


def test_layer_requires_one_explicit_decision_per_capability() -> None:
    decisions = {key: _decision(key) for key in CapabilityKey}
    layer = CapabilityLayer(
        scope=CapabilityScope.MODEL,
        scope_id="GigaChat-2-Max",
        capabilities=decisions,
        revision=_revision("layer"),
    )

    assert tuple(layer.capabilities) == tuple(
        sorted(CapabilityKey, key=lambda item: item.value)
    )
    decisions.pop(CapabilityKey.TEXT_INPUT)
    with pytest.raises(ValidationError, match="text_input"):
        CapabilityLayer(
            scope=CapabilityScope.MODEL,
            scope_id="GigaChat-2-Max",
            capabilities=decisions,
            revision=_revision("incomplete"),
        )


def test_revision_is_deterministic_and_content_sensitive() -> None:
    first = capability_revision({"b": [2, 1], "a": "value"})
    reordered = capability_revision({"a": "value", "b": [2, 1]})
    changed = capability_revision({"a": "value", "b": [1, 2]})

    assert first == reordered
    assert first != changed
    assert json.dumps({"revision": first}).startswith('{"revision": "sha256:')
