import base64
import json
from types import SimpleNamespace

import pytest

from gpt2giga.features.batches.service import (
    BatchesService,
    get_batches_service_from_state,
)
from gpt2giga.core.config.settings import ProxyConfig


class FakeBatch:
    def __init__(
        self,
        batch_id: str,
        *,
        output_file_id: str | None = None,
        status: str = "completed",
        created_at: int = 123,
        updated_at: int = 124,
    ):
        self.id_ = batch_id
        self.method = "chat_completions"
        self.status = status
        self.output_file_id = output_file_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.request_counts = SimpleNamespace(
            model_dump=lambda: {"total": 1, "completed": 1, "failed": 0}
        )


class FakeBatches:
    def __init__(self, batches):
        self.batches = batches


class FakeFileContent:
    def __init__(self, content: bytes):
        self.content = base64.b64encode(content).decode("utf-8")


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {
            "model": data.get("model", "GigaChat"),
            "messages": data["messages"],
            "translated": "chat-v1",
        }

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        class Prepared:
            def model_dump(self, *args, **kwargs):
                return {
                    "model": data.get("model", "GigaChat"),
                    "messages": [{"role": "user", "content": [{"text": "hello"}]}],
                    "translated": "chat-v2",
                }

        return Prepared()

    async def prepare_response(self, data, giga_client=None):
        return {
            "model": data.get("model", "GigaChat"),
            "messages": [{"role": "user", "content": data["input"]}],
            "translated": "responses-v1",
        }

    async def prepare_response_v2(self, data, giga_client=None, response_store=None):
        class Prepared:
            def model_dump(self, *args, **kwargs):
                return {
                    "model": data.get("model", "GigaChat"),
                    "messages": [
                        {"role": "user", "content": [{"text": data["input"]}]}
                    ],
                    "translated": "responses-v2",
                }

        return Prepared()


class FakeBatchesClient:
    def __init__(self):
        self.last_batch_content = None
        self.last_batch_method = None
        self.files = {
            "input-file-1": FakeFileContent(
                b'{"custom_id":"req-1","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-x","messages":[{"role":"user","content":"hello"}]}}\n'
            )
        }
        self.batches = {
            "batch-1": FakeBatch("batch-1", output_file_id="file-output-1"),
            "batch-2": FakeBatch("batch-2", output_file_id="file-output-2"),
        }

    async def aget_file_content(self, file_id: str):
        return self.files[file_id]

    async def acreate_batch(self, file: bytes, method: str):
        self.last_batch_content = file
        self.last_batch_method = method
        batch = self.batches["batch-1"]
        return batch

    async def aget_batches(self, batch_id: str | None = None):
        if batch_id is None:
            return FakeBatches(list(self.batches.values()))
        batch = self.batches.get(batch_id)
        return FakeBatches([batch] if batch else [])


@pytest.mark.asyncio
async def test_batches_service_create_batch_uses_transformer_and_stores_metadata():
    service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
    )
    giga_client = FakeBatchesClient()
    batch_store = {}
    file_store = {}

    result = await service.create_batch(
        {
            "endpoint": "/v1/chat/completions",
            "input_file_id": "input-file-1",
        },
        giga_client=giga_client,
        batch_store=batch_store,
        file_store=file_store,
    )

    translated_line = json.loads(giga_client.last_batch_content.decode("utf-8").strip())
    assert giga_client.last_batch_method == "chat_completions"
    assert translated_line["id"] == "req-1"
    assert translated_line["request"]["translated"] == "chat"
    assert batch_store["batch-1"]["input_file_id"] == "input-file-1"
    assert file_store["file-output-1"]["purpose"] == "batch_output"
    assert result["object"] == "batch"


@pytest.mark.asyncio
async def test_batches_service_create_batch_from_rows_sets_endpoint_metadata():
    service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
    )
    giga_client = FakeBatchesClient()

    record = await service.create_batch_from_rows(
        [
            {
                "custom_id": "req-1",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "gpt-x",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            }
        ],
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"api_format": "anthropic_messages", "requests": []},
        giga_client=giga_client,
        batch_store={},
        file_store={},
    )

    assert record["metadata"]["endpoint"] == "/v1/chat/completions"
    assert record["metadata"]["api_format"] == "anthropic_messages"
    assert record["metadata"]["output_file_id"] == "file-output-1"


@pytest.mark.asyncio
async def test_batches_service_list_anthropic_batches_filters_by_metadata():
    service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
    )
    giga_client = FakeBatchesClient()
    batch_store = {
        "batch-1": {
            "api_format": "anthropic_messages",
            "requests": [],
            "completion_window": "24h",
        },
        "batch-2": {
            "completion_window": "24h",
        },
    }
    file_store = {}

    records = await service.list_anthropic_batches(
        giga_client=giga_client,
        batch_store=batch_store,
        file_store=file_store,
    )

    assert len(records) == 1
    assert records[0]["batch"].id_ == "batch-1"
    assert records[0]["metadata"]["output_file_id"] == "file-output-1"
    assert file_store["file-output-1"]["purpose"] == "batch_output"


@pytest.mark.asyncio
async def test_batches_service_uses_v1_transformer_for_responses_batches():
    service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
        gigachat_api_mode="v1",
    )
    giga_client = FakeBatchesClient()

    await service.create_batch_from_rows(
        [
            {
                "custom_id": "req-1",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-x",
                    "input": "hello",
                },
            }
        ],
        endpoint="/v1/responses",
        completion_window="24h",
        giga_client=giga_client,
        batch_store={},
        file_store={},
    )

    translated_line = json.loads(giga_client.last_batch_content.decode("utf-8").strip())
    assert translated_line["request"]["translated"] == "responses-v1"


@pytest.mark.asyncio
async def test_batches_service_uses_v2_transformer_for_responses_batches():
    service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
        gigachat_api_mode="v2",
    )
    giga_client = FakeBatchesClient()

    await service.create_batch_from_rows(
        [
            {
                "custom_id": "req-1",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-x",
                    "input": "hello",
                },
            }
        ],
        endpoint="/v1/responses",
        completion_window="24h",
        giga_client=giga_client,
        batch_store={},
        file_store={},
    )

    translated_line = json.loads(giga_client.last_batch_content.decode("utf-8").strip())
    assert translated_line["request"]["translated"] == "responses-v2"
    assert translated_line["request"]["messages"][0]["content"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_batches_service_uses_v2_transformer_for_chat_batches():
    service = BatchesService(
        FakeRequestTransformer(),
        embeddings_model="EmbeddingsGigaR",
        gigachat_api_mode="v2",
    )
    giga_client = FakeBatchesClient()

    await service.create_batch_from_rows(
        [
            {
                "custom_id": "req-1",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "gpt-x",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            }
        ],
        endpoint="/v1/chat/completions",
        completion_window="24h",
        giga_client=giga_client,
        batch_store={},
        file_store={},
    )

    translated_line = json.loads(giga_client.last_batch_content.decode("utf-8").strip())
    assert translated_line["request"]["translated"] == "chat-v2"


def test_get_batches_service_from_state_builds_service_from_config():
    state = SimpleNamespace(
        request_transformer=FakeRequestTransformer(),
        config=ProxyConfig(),
    )

    service = get_batches_service_from_state(state)

    assert state.batches_service is service
    assert service.embeddings_model == state.config.proxy_settings.embeddings
    assert service.gigachat_api_mode == "v1"
