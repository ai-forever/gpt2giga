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
        method = "put" if local else "promote_blob"
        original = getattr(store, method)

        async def cancelled_after_write(*args, **kwargs):
            await original(*args, **kwargs)
            raise asyncio.CancelledError

        monkeypatch.setattr(store, method, cancelled_after_write)
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


def native_uploaded_file(file_id="reserved-file"):
    return {
        "id": file_id,
        "object": "file",
        "bytes": 3,
        "created_at": 123,
        "filename": "test.txt",
        "purpose": "general",
    }


def owner_request(app):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/files",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )


async def test_exhausted_resource_quota_rejects_before_native_upload():
    async with sdk_app(lambda _: pytest.fail("Quota must precede native upload")) as (
        client,
        app,
    ):
        store = app.state.resource_store
        store.max_resources = 1
        await store.put("other", "response", "occupied", {})
        result = await client.post(
            "/v1/files",
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert result.status_code == 413
        assert "metadata quota" in result.text


async def test_upload_reservations_serialize_last_available_slot():
    import asyncio
    from gpt2giga.app_state import get_resource_owner

    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handle(request):
        calls.append(request)
        started.set()
        await release.wait()
        return httpx2.Response(200, json=native_uploaded_file())

    async with sdk_app(handle) as (client, app):
        app.state.resource_store.max_resources = 1
        first = asyncio.create_task(
            client.post(
                "/v1/files",
                data={"purpose": "assistants"},
                files={"file": ("test.txt", b"abc", "text/plain")},
            )
        )
        await started.wait()
        second = await client.post(
            "/v1/files",
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert second.status_code == 413
        release.set()
        assert (await first).status_code == 200
        assert len(calls) == 1
        owner = get_resource_owner(owner_request(app))
        assert await app.state.resource_store.list(owner, "file_upload") == []
        assert len(await app.state.resource_store.list(owner, "file")) == 1


@pytest.mark.parametrize("delete_fails", [False, True])
async def test_failed_native_publication_compensates_or_keeps_durable_intent(
    monkeypatch, delete_fails
):
    from gpt2giga.app_state import get_resource_owner
    from gpt2giga.common.files import upload_file_resource
    from gpt2giga.storage.resources import ResourceStoreError

    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/delete"):
            return httpx2.Response(
                503 if delete_fails else 200,
                json={"id": "reserved-file", "deleted": True},
            )
        return httpx2.Response(200, json=native_uploaded_file())

    async with sdk_app(handle) as (_, app):
        store = app.state.resource_store
        request = owner_request(app)

        async def fail(*args, **kwargs):
            raise ResourceStoreError("synthetic publication failure")

        monkeypatch.setattr(store, "promote_blob", fail)
        with pytest.raises(ResourceStoreError):
            await upload_file_resource(
                request, content=b"abc", filename="test.txt", mime_type="text/plain"
            )
        owner = get_resource_owner(request)
        pending = await store.list(owner, "file_upload")
        assert len(pending) == int(delete_fails)
        if delete_fails:
            assert pending[0].metadata["upstream_id"] == "reserved-file"
            assert pending[0].expires_at == float("inf")
            assert await store.is_registered("file", "reserved-file")
        assert await store.list(owner, "file") == []
    assert len(calls) == 2


async def test_unknown_native_upload_outcome_keeps_admitted_intent_without_retry():
    from gpt2giga.app_state import get_resource_owner

    calls = []

    def handle(request):
        calls.append(request)
        raise httpx2.ReadTimeout("unknown outcome", request=request)

    async with sdk_app(handle) as (client, app):
        response = await client.post(
            "/v1/files",
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert response.status_code == 504
        pending = await app.state.resource_store.list(
            get_resource_owner(owner_request(app)), "file_upload"
        )
        assert len(pending) == 1
        assert pending[0].metadata["upstream_id"] is None
        assert len(calls) == 1


async def test_cancelled_reservation_before_upload_releases_admission(monkeypatch):
    import asyncio
    from gpt2giga.app_state import get_resource_owner
    from gpt2giga.common.files import upload_file_resource

    async with sdk_app(
        lambda _: pytest.fail("Cancelled admission must not upload")
    ) as (_, app):
        request = owner_request(app)
        store = app.state.resource_store
        put = store.put

        async def cancel_after_reservation(*args, **kwargs):
            await put(*args, **kwargs)
            raise asyncio.CancelledError

        monkeypatch.setattr(store, "put", cancel_after_reservation)
        with pytest.raises(asyncio.CancelledError):
            await upload_file_resource(
                request, content=b"abc", filename="test.txt", mime_type="text/plain"
            )
        assert await store.list(get_resource_owner(request), "file_upload") == []


@pytest.mark.parametrize("profile", ["missing", "external"])
async def test_invalid_upload_profile_fails_before_sdk(profile):
    async with sdk_app(lambda _: pytest.fail("Invalid profile must not upload")) as (
        client,
        _,
    ):
        response = await client.post(
            "/v1/files",
            headers={"X-GPT2GIGA-Profile": profile},
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert response.status_code == 400


@pytest.mark.parametrize("resumable", [False, True])
@pytest.mark.parametrize("pass_token", [False, True])
async def test_selected_upload_profile_survives_reads_generation_and_resumable_headers(
    tmp_path, monkeypatch, resumable, pass_token
):
    import time
    import httpx
    from gigachat import GigaChat
    from gpt2giga.app.factory import create_app
    from gpt2giga.models.config import ProxyConfig

    profile_path = tmp_path / "providers.json"
    profiles = []
    for name, kind in (("selected", "gigachat"), ("external", "openai_compatible")):
        profiles.append(
            {
                "profile_id": name,
                "provider_kind": kind,
                "base_url": f"https://{name}.giga.example/v1",
                "network_policy_ref": "public-openai",
                "tls_policy_ref": "system-default",
                "models": [
                    {
                        "public_alias": f"{name}/model",
                        "upstream_model": "test-model",
                        "enabled": kind == "gigachat",
                        "capability_profile": "fixture",
                        "support_status": "technical_preview",
                    }
                ],
                **(
                    {"credential_env": "SELECTED_GIGA_CREDENTIAL"}
                    if kind == "gigachat"
                    else {}
                ),
            }
        )
    profile_path.write_text(
        json.dumps(
            {"schema_version": "gpt2giga.provider-profiles.v3", "profiles": profiles}
        )
    )
    monkeypatch.setenv("SELECTED_GIGA_CREDENTIAL", "selected-credential")
    calls = []

    def handle(request):
        if request.url.host == "auth.test":
            assert request.headers["authorization"] == "Basic selected-credential"
            return httpx2.Response(
                200,
                json={
                    "access_token": "selected-token",
                    "expires_at": int((time.time() + 3600) * 1000),
                },
            )
        calls.append(request)
        if request.url.path.endswith("/files"):
            file_id = (
                "selected-file"
                if request.url.host == "selected.giga.example"
                else "default-file"
            )
            return httpx2.Response(200, json=native_uploaded_file(file_id))
        assert request.url.host == "selected.giga.example"
        assert request.headers["authorization"] == (
            "Bearer caller" if pass_token else "Bearer selected-token"
        )
        assert request.url.path.endswith("/chat/completions")
        assert json.loads(request.content)["messages"][-1]["attachments"] == [
            "selected-file"
        ]
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
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

        def injected(**kwargs):
            return GigaChat(
                **kwargs, async_http_client=wire, auth_async_http_client=wire
            )

        monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", injected)
        config = ProxyConfig(
            config=str(profile_path),
            proxy={
                "pass_model": True,
                "pass_token": pass_token,
                "resource_store_path": str(tmp_path / "store"),
            },
            gigachat={
                "base_url": "https://default.giga.example/v1",
                "auth_url": "https://auth.test/oauth",
                "access_token": "default-token",
                "credentials": "",
                "user": "",
                "password": "",
                "max_retries": 0,
                "trust_env": False,
            },
            _env_file=None,
        )
        app = create_app(config)
        async with app.router.lifespan_context(app):
            headers = {"Authorization": "Bearer giga-auth-caller"} if pass_token else {}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://gateway.test",
                headers=headers,
            ) as client:
                for invalid in ("missing", "external"):
                    rejected = await client.post(
                        "/v1/files",
                        headers={"X-GPT2GIGA-Profile": invalid},
                        data={"purpose": "assistants"},
                        files={"file": ("test.txt", b"abc", "text/plain")},
                    )
                    assert rejected.status_code == 400, rejected.text
                    assert calls == []
                if resumable:
                    start = await client.post(
                        "/upload/v1beta/files",
                        headers={
                            "X-GPT2GIGA-Profile": "selected",
                            "X-Goog-Upload-Command": "start",
                            "X-Goog-Upload-Protocol": "resumable",
                            "X-Goog-Upload-Header-Content-Length": "3",
                            "X-Goog-Upload-Header-Content-Type": "text/plain",
                        },
                        json={"file": {"displayName": "test.txt"}},
                    )
                    assert start.status_code == 200, start.text
                    uploaded = await client.post(
                        start.headers["x-goog-upload-url"],
                        headers={
                            "X-GPT2GIGA-Profile": "external",
                            "X-Goog-Upload-Command": "upload, finalize",
                            "X-Goog-Upload-Offset": "0",
                        },
                        content=b"abc",
                    )
                    assert uploaded.status_code == 200, uploaded.text
                    file_id = uploaded.json()["file"]["name"].removeprefix("files/")
                else:
                    uploaded = await client.post(
                        "/v1/files",
                        headers={"X-GPT2GIGA-Profile": "selected"},
                        data={"purpose": "assistants"},
                        files={"file": ("test.txt", b"abc", "text/plain")},
                    )
                    assert uploaded.status_code == 200, uploaded.text
                    file_id = uploaded.json()["id"]
                assert file_id == "selected-file"
                assert calls[0].url.host == "selected.giga.example"
                assert calls[0].headers["authorization"] == (
                    "Bearer caller" if pass_token else "Bearer selected-token"
                )
                assert (await client.get(f"/v1/files/{file_id}")).status_code == 200
                generated = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "selected/model",
                        "messages": [
                            {
                                "role": "user",
                                "content": "hello",
                                "attachments": [file_id],
                            }
                        ],
                    },
                )
                assert generated.status_code == 200, generated.text
                if pass_token:
                    foreign = await client.get(
                        f"/v1/files/{file_id}",
                        headers={"Authorization": "Bearer giga-auth-other"},
                    )
                    assert foreign.status_code == 404, foreign.text
                default = await client.post(
                    "/v1/files",
                    data={"purpose": "assistants"},
                    files={"file": ("test.txt", b"abc", "text/plain")},
                )
                assert default.status_code == 200, default.text
                assert default.json()["id"] == "default-file"
                assert calls[-1].url.host == "default.giga.example"


@pytest.mark.parametrize("status", [400, 401, 403, 413, 422, 429])
async def test_definite_upload_rejection_releases_last_slot(status):
    from gpt2giga.app_state import get_resource_owner

    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) <= 2:
            return httpx2.Response(status, json={"message": "rejected"})
        return httpx2.Response(200, json=native_uploaded_file())

    async with sdk_app(handle) as (client, app):
        app.state.resource_store.max_resources = 1
        for _ in range(2):
            result = await client.post(
                "/v1/files",
                data={"purpose": "assistants"},
                files={"file": ("test.txt", b"abc", "text/plain")},
            )
            assert result.status_code == status, result.text
            assert (
                await app.state.resource_store.list(
                    get_resource_owner(owner_request(app)), "file_upload"
                )
                == []
            )
        result = await client.post(
            "/v1/files",
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert result.status_code == 200, result.text
        assert len(calls) == 3


async def test_duplicate_native_id_failed_publication_never_deletes_original():
    calls = []

    def handle(request):
        calls.append(request)
        assert not request.url.path.endswith("/delete")
        return httpx2.Response(200, json=native_uploaded_file())

    async with sdk_app(handle) as (client, _):
        first = await client.post(
            "/v1/files",
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert first.status_code == 200
        duplicate = await client.post(
            "/v1/files",
            data={"purpose": "assistants"},
            files={"file": ("test.txt", b"abc", "text/plain")},
        )
        assert duplicate.status_code == 500
        retrieved = await client.get("/v1/files/reserved-file")
        assert retrieved.status_code == 200
        assert retrieved.json() == first.json()
        assert len(calls) == 2


async def test_stuck_native_compensation_times_out_and_retains_intent(monkeypatch):
    import asyncio
    from gpt2giga.app_state import get_resource_owner
    from gpt2giga.common.files import upload_file_resource
    from gpt2giga.storage.resources import ResourceStoreError

    closed = asyncio.Event()

    async def handle(request):
        if request.url.path.endswith("/delete"):
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        return httpx2.Response(200, json=native_uploaded_file())

    async with sdk_app(handle) as (_, app):
        monkeypatch.setattr("gpt2giga.common.files._FILE_CLEANUP_TIMEOUT_SECONDS", 0.02)

        async def reject(*args, **kwargs):
            raise ResourceStoreError("publication failed")

        monkeypatch.setattr(app.state.resource_store, "promote_blob", reject)
        request = owner_request(app)
        with pytest.raises(ResourceStoreError):
            await asyncio.wait_for(
                upload_file_resource(
                    request, content=b"abc", filename="test.txt", mime_type="text/plain"
                ),
                1,
            )
        assert closed.is_set()
        pending = await app.state.resource_store.list(
            get_resource_owner(request), "file_upload"
        )
        assert len(pending) == 1
        assert pending[0].metadata["upstream_id"] == "reserved-file"
