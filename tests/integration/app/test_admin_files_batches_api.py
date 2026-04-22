import base64
import json
import time

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
        self.file_content_requests: list[str] = []
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
        self.file_content_requests.append(file_id)
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
    batch_endpoints = {item["api_format"]: item["endpoint"] for item in body["batches"]}
    assert batch_endpoints["anthropic"] == "/v1/messages"
    assert batch_endpoints["gemini"] == "/v1beta/models/gemini-test:generateContent"
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


def test_admin_files_batches_inventory_large_dataset_stays_within_regression_budget():
    app = make_app()
    for index in range(900):
        file_id = f"file-large-output-{index}"
        batch_id = f"batch-large-{index}"
        app.state.gigachat_client.files[file_id] = {
            "content": b'{"response":{"body":{"choices":[]}}}\n',
            "object": FakeUploadedFile(
                id=file_id,
                object="file",
                bytes=34,
                created_at=2_000 + index,
                filename=f"{file_id}.jsonl",
                purpose="general",
            ),
        }
        app.state.gigachat_client.batches[batch_id] = FakeBatch(
            id=batch_id,
            method="chat_completions",
            request_counts=FakeRequestCounts(total=1, completed=1, failed=0),
            status="completed",
            output_file_id=file_id,
            created_at=3_000 + index,
            updated_at=3_001 + index,
        )
        app.state.batch_metadata_store[batch_id] = {
            "endpoint": "/v1/chat/completions",
            "input_file_id": f"file-input-{index}",
            "output_file_id": file_id,
            "model": "gpt-test",
        }

    client = TestClient(app)

    started_at = time.perf_counter()
    response = client.get("/admin/api/files-batches/inventory")
    elapsed = time.perf_counter() - started_at

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["files"] == 904
    assert body["counts"]["batches"] == 903
    assert body["counts"]["output_ready"] == 903
    assert body["files"][0]["id"] == "file-large-output-899"
    assert body["batches"][0]["id"] == "batch-large-899"
    assert elapsed < 2.5


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
    assert batch_response.json()["endpoint"] == "/v1/messages"
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


def test_admin_files_batches_file_content_supports_preview_bytes():
    app = make_app()
    app.state.gigachat_client.files["file-gemini-1"]["content"] = (
        b"line-1\nline-2\nline-3\nline-4\n"
    )
    client = TestClient(app)

    response = client.get(
        "/admin/api/files-batches/files/file-gemini-1/content",
        params={"preview_bytes": 15},
    )

    assert response.status_code == 200
    assert response.content == b"line-1\nline-2\n"
    assert response.headers["x-admin-preview-truncated"] == "true"
    assert response.headers["x-admin-preview-bytes"] == str(len(response.content))
    assert response.headers["x-admin-preview-total-bytes"] == "28"


def test_admin_files_batches_batch_output_supports_preview_bytes():
    app = make_app()
    app.state.gigachat_client.files["file-gemini-output-1"]["content"] = (
        json.dumps(
            {
                "response": {
                    "body": {
                        "candidates": [
                            {"content": {"parts": [{"text": "first result"}]}}
                        ]
                    }
                }
            }
        )
        + "\n"
        + json.dumps(
            {
                "response": {
                    "body": {
                        "candidates": [
                            {"content": {"parts": [{"text": "second result"}]}}
                        ]
                    }
                }
            }
        )
        + "\n"
    ).encode("utf-8")
    client = TestClient(app)

    response = client.get(
        "/admin/api/files-batches/batches/batch-gemini-1/output",
        params={"preview_bytes": 120},
    )

    assert response.status_code == 200
    assert response.headers["x-admin-preview-truncated"] == "true"
    assert int(response.headers["x-admin-preview-bytes"]) == len(response.content)
    assert int(response.headers["x-admin-preview-total-bytes"]) > len(response.content)
    assert response.content.endswith(b"\n")
    assert response.content.count(b"\n") == 1


def test_admin_files_batches_batch_output_accepts_enum_style_completed_status():
    app = make_app()
    app.state.gigachat_client.batches[
        "batch-gemini-1"
    ].status = "BatchState.BATCH_STATE_COMPLETED"
    client = TestClient(app)

    response = client.get("/admin/api/files-batches/batches/batch-gemini-1/output")

    assert response.status_code == 200
    assert b'"response"' in response.content


def test_admin_files_batches_batch_output_infers_anthropic_format_from_input_file():
    app = make_app()
    app.state.gigachat_client.files["file-anthropic-input-1"] = {
        "content": (
            b'{"custom_id":"anthropic-batch-1","params":{"model":"claude-test","max_tokens":64,"messages":[{"role":"user","content":"hello anthropic"}]}}\n'
        ),
        "object": FakeUploadedFile(
            id="file-anthropic-input-1",
            object="file",
            bytes=137,
            created_at=114,
            filename="anthropic-input.jsonl",
            purpose="general",
        ),
    }
    app.state.batch_metadata_store["batch-anthropic-1"] = {
        "endpoint": "/v1/chat/completions",
        "input_file_id": "file-anthropic-input-1",
        "output_file_id": "file-anthropic-output-1",
        "requests": [],
    }
    client = TestClient(app)

    response = client.get("/admin/api/files-batches/batches/batch-anthropic-1/output")

    assert response.status_code == 200
    lines = [
        json.loads(line)
        for line in response.content.decode("utf-8").splitlines()
        if line.strip()
    ]
    assert lines[0]["custom_id"] == "req-1"
    assert lines[0]["result"]["type"] == "succeeded"
    assert "message" in lines[0]["result"]


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


