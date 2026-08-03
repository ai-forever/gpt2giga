"""Integrity and SDK-wire checks for the bounded 0.3 bridge client corpus."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
from anthropic import Anthropic
from google import genai
from google.genai import types
from openai import OpenAI


CORPUS = Path(__file__).parents[1] / "corpora" / "bridge" / "v1"
SCHEMA_VERSION = "gpt2giga.client-corpus.v1"
MAX_FIXTURE_BYTES = 16 * 1024
SCRUBBED = "__SCRUBBED__"


def _load(name: str) -> dict[str, Any]:
    return json.loads((CORPUS / name).read_text(encoding="utf-8"))


def _request_shape(request: httpx.Request, header_names: set[str]) -> dict[str, Any]:
    def scrub(name: str) -> str:
        if name == "authorization":
            return f"Bearer {SCRUBBED}"
        if name in {"x-api-key", "x-goog-api-key"}:
            return SCRUBBED
        return request.headers[name]

    return {
        "body": json.loads(request.content),
        "headers": {name: scrub(name) for name in sorted(header_names)},
        "method": request.method,
        "path": request.url.path,
    }


def test_manifest_pins_bounded_scrubbed_deterministic_files() -> None:
    manifest = _load("manifest.json")
    assert manifest["schema_version"] == "gpt2giga.client-corpus-manifest.v1"
    assert manifest["corpus_version"] == "bridge-v1"

    listed = {entry["path"] for entry in manifest["files"]}
    actual = {path.name for path in CORPUS.glob("*.json")} - {"manifest.json"}
    assert listed == actual

    case_ids: set[str] = set()
    for entry in manifest["files"]:
        path = CORPUS / entry["path"]
        raw = path.read_bytes()
        assert 0 < len(raw) <= MAX_FIXTURE_BYTES
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        assert b"sk-" not in raw and b"Bearer ey" not in raw
        payload = json.loads(raw)
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["case_id"] not in case_ids
        case_ids.add(payload["case_id"])


def test_corpus_sdk_versions_are_exactly_pinned() -> None:
    assert (
        version("openai") == _load("openai_sdk_chat_request.json")["client"]["version"]
    )
    anthropic = _load("claude_code_anthropic_request.json")["client"]["compatible_sdk"]
    assert version("anthropic") == anthropic["version"]
    assert (
        version("google-genai")
        == _load("gemini_sdk_generate_content_request.json")["client"]["version"]
    )


def test_openai_sdk_chat_request_matches_pinned_wire_shape() -> None:
    expected = _load("openai_sdk_chat_request.json")["request"]
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_request_shape(request, set(expected["headers"])))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "index": 0,
                        "message": {"content": "ok", "role": "assistant"},
                    }
                ],
                "created": 0,
                "id": "chatcmpl_fixture",
                "model": "bridge/openai-test",
                "object": "chat.completion",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAI(
            api_key="fixture-key",
            base_url="http://fixture.test",
            http_client=http_client,
        )
        body = expected["body"]
        client.chat.completions.create(**body)

    assert captured == [expected]


def test_openai_sdk_responses_request_matches_pinned_wire_shape() -> None:
    expected = _load("openai_sdk_responses_request.json")["request"]
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_request_shape(request, set(expected["headers"])))
        return httpx.Response(
            200,
            json={
                "created_at": 0,
                "id": "resp_fixture_2",
                "model": "bridge/openai-test",
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
        client.responses.create(**expected["body"])

    assert captured == [expected]


def test_anthropic_sdk_request_matches_claude_gateway_shape() -> None:
    expected = _load("claude_code_anthropic_request.json")["request"]
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_request_shape(request, set(expected["headers"])))
        return httpx.Response(
            200,
            json={
                "content": [{"text": "ok", "type": "text"}],
                "id": "msg_fixture",
                "model": "bridge/anthropic-test",
                "role": "assistant",
                "stop_reason": "end_turn",
                "type": "message",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = Anthropic(
            api_key="fixture-key",
            base_url="http://fixture.test",
            http_client=http_client,
        )
        body = expected["body"]
        client.messages.create(**{**body, "stream": False})

    actual = captured[0]
    actual["body"]["stream"] = True
    assert actual == expected


def test_google_genai_request_matches_pinned_wire_shape() -> None:
    expected = _load("gemini_sdk_generate_content_request.json")["request"]
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_request_shape(request, set(expected["headers"])))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "ok"}], "role": "model"},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ],
                "usageMetadata": {
                    "candidatesTokenCount": 1,
                    "promptTokenCount": 1,
                    "totalTokenCount": 2,
                },
            },
        )

    client = genai.Client(
        api_key="fixture-key",
        http_options=types.HttpOptions(base_url="http://fixture.test", api_version=""),
    )
    original_client = client._api_client._httpx_client
    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    client._api_client._httpx_client = mock_client
    try:
        client.models.generate_content(
            model="bridge/gemini-test",
            contents="Weather in Moscow?",
            config=types.GenerateContentConfig(
                max_output_tokens=64,
                system_instruction="Be concise.",
                temperature=0,
                tools=[
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(
                                description="Return fixture weather.",
                                name="weather",
                                parameters={
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                    "required": ["city"],
                                },
                            )
                        ]
                    )
                ],
            ),
        )
    finally:
        client._api_client._httpx_client = original_client
        mock_client.close()
        client.close()

    assert captured == [expected]


def test_failure_and_unsupported_corpus_closes_required_cases() -> None:
    failures = {case["id"] for case in _load("lifecycle_failures.json")["cases"]}
    assert failures == {
        "cancellation-before-terminal",
        "client-disconnect-after-first-delta",
        "duplicate-terminal",
        "malformed-json-after-stream-start",
    }
    unsupported = _load("unsupported_fields.json")["expected"]
    assert unsupported["network_attempts"] == 0
    assert unsupported["code"] == "unsupported_semantic"
