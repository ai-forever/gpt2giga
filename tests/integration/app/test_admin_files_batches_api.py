import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gpt2giga.api.admin import admin_api_router
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings
from gpt2giga.features.batches import BatchesService
from gpt2giga.features.files import FilesService
from gpt2giga.features.files_batches import FilesBatchesService


class FakeUploadedFile(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(alias="object")
    bytes_: int = Field(alias="bytes")
    created_at: int
    filename: str
    purpose: str


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
        self.next_batch_index = 4
        self.next_file_index = 4
        self.files = {
            "file-openai-1": {
                "content": (
                    b'{"custom_id":"req-openai-1","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-test","messages":[{"role":"user","content":"hello openai"}]}}\n'
                ),
                "object": FakeUploadedFile(
                    id="file-openai-1",
                    object="file",
                    bytes=156,
                    created_at=110,
                    filename="openai-input.jsonl",
                    purpose="general",
                ),
            },
            "file-anthropic-output-1": {
                "content": (
                    json.dumps(
                        {
                            "custom_id": "req-1",
                            "response": {
                                "status_code": 200,
                                "body": {
                                    "choices": [
                                        {
                                            "message": {
                                                "content": "anthropic result",
                                            },
                                            "finish_reason": "stop",
                                        }
                                    ],
                                    "usage": {},
                                },
                            },
                        }
                    )
                    + "\n"
                ).encode("utf-8"),
                "object": FakeUploadedFile(
                    id="file-anthropic-output-1",
                    object="file",
                    bytes=22,
                    created_at=111,
                    filename="anthropic-output.jsonl",
                    purpose="general",
                ),
            },
            "file-gemini-1": {
                "content": b"gemini upload",
                "object": FakeUploadedFile(
                    id="file-gemini-1",
                    object="file",
                    bytes=13,
                    created_at=112,
                    filename="gemini.bin",
                    purpose="general",
                ),
            },
            "file-gemini-output-1": {
                "content": (json.dumps({"response": {"candidates": []}}) + "\n").encode(
                    "utf-8"
                ),
                "object": FakeUploadedFile(
                    id="file-gemini-output-1",
                    object="file",
                    bytes=33,
                    created_at=113,
                    filename="gemini-output.jsonl",
                    purpose="general",
                ),
            },
        }
        self.batches = {
            "batch-openai-1": FakeBatch(
                id="batch-openai-1",
                method="chat_completions",
                request_counts=FakeRequestCounts(total=1, completed=1, failed=0),
                status="completed",
                output_file_id="file-openai-output-1",
                created_at=120,
                updated_at=121,
            ),
            "batch-anthropic-1": FakeBatch(
                id="batch-anthropic-1",
                method="chat_completions",
                request_counts=FakeRequestCounts(total=2, completed=1, failed=1),
                status="completed",
                output_file_id="file-anthropic-output-1",
                created_at=122,
                updated_at=123,
            ),
            "batch-gemini-1": FakeBatch(
                id="batch-gemini-1",
                method="chat_completions",
                request_counts=FakeRequestCounts(total=1, completed=1, failed=0),
                status="completed",
                output_file_id="file-gemini-output-1",
                created_at=124,
                updated_at=125,
            ),
        }

    async def aget_files(self):
        class Payload:
            data = []

        payload = Payload()
        payload.data = [entry["object"] for entry in self.files.values()]
        return payload

    async def aget_file(self, file):
        return self.files[file]["object"]

    async def aget_file_content(self, file_id):
        return FakeFileContent(
            content=base64.b64encode(self.files[file_id]["content"]).decode("utf-8")
        )

    async def adelete_file(self, file):
        raise AssertionError(f"Unexpected delete: {file}")

    async def aupload_file(self, file, purpose):
        filename, content, _content_type = file
        file_id = f"file-created-{self.next_file_index}"
        created_at = 131 + self.next_file_index
        self.next_file_index += 1
        uploaded = FakeUploadedFile(
            id=file_id,
            object="file",
            bytes=len(content),
            created_at=created_at,
            filename=filename or file_id,
            purpose="general",
        )
        self.files[file_id] = {
            "content": content,
            "object": uploaded,
        }
        return uploaded

    async def acreate_batch(self, file, method):
        batch_id = f"batch-created-{self.next_batch_index}"
        output_file_id = f"file-created-output-{self.next_file_index}"
        self.next_batch_index += 1
        self.next_file_index += 1
        self.batches[batch_id] = FakeBatch(
            id=batch_id,
            method=method,
            request_counts=FakeRequestCounts(total=1, completed=1, failed=0),
            status="completed",
            output_file_id=output_file_id,
            created_at=130,
            updated_at=131,
        )
        self.files[output_file_id] = {
            "content": file,
            "object": FakeUploadedFile(
                id=output_file_id,
                object="file",
                bytes=len(file),
                created_at=131,
                filename=f"{output_file_id}.jsonl",
                purpose="general",
            ),
        }
        return self.batches[batch_id]

    async def aget_batches(self, batch_id=None):
        if batch_id is None:
            return FakeBatches(batches=list(self.batches.values()))
        batch = self.batches.get(batch_id)
        return FakeBatches(batches=[batch] if batch else [])


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        del data, giga_client
        return {}


def make_app():
    app = FastAPI()
    app.include_router(admin_api_router)
    ensure_runtime_dependencies(
        app.state,
        config=ProxyConfig(proxy=ProxySettings(logs_ip_allowlist=["testclient"])),
    )
    app.state.gigachat_client = FakeGigaChat()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.files_service = FilesService()
    app.state.batches_service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
    )
    app.state.files_batches_service = FilesBatchesService()
    app.state.file_metadata_store = {
        "file-anthropic-output-1": {"batch_id": "batch-anthropic-1"},
        "file-gemini-1": {
            "display_name": "Gemini Upload",
            "mime_type": "text/plain",
            "source": "UPLOADED",
        },
        "file-gemini-output-1": {"batch_id": "batch-gemini-1"},
    }
    app.state.batch_metadata_store = {
        "batch-openai-1": {
            "endpoint": "/v1/chat/completions",
            "input_file_id": "file-openai-1",
            "output_file_id": "file-openai-output-1",
            "model": "gpt-test",
        },
        "batch-anthropic-1": {
            "api_format": "anthropic_messages",
            "endpoint": "/v1/chat/completions",
            "output_file_id": "file-anthropic-output-1",
            "requests": [{}, {}],
        },
        "batch-gemini-1": {
            "api_format": "gemini_generate_content",
            "display_name": "Gemini Batch",
            "model": "gemini-test",
            "input_file_id": "file-gemini-1",
            "output_file_id": "file-gemini-output-1",
            "requests": [{}],
        },
    }
    return app


