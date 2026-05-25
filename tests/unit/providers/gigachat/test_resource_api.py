from types import SimpleNamespace

import pytest

from gpt2giga.providers.gigachat import resource_api


class FakeChatResource:
    def __init__(self):
        self.created_with = None
        self.streamed_with = None

    async def create(self, chat):
        self.created_with = chat
        return {"created": chat}

    def stream(self, chat):
        self.streamed_with = chat

        async def chunks():
            yield {"chunk": chat}

        return chunks()


class FakeFilesResource:
    def __init__(self):
        self.calls = []

    async def upload(self, file, purpose="general"):
        self.calls.append(("upload", file, purpose))
        return SimpleNamespace(id_="file-1")

    async def retrieve_content(self, file_id):
        self.calls.append(("retrieve_content", file_id))
        return SimpleNamespace(content="encoded")

    async def list(self):
        self.calls.append(("list",))
        return SimpleNamespace(data=[])

    async def retrieve(self, file):
        self.calls.append(("retrieve", file))
        return SimpleNamespace(id_=file)

    async def delete(self, file):
        self.calls.append(("delete", file))
        return SimpleNamespace(id_=file, deleted=True)


class FakeBatchesResource:
    def __init__(self):
        self.calls = []

    async def create(self, file, method):
        self.calls.append(("create", file, method))
        return SimpleNamespace(id_="batch-1")

    async def retrieve(self, batch_id):
        self.calls.append(("retrieve", batch_id))
        return SimpleNamespace(batches=[])

    async def list(self):
        self.calls.append(("list",))
        return SimpleNamespace(batches=[])


class FakeModelsResource:
    def __init__(self):
        self.calls = []

    async def retrieve(self, model):
        self.calls.append(("retrieve", model))
        return SimpleNamespace(id=model)

    async def list(self):
        self.calls.append(("list",))
        return SimpleNamespace(data=[])


class FakeEmbeddingsResource:
    def __init__(self):
        self.calls = []

    async def create(self, texts, model):
        self.calls.append(("create", list(texts), model))
        return SimpleNamespace(data=[])


class FakeResourceClient:
    def __init__(self):
        self.achat = FakeChatResource()
        self.a_files = FakeFilesResource()
        self.a_batches = FakeBatchesResource()
        self.a_models = FakeModelsResource()
        self.a_embeddings = FakeEmbeddingsResource()


@pytest.mark.asyncio
async def test_resource_api_helpers_prefer_resource_namespaces():
    client = FakeResourceClient()

    assert await resource_api.create_primary_chat(client, {"message": "hi"}) == {
        "created": {"message": "hi"}
    }
    assert [
        chunk async for chunk in resource_api.stream_primary_chat(client, "hi")
    ] == [{"chunk": "hi"}]
    await resource_api.upload_file(client, ("input.jsonl", b"{}", "application/json"))
    await resource_api.list_files(client)
    await resource_api.retrieve_file(client, file="file-1")
    await resource_api.delete_file(client, file="file-1")
    await resource_api.retrieve_file_content(client, file_id="file-1")
    await resource_api.create_batch(client, b"{}", method="chat_completions")
    await resource_api.list_batches(client)
    await resource_api.retrieve_batch(client, batch_id="batch-1")
    await resource_api.list_models(client)
    await resource_api.retrieve_model(client, model="GigaChat")
    await resource_api.create_embeddings(
        client,
        texts=["hello"],
        model="EmbeddingsGigaR",
    )

    assert client.achat.created_with == {"message": "hi"}
    assert client.achat.streamed_with == "hi"
    assert client.a_files.calls == [
        ("upload", ("input.jsonl", b"{}", "application/json"), "general"),
        ("list",),
        ("retrieve", "file-1"),
        ("delete", "file-1"),
        ("retrieve_content", "file-1"),
    ]
    assert client.a_batches.calls == [
        ("create", b"{}", "chat_completions"),
        ("list",),
        ("retrieve", "batch-1"),
    ]
    assert client.a_models.calls == [("list",), ("retrieve", "GigaChat")]
    assert client.a_embeddings.calls == [("create", ["hello"], "EmbeddingsGigaR")]
