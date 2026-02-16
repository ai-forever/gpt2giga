import base64

import pytest
from fastapi import HTTPException
from loguru import logger

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer


class DummyAttachmentProc:
    def __init__(self):
        self.calls = 0

    class _UploadMeta:
        def __init__(self, file_id: str, file_size_bytes: int, file_kind: str):
            self.file_id = file_id
            self.file_size_bytes = file_size_bytes
            self.file_kind = file_kind

    async def upload_file(self, giga_client, url, filename=None):
        self.calls += 1
        return f"file_{self.calls}"

    async def upload_file_with_meta(
        self,
        giga_client,
        url,
        filename=None,
        max_audio_image_total_remaining=None,
    ):
        # Каждый файл "весит" 6 байт для тестов
        size_bytes = 6
        if (
            max_audio_image_total_remaining is not None
            and size_bytes > max_audio_image_total_remaining
        ):
            return None
        self.calls += 1
        return self._UploadMeta(f"file_{self.calls}", size_bytes, "image")


class DummyGigaClient:
    async def aupload_file(self, file_tuple):
        return type("DummyUploaded", (), {"id_": "file_x"})()


@pytest.mark.asyncio
async def test_transform_messages_with_images_and_limit_two_per_message():
    cfg = ProxyConfig()
    cfg.proxy_settings.enable_images = True
    ap = DummyAttachmentProc()
    rt = RequestTransformer(cfg, logger=logger, attachment_processor=ap)

    content = [
        {"type": "text", "text": "t1"},
        {"type": "image_url", "image_url": {"url": "u1"}},
        {"type": "image_url", "image_url": {"url": "u2"}},
        {"type": "image_url", "image_url": {"url": "u3"}},
    ]
    messages = [{"role": "user", "content": content}]
    out = await rt.transform_messages(messages, giga_client=object())

    assert out[0]["attachments"] == ["file_1", "file_2"]


@pytest.mark.asyncio
async def test_transform_messages_total_attachments_limit_ten():
    cfg = ProxyConfig()
    cfg.proxy_settings.enable_images = True
    ap = DummyAttachmentProc()
    rt = RequestTransformer(cfg, logger=logger, attachment_processor=ap)

    many = [{"type": "image_url", "image_url": {"url": f"u{i}"}} for i in range(20)]
    messages = [
        {"role": "user", "content": many[:5]},
        {"role": "user", "content": many[5:15]},
    ]
    out = await rt.transform_messages(messages, giga_client=object())
    total = sum(len(m.get("attachments", [])) for m in out)
    assert total == 4


@pytest.mark.asyncio
async def test_transform_messages_audio_image_total_size_limit():
    cfg = ProxyConfig()
    cfg.proxy_settings.enable_images = True
    cfg.proxy_settings.max_audio_image_total_size_bytes = 10
    ap = DummyAttachmentProc()
    rt = RequestTransformer(cfg, logger=logger, attachment_processor=ap)

    content = [
        {"type": "image_url", "image_url": {"url": "u1"}},
        {"type": "image_url", "image_url": {"url": "u2"}},
    ]
    messages = [{"role": "user", "content": content}]
    out = await rt.transform_messages(messages, giga_client=object())

    # Первый файл (6 байт) проходит, второй (еще 6 байт) должен быть отклонен лимитом 10 байт.
    assert out[0]["attachments"] == ["file_1"]


@pytest.mark.asyncio
async def test_transform_messages_raises_413_on_attachment_oversize():
    cfg = ProxyConfig()
    cfg.proxy_settings.enable_images = True
    processor = AttachmentProcessor(logger=logger, max_image_file_size_bytes=3)
    rt = RequestTransformer(cfg, logger=logger, attachment_processor=processor)

    img_bytes = b"\xff\xd8\xff\xd9"
    data_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        }
    ]

    with pytest.raises(HTTPException) as exc:
        await rt.transform_messages(messages, giga_client=DummyGigaClient())
    assert exc.value.status_code == 413
