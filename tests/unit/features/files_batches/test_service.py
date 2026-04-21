import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.files_batches.service import FilesBatchesService


class FakeRequestCounts:
    def __init__(self, *, total: int, completed: int, failed: int):
        self._payload = {
            "total": total,
            "completed": completed,
            "failed": failed,
        }

    def model_dump(self):
        return dict(self._payload)


class FakeBatch:
    def __init__(
        self,
        batch_id: str,
        *,
        status: str = "completed",
        output_file_id: str | None = None,
        created_at: int = 123,
        updated_at: int = 124,
        total: int = 1,
        completed: int = 1,
        failed: int = 0,
    ):
        self.id_ = batch_id
        self.status = status
        self.output_file_id = output_file_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.request_counts = FakeRequestCounts(
            total=total,
            completed=completed,
            failed=failed,
        )


class FakeFilesService:
    async def list_files(self, **kwargs):
        del kwargs
        return {
            "data": [
                {
                    "id": "file-openai-1",
                    "filename": "input.jsonl",
                    "purpose": "batch",
                    "bytes": 12,
                    "status": "processed",
                    "created_at": 120,
                },
                {
                    "id": "file-anthropic-output-1",
                    "filename": "anthropic-output.jsonl",
                    "purpose": "batch_output",
                    "bytes": 10,
                    "status": "processed",
                    "created_at": 121,
                },
                {
                    "id": "file-gemini-1",
                    "filename": "gemini.bin",
                    "purpose": "user_data",
                    "bytes": 8,
                    "status": "processed",
                    "created_at": 122,
                },
            ]
        }

    async def retrieve_file(self, file_id: str, **kwargs):
        del kwargs
        if file_id == "file-gemini-1":
            return {
                "id": "file-gemini-1",
                "filename": "gemini.bin",
                "purpose": "user_data",
                "bytes": 8,
                "status": "processed",
                "created_at": 122,
            }
        raise AssertionError(f"Unexpected file id: {file_id}")


class FakeBatchesService:
    def __init__(self):
        self.last_create_from_content = None
        self.last_create_from_rows = None

    async def list_batch_records(self, **kwargs):
        del kwargs
        return [
            {
                "batch": FakeBatch(
                    "batch-openai-1",
                    output_file_id="file-openai-output-1",
                    created_at=123,
                ),
                "metadata": {
                    "endpoint": "/v1/chat/completions",
                    "input_file_id": "file-openai-1",
                    "output_file_id": "file-openai-output-1",
                    "model": "gpt-test",
                },
            },
            {
                "batch": FakeBatch(
                    "batch-anthropic-1",
                    output_file_id="file-anthropic-output-1",
                    created_at=124,
                    total=2,
                    completed=1,
                    failed=1,
                ),
                "metadata": {
                    "api_format": "anthropic_messages",
                    "endpoint": "/v1/chat/completions",
                    "output_file_id": "file-anthropic-output-1",
                    "requests": [{}, {}],
                },
            },
            {
                "batch": FakeBatch(
                    "batch-gemini-1",
                    output_file_id="file-gemini-output-1",
                    created_at=125,
                ),
                "metadata": {
                    "api_format": "gemini_generate_content",
                    "display_name": "Gemini Batch",
                    "input_file_id": "file-gemini-1",
                    "output_file_id": "file-gemini-output-1",
                    "model": "gemini-test",
                    "requests": [{}],
                },
            },
        ]

    async def get_batch_record(self, batch_id: str, **kwargs):
        del kwargs
        if batch_id != "batch-gemini-1":
            return None
        return {
            "batch": FakeBatch(
                "batch-gemini-1",
                output_file_id="file-gemini-output-1",
                created_at=125,
            ),
            "metadata": {
                "api_format": "gemini_generate_content",
                "display_name": "Gemini Batch",
                "input_file_id": "file-gemini-1",
                "output_file_id": "file-gemini-output-1",
                "model": "gemini-test",
                "requests": [{}],
            },
        }

    async def create_batch_from_content(
        self,
        content: bytes,
        *,
        endpoint: str,
        completion_window: str,
        metadata: dict,
        giga_client,
        batch_store,
        file_store,
    ):
        del giga_client, batch_store, file_store
        self.last_create_from_content = {
            "content": content,
            "endpoint": endpoint,
            "completion_window": completion_window,
            "metadata": metadata,
        }
        return {
            "batch": FakeBatch(
                "batch-openai-created-1",
                output_file_id="file-openai-output-created-1",
                created_at=126,
            ),
            "metadata": {
                "endpoint": endpoint,
                **metadata,
            },
        }

    async def create_batch_from_rows(
        self,
        rows: list[dict],
        *,
        endpoint: str,
        completion_window: str,
        metadata: dict,
        giga_client,
        batch_store,
        file_store,
    ):
        del giga_client, batch_store, file_store
        self.last_create_from_rows = {
            "rows": rows,
            "endpoint": endpoint,
            "completion_window": completion_window,
            "metadata": metadata,
        }
        batch_id = {
            "anthropic_messages": "batch-anthropic-created-1",
            "gemini_generate_content": "batch-gemini-created-1",
        }.get(str(metadata.get("api_format")), "batch-created-1")
        return {
            "batch": FakeBatch(
                batch_id,
                output_file_id=f"file-output-{batch_id}",
                created_at=127,
            ),
            "metadata": {
                "endpoint": endpoint,
                **metadata,
            },
        }


