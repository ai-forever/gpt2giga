"""Google SDK Files lifecycle against mounted gateway and real GigaChat SDK."""

import asyncio
import io
import json

import httpx2
import pytest
from google import genai
from google.genai import types

from test_sdk_alpha_boundaries import sdk_app


def file_backend(seen):
    def handle(request):
        seen.append(request)
        if request.method == "POST" and request.url.path == "/v1/files":
            assert b"native-file-bytes" in request.content
            assert b"text/plain" in request.content
            return httpx2.Response(
                200,
                json={
                    "id": "upstream-file",
                    "bytes": 17,
                    "created_at": 123,
                    "filename": "notes.txt",
                    "purpose": "general",
                    "object": "file",
                },
            )
        if request.method == "POST" and request.url.path.endswith("/delete"):
            return httpx2.Response(
                200, json={"id": "upstream-file", "deleted": True, "object": "file"}
            )
        if request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            if request.url.path.startswith("/v2/"):
                assert payload["messages"][-1]["content"][-1]["files"] == [
                    {"id": "upstream-file"}
                ]
                return httpx2.Response(
                    200,
                    json={
                        "messages": [
                            {"role": "assistant", "content": [{"text": "summary"}]}
                        ],
                        "finish_reason": "stop",
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 1,
                            "total_tokens": 3,
                        },
                    },
                )
            assert payload["messages"][-1]["attachments"] == ["upstream-file"]
            return httpx2.Response(
                200,
                json={
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "summary"},
                        }
                    ],
                    "created": 1,
                    "model": "test-model",
                    "object": "chat.completion",
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                },
            )
        raise AssertionError((request.method, request.url.path))

    return handle


@pytest.mark.parametrize("base_path", ["", "/v1", "/v2"])
async def test_google_sdk_upload_get_list_generate_delete(base_path):
    seen = []
    async with sdk_app(file_backend(seen)) as (http_client, app):
        sdk = genai.Client(
            api_key="synthetic-google-key",
            http_options=types.HttpOptions(
                base_url=f"http://gateway.test{base_path}",
                api_version="v1beta",
                httpx_async_client=http_client,
            ),
        )
        uploaded = await sdk.aio.files.upload(
            file=io.BytesIO(b"native-file-bytes"),
            config={"display_name": "notes.txt", "mime_type": "text/plain"},
        )
        assert uploaded.name == "files/upstream-file"
        assert uploaded.mime_type == "text/plain"
        assert uploaded.state == types.FileState.ACTIVE
        assert uploaded.download_uri is None
        retrieved = await sdk.aio.files.get(name=uploaded.name)
        assert retrieved.create_time == uploaded.create_time
        assert retrieved.display_name == "notes.txt"
        listed = [file async for file in await sdk.aio.files.list()]
        assert [file.name for file in listed] == [uploaded.name]
        result = await sdk.aio.models.generate_content(
            model="test-model", contents=["Summarize", uploaded]
        )
        assert result.text == "summary"
        await sdk.aio.files.delete(name=uploaded.name)
        assert [file async for file in await sdk.aio.files.list()] == []
        assert await app.state.resource_store.list("unused", "upload") == []
    assert (
        sum(
            request.method == "POST" and request.url.path.endswith("/files")
            for request in seen
        )
        == 1
    )


async def start(client, length=17):
    response = await client.post(
        "/upload/v1beta/files",
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(length),
            "X-Goog-Upload-Header-Content-Type": "text/plain",
        },
        json={"file": {"displayName": "notes.txt"}},
    )
    assert response.status_code == 200, response.text
    return response.headers["x-goog-upload-url"]


async def test_resumable_offsets_query_length_and_metadata_only_rejection():
    seen = []
    async with sdk_app(file_backend(seen)) as (client, _):
        response = await client.post(
            "/v1beta/files", json={"file": {"displayName": "fake"}}
        )
        assert response.status_code == 400
        url = await start(client, 17)
        response = await client.post(
            url,
            headers={"X-Goog-Upload-Command": "upload", "X-Goog-Upload-Offset": "1"},
            content=b"native-",
        )
        assert response.status_code == 409
        response = await client.post(
            url,
            headers={"X-Goog-Upload-Command": "upload", "X-Goog-Upload-Offset": "0"},
            content=b"native-",
        )
        assert response.status_code == 200
        response = await client.post(url, headers={"X-Goog-Upload-Command": "query"})
        assert response.headers["x-goog-upload-size-received"] == "7"
        response = await client.post(
            url,
            headers={"X-Goog-Upload-Command": "finalize", "X-Goog-Upload-Offset": "7"},
        )
        assert response.status_code == 400
        response = await client.post(
            url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "7",
            },
            content=b"file-bytes",
        )
        assert response.status_code == 200, response.text
        assert response.json()["file"]["state"] == "ACTIVE"
        response = await client.get("/v1beta/files/upstream-file:download?alt=media")
        assert response.status_code == 403
    assert len(seen) == 1


