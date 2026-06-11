import json

from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedMessage,
    build_normalization_diagnostic,
    normalized_shape_hash,
)


def test_normalized_shape_hash_excludes_scalar_values():
    first = NormalizedChatRequest(
        model="GigaChat",
        messages=[NormalizedMessage(role="user", content="secret prompt")],
    )
    second = NormalizedChatRequest(
        model="Other",
        messages=[NormalizedMessage(role="user", content="different prompt")],
    )

    assert normalized_shape_hash(first) == normalized_shape_hash(second)


def test_normalization_diagnostic_is_json_serializable_without_raw_content():
    normalized = NormalizedChatRequest(
        model="GigaChat",
        messages=[NormalizedMessage(role="user", content="secret prompt")],
    )

    event = build_normalization_diagnostic(
        request_id="req-1",
        route="/v1/chat/completions",
        normalization_status="ok",
        normalized_payload=normalized,
        warnings=["shape-only"],
    )
    payload = event.to_json_dict()
    encoded = json.dumps(payload)

    assert payload["request_id"] == "req-1"
    assert payload["normalization_status"] == "ok"
    assert payload["normalized_shape_hash"].startswith("sha256:")
    assert "secret prompt" not in encoded
