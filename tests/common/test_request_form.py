"""Multipart parsing preserves limits and releases spooled files on every exit."""

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from gpt2giga.common.request_form import read_request_multipart
from gpt2giga.models.config import ProxyConfig, ProxySettings


def _request(
    body, *, content_type="multipart/form-data; boundary=test", limit=10 * 1024 * 1024
):
    app = FastAPI()
    app.state.config = ProxyConfig(proxy=ProxySettings(max_request_body_bytes=limit))
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/files",
            "app": app,
            "headers": [(b"content-type", content_type.encode())],
        },
        receive,
    )


def _body(content=b"file", *, suffix=b"\r\n--test--\r\n"):
    return (
        b'--test\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'
        b'--test\r\nContent-Disposition: form-data; name="file"; filename="data.txt"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n" + content + suffix
    )


async def test_large_file_uses_spooling_and_closes_tempfiles(monkeypatch):
    import starlette.formparsers

    opened = []
    factory = starlette.formparsers.SpooledTemporaryFile

    def record(*args, **kwargs):
        file = factory(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", record)
    content = b"a" * (9 * 1024 * 1024)
    result = await read_request_multipart(_request(_body(content)))
    assert result["files"]["file"]["content"] == content
    assert result["files"]["file"]["content_type"] == "text/plain"
    assert result["form"] == {"purpose": "user_data"}
    assert len(opened) == 1
    assert opened[0]._rolled
    assert opened[0].closed


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b"", "multipart/form-data; boundary=test"),
        (_body(suffix=b""), "multipart/form-data; boundary=test"),
        (_body(), "multipart/form-data"),
        (_body(), "multipart/form-data; boundary=test; charset=not-a-codec"),
        (
            _body().replace(
                b"Content-Type: application/octet-stream",
                b"Content-Type: text/plain; charset=not-a-codec",
            ),
            "multipart/form-data; boundary=test",
        ),
        (_body().replace(b'name="file";', b""), "multipart/form-data; boundary=test"),
    ],
)
async def test_malformed_multipart_has_public_error_and_closes_files(
    monkeypatch, body, content_type
):
    import starlette.formparsers

    opened = []
    factory = starlette.formparsers.SpooledTemporaryFile

    def record(*args, **kwargs):
        file = factory(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", record)
    with pytest.raises(HTTPException) as error:
        await read_request_multipart(_request(body, content_type=content_type))
    assert error.value.status_code == 400
    assert error.value.detail["error"]["code"] == "invalid_multipart"
    assert all(file.closed for file in opened)


async def test_multipart_enforces_actual_body_limit():
    with pytest.raises(HTTPException) as error:
        await read_request_multipart(_request(_body(b"a" * 1000), limit=512))
    assert error.value.status_code == 413


@pytest.mark.parametrize("purpose,accepted", [("user_data", False), ("batch", True)])
async def test_mime_file_limit_is_checked_before_read_and_after_all_fields(
    monkeypatch, purpose, accepted
):
    from starlette.datastructures import UploadFile

    request = _request(
        _body(
            b"a" * 1000,
            suffix=(
                b'\r\n--test\r\nContent-Disposition: form-data; name="purpose"\r\n\r\n'
                + purpose.encode()
                + b"\r\n--test--\r\n"
            ),
        )
    )
    request.app.state.config.proxy_settings.max_text_file_size_bytes = 512
    read = UploadFile.read
    reads = []

    async def record(self, *args):
        reads.append(self)
        return await read(self, *args)

    monkeypatch.setattr(UploadFile, "read", record)
    if accepted:
        result = await read_request_multipart(request)
        assert result["form"]["purpose"] == "batch"
        assert len(result["files"]["file"]["content"]) == 1000
        assert len(reads) == 1
    else:
        with pytest.raises(HTTPException) as error:
            await read_request_multipart(request)
        assert error.value.status_code == 413
        assert not reads


async def test_cancelled_parse_closes_partial_upload(monkeypatch):
    import starlette.formparsers

    opened = []
    factory = starlette.formparsers.SpooledTemporaryFile

    def record(*args, **kwargs):
        file = factory(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", record)
    request = _request(b"")
    receiving = asyncio.Event()

    async def stream():
        yield _body(b"a" * (2 * 1024 * 1024), suffix=b"")
        receiving.set()
        await asyncio.Event().wait()

    request.stream = stream
    task = asyncio.create_task(read_request_multipart(request))
    await receiving.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert opened and all(file.closed for file in opened)
