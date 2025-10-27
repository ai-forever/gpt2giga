from gpt2giga.protocol import AttachmentProcessor


class DummyClient:
    def __init__(self):
        self.called = False


def test_attachment_processor_construction():
    p = AttachmentProcessor(DummyClient())
    assert hasattr(p, "upload_image")