def test_admin_files_batches_inventory_returns_mixed_formats():
    client = TestClient(make_app())

    response = client.get("/admin/api/files-batches/inventory")

    assert response.status_code == 200
    body = response.json()
    assert {item["api_format"] for item in body["files"]} == {
        "openai",
        "anthropic",
        "gemini",
    }
    assert {item["api_format"] for item in body["batches"]} == {
        "openai",
        "anthropic",
        "gemini",
    }
    assert body["counts"] == {
        "files": 4,
        "batches": 3,
        "output_ready": 3,
        "needs_attention": 1,
    }


def test_admin_files_batches_inventory_filters_by_api_format():
    client = TestClient(make_app())

    response = client.get(
        "/admin/api/files-batches/inventory",
        params={"api_format": "gemini"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["files"]] == [
        "file-gemini-output-1",
        "file-gemini-1",
    ]
    assert [item["id"] for item in body["batches"]] == ["batch-gemini-1"]


def test_admin_files_batches_detail_endpoints_return_normalized_records():
    client = TestClient(make_app())

    file_response = client.get("/admin/api/files-batches/files/file-gemini-1")
    batch_response = client.get("/admin/api/files-batches/batches/batch-anthropic-1")

    assert file_response.status_code == 200
    assert (
        file_response.json()["content_path"]
        == "/admin/api/files-batches/files/file-gemini-1/content"
    )
    assert batch_response.status_code == 200
    assert (
        batch_response.json()["output_path"]
        == "/admin/api/files-batches/batches/batch-anthropic-1/output"
    )


def test_admin_files_batches_content_endpoints_proxy_canonical_artifacts():
    client = TestClient(make_app())

    file_response = client.get("/admin/api/files-batches/files/file-gemini-1/content")
    anthropic_output_response = client.get(
        "/admin/api/files-batches/files/file-anthropic-output-1/content"
    )
    batch_output_response = client.get(
        "/admin/api/files-batches/batches/batch-gemini-1/output"
    )

    assert file_response.status_code == 200
    assert file_response.content == b"gemini upload"
    assert anthropic_output_response.status_code == 200
    assert b'"type": "succeeded"' in anthropic_output_response.content
    assert batch_output_response.status_code == 200
    assert b'"response"' in batch_output_response.content


def test_admin_files_batches_create_openai_batch_returns_normalized_record():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "openai",
            "endpoint": "/v1/chat/completions",
            "input_file_id": "file-openai-1",
            "metadata": {"label": "openai-admin"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "openai"
    assert body["endpoint"] == "/v1/chat/completions"
    assert body["input_file_id"] == "file-openai-1"
    assert (
        body["output_path"] == f"/admin/api/files-batches/batches/{body['id']}/output"
    )


def test_admin_files_batches_create_anthropic_file_returns_normalized_record():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/files",
        data={"api_format": "anthropic", "purpose": "batch"},
        files={
            "file": (
                "anthropic-input.jsonl",
                b'{"custom_id":"anthropic-1"}\n',
                "application/json",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "anthropic"
    assert body["content_kind"] == "jsonl"
    assert body["delete_path"] == f"/v1/files/{body['id']}"


def test_admin_files_batches_create_gemini_file_returns_normalized_record():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/files",
        data={
            "api_format": "gemini",
            "purpose": "user_data",
            "display_name": "Gemini Diagram",
        },
        files={"file": ("diagram.png", b"png-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "gemini"
    assert body["filename"] == "Gemini Diagram"
    assert body["delete_path"] == f"/v1beta/files/{body['id']}"
    assert body["raw"]["metadata"]["mime_type"] == "image/png"


def test_admin_files_batches_create_anthropic_batch_from_staged_file():
    app = make_app()
    app.state.gigachat_client.files["file-anthropic-input-1"] = {
        "content": (
            b'{"custom_id":"anthropic-1","params":{"model":"claude-test","max_tokens":64,"messages":[{"role":"user","content":"hello anthropic"}]}}\n'
        ),
        "object": FakeUploadedFile(
            id="file-anthropic-input-1",
            object="file",
            bytes=132,
            created_at=114,
            filename="anthropic-input.jsonl",
            purpose="general",
        ),
    }
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "anthropic",
            "input_file_id": "file-anthropic-input-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "anthropic"
    assert body["input_file_id"] == "file-anthropic-input-1"
    assert body["output_kind"] == "results"


def test_admin_files_batches_create_gemini_batch_from_staged_file():
    app = make_app()
    app.state.gigachat_client.files["file-gemini-input-1"] = {
        "content": (
            b'{"request":{"contents":[{"role":"user","parts":[{"text":"hello gemini"}]}],"model":"models/gemini-test"},"metadata":{"requestLabel":"row-1"}}\n'
        ),
        "object": FakeUploadedFile(
            id="file-gemini-input-1",
            object="file",
            bytes=143,
            created_at=115,
            filename="gemini-input.jsonl",
            purpose="general",
        ),
    }
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "gemini",
            "input_file_id": "file-gemini-input-1",
            "display_name": "Gemini Admin Batch",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "gemini"
    assert body["display_name"] == "Gemini Admin Batch"
    assert body["model"] == "gemini-test"
