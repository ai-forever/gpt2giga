"""Mounted vendor SDK batch flows over the real alpha SDK HTTP boundary."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import openai
import pytest
from gigachat import GigaChat
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.storage.resources import ResourceStore


class NativeBatches:
    def __init__(self):
        self.calls = []
        self.rows = []
        self.status = "completed"
        self.outputs = None
        self.submit_timeout = False

    def __call__(self, request):
        self.calls.append(request)
        if request.method == "POST" and request.url.path == "/v1/batches":
            if self.submit_timeout:
                raise httpx2.ReadTimeout("private input", request=request)
            self.rows = [json.loads(line) for line in request.content.splitlines()]
            assert request.url.params["method"] in {"chat_completions", "embedder"}
            return httpx2.Response(200, json=self.batch("created"))
        if request.url.path == "/v1/batches":
            assert request.url.params["batch_id"] == "native-job"
            return httpx2.Response(200, json={"batches": [self.batch(self.status)]})
        if request.url.path == "/v1/files/native-output/content":
            outputs = self.outputs
            if outputs is None:
                outputs = [
                    {"id": row["id"], "result": self.result()}
                    for row in reversed(self.rows)
                ]
            return httpx2.Response(
                200,
                content=("\n".join(json.dumps(row) for row in outputs) + "\n").encode(),
            )
        raise AssertionError(str(request.url))

    @staticmethod
    def result():
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "done"},
                    "finish_reason": "stop",
                    "index": 0,
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": "test-model",
        }

    @staticmethod
    def batch(status):
        return {
            "id": "native-job",
            "method": "chat_completions",
            "request_counts": {"total": 2},
            "status": status,
            "created_at": 10,
            "updated_at": 11,
            "output_file_id": "native-output" if status == "completed" else None,
        }


@asynccontextmanager
async def app_client(tmp_path, native, *, pass_token=False):
    config = ProxyConfig(
        proxy=ProxySettings(resource_store_path=str(tmp_path), pass_token=pass_token),
        gigachat={"model": "test-model", "max_retries": 2},
        _env_file=None,
    )
    app = create_app(config)
    app.state.logger = logger
    app.state.resource_store = await ResourceStore.open(tmp_path)
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(native), trust_env=False
    ) as wire:
        sdk = GigaChat(
            base_url="https://gigachat.test/v1",
            access_token="synthetic-token",
            credentials="",
            user="",
            password="",
            scope="",
            max_retries=2,
            async_http_client=wire,
            trust_env=False,
        )
        app.state.gigachat_client = sdk
        app.state.request_transformer = RequestTransformer(config, logger=logger)
        app.state.response_processor = ResponseProcessor(logger=logger)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway.test"
        ) as client:
            yield app, client
        await sdk.aclose()
    await app.state.resource_store.aclose()


def openai_rows():
    return [
        {
            "custom_id": key,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "test-model",
                "messages": [{"role": "user", "content": key}],
            },
        }
        for key in ["one", "two"]
    ]


async def upload(client, rows):
    content = "\n".join(json.dumps(row) for row in rows).encode()
    response = await client.post(
        "/v1/files",
        files={"file": ("input.jsonl", content, "application/jsonl")},
        data={"purpose": "batch"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_openai_sdk_create_restart_poll_output_error_and_no_repeat(tmp_path):
    native = NativeBatches()
    async with app_client(tmp_path, native) as (_, client):
        sdk = openai.AsyncOpenAI(
            base_url="http://gateway.test/v1", api_key="0", http_client=client
        )
        file = await sdk.files.create(
            file=(
                "input.jsonl",
                "\n".join(json.dumps(row) for row in openai_rows()).encode(),
            ),
            purpose="batch",
        )
        created = await sdk.batches.create(
            input_file_id=file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        assert created.status == "validating"
        assert created.id.startswith("batch_g2g_")
    native.outputs = [
        {"id": "two", "error": {"type": "invalid_request_error", "message": "bad row"}},
        {"id": "one", "result": native.result()},
    ]
    async with app_client(tmp_path, native) as (_, client):
        sdk = openai.AsyncOpenAI(
            base_url="http://gateway.test/v1", api_key="0", http_client=client
        )
        polled = await sdk.batches.retrieve(created.id)
        assert polled.status == "completed"
        assert polled.request_counts.completed == 1
        assert polled.request_counts.failed == 1
        success = json.loads((await sdk.files.content(polled.output_file_id)).content)
        failure = json.loads((await sdk.files.content(polled.error_file_id)).content)
        assert success["custom_id"] == "one"
        assert success["response"]["body"]["choices"][0]["message"]["content"] == "done"
        assert failure["custom_id"] == "two"
        calls = len(native.calls)
        assert (
            await sdk.batches.retrieve(created.id)
        ).output_file_id == polled.output_file_id
        assert (await sdk.batches.list()).data[0].id == created.id
        assert len(native.calls) == calls
        cancel = await client.post(f"/v1/batches/{created.id}/cancel")
        assert cancel.status_code == 501
        assert "error" in cancel.json() and "detail" not in cancel.json()
    assert sum(r.method == "POST" for r in native.calls) == 1


async def test_anthropic_sdk_results_mixed_and_protocol_scoped_listing(tmp_path):
    native = NativeBatches()
    async with app_client(tmp_path, native) as (_, client):
        sdk = anthropic.AsyncAnthropic(
            base_url="http://gateway.test", api_key="0", http_client=client
        )
        batch = await sdk.messages.batches.create(
            requests=[
                {
                    "custom_id": key,
                    "params": {
                        "model": "test-model",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": key}],
                    },
                }
                for key in ["one", "two"]
            ]
        )
        native.outputs = [
            {"id": "two", "error": {"type": "invalid_request_error", "message": "bad"}},
            {"id": "one", "result": native.result()},
        ]
        polled = await sdk.messages.batches.retrieve(batch.id)
        assert polled.processing_status == "ended"
        assert polled.request_counts.succeeded == 1
        assert polled.request_counts.errored == 1
        assert polled.results_url.endswith(f"/v1/messages/batches/{batch.id}/results")
        results = [item async for item in await sdk.messages.batches.results(batch.id)]
        assert [item.custom_id for item in results] == ["one", "two"]
        assert results[0].result.message.content[0].text == "done"
        assert results[1].result.type == "errored"
        assert (await client.get("/v1/batches")).json()["data"] == []
        assert (await client.get(f"/v1/batches/{batch.id}")).status_code == 404
        assert (await client.get("/v1/messages/batches")).json()["data"][0][
            "id"
        ] == batch.id


async def test_deadline_first_poll_after_restart_never_fetches_late_success(
    tmp_path, monkeypatch
):
    native = NativeBatches()
    clock = [1000.0]
    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.batches.time",
        SimpleNamespace(time=lambda: clock[0]),
    )
    async with app_client(tmp_path, native) as (_, client):
        data = {
            "requests": [
                {
                    "custom_id": key,
                    "params": {
                        "model": "test-model",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": key}],
                    },
                }
                for key in ["one", "two"]
            ]
        }
        response = await client.post("/v1/messages/batches", json=data)
        assert response.status_code == 200, response.text
        batch_id = response.json()["id"]
    clock[0] += 86401
    async with app_client(tmp_path, native) as (_, client):
        polled = (await client.get(f"/v1/messages/batches/{batch_id}")).json()
        assert polled["processing_status"] == "ended"
        assert polled["request_counts"] == {
            "canceled": 0,
            "succeeded": 0,
            "errored": 0,
            "processing": 0,
            "expired": 2,
        }
        result = await client.get(f"/v1/messages/batches/{batch_id}/results")
        assert all(
            json.loads(line)["result"]["type"] == "expired"
            for line in result.content.splitlines()
        )
        assert len(native.calls) == 1


async def test_ambiguous_submit_timeout_is_not_replayed(tmp_path):
    native = NativeBatches()
    native.submit_timeout = True
    async with app_client(tmp_path, native) as (app, client):
        file_id = await upload(client, openai_rows())
        response = await client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        assert response.status_code == 504
        assert "private input" not in response.text
        assert len(native.calls) == 1
        assert not await app.state.resource_store.list("any", "batch")


@pytest.mark.parametrize(
    "change",
    ["duplicate", "no_id", "stream", "stateful", "tools", "mixed", "bad_jsonl"],
)
async def test_invalid_batch_has_no_submission(tmp_path, change):
    native = NativeBatches()
    rows = openai_rows()
    if change == "duplicate":
        rows[1]["custom_id"] = "one"
    elif change == "no_id":
        rows[0].pop("custom_id")
    elif change == "stream":
        rows[0]["body"]["stream"] = True
    elif change == "stateful":
        rows[0]["body"]["previous_response_id"] = "resp-old"
    elif change == "tools":
        rows[0]["body"]["tools"] = [{"type": "web_search"}]
    elif change == "mixed":
        rows[1]["body"]["model"] = "other-model"
    elif change == "bad_jsonl":
        rows = ["not-an-object"]
    async with app_client(tmp_path, native) as (_, client):
        file_id = await upload(client, rows)
        response = await client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        assert response.status_code == 400, response.text
    assert native.calls == []


@pytest.mark.parametrize(
    "problem", ["unknown_status", "duplicate", "missing", "wrong_id"]
)
async def test_invalid_upstream_results_are_502(tmp_path, problem):
    native = NativeBatches()
    async with app_client(tmp_path, native) as (_, client):
        file_id = await upload(client, openai_rows())
        created = await client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        assert created.status_code == 200, created.text
        if problem == "unknown_status":
            native.status = "unknown"
        else:
            ids = {
                "duplicate": ["one", "one"],
                "missing": ["one"],
                "wrong_id": ["one", "wrong"],
            }[problem]
            native.outputs = [{"id": key, "result": native.result()} for key in ids]
        response = await client.get(f"/v1/batches/{created.json()['id']}")
        assert response.status_code == 502, response.text


async def test_partial_confirmed_result_survives_deadline(tmp_path, monkeypatch):
    native = NativeBatches()
    native.status = "in_progress"
    original_batch = native.batch
    native.batch = lambda status: {
        **original_batch(status),
        "output_file_id": "native-output" if status == "in_progress" else None,
    }
    native.outputs = [{"id": "one", "result": native.result()}]
    clock = [1000.0]
    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.batches.time",
        SimpleNamespace(time=lambda: clock[0]),
    )
    async with app_client(tmp_path, native) as (_, client):
        file_id = await upload(client, openai_rows())
        created = await client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        batch_id = created.json()["id"]
        polled = await client.get(f"/v1/batches/{batch_id}")
        assert polled.json()["request_counts"] == {
            "total": 2,
            "completed": 1,
            "failed": 0,
        }
        clock[0] += 86401
        expired = (await client.get(f"/v1/batches/{batch_id}")).json()
        assert expired["status"] == "expired"
        assert expired["request_counts"] == {"total": 2, "completed": 1, "failed": 1}
        success = await client.get(f"/v1/files/{expired['output_file_id']}/content")
        assert json.loads(success.content)["custom_id"] == "one"
        error = await client.get(f"/v1/files/{expired['error_file_id']}/content")
        assert json.loads(error.content)["custom_id"] == "two"


@pytest.mark.parametrize("kind", ["embeddings", "responses", "functions"])
async def test_batch_supported_families_transform_outputs(tmp_path, kind):
    native = NativeBatches()
    if kind == "embeddings":
        endpoint = "/v1/embeddings"
        body = {"model": "test-model", "input": ["first", "second"]}
        result = {
            "data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]
        }
    elif kind == "responses":
        endpoint = "/v1/responses"
        body = {"model": "test-model", "input": "hi", "store": False}
        result = native.result()
    else:
        endpoint = "/v1/chat/completions"
        body = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "call a function"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "weather",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        }
        result = {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "function_call": {"name": "weather", "arguments": {}},
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    async with app_client(tmp_path, native) as (_, client):
        file_id = await upload(
            client,
            [{"custom_id": "one", "method": "POST", "url": endpoint, "body": body}],
        )
        response = await client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": endpoint,
                "completion_window": "24h",
            },
        )
        assert response.status_code == 200, response.text
        native.outputs = [{"id": "one", "result": result}]
        batch = await client.get(f"/v1/batches/{response.json()['id']}")
        assert batch.status_code == 200, batch.text
        output = await client.get(f"/v1/files/{batch.json()['output_file_id']}/content")
        projected = json.loads(output.content)["response"]["body"]
        if kind == "embeddings":
            assert [row["embedding"] for row in projected["data"]] == [[1.0], [2.0]]
        elif kind == "responses":
            assert projected["object"] == "response"
            assert projected["output"][0]["content"][0]["text"] == "done"
        else:
            assert native.rows[0]["request"]["functions"][0]["name"] == "weather"
            assert (
                projected["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "weather"
            )


async def test_batch_ownership_hides_guessed_ids_and_outputs(tmp_path):
    native = NativeBatches()
    async with app_client(tmp_path, native) as (app, client):
        app.state.config.proxy_settings.resource_trusted_identity = "owner-one"
        file_id = await upload(client, openai_rows())
        created = await client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        batch_id = created.json()["id"]
        polled = (await client.get(f"/v1/batches/{batch_id}")).json()
        app.state.config.proxy_settings.resource_trusted_identity = "owner-two"
        before = len(native.calls)
        assert (await client.get(f"/v1/batches/{batch_id}")).status_code == 404
        assert (
            await client.get(f"/v1/files/{polled['output_file_id']}/content")
        ).status_code == 404
        assert (await client.get("/v1/batches")).json()["data"] == []
        assert len(native.calls) == before
