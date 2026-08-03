"""Pinned client request shapes for the corrective compatibility surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI


CORPUS = (
    Path(__file__).parents[1] / "corpora" / "correction" / "v1" / "client_smokes.json"
)


def _load() -> dict[str, Any]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_client_corpus_pins_every_required_public_facade() -> None:
    clients = _load()["clients"]

    assert {(case["client"], case["wire_api"]) for case in clients} == {
        ("anthropic-python", "anthropic_messages"),
        ("codex-cli", "responses"),
        ("curl", "responses"),
        ("google-genai-python", "gemini_generate_content"),
        ("openai-python", "chat_completions"),
        ("openai-python", "responses"),
    }


def test_captured_versions_are_inside_declared_supported_windows() -> None:
    for case in _load()["clients"]:
        window = case["supported_window"]
        assert _version(window["minimum"]) <= _version(case["captured_version"])
        assert _version(case["captured_version"]) < _version(
            window["maximum_exclusive"]
        )


def test_smokes_include_real_hosted_tool_shapes_not_only_custom_functions() -> None:
    cases = {case["id"]: case for case in _load()["clients"]}
    hosted = {case["client"] for case in cases.values() if case["hosted_tool"]}

    assert hosted == {
        "anthropic-python",
        "codex-cli",
        "curl",
        "google-genai-python",
        "openai-python",
    }
    assert cases["codex-cli-responses-hosted-tool"]["request"]["body"]["tools"] == [
        {"type": "web_search_preview"}
    ]
    assert cases["curl-responses-hosted-tool"]["request"]["body"]["tools"] == [
        {"type": "code_interpreter"}
    ]
    assert cases["google-genai-google-search"]["request"]["body"]["tools"] == [
        {"googleSearch": {}}
    ]


def test_openai_python_emits_the_pinned_hosted_tool_wire_shape() -> None:
    case = next(
        case
        for case in _load()["clients"]
        if case["id"] == "openai-python-responses-hosted-tool"
    )
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "body": json.loads(request.content),
                "method": request.method,
                "path": request.url.path,
            }
        )
        return httpx.Response(
            200,
            json={
                "created_at": 0,
                "id": "resp_fixture_hosted_tool",
                "model": "GigaChat-2-Max",
                "object": "response",
                "output": [],
                "status": "completed",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAI(
            api_key="fixture-key",
            base_url="http://fixture.test",
            http_client=http_client,
        )
        client.responses.create(**case["request"]["body"])

    assert captured == [case["request"]]


def test_chat_custom_web_search_remains_distinct_from_hosted_tool() -> None:
    case = next(
        case
        for case in _load()["clients"]
        if case["id"] == "openai-python-chat-completions-reserved-function"
    )
    tool = case["request"]["body"]["tools"][0]

    assert case["hosted_tool"] is False
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "web_search"


def test_client_smoke_corpus_is_hermetic_and_bounded() -> None:
    raw = CORPUS.read_bytes()

    assert 0 < len(raw) < 32 * 1024
    assert raw.endswith(b"\n")
    assert b"Bearer " not in raw
    assert b"sk-" not in raw
    assert _load()["rules"] == {
        "authorization": "fixture_only",
        "provider_traffic": False,
        "requires_hosted_tool_coverage": True,
    }
