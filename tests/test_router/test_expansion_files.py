"""Files SDK round trips across persistent metadata and attachment boundaries."""

import json

import httpx2
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from gpt2giga.storage.resources import ResourceStore
from test_sdk_alpha_boundaries import sdk_app


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_file_sdk_roundtrip_preserves_metadata_after_restart(protocol, tmp_path):
    seen = []
    content = b"%PDF-1.4\x00test\xff"
    upstream = {
        "id": "native-file",
        "object": "file",
        "bytes": len(content),
        "created_at": 100,
        "filename": "test.pdf",
        "purpose": "general",
    }

    def handle(request):
        seen.append(request)
        path = request.url.path
        if request.method == "POST" and path.endswith("/files"):
            assert b"application/pdf" in request.content
            return httpx2.Response(200, json=upstream)
        if path.endswith("/files"):
            return httpx2.Response(200, json={"data": [upstream]})
        if path.endswith("/delete"):
            return httpx2.Response(200, json={"id": "native-file", "deleted": True})
        if path.endswith("/content"):
            return httpx2.Response(200, content=content)
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            assert payload["messages"][-1]["attachments"] == ["native-file"]
            return httpx2.Response(
                200,
                json={
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "PDF received"},
                            "finish_reason": "stop",
                        }
                    ],
                    "created": 1,
                    "model": "test-model",
                    "object": "chat.completion",
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 2,
                        "total_tokens": 4,
                    },
                },
            )
        return httpx2.Response(200, json=upstream)

    async with sdk_app(handle) as (http, app):
        old_store = app.state.resource_store
        app.state.resource_store = await ResourceStore.open(tmp_path)
        if protocol == "openai":
            sdk = AsyncOpenAI(
                api_key="test", base_url="http://gateway.test/v1", http_client=http
            )
            uploaded = await sdk.files.create(
                file=("test.pdf", content, "application/pdf"), purpose="assistants"
            )
        else:
            sdk = AsyncAnthropic(
                api_key="test", base_url="http://gateway.test", http_client=http
            )
            uploaded = await sdk.beta.files.upload(
                file=("test.pdf", content, "application/pdf")
            )
        await app.state.resource_store.aclose()
        app.state.resource_store = await ResourceStore.open(tmp_path)
        if protocol == "openai":
            retrieved = await sdk.files.retrieve(uploaded.id)
            assert retrieved.purpose == "assistants"
            assert (await sdk.files.content(uploaded.id)).content == content
            assert (await sdk.files.list()).data[0].id == uploaded.id
            assert (await sdk.files.delete(uploaded.id)).deleted
        else:
            retrieved = await sdk.beta.files.retrieve_metadata(uploaded.id)
            assert retrieved.mime_type == "application/pdf"
            assert retrieved.size_bytes == len(content)
            assert (await sdk.beta.files.list()).data[0].id == uploaded.id
            message = await sdk.messages.create(
                model="test-model",
                max_tokens=32,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {"type": "file", "file_id": uploaded.id},
                            }
                        ],
                    }
                ],
            )
            assert message.content[0].text == "PDF received"
            assert (await sdk.beta.files.delete(uploaded.id)).type == "file_deleted"
        await app.state.resource_store.aclose()
        app.state.resource_store = old_store


async def test_local_batch_file_never_uploads_to_document_api():
    def handle(request):
        pytest.fail("Local JSONL must never call document upload/content")

    async with sdk_app(handle) as (http, _):
        sdk = AsyncOpenAI(
            api_key="test", base_url="http://gateway.test/v1", http_client=http
        )
        content = b'{"custom_id":"row1"}\n'
        uploaded = await sdk.files.create(file=("rows.jsonl", content), purpose="batch")
        assert uploaded.id.startswith("file_g2g_")
        assert (await sdk.files.content(uploaded.id)).content == content
        assert (await sdk.files.delete(uploaded.id)).deleted
        response = await http.get(f"/v1/files/{uploaded.id}")
        assert response.status_code == 404


async def test_foreign_file_denied_before_upstream_call():
    def handle(request):
        pytest.fail("Foreign resource must not reach upstream")

    async with sdk_app(handle) as (http, app):
        await app.state.resource_store.put(
            "foreign-owner", "file", "native-file", {"upstream_id": "native-file"}
        )
        for suffix in ("", "/content"):
            response = await http.get(f"/v1/files/native-file{suffix}")
            assert response.status_code == 404