class FakeFilesContentClient:
    def __init__(self):
        self.files = {
            "file-openai-1": (
                b'{"custom_id":"req-1","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-test","messages":[{"role":"user","content":"hello"}]}}\n'
            ),
            "file-anthropic-1": (
                b'{"custom_id":"anthropic-1","params":{"model":"claude-test","max_tokens":64,"messages":[{"role":"user","content":"hello anthropic"}]}}\n'
            ),
            "file-gemini-1": (
                b'{"request":{"contents":[{"role":"user","parts":[{"text":"hello gemini"}]}],"model":"models/gemini-test"},"metadata":{"requestLabel":"row-1"}}\n'
            ),
        }

    async def aget_file_content(self, file_id: str):
        return SimpleNamespace(
            content=base64.b64encode(self.files[file_id]).decode("utf-8")
        )


@pytest.mark.asyncio
async def test_files_batches_service_lists_mixed_inventory_and_counts():
    service = FilesBatchesService()
    file_store = {
        "file-anthropic-output-1": {"batch_id": "batch-anthropic-1"},
        "file-gemini-1": {
            "display_name": "Gemini Upload",
            "mime_type": "text/plain",
            "source": "UPLOADED",
        },
    }
    batch_store = {
        "batch-anthropic-1": {
            "api_format": "anthropic_messages",
            "output_file_id": "file-anthropic-output-1",
        },
        "batch-gemini-1": {
            "api_format": "gemini_generate_content",
            "output_file_id": "file-gemini-output-1",
        },
    }

    inventory = await service.list_inventory(
        giga_client=SimpleNamespace(),
        files_service=FakeFilesService(),
        batches_service=FakeBatchesService(),
        file_store=file_store,
        batch_store=batch_store,
    )

    assert {record.api_format for record in inventory.files} == {
        NormalizedArtifactFormat.OPENAI,
        NormalizedArtifactFormat.ANTHROPIC,
        NormalizedArtifactFormat.GEMINI,
    }
    assert {record.api_format for record in inventory.batches} == {
        NormalizedArtifactFormat.OPENAI,
        NormalizedArtifactFormat.ANTHROPIC,
        NormalizedArtifactFormat.GEMINI,
    }
    assert inventory.counts.files == 3
    assert inventory.counts.batches == 3
    assert inventory.counts.output_ready == 3
    assert inventory.counts.needs_attention == 1


@pytest.mark.asyncio
async def test_files_batches_service_filters_by_api_format():
    service = FilesBatchesService()

    inventory = await service.list_inventory(
        giga_client=SimpleNamespace(),
        files_service=FakeFilesService(),
        batches_service=FakeBatchesService(),
        api_format="gemini",
        file_store={
            "file-gemini-1": {
                "display_name": "Gemini Upload",
                "mime_type": "text/plain",
                "source": "UPLOADED",
            }
        },
        batch_store={
            "batch-gemini-1": {
                "api_format": "gemini_generate_content",
                "output_file_id": "file-gemini-output-1",
            }
        },
    )

    assert [record.id for record in inventory.files] == ["file-gemini-1"]
    assert [record.id for record in inventory.batches] == ["batch-gemini-1"]


