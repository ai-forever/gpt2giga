import base64

import pytest
from fastapi import HTTPException

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.files_batches.creation import (
    apply_anthropic_fallback_model,
    apply_openai_fallback_model,
    build_anthropic_batch_metadata,
    build_gemini_batch_metadata,
    build_openai_inline_batch_metadata,
    build_openai_staged_batch_metadata,
    build_uploaded_file_metadata,
    normalize_openai_batch_endpoint,
    resolve_gemini_batch_display_name,
    resolve_gemini_batch_model,
)


def test_build_uploaded_file_metadata_adds_gemini_specific_fields():
    metadata = build_uploaded_file_metadata(
        api_format=NormalizedArtifactFormat.GEMINI,
        purpose="user_data",
        upload={
            "filename": "diagram.png",
            "content": b"png-bytes",
            "content_type": "image/png",
        },
        display_name="Gemini Diagram",
    )

    assert metadata["api_format"] == "gemini"
    assert metadata["display_name"] == "Gemini Diagram"
    assert metadata["mime_type"] == "image/png"
    assert metadata["source"] == "UPLOADED"
    assert metadata["sha256_hash"] == base64.b64encode(
        __import__("hashlib").sha256(b"png-bytes").digest()
    ).decode("ascii")


def test_build_openai_batch_metadata_helpers_preserve_optional_fields():
    inline = build_openai_inline_batch_metadata(
        input_file_id="file-1",
        metadata={"label": "openai"},
        model="GigaChat-2-Max",
    )
    staged = build_openai_staged_batch_metadata(
        input_file_id="file-2",
        metadata={"label": "staged"},
    )

    assert inline == {
        "metadata": {"label": "openai"},
        "input_file_id": "file-1",
        "model": "GigaChat-2-Max",
    }
    assert staged == {
        "input_file_id": "file-2",
        "metadata": {"label": "staged"},
    }


def test_build_provider_batch_metadata_helpers_preserve_provider_shape():
    anthropic = build_anthropic_batch_metadata(
        input_file_id="anthropic-file-1",
        metadata={"label": "anthropic"},
        display_name=" Anthropic Import ",
        model=" Claude-Test ",
        stored_requests=[{"custom_id": "req-1"}],
    )
    gemini = build_gemini_batch_metadata(
        input_file_id="gemini-file-1",
        metadata={"label": "gemini"},
        display_name=None,
        model="gemini-2.5-flash",
        stored_requests=[{"key": "row-1"}],
    )

    assert anthropic == {
        "api_format": "anthropic_messages",
        "provider_endpoint": "/v1/messages",
        "requests": [{"custom_id": "req-1"}],
        "input_file_id": "anthropic-file-1",
        "metadata": {"label": "anthropic"},
        "display_name": "Anthropic Import",
        "model": "Claude-Test",
    }
    assert gemini["api_format"] == "gemini_generate_content"
    assert gemini["display_name"] == "Gemini batch for gemini-file-1"
    assert (
        gemini["provider_endpoint"] == "/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert gemini["requests"] == [{"key": "row-1"}]
    assert gemini["input_file_id"] == "gemini-file-1"


def test_apply_batch_fallback_models_only_fills_missing_values():
    openai_rows = apply_openai_fallback_model(
        [
            {"body": {"messages": [{"role": "user", "content": "hi"}]}},
            {"body": {"model": "gpt-existing", "messages": []}},
            "raw-row",
        ],
        fallback_model="gpt-fallback",
    )
    anthropic_rows = apply_anthropic_fallback_model(
        [
            {"params": {"messages": [{"role": "user", "content": "hi"}]}},
            {"params": {"model": "claude-existing", "messages": []}},
            "raw-row",
        ],
        fallback_model="claude-fallback",
    )

    assert openai_rows[0]["body"]["model"] == "gpt-fallback"
    assert openai_rows[1]["body"]["model"] == "gpt-existing"
    assert openai_rows[2] == "raw-row"
    assert anthropic_rows[0]["params"]["model"] == "claude-fallback"
    assert anthropic_rows[1]["params"]["model"] == "claude-existing"
    assert anthropic_rows[2] == "raw-row"


def test_resolve_gemini_batch_model_prefers_fallback_and_normalizes_request_models():
    assert normalize_openai_batch_endpoint(None) == "/v1/chat/completions"
    assert normalize_openai_batch_endpoint("/v1/responses") == "/v1/responses"
    assert resolve_gemini_batch_display_name(None, input_file_id=None) == "Gemini batch"
    assert (
        resolve_gemini_batch_display_name(None, input_file_id="file-1")
        == "Gemini batch for file-1"
    )

    resolved = resolve_gemini_batch_model(
        [
            {
                "request": {
                    "model": "models/gemini-2.5-flash",
                    "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                }
            }
        ],
        fallback_model=None,
    )

    assert resolved == "gemini-2.5-flash"

    fallback = resolve_gemini_batch_model(
        [
            {
                "request": {
                    "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                }
            }
        ],
        fallback_model=(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-pro:batchGenerateContent"
        ),
    )

    assert fallback == "gemini-2.5-pro"


def test_resolve_gemini_batch_model_rejects_mixed_models_without_fallback():
    with pytest.raises(HTTPException) as exc_info:
        resolve_gemini_batch_model(
            [
                {"request": {"model": "models/gemini-2.5-flash"}},
                {"request": {"model": "models/gemini-2.5-pro"}},
            ],
            fallback_model=None,
        )

    assert exc_info.value.status_code == 400
    assert "mix multiple request models" in str(exc_info.value.detail["model"])
