"""Opt-in live tests that exercise gpt2giga against real GigaChat."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings

pytestmark = [pytest.mark.integration, pytest.mark.live_gigachat, pytest.mark.slow]

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SUPPORTED_BACKEND_MODES = {"v1", "v2"}


def _load_live_env_file() -> None:
    env_file = os.getenv("GPT2GIGA_LIVE_ENV_FILE", ".env.live").strip()
    if not env_file:
        return
    path = Path(env_file)
    if path.exists():
        load_dotenv(path, override=False)


_load_live_env_file()


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def _configured(value: str | None) -> bool:
    if value is None:
        return False
    value = value.strip()
    if not value:
        return False
    return "REPLACE_WITH" not in value and not value.startswith("<")


def _has_live_auth() -> bool:
    if _configured(os.getenv("GIGACHAT_ACCESS_TOKEN")):
        return True
    if _configured(os.getenv("GIGACHAT_CREDENTIALS")):
        return True
    return (
        _configured(os.getenv("GIGACHAT_USER"))
        and _configured(os.getenv("GIGACHAT_PASSWORD"))
        and _configured(os.getenv("GIGACHAT_BASE_URL"))
    )


def _skip_reason() -> str | None:
    if not _enabled(os.getenv("GPT2GIGA_RUN_LIVE_TESTS")):
        return "set GPT2GIGA_RUN_LIVE_TESTS=1 to run real GigaChat tests"
    if not _has_live_auth():
        return (
            "set GIGACHAT_ACCESS_TOKEN, GIGACHAT_CREDENTIALS, or "
            "GIGACHAT_USER+GIGACHAT_PASSWORD+GIGACHAT_BASE_URL"
        )
    return None


@pytest.fixture(scope="session", autouse=True)
def require_live_gigachat_env() -> None:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)


@pytest.fixture(scope="session")
def live_model() -> str:
    return os.getenv("GPT2GIGA_LIVE_MODEL") or os.getenv("GIGACHAT_MODEL") or "GigaChat"


@pytest.fixture(scope="session")
def live_embeddings_model() -> str:
    return (
        os.getenv("GPT2GIGA_LIVE_EMBEDDINGS_MODEL")
        or os.getenv("GPT2GIGA_EMBEDDINGS")
        or "EmbeddingsGigaR"
    )


@pytest.fixture(scope="session")
def live_proxy_client(
    tmp_path_factory: pytest.TempPathFactory,
    live_embeddings_model: str,
) -> TestClient:
    log_path = tmp_path_factory.mktemp("gpt2giga-live") / "gpt2giga.log"
    config = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            enable_api_key_auth=False,
            log_filename=str(log_path),
            default_max_tokens=64,
            gigachat_api_mode="v1",
            embeddings=live_embeddings_model,
        )
    )
    app = create_app(config=config)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _live_backend_prefixes() -> tuple[str, ...]:
    raw = os.getenv("GPT2GIGA_LIVE_BACKEND_MODES", "v1,v2")
    modes: list[str] = []
    for item in raw.split(","):
        mode = item.strip().lower().removeprefix("/")
        if mode in _SUPPORTED_BACKEND_MODES and mode not in modes:
            modes.append(mode)
    return tuple(f"/{mode}" for mode in modes) or ("/v1",)


def _prompt(protocol: str) -> str:
    return (
        f"Live gpt2giga {protocol} integration check. "
        "Reply with a short plain-text acknowledgement."
    )


def _codex_headers() -> dict[str, str]:
    return {
        "user-agent": "codex-cli/live-integration-test",
        "openai-organization": "gpt2giga-live-test",
    }


def _claude_code_headers() -> dict[str, str]:
    return {
        "user-agent": "claude-code/live-integration-test",
        "anthropic-version": "2023-06-01",
    }


def _gemini_cli_headers() -> dict[str, str]:
    return {"user-agent": "gemini-cli/live-integration-test"}


def _assert_ok(response) -> None:
    assert response.status_code == 200, response.text


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        return "".join(texts).strip()
    return ""


def _sse_data_events(body: str) -> list[str]:
    return [
        line.removeprefix("data: ")
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _named_sse_events(body: str) -> list[tuple[str | None, str]]:
    events: list[tuple[str | None, str]] = []
    event_type: str | None = None
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event: "):
            event_type = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data_lines.append(line.removeprefix("data: "))
        elif not line and (event_type is not None or data_lines):
            events.append((event_type, "\n".join(data_lines)))
            event_type = None
            data_lines = []
    if event_type is not None or data_lines:
        events.append((event_type, "\n".join(data_lines)))
    return events


def _json_sse_payloads(body: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for raw in _sse_data_events(body):
        if raw == "[DONE]":
            continue
        payload = json.loads(raw)
        assert "error" not in payload, payload
        payloads.append(payload)
    return payloads


def _response_output_text(body: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "".join(texts).strip()


def _gemini_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "".join(texts).strip()


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_openai_models_lists_real_gigachat_models(
    live_proxy_client: TestClient,
    api_prefix: str,
):
    response = live_proxy_client.get(f"{api_prefix}/models", headers=_codex_headers())

    _assert_ok(response)
    body = response.json()
    assert body["object"] == "list"
    assert body["data"]
    assert isinstance(body["data"][0]["id"], str)


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_openai_model_retrieve(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.get(
        f"{api_prefix}/models/{live_model}",
        headers=_codex_headers(),
    )

    _assert_ok(response)
    body = response.json()
    assert body["object"] == "model"
    assert body["id"]


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_openai_chat_completion(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/chat/completions",
        headers=_codex_headers(),
        json={
            "model": live_model,
            "messages": [{"role": "user", "content": _prompt("OpenAI chat")}],
            "max_tokens": 64,
            "temperature": 0,
        },
    )

    _assert_ok(response)
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert _message_text(body["choices"][0]["message"].get("content"))
    assert body["usage"]["total_tokens"] >= 0


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_openai_chat_completion_stream(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    with live_proxy_client.stream(
        "POST",
        f"{api_prefix}/chat/completions",
        headers=_codex_headers(),
        json={
            "model": live_model,
            "messages": [{"role": "user", "content": _prompt("OpenAI stream")}],
            "max_tokens": 64,
            "stream": True,
            "temperature": 0,
        },
    ) as response:
        body = "".join(response.iter_text())

    _assert_ok(response)
    events = _sse_data_events(body)
    assert events[-1] == "[DONE]"
    payloads = _json_sse_payloads(body)
    assert payloads
    assert any(payload.get("object") == "chat.completion.chunk" for payload in payloads)
    assert any(
        _message_text(payload["choices"][0].get("delta", {}).get("content"))
        or payload["choices"][0].get("finish_reason")
        for payload in payloads
    )


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_openai_responses(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/responses",
        headers=_codex_headers(),
        json={
            "model": live_model,
            "input": _prompt("OpenAI Responses"),
            "max_output_tokens": 64,
            "temperature": 0,
        },
    )

    _assert_ok(response)
    body = response.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert _response_output_text(body)


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_openai_embeddings(
    live_proxy_client: TestClient,
    live_embeddings_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/embeddings",
        headers=_codex_headers(),
        json={"model": live_embeddings_model, "input": "live embeddings check"},
    )

    _assert_ok(response)
    body = response.json()
    assert body["object"] == "list"
    assert body["data"]
    assert body["data"][0]["object"] == "embedding"
    assert isinstance(body["data"][0]["embedding"], list)


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_anthropic_messages(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/messages",
        headers=_claude_code_headers(),
        json={
            "model": live_model,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": _prompt("Anthropic")}],
            "temperature": 0,
        },
    )

    _assert_ok(response)
    body = response.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert _message_text(body["content"])


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_anthropic_count_tokens(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/messages/count_tokens",
        headers=_claude_code_headers(),
        json={
            "model": live_model,
            "messages": [{"role": "user", "content": "count live anthropic tokens"}],
        },
    )

    _assert_ok(response)
    body = response.json()
    assert isinstance(body["input_tokens"], int)
    assert body["input_tokens"] > 0


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_anthropic_messages_stream(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    with live_proxy_client.stream(
        "POST",
        f"{api_prefix}/messages",
        headers=_claude_code_headers(),
        json={
            "model": live_model,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": _prompt("Anthropic stream")}],
            "stream": True,
            "temperature": 0,
        },
    ) as response:
        body = "".join(response.iter_text())

    _assert_ok(response)
    events = _named_sse_events(body)
    event_types = [event_type for event_type, _ in events]
    assert "error" not in event_types, body
    assert "message_start" in event_types
    assert "message_stop" in event_types
    assert any(event_type == "content_block_delta" for event_type, _ in events)


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_gemini_generate_content(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/models/{live_model}:generateContent",
        headers=_gemini_cli_headers(),
        json={
            "contents": [
                {"role": "user", "parts": [{"text": _prompt("Gemini")}]},
            ],
            "generationConfig": {
                "maxOutputTokens": 64,
                "temperature": 0,
            },
        },
    )

    _assert_ok(response)
    body = response.json()
    assert body["candidates"]
    assert _gemini_text(body)


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_gemini_stream_generate_content(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    with live_proxy_client.stream(
        "POST",
        f"{api_prefix}/models/{live_model}:streamGenerateContent?alt=sse",
        headers=_gemini_cli_headers(),
        json={
            "contents": [
                {"role": "user", "parts": [{"text": _prompt("Gemini stream")}]},
            ],
            "generationConfig": {
                "maxOutputTokens": 64,
                "temperature": 0,
            },
        },
    ) as response:
        body = "".join(response.iter_text())

    _assert_ok(response)
    payloads = _json_sse_payloads(body)
    assert payloads
    assert "[DONE]" not in _sse_data_events(body)
    assert any(payload.get("candidates") for payload in payloads)
    assert any(
        _gemini_text(payload) or payload["candidates"][0].get("finishReason")
        for payload in payloads
    )


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_gemini_count_tokens(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/models/{live_model}:countTokens",
        headers=_gemini_cli_headers(),
        json={
            "contents": [
                {"role": "user", "parts": [{"text": "count live tokens"}]},
            ],
        },
    )

    _assert_ok(response)
    body = response.json()
    assert isinstance(body["totalTokens"], int)
    assert body["totalTokens"] > 0


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_gemini_embed_content(
    live_proxy_client: TestClient,
    live_embeddings_model: str,
    api_prefix: str,
):
    response = live_proxy_client.post(
        f"{api_prefix}/models/{live_embeddings_model}:embedContent",
        headers=_gemini_cli_headers(),
        json={"content": {"parts": [{"text": "live gemini embedding check"}]}},
    )

    _assert_ok(response)
    body = response.json()
    assert isinstance(body["embedding"]["values"], list)
    assert body["embedding"]["values"]


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_litellm_model_info(live_proxy_client: TestClient, api_prefix: str):
    response = live_proxy_client.get(
        f"{api_prefix}/model/info",
        headers=_codex_headers(),
    )

    _assert_ok(response)
    body = response.json()
    assert body["data"]
    assert body["data"][0]["model_name"]


@pytest.mark.parametrize("api_prefix", _live_backend_prefixes())
def test_live_litellm_model_info_retrieve(
    live_proxy_client: TestClient,
    live_model: str,
    api_prefix: str,
):
    response = live_proxy_client.get(
        f"{api_prefix}/model/info",
        headers=_codex_headers(),
        params={"model": live_model},
    )

    _assert_ok(response)
    body = response.json()
    assert body["model_name"]
    assert body["litellm_params"]["model"] == body["model_name"]


def test_live_gemini_native_models_list(live_proxy_client: TestClient):
    response = live_proxy_client.get(
        "/v1beta/models",
        headers=_gemini_cli_headers(),
    )

    _assert_ok(response)
    body = response.json()
    assert body["models"]
    assert body["models"][0]["name"].startswith("models/")


def test_live_gemini_native_model_retrieve(
    live_proxy_client: TestClient,
    live_model: str,
):
    response = live_proxy_client.get(
        f"/v1beta/models/{live_model}",
        headers=_gemini_cli_headers(),
    )

    _assert_ok(response)
    body = response.json()
    assert body["name"].startswith("models/")
    assert "generateContent" in body["supportedGenerationMethods"]