def test_admin_files_batches_create_openai_batch_from_inline_requests():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "openai",
            "endpoint": "/v1/chat/completions",
            "requests": [
                {
                    "custom_id": "req-inline-1",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-4.1-mini",
                        "messages": [
                            {"role": "user", "content": "hello inline openai"}
                        ],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "openai"
    assert body["endpoint"] == "/v1/chat/completions"
    assert body["input_file_id"] is None


def test_admin_files_batches_create_openai_batch_from_inline_requests_with_fallback_model():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "openai",
            "endpoint": "/v1/chat/completions",
            "model": "GigaChat-2-Max",
            "requests": [
                {
                    "custom_id": "req-inline-1",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "messages": [
                            {"role": "user", "content": "hello inline openai"}
                        ],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "openai"
    assert body["input_file_id"] is None


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
    assert body["endpoint"] == "/v1/messages"
    assert body["input_file_id"] == "file-anthropic-input-1"
    assert body["output_kind"] == "results"


def test_admin_files_batches_create_anthropic_batch_from_inline_requests():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "anthropic",
            "display_name": "Anthropic Inline Batch",
            "requests": [
                {
                    "custom_id": "anthropic-inline-1",
                    "params": {
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 64,
                        "messages": [
                            {
                                "role": "user",
                                "content": "hello inline anthropic",
                            }
                        ],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "anthropic"
    assert body["display_name"] == "Anthropic Inline Batch"
    assert body["endpoint"] == "/v1/messages"
    assert body["input_file_id"] is None
    assert body["output_kind"] == "results"


def test_admin_files_batches_create_anthropic_batch_from_inline_requests_with_fallback_model():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "anthropic",
            "model": "GigaChat-2-Max",
            "requests": [
                {
                    "custom_id": "anthropic-inline-1",
                    "params": {
                        "max_tokens": 64,
                        "messages": [
                            {
                                "role": "user",
                                "content": "hello inline anthropic",
                            }
                        ],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "anthropic"
    assert body["endpoint"] == "/v1/messages"
    assert body["input_file_id"] is None
    assert body["output_kind"] == "results"


def test_admin_files_batches_create_gemini_batch_from_staged_file():
    app = make_app()
    app.state.gigachat_client.files["file-gemini-input-1"] = {
        "content": (
            b'{"key":"row-1","request":{"contents":[{"role":"user","parts":[{"text":"hello gemini"}]}],"model":"models/gemini-test"},"metadata":{"requestLabel":"row-1"}}\n'
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
    assert body["endpoint"] == "/v1beta/models/gemini-test:generateContent"
    assert body["model"] == "gemini-test"


def test_admin_files_batches_create_gemini_batch_from_doc_style_file_with_model():
    app = make_app()
    app.state.gigachat_client.files["file-gemini-input-keyed-1"] = {
        "content": (
            b'{"key":"doc-row-1","request":{"contents":[{"role":"user","parts":[{"text":"hello keyed gemini"}]}]}}\n'
        ),
        "object": FakeUploadedFile(
            id="file-gemini-input-keyed-1",
            object="file",
            bytes=101,
            created_at=116,
            filename="gemini-keyed-input.jsonl",
            purpose="general",
        ),
    }
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "gemini",
            "input_file_id": "file-gemini-input-keyed-1",
            "model": (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-2.5-flash:batchGenerateContent"
            ),
            "display_name": "Gemini Keyed Batch",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "gemini"
    assert body["display_name"] == "Gemini Keyed Batch"
    assert body["endpoint"] == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert body["model"] == "gemini-2.5-flash"


def test_admin_files_batches_create_gemini_batch_from_inline_requests():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "gemini",
            "display_name": "Gemini Inline Batch",
            "requests": [
                {
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": "hello inline gemini"}],
                            }
                        ],
                        "model": "models/gemini-inline",
                    },
                    "metadata": {"requestLabel": "inline-row-1"},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_format"] == "gemini"
    assert body["display_name"] == "Gemini Inline Batch"
    assert body["endpoint"] == "/v1beta/models/gemini-inline:generateContent"
    assert body["model"] == "gemini-inline"
    assert body["input_file_id"] is None


def test_admin_files_batches_create_openai_batch_returns_field_error_detail():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={"api_format": "openai"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "input_file_id": "`input_file_id` or `requests` is required for OpenAI batches."
        }
    }


def test_admin_files_batches_create_rejects_invalid_staged_input_with_validation_report():
    app = make_app()
    app.state.gigachat_client.files["file-openai-invalid-create-1"] = {
        "content": (
            b'{"custom_id":"dup","url":"/v1/chat/completions","body":{"messages":[]}}\n'
            b'{"custom_id":"dup","url":"/v1/chat/completions","body":{"messages":"bad"}}\n'
        ),
        "object": FakeUploadedFile(
            id="file-openai-invalid-create-1",
            object="file",
            bytes=146,
            created_at=141,
            filename="openai-invalid-create.jsonl",
            purpose="general",
        ),
    }
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-invalid-create-1",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["message"] == (
        "Batch input validation failed. "
        "Run validation and fix blocking issues before creating the batch."
    )
    assert body["detail"]["validation_report"]["valid"] is False
    assert body["detail"]["validation_report"]["summary"]["error_count"] >= 2
    assert {
        issue["code"] for issue in body["detail"]["validation_report"]["issues"]
    } >= {
        "duplicate_identifier",
        "missing_field",
    }


def test_admin_files_batches_create_rejects_invalid_inline_input_with_validation_report():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "gemini",
            "requests": [
                {
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": "hello broken gemini"}],
                            }
                        ]
                    }
                }
            ],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["validation_report"]["valid"] is False
    assert body["detail"]["validation_report"]["api_format"] == "gemini"
    assert {
        issue["code"] for issue in body["detail"]["validation_report"]["issues"]
    } == {"missing_field"}


def test_admin_files_batches_validate_staged_file_returns_diagnostic_report():
    app = make_app()
    app.state.gigachat_client.files["file-openai-invalid-1"] = {
        "content": (
            b'{"custom_id":"dup","url":"/v1/chat/completions","body":{"messages":[]}}\n'
            b'{"custom_id":"dup","url":"/v1/chat/completions","body":{"messages":"bad"}}\n'
        ),
        "object": FakeUploadedFile(
            id="file-openai-invalid-1",
            object="file",
            bytes=146,
            created_at=140,
            filename="openai-invalid.jsonl",
            purpose="general",
        ),
    }
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-invalid-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["api_format"] == "openai"
    assert body["detected_format"] == "openai"
    assert body["summary"]["total_rows"] == 2
    assert body["summary"]["error_count"] >= 2
    assert {issue["code"] for issue in body["issues"]} >= {
        "duplicate_identifier",
        "missing_field",
    }


def test_admin_files_batches_validate_reuses_cached_staged_file_bytes():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-1",
        },
    )

    assert response.status_code == 200
    second_response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-1",
        },
    )

    assert second_response.status_code == 200
    assert app.state.gigachat_client.file_content_requests == ["file-openai-1"]


def test_admin_files_batches_create_uses_one_staged_file_read_for_validate_and_create():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-1",
        },
    )

    assert response.status_code == 200
    assert app.state.gigachat_client.file_content_requests == ["file-openai-1"]


