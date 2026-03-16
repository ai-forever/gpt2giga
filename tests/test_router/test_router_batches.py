import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
from pydantic import BaseModel, Field

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.api import router


class FakeUploadedFile(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(alias="object")
    bytes_: int = Field(alias="bytes")
    created_at: int
    filename: str
    purpose: str
    access_policy: str | None = None


class FakeDeletedFile(BaseModel):
    id_: str = Field(alias="id")
    deleted: bool


class FakeRequestCounts(BaseModel):
    total: int
    completed: int | None = None
    failed: int | None = None


class FakeBatch(BaseModel):
    id_: str = Field(alias="id")
    method: str
    request_counts: FakeRequestCounts
    status: str
    output_file_id: str | None = None
    created_at: int
    updated_at: int


class FakeBatches(BaseModel):
    batches: list[FakeBatch]


class FakeFileContent(BaseModel):
    content: str


class FakeGigaChat:
    def __init__(self):
        self.files = {}
        self.batches = {}
        self.last_batch_content = None
        self.last_batch_method = None
        self._created_at = 100

    async def aupload_file(self, file, purpose):
        filename, content, _content_type = file
        file_id = f"file-{len(self.files) + 1}"
        uploaded = FakeUploadedFile(
            id=file_id,
            object="file",
            bytes=len(content),
            created_at=self._created_at,
            filename=filename or file_id,
            purpose=purpose,
        )
        self.files[file_id] = {
            "content": content,
            "object": uploaded,
        }
        self._created_at += 1
        return uploaded

    async def aget_files(self):
        class Payload:
            data = []

        payload = Payload()
        payload.data = [file_data["object"] for file_data in self.files.values()]
        return payload

    async def aget_file(self, file):
        return self.files[file]["object"]

    async def adelete_file(self, file):
        self.files.pop(file, None)
        return FakeDeletedFile(id=file, deleted=True)

    async def aget_file_content(self, file_id):
        return FakeFileContent(
            content=base64.b64encode(self.files[file_id]["content"]).decode("utf-8")
        )

    async def acreate_batch(self, content, method):
        self.last_batch_content = content
        self.last_batch_method = method
        output_file_id = "file-output-1"
        if output_file_id not in self.files:
            output_payload = {
                "id": "req-1",
                "result": {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "done",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            }
            self.files[output_file_id] = {
                "content": (json.dumps(output_payload) + "\n").encode("utf-8"),
                "object": FakeUploadedFile(
                    id=output_file_id,
                    object="file",
                    bytes=len(json.dumps(output_payload)) + 1,
                    created_at=self._created_at,
                    filename="batch-output.jsonl",
                    purpose="general",
                ),
            }
            self._created_at += 1

        batch = FakeBatch(
            id="batch-1",
            method=method,
            request_counts=FakeRequestCounts(total=1, completed=1, failed=0),
            status="completed",
            output_file_id=output_file_id,
            created_at=123,
            updated_at=124,
        )
        self.batches[batch.id_] = batch
        return batch

    async def aget_batches(self, batch_id=None):
        if batch_id is None:
            return FakeBatches(batches=list(self.batches.values()))
        batch = self.batches.get(batch_id)
        return FakeBatches(batches=[batch] if batch else [])


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {
            "model": "GigaChat",
            "messages": data["messages"],
            "translated": "chat",
        }

    async def prepare_response(self, data, giga_client=None):
        return {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": data["input"]}],
            "translated": "responses",
        }


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigaChat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    return app


def test_files_endpoints_roundtrip():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/files",
        data={"purpose": "batch"},
        files={"file": ("input.jsonl", b'{"hello":"world"}\n', "application/json")},
    )
    assert response.status_code == 200
    file_id = response.json()["id"]
    assert response.json()["purpose"] == "batch"

    retrieve = client.get(f"/files/{file_id}")
    assert retrieve.status_code == 200
    assert retrieve.json()["purpose"] == "batch"

    listed = client.get("/files", params={"purpose": "batch"})
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == file_id

    content = client.get(f"/files/{file_id}/content")
    assert content.status_code == 200
    assert content.content == b'{"hello":"world"}\n'

    deleted = client.delete(f"/files/{file_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"id": file_id, "deleted": True, "object": "file"}


def test_batches_endpoints_translate_openai_flow():
    app = make_app()
    giga_client = app.state.gigachat_client
    client = TestClient(app)

    input_line = {
        "custom_id": "req-1",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hello"}],
        },
    }
    upload = client.post(
        "/files",
        data={"purpose": "batch"},
        files={
            "file": (
                "batch.jsonl",
                (json.dumps(input_line) + "\n").encode("utf-8"),
                "application/json",
            )
        },
    )
    input_file_id = upload.json()["id"]

    created = client.post(
        "/batches",
        json={
            "completion_window": "24h",
            "endpoint": "/v1/chat/completions",
            "input_file_id": input_file_id,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["object"] == "batch"
    assert body["endpoint"] == "/v1/chat/completions"
    assert body["input_file_id"] == input_file_id
    assert giga_client.last_batch_method == "chat_completions"

    translated_line = json.loads(giga_client.last_batch_content.decode("utf-8").strip())
    assert translated_line["custom_id"] == "req-1"
    assert translated_line["body"]["translated"] == "chat"
    assert translated_line["body"]["messages"][0]["content"] == "hello"

    retrieved = client.get("/batches/batch-1")
    assert retrieved.status_code == 200
    assert retrieved.json()["output_file_id"] == "file-output-1"

    listed = client.get("/batches")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == "batch-1"

    output_file = client.get("/files/file-output-1")
    assert output_file.status_code == 200
    assert output_file.json()["purpose"] == "batch_output"

    output_content = client.get("/files/file-output-1/content")
    assert output_content.status_code == 200
    transformed_line = json.loads(output_content.content.decode("utf-8").strip())
    assert transformed_line["custom_id"] == "req-1"
    assert transformed_line["response"]["body"]["object"] == "chat.completion"
    assert transformed_line["response"]["body"]["model"] == "gpt-x"
