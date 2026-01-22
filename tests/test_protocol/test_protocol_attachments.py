import base64
import time

import httpx
import pytest
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

    class FakeResponse:
        def __init__(self):
            self.headers = {"content-type": "image/jpeg"}
            self.content = b"\xff\xd8\xff\xd9"
            self.status_code = 200

        def raise_for_status(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        async def get(self, url):
            return FakeResponse()

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(
        "gpt2giga.protocol.attachments.httpx.AsyncClient", FakeAsyncClient
    )

    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
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

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        async def get(self, url):
            raise httpx.RequestError("Connection failed")

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(
        "gpt2giga.protocol.attachments.httpx.AsyncClient", FakeAsyncClient
    )

    client = DummyClient()
    p = AttachmentProcessor(logger=logger)
    result = await p.upload_file(client, "http://example.com/image.jpg")
    assert result is None  # Ошибка должна вернуть None

    await p.close()
