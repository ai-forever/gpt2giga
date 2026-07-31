from types import SimpleNamespace

import pytest

from gpt2giga.providers.gigachat.model_resolution import (
    UpstreamModelRequiredError,
    resolve_upstream_model,
)


def _config(model: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(gigachat_settings=SimpleNamespace(model=model))


def test_forced_model_wins_over_payload_and_settings() -> None:
    resolved = resolve_upstream_model(
        {"model": "payload"},
        _config("settings"),
        forced_model="forced",
    )

    assert resolved.model == "forced"
    assert resolved.limiter_key == "forced"
    assert resolved.source == "forced"


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "payload"},
        SimpleNamespace(model="payload"),
    ],
)
def test_payload_model_wins_over_settings(payload: object) -> None:
    resolved = resolve_upstream_model(payload, _config("settings"))

    assert resolved.model == "payload"
    assert resolved.limiter_key == "payload"
    assert resolved.source == "payload"


def test_settings_model_is_used_after_blank_payload_model() -> None:
    resolved = resolve_upstream_model({"model": "  "}, _config("settings"))

    assert resolved.model == "settings"
    assert resolved.source == "settings"


@pytest.mark.parametrize(
    ("payload", "limiter_key", "source"),
    [
        ({"assistant_id": "asst-1"}, "assistant:asst-1", "assistant"),
        ({"storage": {"thread_id": "thread-1"}}, "thread:thread-1", "thread"),
        (
            SimpleNamespace(storage=SimpleNamespace(thread_id="thread-2")),
            "thread:thread-2",
            "thread",
        ),
    ],
)
def test_v2_assistant_and_thread_paths_do_not_invent_model(
    payload: object,
    limiter_key: str,
    source: str,
) -> None:
    resolved = resolve_upstream_model(payload, _config(), api_mode="v2")

    assert resolved.model is None
    assert resolved.limiter_key == limiter_key
    assert resolved.source == source


def test_v1_does_not_accept_v2_assistant_without_model() -> None:
    with pytest.raises(UpstreamModelRequiredError):
        resolve_upstream_model({"assistant_id": "asst-1"}, _config(), api_mode="v1")


@pytest.mark.parametrize("model", [None, "", " \t\n "])
def test_missing_or_whitespace_model_raises_safe_domain_error(
    model: str | None,
) -> None:
    with pytest.raises(UpstreamModelRequiredError) as exc_info:
        resolve_upstream_model(
            {"model": model, "authorization": "secret"},
            _config(),
            provider="gemini",
        )

    assert exc_info.value.provider == "gemini"
    assert "secret" not in str(exc_info.value)
    assert "GigaChat" in str(exc_info.value)
