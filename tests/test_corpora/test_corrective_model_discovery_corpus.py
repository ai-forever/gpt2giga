"""Completeness contracts for the corrective dynamic model catalog corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CORPUS = (
    Path(__file__).parents[1] / "corpora" / "correction" / "v1" / "model_discovery.json"
)


def _load() -> dict[str, Any]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _valid_model_ids(pages: list[list[Any]]) -> tuple[list[str], list[str], int]:
    model_ids: list[str] = []
    duplicate_ids: list[str] = []
    invalid_entries = 0
    for page in pages:
        for entry in page:
            if not isinstance(entry, dict):
                invalid_entries += 1
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id:
                invalid_entries += 1
                continue
            if model_id in model_ids:
                duplicate_ids.append(model_id)
                continue
            model_ids.append(model_id)
    return model_ids, duplicate_ids, invalid_entries


def test_model_discovery_corpus_closes_every_required_scenario() -> None:
    corpus = _load()
    case_ids = {case["id"] for case in corpus["cases"]}

    assert case_ids == {
        "concurrent-refresh-single-flight",
        "credential-scope-isolation",
        "duplicate-model-ids",
        "explicit-refresh",
        "malformed-provider-entry",
        "multiple-models",
        "new-unknown-model",
        "one-model",
        "pagination-and-projection",
        "provider-metadata-extensions",
        "stale-refresh-failure",
        "zero-models",
    }
    assert corpus["rules"] == {
        "cache_key_includes_credential_scope": True,
        "fabricated_fallback_model": False,
        "max_models_per_snapshot": 1024,
        "provider_traffic": False,
    }


def test_static_discovery_cases_have_deterministic_normalization_expectations() -> None:
    for case in _load()["cases"]:
        pages = case.get("provider_pages")
        if pages is None:
            continue
        model_ids, duplicate_ids, invalid_entries = _valid_model_ids(pages)
        expected = case["expected"]
        assert model_ids == expected["model_ids"]
        assert duplicate_ids == expected.get("duplicate_ids", [])
        assert invalid_entries == expected.get("invalid_entries", 0)
        assert expected["provider_calls"] == len(pages)


def test_unknown_models_remain_available_without_fabricated_capabilities() -> None:
    case = next(case for case in _load()["cases"] if case["id"] == "new-unknown-model")

    assert case["expected"]["available"] is True
    assert case["expected"]["capability_state"] == "unknown"
    assert case["expected"]["model_ids"] == ["GigaChat-Future-1"]


def test_catalog_projections_and_credential_scopes_cannot_diverge() -> None:
    cases = {case["id"]: case for case in _load()["cases"]}
    projections = cases["pagination-and-projection"]["expected"]["projection_ids"]
    scoped = cases["credential-scope-isolation"]["expected"]["models_by_scope"]

    assert projections["/models"] == projections["/bridge/models"]
    assert scoped["credential-a"] == ["GigaChat-A"]
    assert scoped["credential-b"] == ["GigaChat-B"]
    assert set(scoped["credential-a"]).isdisjoint(scoped["credential-b"])


def test_refresh_cases_pin_single_flight_stale_and_explicit_refresh_contracts() -> None:
    cases = {case["id"]: case for case in _load()["cases"]}
    concurrent = cases["concurrent-refresh-single-flight"]
    stale = cases["stale-refresh-failure"]
    explicit = cases["explicit-refresh"]

    assert concurrent["concurrency"] == concurrent["expected"]["snapshots"] == 16
    assert concurrent["expected"]["provider_calls"] == 1
    assert stale["expected"]["stale"] is True
    assert stale["expected"]["error_reason_id"] == "model_catalog_refresh_failed"
    assert explicit["expected"]["provider_calls"] == len(explicit["provider_sequences"])
    assert explicit["expected"]["revision_changed"] is True


def test_model_discovery_corpus_is_hermetic_and_bounded() -> None:
    raw = CORPUS.read_bytes()

    assert 0 < len(raw) < 32 * 1024
    assert raw.endswith(b"\n")
    assert b"Bearer " not in raw
    assert b"sk-" not in raw
