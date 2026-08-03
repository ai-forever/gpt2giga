"""Contract tests for model-aware tri-state capabilities."""

import json

import pytest
from pydantic import ValidationError

from gpt2giga.capabilities import (
    CAPABILITY_KEYS_V1,
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
    assert CapabilityState.SUPPORTED.value == "supported"
    assert CapabilityState.UNSUPPORTED.value == "unsupported"
    assert CapabilityState.UNKNOWN.value == "unknown"
    assert tuple(item.name for item in CAPABILITY_KEYS_V1) == tuple(
        CapabilityKey.__members__
    )


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
    decisions = {key: _decision(key) for key in CAPABILITY_KEYS_V1}
    layer = CapabilityLayer(
        scope=CapabilityScope.MODEL,
        scope_id="GigaChat-2-Max",
        capabilities=decisions,
        revision=_revision("layer"),
    )

    assert tuple(layer.capabilities) == tuple(
        sorted(CAPABILITY_KEYS_V1, key=lambda item: item.value)
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
