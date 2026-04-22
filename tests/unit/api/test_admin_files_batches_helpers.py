import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gpt2giga.api.admin import files_batches_helpers


@pytest.mark.asyncio
async def test_read_admin_file_create_payload_normalizes_defaults(monkeypatch):
    async def fake_read_request_multipart(_request):
        return {
            "form": {
                "api_format": " gemini ",
                "purpose": " user_data ",
                "display_name": " Diagram ",
            },
            "files": {"file": {"content": b"png-bytes"}},
        }

    monkeypatch.setattr(
        files_batches_helpers,
        "read_request_multipart",
        fake_read_request_multipart,
    )

    payload = await files_batches_helpers.read_admin_file_create_payload(object())

    assert payload.api_format == "gemini"
    assert payload.purpose == "user_data"
    assert payload.display_name == "Diagram"
    assert payload.upload == {"content": b"png-bytes"}


@pytest.mark.asyncio
async def test_read_admin_file_create_payload_requires_upload(monkeypatch):
    async def fake_read_request_multipart(_request):
        return {"form": {}, "files": {}}

    monkeypatch.setattr(
        files_batches_helpers,
        "read_request_multipart",
        fake_read_request_multipart,
    )

    with pytest.raises(HTTPException) as exc_info:
        await files_batches_helpers.read_admin_file_create_payload(object())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "`file` is required."


@pytest.mark.asyncio
async def test_resolve_admin_batch_input_bytes_decodes_base64_inline_content():
    input_bytes = await files_batches_helpers.resolve_admin_batch_input_bytes(
        object(),
        input_file_id=None,
        requests=None,
        input_content_base64=base64.b64encode(b'{"hello":"world"}\n').decode("utf-8"),
    )

    assert input_bytes == b'{"hello":"world"}\n'


@pytest.mark.asyncio
async def test_resolve_admin_batch_input_bytes_reads_staged_file_once(monkeypatch):
    calls: list[str] = []

    async def fake_resolve_batch_input_bytes(request, *, file_id):
        del request
        calls.append(file_id)
        return b"staged-jsonl"

    monkeypatch.setattr(
        files_batches_helpers,
        "resolve_batch_input_bytes",
        fake_resolve_batch_input_bytes,
    )

    input_bytes = await files_batches_helpers.resolve_admin_batch_input_bytes(
        object(),
        input_file_id="file-123",
        requests=None,
    )

    assert input_bytes == b"staged-jsonl"
    assert calls == ["file-123"]


def test_infer_batch_api_format_from_rows_detects_known_shapes():
    assert (
        files_batches_helpers.infer_batch_api_format_from_rows(
            [{"params": {"model": "claude"}}]
        )
        == "anthropic"
    )
    assert (
        files_batches_helpers.infer_batch_api_format_from_rows(
            [{"request": {"contents": []}}]
        )
        == "gemini"
    )
    assert (
        files_batches_helpers.infer_batch_api_format_from_rows(
            [{"method": "POST", "url": "/v1/chat/completions"}]
        )
        == "openai"
    )
    assert files_batches_helpers.infer_batch_api_format_from_rows("not-a-list") is None


def test_resolve_output_batch_id_prefers_stored_file_metadata():
    batch_id = files_batches_helpers.resolve_output_batch_id(
        "file-output-1",
        file_store={"file-output-1": {"batch_id": "batch-direct-1"}},
        batch_store={"batch-fallback-1": {"output_file_id": "file-output-1"}},
    )

    assert batch_id == "batch-direct-1"


def test_limit_preview_content_trims_to_newline_boundary():
    content, headers = files_batches_helpers.limit_preview_content(
        b"line-1\nline-2\nline-3\n",
        media_type="application/json",
        preview_bytes=15,
    )

    assert content == b"line-1\nline-2\n"
    assert headers == {
        "X-Admin-Preview-Truncated": "true",
        "X-Admin-Preview-Bytes": "14",
        "X-Admin-Preview-Total-Bytes": "21",
    }


def test_limit_preview_content_keeps_full_image_payload():
    content, headers = files_batches_helpers.limit_preview_content(
        b"image-bytes",
        media_type="image/png",
        preview_bytes=4,
    )

    assert content == b"image-bytes"
    assert headers == {
        "X-Admin-Preview-Truncated": "false",
        "X-Admin-Preview-Bytes": "11",
        "X-Admin-Preview-Total-Bytes": "11",
    }


@pytest.mark.asyncio
async def test_resolve_batch_output_api_format_falls_back_to_input_file_rows():
    class FakeGigaClient:
        async def aget_file_content(self, *, file_id):
            assert file_id == "file-input-1"
            return SimpleNamespace(
                content=base64.b64encode(
                    b'{"custom_id":"row-1","params":{"model":"claude-test"}}\n'
                ).decode("utf-8")
            )

    batch_record = SimpleNamespace(
        output_file_id="file-output-1",
        api_format=SimpleNamespace(value="openai"),
    )

    output_api_format = await files_batches_helpers.resolve_batch_output_api_format(
        batch_record,
        raw_metadata={},
        giga_client=FakeGigaClient(),
        file_store={"file-output-1": {"batch_input_file_id": "file-input-1"}},
    )

    assert output_api_format == "anthropic"
