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


async def test_anthropic_expires_in_seconds_rejected_before_upload():
    def unexpected(request):
        pytest.fail("Unsupported expiry must not upload bytes")

    async with sdk_app(unexpected) as (client, _):
        response = await client.post(
            "/v1/files",
            headers={"anthropic-version": "2026-10-21"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"expires_in_seconds": "3600"},
        )
        assert response.status_code == 400, response.text


@pytest.mark.parametrize("normalization", ["off", "on"])
@pytest.mark.parametrize("failure", ["timeout", "connection", "auth", "invalid"])
async def test_required_attachment_upload_failure_never_dispatches_generation(
    normalization, failure
):
    from loguru import logger
    from gpt2giga.protocol import AttachmentProcessor

    seen = []

    def handle(request):
        seen.append(request.url.path)
        assert request.url.path.endswith("/files")
        if failure == "timeout":
            raise httpx2.ReadTimeout("synthetic-secret", request=request)
        if failure == "connection":
            raise httpx2.ConnectError("synthetic-secret", request=request)
        if failure == "auth":
            return httpx2.Response(401, json={"message": "synthetic-secret"})
        return httpx2.Response(200, json={"invalid": "synthetic-secret"})

    async with sdk_app(handle, normalization=normalization) as (client, app):
        app.state.config.proxy_settings.enable_images = True
        app.state.request_transformer.attachment_processor = AttachmentProcessor(logger)
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,eA=="},
                            }
                        ],
                    }
                ],
            },
        )
    assert (
        response.status_code
        == {"timeout": 504, "connection": 502, "auth": 401, "invalid": 502}[failure]
    ), response.text
    assert seen == ["/v1/files"]
    assert "synthetic-secret" not in response.text


@pytest.mark.parametrize("normalization", ["off", "on"])
async def test_attachment_cache_separates_request_credentials_on_sdk_wire(
    normalization, monkeypatch
):
    from gigachat import GigaChat
    from loguru import logger
    from gpt2giga.middlewares.pass_token import PassTokenMiddleware
    from gpt2giga.protocol import AttachmentProcessor

    uploaded, generated = [], []

    def handle(request):
        auth = request.headers["authorization"]
        if request.url.path.endswith("/files"):
            uploaded.append(auth)
            return httpx2.Response(
                200,
                json={
                    "id": "native-" + auth.removeprefix("Bearer "),
                    "object": "file",
                    "bytes": 1,
                    "created_at": 1,
                    "filename": "image.png",
                    "purpose": "general",
                },
            )
        payload = json.loads(request.content)
        generated.append((auth, payload["messages"][-1]["attachments"]))
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "created": 1,
                "model": "test-model",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handle), trust_env=False
    ) as wire:

        def scoped_client(settings, token):
            return GigaChat(
                base_url="https://gigachat.test/v1",
                access_token=token,
                credentials="",
                user="",
                password="",
                scope="",
                max_retries=0,
                async_http_client=wire,
                trust_env=False,
            )

        monkeypatch.setattr(
            "gpt2giga.middlewares.pass_token.create_gigachat_client_for_request",
            scoped_client,
        )
        async with sdk_app(handle, normalization=normalization) as (client, app):
            app.state.config.proxy_settings.enable_images = True
            app.state.config.proxy_settings.pass_token = True
            app.add_middleware(PassTokenMiddleware)
            app.state.request_transformer.attachment_processor = AttachmentProcessor(
                logger
            )
            for owner in ("owner-a", "owner-b", "owner-a"):
                response = await client.post(
                    "/v1/chat/completions",
                    headers={"authorization": f"Bearer {owner}"},
                    json={
                        "model": "test-model",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": "data:image/png;base64,eA=="
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                )
                assert response.status_code == 200, response.text
    assert uploaded == ["Bearer owner-a", "Bearer owner-b"]
    assert generated == [
        ("Bearer owner-a", ["native-owner-a"]),
        ("Bearer owner-b", ["native-owner-b"]),
        ("Bearer owner-a", ["native-owner-a"]),
    ]


@pytest.mark.parametrize("normalization", ["off", "on"])
@pytest.mark.parametrize("shape", ["raw", "header", "anthropic", "gemini"])
async def test_registered_foreign_model_attachment_never_reaches_upstream(
    normalization, shape
):
    async with sdk_app(
        lambda _: pytest.fail("Foreign attachment must not dispatch"),
        normalization=normalization,
    ) as (client, app):
        await app.state.resource_store.put(
            "foreign-owner", "file", "native-foreign", {"upstream_id": "native-foreign"}
        )
        headers = {}
        path = "/v1/chat/completions"
        data = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        if shape == "raw":
            data["messages"][0]["attachments"] = ["native-foreign"]
        elif shape == "header":
            path = "/v1/responses"
            data = {"model": "test-model", "input": "hello"}
            headers = {"x-gpt2giga-attachment-ids": "native-foreign"}
        elif shape == "anthropic":
            path = "/v1/messages"
            data["max_tokens"] = 32
            data["messages"][0]["content"] = [
                {
                    "type": "document",
                    "source": {"type": "file", "file_id": "native-foreign"},
                }
            ]
        else:
            path = "/v1beta/models/test-model:generateContent"
            data = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "fileData": {
                                    "fileUri": "files/native-foreign",
                                    "mimeType": "application/pdf",
                                }
                            }
                        ],
                    }
                ]
            }
        response = await client.post(path, json=data, headers=headers)
        assert response.status_code == 404, response.text