@pytest.mark.parametrize(
    "uri", ["https://outside.test/file", "files/unknown", "files/file_g2g_unknown"]
)
async def test_unresolved_gemini_file_never_calls_provider(uri):
    seen = []
    async with sdk_app(file_backend(seen)) as (client, _):
        response = await client.post(
            "/models/test-model:generateContent",
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"fileData": {"fileUri": uri, "mimeType": "text/plain"}}
                        ],
                    }
                ]
            },
        )
        assert response.status_code in {400, 404}, response.text
    assert not seen


async def test_google_sdk_authenticated_finalize_requires_transport_header():
    seen = []
    async with sdk_app(file_backend(seen), auth=True) as (http_client, _):
        denied = await http_client.post("/upload/v1beta/files", json={})
        assert denied.status_code == 401
        # google-genai's raw-byte request uses transport defaults, unlike normal API calls.
        http_client.headers["x-api-key"] = "synthetic-gateway-key"
        sdk = genai.Client(
            api_key="synthetic-gateway-key",
            http_options=types.HttpOptions(
                base_url="http://gateway.test",
                api_version="v1beta",
                httpx_async_client=http_client,
            ),
        )
        uploaded = await sdk.aio.files.upload(
            file=io.BytesIO(b"native-file-bytes"),
            config={"display_name": "notes.txt", "mime_type": "text/plain"},
        )
        assert uploaded.name == "files/upstream-file"
    assert len(seen) == 1


async def test_gemini_file_metadata_restart_and_owner_isolation(tmp_path):
    from gpt2giga.storage.resources import ResourceStore

    seen = []
    async with sdk_app(file_backend(seen)) as (client, app):
        original = app.state.resource_store
        app.state.resource_store = await ResourceStore.open(tmp_path)
        url = await start(client)
        response = await client.post(
            url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            },
            content=b"native-file-bytes",
        )
        expected = response.json()["file"]
        await app.state.resource_store.aclose()
        app.state.resource_store = await ResourceStore.open(tmp_path)
        response = await client.get("/v1beta/files/upstream-file")
        assert response.json() == expected
        app.state.config.proxy_settings.resource_trusted_identity = "another-owner"
        response = await client.get("/v1beta/files/upstream-file")
        assert response.status_code == 404
        assert (await client.get("/v1beta/files")).json()["files"] == []
        await app.state.resource_store.aclose()
        app.state.resource_store = original
    assert len(seen) == 1


async def test_failed_finalize_cleans_session_and_does_not_replay():
    seen = []

    def fail(request):
        seen.append(request)
        raise httpx2.ReadTimeout("synthetic-secret", request=request)

    async with sdk_app(fail) as (client, _):
        url = await start(client)
        response = await client.post(
            url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            },
            content=b"native-file-bytes",
        )
        assert response.status_code == 504
        assert "synthetic-secret" not in response.text
        response = await client.post(url, headers={"X-Goog-Upload-Command": "query"})
        assert response.status_code == 404
    assert len(seen) == 1


async def test_google_sdk_downloads_generated_binary_bytes_and_session_expires():
    from starlette.requests import Request
    from gpt2giga.app_state import get_resource_owner

    async with sdk_app(
        lambda _: (_ for _ in ()).throw(AssertionError("unexpected upstream"))
    ) as (client, app):
        request = Request(
            {"type": "http", "method": "GET", "path": "/", "headers": [], "app": app}
        )
        owner = get_resource_owner(request)
        content = b"\x00\xffresult\r\n"
        await app.state.resource_store.put(
            owner,
            "file",
            "file_g2g_generated",
            {
                "id": "file_g2g_generated",
                "bytes": len(content),
                "created_at": 123,
                "filename": "result.jsonl",
                "mime_type": "application/jsonl",
                "local": True,
                "downloadable": True,
            },
            blob=content,
        )
        sdk = genai.Client(
            api_key="synthetic",
            http_options=types.HttpOptions(
                base_url="http://gateway.test",
                api_version="v1beta",
                httpx_async_client=client,
            ),
        )
        file = await sdk.aio.files.get(name="files/file_g2g_generated")
        assert (
            file.download_uri
            == "http://gateway.test/v1beta/files/file_g2g_generated:download?alt=media"
        )
        assert await sdk.aio.files.download(file=file) == content
        url = await start(client)
        app.state.resource_store._clock = lambda: 10**12
        response = await client.post(url, headers={"X-Goog-Upload-Command": "query"})
        assert response.status_code == 404
        assert await app.state.resource_store.purge_expired() == 2


