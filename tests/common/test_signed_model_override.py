from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import Request

from gpt2giga.common import signed_model_override
from gpt2giga.common.signed_model_override import (
    LEGACY_GIGALOOM_HMAC_DOMAIN,
    LEGACY_GIGALOOM_MODEL_HEADER,
    LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER,
    MAX_MODEL_LENGTH,
    _model_override_signature,
    resolve_signed_model_override,
)

MODEL = "GigaChat-Selected"
KEY = "model-key"
GOLDEN_ANTHROPIC_SIGNATURE = (
    "v1:fa04329f5be13a1e4fef476c1e346b60a359ecd40f48f1abcdf2e23eca552234"
)


def _request(
    *,
    model: str = MODEL,
    signature: str | None = GOLDEN_ANTHROPIC_SIGNATURE,
    pass_model: str | None = "false",
    user_agent: str = "claude-cli/2.1.197 (external, sdk-cli)",
    key: str | None = KEY,
) -> Request:
    headers = {
        "user-agent": user_agent,
        LEGACY_GIGALOOM_MODEL_HEADER: quote(model, safe=""),
    }
    if signature is not None:
        headers[LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER] = signature
    if pass_model is not None:
        headers["x-gpt2giga-pass-model"] = pass_model
    app = SimpleNamespace(
        state=SimpleNamespace(
            config=SimpleNamespace(
                proxy_settings=SimpleNamespace(harness_model_key=key)
            )
        )
    )
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [
                (name.encode("ascii"), value.encode("ascii"))
                for name, value in headers.items()
            ],
        }
    )


def _resolve(request: Request, *, protocol: str = "anthropic") -> str | None:
    return resolve_signed_model_override(
        request,
        protocol=protocol,
        user_agent_prefix="claude-cli/",
    )


def test_legacy_signed_model_override_bytes_are_stable() -> None:
    assert LEGACY_GIGALOOM_MODEL_HEADER == "x-gigaloom-model"
    assert LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER == "x-gigaloom-model-signature"
    assert LEGACY_GIGALOOM_HMAC_DOMAIN == "gigaloom-model/v1"
    assert (
        _model_override_signature(KEY, protocol="anthropic", model=MODEL)
        == GOLDEN_ANTHROPIC_SIGNATURE
    )


def test_valid_signed_model_override_is_accepted() -> None:
    assert _resolve(_request()) == MODEL


@pytest.mark.parametrize(
    ("signed_request", "protocol"),
    [
        (
            _request(
                signature=_model_override_signature(
                    KEY,
                    protocol="gemini",
                    model=MODEL,
                )
            ),
            "anthropic",
        ),
        (
            _request(
                model="GigaChat-Other",
                signature=_model_override_signature(
                    KEY,
                    protocol="anthropic",
                    model=MODEL,
                ),
            ),
            "anthropic",
        ),
    ],
    ids=["wrong-protocol", "wrong-model"],
)
def test_signature_is_bound_to_protocol_and_model(
    signed_request: Request,
    protocol: str,
) -> None:
    assert _resolve(signed_request, protocol=protocol) is None


@pytest.mark.parametrize(
    "signed_request",
    [
        _request(signature=None),
        _request(key=None),
    ],
    ids=["unsigned", "unconfigured-key"],
)
def test_unsigned_model_override_is_rejected(signed_request: Request) -> None:
    assert _resolve(signed_request) is None


@pytest.mark.parametrize(
    ("pass_model", "expected"),
    [
        ("false", MODEL),
        (" FALSE ", MODEL),
        ("true", None),
        (None, None),
    ],
)
def test_pass_model_policy_is_preserved(
    pass_model: str | None,
    expected: str | None,
) -> None:
    assert _resolve(_request(pass_model=pass_model)) == expected


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        ("claude-cli/2.1.197", MODEL),
        (" Claude-CLI/2.1.197 ", MODEL),
        ("anthropic-sdk-python/1.0", None),
        ("", None),
    ],
)
def test_trusted_user_agent_prefix_policy_is_preserved(
    user_agent: str,
    expected: str | None,
) -> None:
    assert _resolve(_request(user_agent=user_agent)) == expected


@pytest.mark.parametrize(
    "model",
    [
        "GigaChat\nSelected",
        "GigaChat\x7fSelected",
        "x" * (MAX_MODEL_LENGTH + 1),
    ],
    ids=["control-character", "delete-character", "oversized"],
)
def test_invalid_model_override_is_rejected(model: str) -> None:
    signature = _model_override_signature(KEY, protocol="anthropic", model=model)
    assert _resolve(_request(model=model, signature=signature)) is None


def test_signature_verification_uses_compare_digest(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    original = signed_model_override.hmac.compare_digest

    def recording_compare_digest(received: str, expected: str) -> bool:
        calls.append((received, expected))
        return original(received, expected)

    monkeypatch.setattr(
        signed_model_override.hmac,
        "compare_digest",
        recording_compare_digest,
    )

    assert _resolve(_request()) == MODEL
    assert calls == [(GOLDEN_ANTHROPIC_SIGNATURE, GOLDEN_ANTHROPIC_SIGNATURE)]
