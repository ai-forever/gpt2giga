import base64
import ipaddress
import time

import httpx
import pytest
from fastapi import HTTPException
from loguru import logger

from gpt2giga.protocol import AttachmentProcessor


class DummyFile:
    def __init__(self, id_="file123"):
        self.id_ = id_


class DummyClient:
    def __init__(self):
        self.calls = 0

    async def aupload_file(self, file_tuple):
        self.calls += 1
        return DummyFile(id_="f" + str(self.calls))


class FakeStreamResponse:
    def __init__(
        self,
        *,
        content: bytes = b"\xff\xd8\xff\xd9",
        content_type: str = "image/jpeg",
        content_length: str | None = None,
    ):
        self.headers = {"content-type": content_type}
        if content_length is not None:
            self.headers["content-length"] = content_length
        self._content = content
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        yield self._content


@pytest.mark.asyncio
async def test_attachment_processor_base64_and_cache(monkeypatch):
    client = DummyClient()
    p = AttachmentProcessor(logger=logger)

    img_bytes = b"\xff\xd8\xff\xd9"  # минимальный jpeg маркер SOI/EOI
    data_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()

    id1 = await p.upload_file(client, data_url)
    assert id1 == "f1"

    # Повтор с тем же URL должен взять из кэша, не дергая upload_file
    before = client.calls
    id2 = await p.upload_file(client, data_url)
    assert id2 == id1
    assert client.calls == before


@pytest.mark.asyncio
async def test_attachment_processor_async_httpx(monkeypatch):
    """Тест async HTTP клиента для скачивания изображений"""

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        def stream(self, method, url):
            return FakeStreamResponse()

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(
        "gpt2giga.protocol.attachment.attachments.httpx.AsyncClient", FakeAsyncClient
    )

    client = DummyClient()
    p = AttachmentProcessor(logger=logger)

    async def fake_resolve(host: str, port: int):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(p, "_resolve_host_ips", fake_resolve)
    result = await p.upload_file(client, "http://example.com/image.jpg")
    assert result == "f1"

    # Cleanup
    await p.close()


@pytest.mark.asyncio
async def test_attachment_processor_cache_ttl(monkeypatch):
    """Тест TTL кэша - записи должны истекать"""

    client = DummyClient()
    # Очень короткий TTL для теста
    p = AttachmentProcessor(logger=logger, cache_ttl_seconds=1)

    img_bytes = b"\xff\xd8\xff\xd9"
    data_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()

    id1 = await p.upload_file(client, data_url)
    assert id1 == "f1"
    assert client.calls == 1

    # Ждём истечения TTL
    time.sleep(1.1)

    # Теперь должен загрузить заново
    id2 = await p.upload_file(client, data_url)
    assert id2 == "f2"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_attachment_processor_cache_lru_eviction(monkeypatch):
    """Тест LRU eviction при переполнении кэша"""

    client = DummyClient()
    # Маленький кэш для теста
    p = AttachmentProcessor(logger=logger, max_cache_size=3)

    # Заполняем кэш
    for i in range(5):
        img_bytes = f"image{i}".encode()
        data_url = f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode()}"
        await p.upload_file(client, data_url)

    # Кэш не должен превышать max_size
    assert len(p._cache) <= 3


@pytest.mark.asyncio
async def test_attachment_processor_cache_stats():
    """Тест получения статистики кэша"""

    p = AttachmentProcessor(logger=logger, max_cache_size=100, cache_ttl_seconds=3600)

    stats = p.get_cache_stats()
    assert stats["size"] == 0
    assert stats["max_size"] == 100
    assert stats["ttl_seconds"] == 3600
    assert stats["expired_entries"] == 0


@pytest.mark.asyncio
async def test_attachment_processor_clear_cache():
    """Тест очистки кэша"""

    client = DummyClient()
    p = AttachmentProcessor(logger=logger)

    img_bytes = b"\xff\xd8\xff\xd9"
    data_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
    await p.upload_file(client, data_url)

    assert len(p._cache) == 1

    cleared = p.clear_cache()
    assert cleared == 1
    assert len(p._cache) == 0


@pytest.mark.asyncio
async def test_attachment_processor_http_error(monkeypatch):
    """Тест обработки HTTP ошибок"""

    class ErrorStreamResponse:
        async def __aenter__(self):
            raise httpx.RequestError("Connection failed")

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        def stream(self, method, url):
            return ErrorStreamResponse()

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(
        "gpt2giga.protocol.attachment.attachments.httpx.AsyncClient", FakeAsyncClient
    )

    client = DummyClient()
    p = AttachmentProcessor(logger=logger)

    async def fake_resolve(host: str, port: int):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(p, "_resolve_host_ips", fake_resolve)
    result = await p.upload_file(client, "http://example.com/image.jpg")
    assert result is None  # Ошибка должна вернуть None

    await p.close()


@pytest.mark.asyncio
async def test_attachment_processor_base64_image_limit():
    client = DummyClient()
    p = AttachmentProcessor(logger=logger, max_image_file_size_bytes=3)
    img_bytes = b"\xff\xd8\xff\xd9"
    data_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()

    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, data_url)
    assert exc.value.status_code == 413
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_remote_content_length_limit(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        def stream(self, method, url):
            return FakeStreamResponse(
                content=b"\x00\x01\x02\x03",
                content_type="image/jpeg",
                content_length="100",
            )

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(
        "gpt2giga.protocol.attachment.attachments.httpx.AsyncClient", FakeAsyncClient
    )

    client = DummyClient()
    p = AttachmentProcessor(logger=logger, max_image_file_size_bytes=50)

    async def fake_resolve(host: str, port: int):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(p, "_resolve_host_ips", fake_resolve)
    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, "http://example.com/image.jpg")
    assert exc.value.status_code == 413
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_rejects_unsupported_base64_mime():
    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
    payload = base64.b64encode(b"hello").decode()
    data_url = f"data:application/zip;base64,{payload}"

    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, data_url)
    assert exc.value.status_code == 415
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_rejects_unsupported_remote_content_type(
    monkeypatch,
):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        def stream(self, method, url):
            return FakeStreamResponse(
                content=b"dummy",
                content_type="application/octet-stream",
                content_length="5",
            )

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(
        "gpt2giga.protocol.attachment.attachments.httpx.AsyncClient", FakeAsyncClient
    )

    client = DummyClient()
    p = AttachmentProcessor(logger=logger)

    async def fake_resolve(host: str, port: int):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(p, "_resolve_host_ips", fake_resolve)

    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, "http://example.com/unknown.bin")
    assert exc.value.status_code == 415
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_blocks_localhost_url():
    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, "http://localhost/image.jpg")
    assert exc.value.status_code == 400
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_blocks_loopback_ip_url():
    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, "http://127.0.0.1/image.jpg")
    assert exc.value.status_code == 400
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_blocks_metadata_ip_url():
    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, "http://169.254.169.254/latest/meta-data/")
    assert exc.value.status_code == 400
    assert client.calls == 0


@pytest.mark.asyncio
async def test_attachment_processor_blocks_private_ip_url():
    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
    with pytest.raises(HTTPException) as exc:
        await p.upload_file(client, "http://10.0.0.1/image.jpg")
    assert exc.value.status_code == 400
    assert client.calls == 0
