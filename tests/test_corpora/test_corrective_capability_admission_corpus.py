"""Tri-state pre-dispatch contracts for the corrective capability corpus."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any


CORPUS = (
    Path(__file__).parents[1]
    / "corpora"
    / "correction"
    / "v1"
    / "capability_admission.json"
)
CAPABILITY_STATES = {"supported", "unsupported", "unknown"}
COORDINATE_KEYS = {
    "api_mode",
    "model_id",
    "provider_kind",
    "public_protocol",
    "route_policy",
    "semantic",
}


def _load() -> dict[str, Any]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_admission_cases_bind_every_decision_to_full_runtime_coordinates() -> None:
    corpus = _load()
    case_ids: set[str] = set()

    for case in corpus["cases"]:
        assert case["id"] not in case_ids
        case_ids.add(case["id"])
        assert set(case["coordinates"]) == COORDINATE_KEYS
        assert case["decision"]["state"] in CAPABILITY_STATES
        assert case["decision"]["reason_id"]
        assert case["decision"]["evidence_revision"]


def test_each_representative_model_has_supported_unsupported_and_unknown_evidence() -> (
    None
):
    states_by_model: dict[str, set[str]] = defaultdict(set)
    for case in _load()["cases"]:
        if case["coordinates"]["route_policy"] == "blocked":
            continue
        states_by_model[case["coordinates"]["model_id"]].add(case["decision"]["state"])

    assert states_by_model == {
        "GigaChat-2-Max": CAPABILITY_STATES,
        "GigaChat-2-Pro": CAPABILITY_STATES,
        "GigaChat-Future-1": CAPABILITY_STATES,
    }


def test_supported_dispatches_once_and_other_states_never_reach_provider_io() -> None:
    for case in _load()["cases"]:
        state = case["decision"]["state"]
        expected = case["expected"]
        if state == "supported" and case["coordinates"]["route_policy"] != "blocked":
            assert expected["dispatch"] is True
            assert expected["network_attempts"] == 1
            assert expected["http_status"] == 200
        else:
            assert expected["dispatch"] is False
            assert expected["network_attempts"] == 0
            assert expected["http_status"] == 400


def test_unknown_is_distinct_and_pins_one_explicit_policy_response() -> None:
    corpus = _load()
    policy = corpus["unknown_policy"]
    unknown_cases = [
        case for case in corpus["cases"] if case["decision"]["state"] == "unknown"
    ]

    assert policy == {
        "dispatch": False,
        "error_code": "capability_unknown",
        "http_status": 400,
        "reason_id": "capability_unknown_requires_review",
    }
    assert unknown_cases
    for case in unknown_cases:
        assert case["decision"]["reason_id"] == policy["reason_id"]
        assert case["expected"]["dispatch"] == policy["dispatch"]
        assert case["expected"]["http_status"] == policy["http_status"]


def test_evidence_precedence_and_revisions_are_exactly_recorded() -> None:
    corpus = _load()
    precedence = corpus["evidence_source_precedence"]

    assert precedence == [
        "provider_metadata",
        "reviewed_exact_model_overlay",
        "reviewed_model_family_overlay",
        "hermetic_probe",
        "provider_invariant",
        "unknown",
    ]
    assert all(case["decision"]["source"] in precedence for case in corpus["cases"])
    assert {case["decision"]["evidence_revision"] for case in corpus["cases"]} == {
        "gigachat-capabilities-2026-08-03.1",
        "route-policy-2026-08-03.1",
    }


def test_blocked_route_stops_before_client_construction() -> None:
    case = next(
        case
        for case in _load()["cases"]
        if case["id"] == "blocked-route-rejected-before-client-construction"
    )

    assert case["decision"]["reason_id"] == "route_policy_blocked"
    assert case["expected"]["client_constructions"] == 0
    assert case["expected"]["network_attempts"] == 0


def test_capability_corpus_is_hermetic_and_bounded() -> None:
    raw = CORPUS.read_bytes()

    assert 0 < len(raw) < 32 * 1024
    assert raw.endswith(b"\n")
    assert b"Bearer " not in raw
    assert b"sk-" not in raw