@pytest.mark.parametrize("local", [False, True])
async def test_upload_size_limit_rejects_before_native_upload(local):
    def unexpected(request):
        pytest.fail("Oversize files must not dispatch upstream")

    async with sdk_app(unexpected) as (client, app):
        app.state.resource_store.max_blob_bytes = 4
        response = await client.post(
            "/v1/files",
            data={"purpose": "batch" if local else "assistants"},
            files={
                "file": (
                    "input.jsonl" if local else "document.txt",
                    b"too large",
                    "text/plain",
                )
            },
        )
        assert response.status_code == 413
        assert response.json()["error"]["type"] == "invalid_request_error"


async def test_anthropic_document_reference_rejects_audio_before_dispatch():
    from starlette.requests import Request
    from gpt2giga.app_state import get_resource_owner

    async with sdk_app(lambda _: pytest.fail("Audio document must not dispatch")) as (
        client,
        app,
    ):
        request = Request(
            {"type": "http", "method": "GET", "path": "/", "headers": [], "app": app}
        )
        await app.state.resource_store.put(
            get_resource_owner(request),
            "file",
            "audio-file",
            {
                "id": "audio-file",
                "mime_type": "audio/wav",
                "upstream_id": "audio-file",
                "local": False,
            },
        )
        response = await client.post(
            "/v1/messages",
            headers={"anthropic-version": "2023-06-01"},
            json={
                "model": "test-model",
                "max_tokens": 32,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {"type": "file", "file_id": "audio-file"},
                            }
                        ],
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert response.json()["type"] == "error"


@pytest.mark.parametrize("local", [False, True])
async def test_cancelled_file_publication_does_not_leave_visible_metadata(
    local, monkeypatch
):
    import asyncio
    from starlette.requests import Request
    from gpt2giga.app_state import get_resource_owner
    from gpt2giga.common.files import upload_file_resource

    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/delete"):
            return httpx2.Response(200, json={"id": "cancel-file", "deleted": True})
        return httpx2.Response(
            200,
            json={
                "id": "cancel-file",
                "object": "file",
                "bytes": 3,
                "created_at": 123,
                "filename": "test.txt",
                "purpose": "general",
            },
        )

    async with sdk_app(handle) as (_, app):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/files",
                "headers": [],
                "query_string": b"",
                "app": app,
            }
        )
        store = app.state.resource_store
        original = store.put

        async def cancelled_after_write(*args, **kwargs):
            await original(*args, **kwargs)
            raise asyncio.CancelledError

        monkeypatch.setattr(store, "put", cancelled_after_write)
        with pytest.raises(asyncio.CancelledError):
            await upload_file_resource(
                request,
                content=b"abc",
                filename="test.jsonl" if local else "test.txt",
                mime_type="text/plain",
                purpose="batch" if local else "assistants",
            )
        assert await store.list(get_resource_owner(request), "file") == []
    assert len(seen) == (0 if local else 2)


async def test_repeated_cancellation_drains_file_cleanup(monkeypatch):
    import asyncio
    from starlette.requests import Request
    from gpt2giga.app_state import get_resource_owner
    from gpt2giga.common.files import upload_file_resource

    async with sdk_app(lambda _: pytest.fail("Local file needs no upstream")) as (
        _,
        app,
    ):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/files",
                "headers": [],
                "query_string": b"",
                "app": app,
            }
        )
        store = app.state.resource_store
        original_put, original_delete = store.put, store.delete
        deleting, release = asyncio.Event(), asyncio.Event()

        async def cancelled_after_write(*args, **kwargs):
            await original_put(*args, **kwargs)
            raise asyncio.CancelledError

        async def slow_delete(*args, **kwargs):
            deleting.set()
            await release.wait()
            return await original_delete(*args, **kwargs)

        monkeypatch.setattr(store, "put", cancelled_after_write)
        monkeypatch.setattr(store, "delete", slow_delete)
        operation = asyncio.create_task(
            upload_file_resource(
                request,
                content=b"abc",
                filename="input.jsonl",
                mime_type="application/jsonl",
                purpose="batch",
            )
        )
        await deleting.wait()
        operation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert await store.list(get_resource_owner(request), "file") == []
