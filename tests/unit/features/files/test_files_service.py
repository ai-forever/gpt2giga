import base64
import json
from types import SimpleNamespace

import pytest
from loguru import logger

from gpt2giga.features.files.service import FilesService, get_files_service_from_state
from gpt2giga.providers.gigachat import ResponseProcessor


class FakeUploadedFile:
    def __init__(
        self,
        file_id: str,
        *,
        bytes_: int,
        created_at: int,
        filename: str,
        purpose: str,
    ):
        self.id_ = file_id
        self.bytes_ = bytes_
        self.created_at = created_at
        self.filename = filename
        self.purpose = purpose


class FakeDeletedFile:
    def __init__(self, file_id: str):
        self.id_ = file_id
        self.deleted = True


class FakeFileContent:
    def __init__(self, content: bytes):
        self.content = base64.b64encode(content).decode("utf-8")


class FakeFilesClient:
    def __init__(self):
        self.last_upload = None
        self.files = {
            "input-file-1": FakeFileContent(
                b'{"custom_id":"req-1","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-x","messages":[{"role":"user","content":"hello"}]}}\n'
            ),
            "file-output-1": FakeFileContent(
                b'{"id":"req-1","result":{"choices":[{"message":{"role":"assistant","content":"done"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}}\n'
            ),
        }

    async def aupload_file(self, file, purpose):
        self.last_upload = (file, purpose)
        filename, content, _ = file
        return FakeUploadedFile(
            "file-1",
            bytes_=len(content),
            created_at=123,
            filename=filename or "file-1",
            purpose=purpose,
        )

    async def aget_files(self):
        return SimpleNamespace(data=[])

    async def aget_file(self, file):
        return FakeUploadedFile(
            file,
            bytes_=11,
            created_at=123,
            filename="payload.jsonl",
            purpose="general",
        )

    async def adelete_file(self, file):
        return FakeDeletedFile(file)

    async def aget_file_content(self, file_id):
        return self.files[file_id]


@pytest.mark.asyncio
async def test_files_service_create_file_uses_provider_and_store_contract():
    service = FilesService()
    giga_client = FakeFilesClient()
    file_store = {}

    result = await service.create_file(
        purpose="batch",
        upload={
            "filename": "input.jsonl",
            "content": b'{"hello":"world"}\n',
            "content_type": "application/json",
        },
        giga_client=giga_client,
        file_store=file_store,
    )

    assert giga_client.last_upload[1] == "general"
    assert file_store["file-1"]["purpose"] == "batch"
    assert result["id"] == "file-1"
    assert result["purpose"] == "batch"


@pytest.mark.asyncio
async def test_files_service_get_file_content_transforms_batch_output():
    service = FilesService()
    giga_client = FakeFilesClient()
    response_processor = ResponseProcessor(logger=logger)

    content = await service.get_file_content(
        "file-output-1",
        giga_client=giga_client,
        batch_store={
            "batch-1": {
                "endpoint": "/v1/chat/completions",
                "input_file_id": "input-file-1",
                "completion_window": "24h",
                "output_file_id": "file-output-1",
            }
        },
        response_processor=response_processor,
    )

    line = json.loads(content.decode("utf-8").strip())
    assert line["custom_id"] == "req-1"
    assert line["response"]["body"]["object"] == "chat.completion"
    assert line["response"]["body"]["model"] == "gpt-x"


def test_get_files_service_from_state_reuses_existing_service():
    state = SimpleNamespace()

    first = get_files_service_from_state(state)
    second = get_files_service_from_state(state)

    assert first is second
    assert state.files_service is first