@pytest.mark.parametrize("failure", ["timeout", "connection", "http_status"])
async def test_required_attachment_download_failure_stops_before_sdk(
    failure, monkeypatch
):
    import ipaddress
    import httpx
    from loguru import logger
    from gpt2giga.protocol import AttachmentProcessor

    def download(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-source-url", request=request)
        if failure == "connection":
            raise httpx.ConnectError("secret-source-url", request=request)
        return httpx.Response(403, text="secret-source-url")

    async with httpx.AsyncClient(transport=httpx.MockTransport(download)) as downloader:
        async with sdk_app(
            lambda _: pytest.fail("Download failed before provider I/O")
        ) as (client, app):
            processor = AttachmentProcessor(logger)
            processor._http_client = downloader

            async def public_ip(*args):
                return [ipaddress.ip_address("93.184.216.34")]

            monkeypatch.setattr(processor, "_resolve_host_ips", public_ip)
            app.state.request_transformer.attachment_processor = processor
            app.state.config.proxy_settings.enable_images = True
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "https://source.test/image.png?secret-source-url"
                                    },
                                }
                            ],
                        }
                    ],
                },
            )
    assert response.status_code == (504 if failure == "timeout" else 502), response.text
    assert "secret-source-url" not in response.text


@pytest.mark.parametrize("resource_state", ["owned", "legacy", "expired", "local"])
async def test_model_native_attachment_ownership_policy(resource_state):
    from starlette.requests import Request
    from gpt2giga.app_state import get_resource_owner

    calls = []

    def handle(request):
        calls.append(request.url.path)
        assert json.loads(request.content)["messages"][-1]["attachments"] == [
            "native-file"
        ]
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "created": 1,
                "model": "test-model",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    async with sdk_app(handle) as (client, app):
        if resource_state != "legacy":
            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/",
                    "headers": [],
                    "app": app,
                }
            )
            await app.state.resource_store.put(
                get_resource_owner(request),
                "file",
                "native-file",
                {"upstream_id": "native-file", "local": resource_state == "local"},
                expires_at=1 if resource_state == "expired" else None,
            )
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "user", "content": "hello", "attachments": ["native-file"]}
                ],
            },
        )
    expected = {"owned": 200, "legacy": 200, "expired": 404, "local": 400}[
        resource_state
    ]
    assert response.status_code == expected, response.text
    assert calls == (["/v1/chat/completions"] if expected == 200 else [])
