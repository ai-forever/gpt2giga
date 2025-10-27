import io

from PIL import Image

from gpt2giga.protocol import AttachmentProcessor


class DummyFile:
    def __init__(self, id_="ok1"):
        self.id_ = id_


class DummyClient:
    def upload_file(self, file_tuple):
        return DummyFile("ok2")


def test_attachment_processor_success_with_pil(monkeypatch):
    # Подменяем Image.open, чтобы не требовались реальные байты
    real_open = Image.open

    def fake_open(fp):
        # создаём минимальное корректное изображение в памяти
        img = Image.new("RGB", (1, 1))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return real_open(buf)

    monkeypatch.setattr("gpt2giga.protocol.Image.open", fake_open)

    client = DummyClient()
    p = AttachmentProcessor(client)
    # Используем data URL с корректной base64-строкой PNG 1x1
    img = Image.new("RGB", (1, 1))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = buf.getvalue()
    import base64

    data_url = "data:image/png;base64," + base64.b64encode(b64).decode()
    file_id = p.upload_image(data_url)
    assert file_id == "ok2"