def test_admin_files_batches_create_reuses_cached_validation_after_validate():
    app = make_app()
    client = TestClient(app)

    validate_response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-1",
        },
    )

    assert validate_response.status_code == 200
    create_response = client.post(
        "/admin/api/files-batches/batches",
        json={
            "api_format": "openai",
            "input_file_id": "file-openai-1",
        },
    )

    assert create_response.status_code == 200
    assert app.state.gigachat_client.file_content_requests == ["file-openai-1"]


def test_admin_files_batches_validate_inline_gemini_rows_returns_warnings_only():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={
            "api_format": "gemini",
            "model": "models/gemini-2.5-flash",
            "requests": [
                {
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": "hello validate gemini"}],
                            }
                        ]
                    },
                    "metadata": {"label": "row-1"},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["api_format"] == "gemini"
    assert body["detected_format"] == "gemini"
    assert body["summary"]["total_rows"] == 1
    assert body["summary"]["error_count"] == 0
    assert body["summary"]["warning_count"] == 2
    assert {issue["code"] for issue in body["issues"]} == {
        "default_model_applied",
        "metadata_ignored",
    }


def test_admin_files_batches_validate_reports_gigachat_row_limit():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={
            "api_format": "openai",
            "requests": [
                {
                    "custom_id": f"row-{index}",
                    "url": "/v1/chat/completions",
                    "body": {"messages": []},
                }
                for index in range(101)
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["summary"]["total_rows"] == 101
    assert body["summary"]["error_count"] == 1
    assert body["issues"][0]["severity"] == "error"
    assert body["issues"][0]["code"] == "row_limit_exceeded"
    assert "does not support more than 100 batch rows" in body["issues"][0]["message"]


def test_admin_files_batches_validate_requires_file_or_requests():
    client = TestClient(make_app())

    response = client.post(
        "/admin/api/files-batches/batches/validate",
        json={"api_format": "openai"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "`input_file_id`, `input_content_base64`, or `requests` is required for validation."
    )