@pytest.mark.asyncio
async def test_files_batches_service_retrieves_provider_specific_records():
    service = FilesBatchesService()
    file_store = {
        "file-gemini-1": {
            "display_name": "Gemini Upload",
            "mime_type": "text/plain",
            "source": "UPLOADED",
        }
    }

    file_record = await service.retrieve_file(
        "file-gemini-1",
        giga_client=SimpleNamespace(),
        files_service=FakeFilesService(),
        file_store=file_store,
        batch_store={},
    )
    batch_record = await service.retrieve_batch(
        "batch-gemini-1",
        giga_client=SimpleNamespace(),
        batches_service=FakeBatchesService(),
        batch_store={},
        file_store=file_store,
    )

    assert file_record.api_format is NormalizedArtifactFormat.GEMINI
    assert batch_record is not None
    assert batch_record.api_format is NormalizedArtifactFormat.GEMINI


@pytest.mark.asyncio
async def test_files_batches_service_creates_openai_batch_from_staged_file():
    service = FilesBatchesService()
    batches_service = FakeBatchesService()

    record = await service.create_batch(
        api_format="openai",
        endpoint="/v1/responses",
        input_file_id="file-openai-1",
        metadata={"label": "openai"},
        giga_client=FakeFilesContentClient(),
        batches_service=batches_service,
        logger=None,
        batch_store={},
        file_store={},
    )

    assert record.api_format is NormalizedArtifactFormat.OPENAI
    assert record.endpoint == "/v1/responses"
    assert record.input_file_id == "file-openai-1"
    assert batches_service.last_create_from_content is not None
    assert (
        batches_service.last_create_from_content["content"]
        == FakeFilesContentClient().files["file-openai-1"]
    )


@pytest.mark.asyncio
async def test_files_batches_service_creates_anthropic_batch_from_staged_file():
    service = FilesBatchesService()
    batches_service = FakeBatchesService()

    record = await service.create_batch(
        api_format="anthropic",
        input_file_id="file-anthropic-1",
        metadata={"label": "anthropic"},
        giga_client=FakeFilesContentClient(),
        batches_service=batches_service,
        logger=None,
        batch_store={},
        file_store={},
    )

    assert record.api_format is NormalizedArtifactFormat.ANTHROPIC
    assert record.input_file_id == "file-anthropic-1"
    assert batches_service.last_create_from_rows is not None
    assert (
        batches_service.last_create_from_rows["metadata"]["api_format"]
        == "anthropic_messages"
    )
    assert (
        batches_service.last_create_from_rows["rows"][0]["body"]["messages"][0][
            "content"
        ]
        == "hello anthropic"
    )


@pytest.mark.asyncio
async def test_files_batches_service_creates_gemini_batch_from_staged_file():
    service = FilesBatchesService()
    batches_service = FakeBatchesService()

    record = await service.create_batch(
        api_format="gemini",
        input_file_id="file-gemini-1",
        display_name="Gemini Import",
        giga_client=FakeFilesContentClient(),
        batches_service=batches_service,
        logger=None,
        batch_store={},
        file_store={},
    )

    assert record.api_format is NormalizedArtifactFormat.GEMINI
    assert record.model == "gemini-test"
    assert record.display_name == "Gemini Import"
    assert batches_service.last_create_from_rows is not None
    assert (
        batches_service.last_create_from_rows["metadata"]["api_format"]
        == "gemini_generate_content"
    )
    assert (
        batches_service.last_create_from_rows["rows"][0]["body"]["messages"][0][
            "content"
        ]
        == "hello gemini"
    )


@pytest.mark.asyncio
async def test_files_batches_service_requires_model_for_gemini_rows_without_model():
    service = FilesBatchesService()

    with pytest.raises(HTTPException) as exc_info:
        await service.create_batch(
            api_format="gemini",
            requests=[
                {
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": "hello gemini"}],
                            }
                        ]
                    }
                }
            ],
            giga_client=FakeFilesContentClient(),
            batches_service=FakeBatchesService(),
            logger=None,
            batch_store={},
            file_store={},
        )

    assert "`model` is required for Gemini batches" in str(exc_info.value)
