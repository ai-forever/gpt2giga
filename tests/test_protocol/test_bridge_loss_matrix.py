import json

import pytest
from pydantic import ValidationError

from gpt2giga.protocols.normalized.loss_matrix import (
    BRIDGE_LOSS_MATRIX_SCHEMA_VERSION,
    BRIDGE_LOSS_MATRIX_V1,
    BridgeLossCell,
    BridgeLossMatrix,
    BridgeSemantic,
    BridgeSemanticRule,
    BridgeSupportStatus,
    LossDisposition,
    PublicProtocol,
    UpstreamProvider,
    bridge_loss_matrix_json,
)


def test_bridge_loss_matrix_is_complete_and_explicit() -> None:
    identities = {
        (cell.public_protocol, cell.upstream_provider)
        for cell in BRIDGE_LOSS_MATRIX_V1.cells
    }

    assert identities == {
        (protocol, provider)
        for protocol in PublicProtocol
        for provider in UpstreamProvider
    }
    assert len(BRIDGE_LOSS_MATRIX_V1.cells) == 16
    assert {cell.status for cell in BRIDGE_LOSS_MATRIX_V1.cells} == {
        BridgeSupportStatus.STABLE,
        BridgeSupportStatus.TECHNICAL_PREVIEW,
        BridgeSupportStatus.BLOCKED,
    }
    for cell in BRIDGE_LOSS_MATRIX_V1.cells:
        assert {row.semantic for row in cell.semantics} == set(BridgeSemantic)


def test_normalized_responses_cell_is_preview_and_evidence_bound() -> None:
    cell = next(
        cell
        for cell in BRIDGE_LOSS_MATRIX_V1.cells
        if cell.public_protocol is PublicProtocol.OPENAI_RESPONSES
        and cell.upstream_provider is UpstreamProvider.GIGACHAT
    )

    assert cell.status is BridgeSupportStatus.TECHNICAL_PREVIEW
    assert cell.reason_ids == ("normalized_responses_parity_incomplete",)
    assert cell.evidence_ids == ("COR-01-CODEX-RESPONSES-2026-08-03",)


def test_bridge_loss_matrix_serialization_and_revision_are_deterministic() -> None:
    reordered = BridgeLossMatrix(cells=tuple(reversed(BRIDGE_LOSS_MATRIX_V1.cells)))
    payload = bridge_loss_matrix_json()

    assert reordered.canonical_json() == BRIDGE_LOSS_MATRIX_V1.canonical_json()
    assert reordered.revision == BRIDGE_LOSS_MATRIX_V1.revision
    assert payload["schema_version"] == BRIDGE_LOSS_MATRIX_SCHEMA_VERSION
    assert payload["matrix_revision"] == BRIDGE_LOSS_MATRIX_V1.revision
    assert payload["matrix_revision"].startswith("sha256:")
    assert len(payload["matrix_revision"]) == len("sha256:") + 64
    assert json.dumps(payload, sort_keys=True)


def test_bridge_loss_matrix_projection_is_isolated_from_caller_mutation() -> None:
    first = bridge_loss_matrix_json()
    first["cells"][0]["status"] = "tampered"

    second = bridge_loss_matrix_json()

    assert second["cells"][0]["status"] != "tampered"
    assert second["matrix_revision"] == BRIDGE_LOSS_MATRIX_V1.revision


def test_bridge_loss_matrix_revision_covers_semantic_evidence() -> None:
    payload = BRIDGE_LOSS_MATRIX_V1.canonical_payload()
    payload["cells"][0]["semantics"][0]["evidence_ids"] = ["changed-evidence"]
    changed = BridgeLossMatrix.model_validate(payload)

    assert changed.revision != BRIDGE_LOSS_MATRIX_V1.revision


def test_bridge_loss_matrix_rejects_incomplete_cells_and_matrix() -> None:
    cell_payload = BRIDGE_LOSS_MATRIX_V1.cells[0].model_dump(mode="json")
    cell_payload["semantics"] = cell_payload["semantics"][:-1]
    with pytest.raises(ValidationError, match="missing semantic rows"):
        BridgeLossCell.model_validate(cell_payload)

    with pytest.raises(ValidationError, match="missing cells"):
        BridgeLossMatrix(cells=BRIDGE_LOSS_MATRIX_V1.cells[:-1])


def test_conditional_semantics_require_one_named_predicate() -> None:
    with pytest.raises(ValidationError, match="require a predicate"):
        BridgeSemanticRule(
            semantic=BridgeSemantic.MULTIMODAL_INPUTS,
            disposition=LossDisposition.CONDITIONAL,
            reason_id="requires_reviewed_capability",
        )

    with pytest.raises(ValidationError, match="only conditional"):
        BridgeSemanticRule(
            semantic=BridgeSemantic.ROLES,
            disposition=LossDisposition.EXACT,
            reason_id="hermetic_facade_evidence",
            capability_predicate="capability.roles",
        )


def test_bridge_loss_matrix_projection_is_content_free() -> None:
    serialized = json.dumps(bridge_loss_matrix_json(), sort_keys=True).lower()

    assert "unknown" not in serialized
    assert "credential" not in serialized
    assert "api_key" not in serialized
    assert "base_url" not in serialized
    assert "prompt" not in serialized