async def test_jsonl_finalize_does_not_charge_double_blob_quota():
    def unexpected(request):
        pytest.fail("Local JSONL must not upload upstream")

    async with sdk_app(unexpected) as (client, app):
        app.state.resource_store.max_total_blob_bytes = 6
        response = await client.post(
            "/upload/v1beta/files",
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": "4",
                "X-Goog-Upload-Header-Content-Type": "application/jsonl",
            },
            json={"file": {"displayName": "input.jsonl"}},
        )
        url = response.headers["x-goog-upload-url"]
        result = await client.post(
            url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            },
            content=b"{}\n\n",
        )
        assert result.status_code == 200, result.text
        file_id = result.json()["file"]["name"].removeprefix("files/")
        content = await client.get(f"/v1/files/{file_id}/content")
        assert content.content == b"{}\n\n"


async def test_atomic_offset_conflict_maps_to_409(monkeypatch):
    async with sdk_app(lambda request: pytest.fail("No upstream call")) as (
        client,
        app,
    ):
        url = await start(client, 4)
        original = app.state.resource_store.append_blob
        arrived = 0
        ready = asyncio.Event()

        async def concurrent_append(*args, **kwargs):
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                ready.set()
            await ready.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(app.state.resource_store, "append_blob", concurrent_append)
        responses = await asyncio.gather(
            *(
                client.post(
                    url,
                    headers={
                        "X-Goog-Upload-Command": "upload",
                        "X-Goog-Upload-Offset": "0",
                    },
                    content=b"ab",
                )
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in responses) == [200, 409]
        queried = await client.post(url, headers={"X-Goog-Upload-Command": "query"})
        assert queried.headers["X-Goog-Upload-Size-Received"] == "2"


@pytest.mark.parametrize("command", ["upload", "upload, finalize"])
async def test_rejected_resumable_appends_leave_no_unaccounted_disk(command):
    seen = []
    async with sdk_app(file_backend(seen)) as (client, app):
        store = app.state.resource_store
        size = 1024 * 1024
        store.max_total_blob_bytes = size
        urls = [await start(client, size) for _ in range(8)]
        store.max_metadata_bytes = store._db.execute(
            "SELECT metadata_bytes FROM resource_usage"
        ).fetchone()[0]
        for url in urls:
            response = await client.post(
                url,
                headers={"X-Goog-Upload-Command": command, "X-Goog-Upload-Offset": "0"},
                content=b"x" * size,
            )
            assert response.status_code == 413, response.text
            query = await client.post(url, headers={"X-Goog-Upload-Command": "query"})
            assert query.headers["x-goog-upload-size-received"] == "0"
            assert query.headers["x-goog-upload-status"] == "active"
        assert (
            store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0]
            == 0
        )
        assert sum(p.stat().st_size for p in (store.path / "blobs").iterdir()) == 0
        assert seen == []


async def test_cancel_cannot_win_after_finalization_claim():
    seen = []
    entered, release = asyncio.Event(), asyncio.Event()
    backend = file_backend(seen)

    async def handle(request):
        entered.set()
        await release.wait()
        return backend(request)

    async with sdk_app(handle) as (client, _):
        url = await start(client)
        finalizing = asyncio.create_task(
            client.post(
                url,
                headers={
                    "X-Goog-Upload-Command": "upload, finalize",
                    "X-Goog-Upload-Offset": "0",
                },
                content=b"native-file-bytes",
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            cancelled = await client.post(
                url, headers={"X-Goog-Upload-Command": "cancel"}
            )
            assert cancelled.status_code == 409, cancelled.text
            assert "x-goog-upload-status" not in cancelled.headers
        finally:
            release.set()
            finalized = await finalizing
        assert finalized.status_code == 200, finalized.text
        assert finalized.headers["x-goog-upload-status"] == "final"
        assert (await client.get("/v1beta/files/upstream-file")).status_code == 200
        assert len(seen) == 1


async def test_cancel_wins_before_finalization_claim(monkeypatch):
    seen = []
    async with sdk_app(file_backend(seen)) as (client, app):
        url = await start(client)
        entered, release = asyncio.Event(), asyncio.Event()
        store = app.state.resource_store
        original_update = store.update

        async def delayed_claim(owner, kind, public_id, updates):
            if kind == "upload":
                entered.set()
                await release.wait()
            return await original_update(owner, kind, public_id, updates)

        monkeypatch.setattr(store, "update", delayed_claim)
        finalizing = asyncio.create_task(
            client.post(
                url,
                headers={
                    "X-Goog-Upload-Command": "upload, finalize",
                    "X-Goog-Upload-Offset": "0",
                },
                content=b"native-file-bytes",
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            cancelled = await client.post(
                url, headers={"X-Goog-Upload-Command": "cancel"}
            )
            assert cancelled.status_code == 200
            assert cancelled.headers["x-goog-upload-status"] == "cancelled"
        finally:
            release.set()
            finalized = await finalizing
        assert finalized.status_code == 404
        assert seen == []
