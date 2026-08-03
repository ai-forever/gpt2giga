"""Completeness contracts for the corrective native Responses parity corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gpt2giga.common.tools import (
    find_imagegen_tool,
    map_tool_name_to_gigachat,
    normalize_gigachat_builtin_tool_type,
)


CORPUS = (
    Path(__file__).parents[1]
    / "corpora"
    / "correction"
    / "v1"
    / "native_gigachat_responses.json"
)


def _load() -> dict[str, Any]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_native_responses_corpus_closes_the_required_semantic_inventory() -> None:
    corpus = _load()
    cases = {case["id"]: case for case in corpus["cases"]}

    assert set(cases) == {
        "attachments",
        "code-execution",
        "code-interpreter",
        "codex-image-gen-namespace",
        "conversation-state",
        "custom-function",
        "custom-function-named-web-search",
        "image-generate",
        "image-generation",
        "model-3d-generate",
        "plain-text",
        "previous-response-state",
        "reasoning-request",
        "url-content-extraction",
        "url-context",
        "web-fetch",
        "web-search",
        "web-search-preview",
    }
    assert corpus["schema_version"] == "gpt2giga.corrective-conformance.v1"
    assert corpus["expected"] == {
        "executor": "native_gigachat",
        "fallback_after_dispatch": False,
        "network_attempts_after_dispatch": 1,
        "requires_compatibility_flag": False,
    }


def test_each_applicable_native_case_expands_to_success_and_failure_variants() -> None:
    corpus = _load()
    outcomes = corpus["outcome_matrix"]
    expanded: set[tuple[str, str, str, str]] = set()

    for case in corpus["cases"]:
        assert case["api_modes"]
        for api_mode in case["api_modes"]:
            for transport, transport_outcomes in outcomes.items():
                for outcome in transport_outcomes:
                    expanded.add((case["id"], api_mode, transport, outcome))

    for case in corpus["cases"]:
        for api_mode in case["api_modes"]:
            assert (case["id"], api_mode, "non_stream", "success") in expanded
            assert (case["id"], api_mode, "stream", "success") in expanded
            assert (case["id"], api_mode, "non_stream", "provider_error") in expanded
            assert (case["id"], api_mode, "stream", "provider_error") in expanded
            assert (case["id"], api_mode, "stream", "disconnect") in expanded
            assert (
                case["id"],
                api_mode,
                "stream",
                "malformed_provider_event",
            ) in expanded

    assert len(expanded) == sum(
        len(case["api_modes"])
        * sum(len(transport_outcomes) for transport_outcomes in outcomes.values())
        for case in corpus["cases"]
    )


def test_hosted_tool_aliases_are_bound_to_reviewed_gigachat_names() -> None:
    hosted = [case for case in _load()["cases"] if case["semantic"] == "hosted_tool"]

    assert hosted
    for case in hosted:
        tool_type = case["request"]["tools"][0]["type"]
        assert (
            normalize_gigachat_builtin_tool_type(tool_type)
            == case["canonical_gigachat_tool"]
        )


def test_reserved_custom_web_search_and_codex_imagegen_remain_custom_tools() -> None:
    cases = {case["id"]: case for case in _load()["cases"]}
    custom_search = cases["custom-function-named-web-search"]["request"]["tools"][0]
    imagegen_tools = cases["codex-image-gen-namespace"]["request"]["tools"]

    assert custom_search["type"] == "function"
    assert map_tool_name_to_gigachat(custom_search["name"]) == (
        "__gpt2giga_user_search_web"
    )
    assert find_imagegen_tool(imagegen_tools) == ("imagegen", "image_gen")


def test_native_corpus_is_hermetic_and_bounded() -> None:
    raw = CORPUS.read_bytes()

    assert 0 < len(raw) < 32 * 1024
    assert raw.endswith(b"\n")
    assert b"Bearer " not in raw
    assert b"sk-" not in raw
    assert _load()["cases"][14]["headers"] == {
        "x-gpt2giga-attachment-ids": "file-fixture-1"
    }
