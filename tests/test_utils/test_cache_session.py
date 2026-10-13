"""Built cache sessions for GigaChat prompt-cache reuse."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from gpt2giga.common.cache_session import (
    apply_cache_session_id,
    build_cache_session_id,
)
from gpt2giga.common.gigachat_options import GigaRequestOptions
from gpt2giga.models.config import ProxySettings

_LONG_SYSTEM = "You are a helpful assistant. " * 300


def _settings(**overrides) -> ProxySettings:
    return ProxySettings(**overrides)


def _request(
    *,
    settings: ProxySettings | None = None,
    session_id: str | None = None,
    gigachat_session_id: str | None = None,
    path: str = "/v1/chat/completions",
) -> Request:
    headers = []
    if session_id is not None:
        headers.append((b"x-session-id", session_id.encode("latin-1")))
    config = SimpleNamespace(
        proxy_settings=settings or _settings(),
        gigachat_settings=SimpleNamespace(session_id=gigachat_session_id),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "query_string": b"",
        }
    )
    request.scope["app"] = SimpleNamespace(state=SimpleNamespace(config=config))
    return request


def _options(**headers: str) -> GigaRequestOptions:
    return GigaRequestOptions(headers=headers, query=(), body={})


def _openai_payload(system: str = _LONG_SYSTEM) -> dict:
    return {
        "model": "GigaChat-2-Max",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": "Answer with one word: ok"},
        ],
    }


def test_derive_is_deterministic_for_same_prefix() -> None:
    payload = _openai_payload()
    assert build_cache_session_id(payload) == build_cache_session_id(payload)


def test_derive_is_sensitive_to_prefix_changes() -> None:
    first = build_cache_session_id(_openai_payload())
    second = build_cache_session_id(_openai_payload(_LONG_SYSTEM + " Extra rule."))
    assert first is not None
    assert first != second


def test_derive_returns_none_for_short_prefix() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "hi"},
        ]
    }
    assert build_cache_session_id(payload) is None


def test_derive_system_scope_ignores_user_turn() -> None:
    first = {
        "messages": [
            {"role": "system", "content": _LONG_SYSTEM},
            {"role": "user", "content": "Question one"},
        ]
    }
    second = {
        "messages": [
            {"role": "system", "content": _LONG_SYSTEM},
            {"role": "user", "content": "Question two"},
        ]
    }
    assert build_cache_session_id(first, scope="system") == build_cache_session_id(
        second, scope="system"
    )


def test_derive_handles_anthropic_shape() -> None:
    payload = {
        "system": _LONG_SYSTEM,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Answer: ok"}]}
        ],
    }
    session_id = build_cache_session_id(payload)
    assert session_id is not None
    assert session_id.startswith("gpt2giga-cache-")


def test_derive_handles_gemini_shape() -> None:
    payload = {
        "systemInstruction": {"parts": [{"text": _LONG_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": "Answer: ok"}]}],
    }
    session_id = build_cache_session_id(payload)
    assert session_id is not None
    assert session_id.startswith("gpt2giga-cache-")


def test_derive_handles_responses_shape() -> None:
    payload = {"instructions": _LONG_SYSTEM, "input": "Answer with one word: ok"}
    session_id = build_cache_session_id(payload)
    assert session_id is not None


def test_apply_is_disabled_by_default() -> None:
    request = _request()
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_adds_built_session_when_enabled() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert options.headers["x-session-id"].startswith("gpt2giga-cache-")


def test_apply_preserves_client_session_header() -> None:
    request = _request(
        settings=_settings(cache_session_enabled=True),
        session_id="client-session",
    )
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_preserves_session_from_extra_headers() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    options = apply_cache_session_id(
        request,
        _openai_payload(),
        _options(**{"x-session-id": "from-extra-headers"}),
    )
    assert options.headers["x-session-id"] == "from-extra-headers"


def test_apply_defers_to_configured_default_session() -> None:
    request = _request(
        settings=_settings(cache_session_enabled=True),
        gigachat_session_id="global-session",
    )
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_skips_non_chat_routes() -> None:
    request = _request(
        settings=_settings(cache_session_enabled=True),
        path="/v1/embeddings",
    )
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_does_not_mutate_original_options() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    original = _options()
    apply_cache_session_id(request, _openai_payload(), original)
    assert "x-session-id" not in original.headers


def test_apply_honors_system_scope() -> None:
    request = _request(
        settings=_settings(
            cache_session_enabled=True,
            cache_session_scope="system",
        )
    )
    first = apply_cache_session_id(
        request,
        {
            "messages": [
                {"role": "system", "content": _LONG_SYSTEM},
                {"role": "user", "content": "Question one"},
            ]
        },
        _options(),
    )
    second = apply_cache_session_id(
        request,
        {
            "messages": [
                {"role": "system", "content": _LONG_SYSTEM},
                {"role": "user", "content": "Question two"},
            ]
        },
        _options(),
    )
    assert first.headers["x-session-id"] == second.headers["x-session-id"]


def test_apply_skips_short_prefix() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    options = apply_cache_session_id(
        request,
        {"messages": [{"role": "user", "content": "hi"}]},
        _options(),
    )
    assert "x-session-id" not in options.headers


def test_apply_handles_none_payload() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    options = apply_cache_session_id(request, None, _options())
    assert "x-session-id" not in options.headers


def test_apply_without_config_is_safe() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    request.scope["app"] = SimpleNamespace(state=SimpleNamespace(config=None))
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


@pytest.mark.parametrize(
    "path",
    [
        "/v1/chat/completions",
        "/v2/chat/completions",
        "/chat/completions",
        "/v1/messages",
        "/v2/messages",
        "/messages",
        "/v1/responses",
        "/responses",
        "/v1beta/models/gemini-pro:generateContent",
        "/v1beta/models/gemini-pro:streamGenerateContent",
        "/v1/chat/completions/",
    ],
)
def test_apply_covers_chat_like_routes(path: str) -> None:
    request = _request(
        settings=_settings(cache_session_enabled=True),
        path=path,
    )
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert options.headers["x-session-id"].startswith("gpt2giga-cache-")


@pytest.mark.parametrize(
    "path",
    [
        "/v1/embeddings",
        "/v1/models",
        "/v1/messages/count_tokens",
        "/v1beta/models/gemini-pro:countTokens",
        "/health",
    ],
)
def test_apply_skips_non_chat_routes_by_path(path: str) -> None:
    request = _request(
        settings=_settings(cache_session_enabled=True),
        path=path,
    )
    options = apply_cache_session_id(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_derive_differs_by_model() -> None:
    payload = _openai_payload()
    first = build_cache_session_id(payload, model="GigaChat-2-Max")
    second = build_cache_session_id(payload, model="GigaChat-2-Pro")
    assert first is not None
    assert first != second


def test_apply_mixes_payload_model_into_session() -> None:
    request = _request(settings=_settings(cache_session_enabled=True))
    max_options = apply_cache_session_id(
        request, {**_openai_payload(), "model": "GigaChat-2-Max"}, _options()
    )
    pro_options = apply_cache_session_id(
        request, {**_openai_payload(), "model": "GigaChat-2-Pro"}, _options()
    )
    assert max_options.headers["x-session-id"] != pro_options.headers["x-session-id"]


def test_derive_responses_excludes_non_leading_items() -> None:
    # Only the stable `instructions` prefix is hashed; the leading assistant or
    # tool-result item is not part of the prefix and must not change the id.
    assistant_first = {
        "instructions": _LONG_SYSTEM,
        "input": [{"role": "assistant", "content": "already answered"}],
    }
    tool_first = {
        "instructions": _LONG_SYSTEM,
        "input": [{"type": "function_call_output", "output": "result"}],
    }
    first = build_cache_session_id(assistant_first)
    second = build_cache_session_id(tool_first)
    assert first is not None
    assert first == second


def test_derive_responses_without_instructions_needs_leading_user() -> None:
    payload = {
        "input": [{"type": "function_call_output", "output": "result"}],
    }
    assert build_cache_session_id(payload) is None


def test_derive_responses_leading_user_turn() -> None:
    payload = {
        "instructions": _LONG_SYSTEM,
        "input": [{"role": "user", "content": "Answer with one word: ok"}],
    }
    assert (build_cache_session_id(payload) or "").startswith("gpt2giga-cache-")


def test_derive_gemini_snake_case_system_instruction() -> None:
    payload = {
        "system_instruction": {"parts": [{"text": _LONG_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": "Answer: ok"}]}],
    }
    assert (build_cache_session_id(payload) or "").startswith("gpt2giga-cache-")


def test_derive_anthropic_system_block_list() -> None:
    payload = {
        "system": [{"type": "text", "text": _LONG_SYSTEM}],
        "messages": [{"role": "user", "content": "Answer: ok"}],
    }
    assert (build_cache_session_id(payload) or "").startswith("gpt2giga-cache-")
