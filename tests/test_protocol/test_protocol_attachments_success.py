from loguru import logger

from gpt2giga.protocol import AttachmentProcessor


class DummyFile:
    def __init__(self, id_="ok1"):
        self.id_ = id_


class DummyClient:
    async def aupload_file(self, file_tuple):
        self.uploaded_file = file_tuple
        return DummyFile("ok2")


async def test_attachment_processor_success_with_png_data_url():
    client = DummyClient()
    p = AttachmentProcessor(logger)
    # Valid 1x1 PNG; attachment uploads do not decode or transcode images.
    data_url = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAA"
        "AAAEAAH2FzhVAAAAAElFTkSuQmCC"
    )
    file_id = await p.upload_file(client, data_url)
    assert file_id == "ok2"
    filename, content = client.uploaded_file
    assert filename.endswith(".png")
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
