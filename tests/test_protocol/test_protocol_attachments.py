import base64

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
    p = AttachmentProcessor(client, logger=logger)

    img_bytes = b"\xff\xd8\xff\xd9"  # минимальный jpeg маркер SOI/EOI
    data_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()

    id1 = await p.upload_file(data_url)
    assert id1 == "f1"

    # Повтор с тем же URL должен взять из кэша, не дергая upload_file
    before = client.calls
    id2 = await p.upload_file(data_url)
    assert id2 == id1
    assert client.calls == before


@pytest.mark.asyncio
async def test_attachment_processor_httpx_invalid_content_type(monkeypatch):
    class FakeResp:
        def __init__(self):
            self.headers = {"content-type": "text/html"}
            self.content = b"<html>not image</html>"

    monkeypatch.setattr(
        "gpt2giga.protocol.attachments.httpx.get", lambda url, timeout=30: FakeResp()
    )

    client = DummyClient()
    p = AttachmentProcessor(client, logger=logger)
    result = await p.upload_file("http://example.com/image")
    assert result == "f1"
