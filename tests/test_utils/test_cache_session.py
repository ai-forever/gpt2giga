"""Cache session derivation for GigaChat prompt-cache affinity."""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from gpt2giga.common.cache_session import (
    apply_cache_session_derivation,
    derive_cache_session_id,
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
    assert derive_cache_session_id(payload) == derive_cache_session_id(payload)


def test_derive_is_sensitive_to_prefix_changes() -> None:
    first = derive_cache_session_id(_openai_payload())
    second = derive_cache_session_id(_openai_payload(_LONG_SYSTEM + " Extra rule."))
    assert first is not None
    assert first != second


def test_derive_returns_none_for_short_prefix() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "hi"},
        ]
    }
    assert derive_cache_session_id(payload) is None


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
    assert derive_cache_session_id(first, scope="system") == derive_cache_session_id(
        second, scope="system"
    )


def test_derive_handles_anthropic_shape() -> None:
    payload = {
        "system": _LONG_SYSTEM,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Answer: ok"}]}
        ],
    }
    session_id = derive_cache_session_id(payload)
    assert session_id is not None
    assert session_id.startswith("gpt2giga-cache-")


def test_derive_handles_gemini_shape() -> None:
    payload = {
        "systemInstruction": {"parts": [{"text": _LONG_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": "Answer: ok"}]}],
    }
    session_id = derive_cache_session_id(payload)
    assert session_id is not None
    assert session_id.startswith("gpt2giga-cache-")


def test_derive_handles_responses_shape() -> None:
    payload = {"instructions": _LONG_SYSTEM, "input": "Answer with one word: ok"}
    session_id = derive_cache_session_id(payload)
    assert session_id is not None


def test_apply_is_disabled_by_default() -> None:
    request = _request()
    options = apply_cache_session_derivation(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_adds_derived_session_when_enabled() -> None:
    request = _request(settings=_settings(cache_session_derivation_enabled=True))
    options = apply_cache_session_derivation(request, _openai_payload(), _options())
    assert options.headers["x-session-id"].startswith("gpt2giga-cache-")


def test_apply_preserves_client_session_header() -> None:
    request = _request(
        settings=_settings(cache_session_derivation_enabled=True),
        session_id="client-session",
    )
    options = apply_cache_session_derivation(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_preserves_session_from_extra_headers() -> None:
    request = _request(settings=_settings(cache_session_derivation_enabled=True))
    options = apply_cache_session_derivation(
        request,
        _openai_payload(),
        _options(**{"x-session-id": "from-extra-headers"}),
    )
    assert options.headers["x-session-id"] == "from-extra-headers"


def test_apply_defers_to_configured_default_session() -> None:
    request = _request(
        settings=_settings(cache_session_derivation_enabled=True),
        gigachat_session_id="global-session",
    )
    options = apply_cache_session_derivation(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_skips_non_chat_routes() -> None:
    request = _request(
        settings=_settings(cache_session_derivation_enabled=True),
        path="/v1/embeddings",
    )
    options = apply_cache_session_derivation(request, _openai_payload(), _options())
    assert "x-session-id" not in options.headers


def test_apply_does_not_mutate_original_options() -> None:
    request = _request(settings=_settings(cache_session_derivation_enabled=True))
    original = _options()
    apply_cache_session_derivation(request, _openai_payload(), original)
    assert "x-session-id" not in original.headers
