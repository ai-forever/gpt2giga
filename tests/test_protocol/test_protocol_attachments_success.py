import io

import pytest
from PIL import Image
from loguru import logger

from gpt2giga.protocol import AttachmentProcessor


class DummyFile:
    def __init__(self, id_="ok1"):
        self.id_ = id_


class DummyClient:
    async def aupload_file(self, file_tuple):
        return DummyFile("ok2")


@pytest.mark.asyncio
async def test_attachment_processor_success_with_pil(monkeypatch):
    client = DummyClient()
    p = AttachmentProcessor(client, logger)
    # Используем data URL с корректной base64-строкой PNG 1x1
    img = Image.new("RGB", (1, 1))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = buf.getvalue()
    import base64

    data_url = "data:image/png;base64," + base64.b64encode(b64).decode()
    file_id = await p.upload_file(data_url)
    assert file_id == "ok2"
