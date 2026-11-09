"""Real Google/GigaChat SDK batch contracts, including shuffled native rows."""

import json

import httpx2
import pytest
from google import genai
from google.genai import types

from test_sdk_alpha_boundaries import sdk_app


def batch_backend(seen, *, embedding=False):
    state = {}

    def batch(status):
        return {
            "id": "native-job",
            "method": "embedder" if embedding else "chat_completions",
            "request_counts": {"total": len(state["rows"])},
            "status": status,
            "created_at": 123,
            "updated_at": 124,
            "output_file_id": "native-output" if status == "completed" else None,
        }

    def handle(request):
        seen.append(request)
        if request.url.path == "/v1/batches":
            if request.method == "POST":
                state["rows"] = [
                    json.loads(line) for line in request.content.splitlines()
                ]
                assert request.url.params["method"] == (
                    "embedder" if embedding else "chat_completions"
                )
                assert all(
                    row["request"]["model"] == "test-model" for row in state["rows"]
                )
                return httpx2.Response(200, json=batch("created"))
            assert request.url.params["batch_id"] == "native-job"
            return httpx2.Response(200, json={"batches": [batch("completed")]})
        if request.url.path == "/v1/files/native-output/content":
            rows = []
            for index, row in enumerate(state["rows"]):
                if index == 1:
                    rows.append(
                        {"id": row["id"], "error": {"message": "one row rejected"}}
                    )
                else:
                    body = (
                        {
                            "data": [{"index": 0, "embedding": [float(index)]}],
                            "model": "test-model",
                        }
                        if embedding
                        else {
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "stop",
                                    "message": {
                                        "role": "assistant",
                                        "content": f"row {index}",
                                    },
                                }
                            ],
                            "created": 1,
                            "model": "test-model",
                            "object": "chat.completion",
                            "usage": {
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                                "total_tokens": 2,
                            },
                        }
                    )
                    rows.append(
                        {
                            "id": row["id"],
                            "response": {"status_code": 200, "body": body},
                        }
                    )
            return httpx2.Response(
                200,
                content=(
                    "\n".join(json.dumps(row) for row in reversed(rows)) + "\n"
                ).encode(),
            )
        raise AssertionError((request.method, request.url))

    return handle


@pytest.mark.parametrize("embedding", [False, True])
async def test_google_sdk_batch_create_poll_list_mixed_results(embedding):
    seen = []
    async with sdk_app(batch_backend(seen, embedding=embedding)) as (http_client, _):
        client = genai.Client(
            api_key="synthetic",
            http_options=types.HttpOptions(
                base_url="http://gateway.test",
                api_version="v1beta",
                httpx_async_client=http_client,
            ),
        )
        if embedding:
            batch = await client.aio.batches.create_embeddings(
                model="test-model",
                src={"inlined_requests": {"contents": ["first", "second", "third"]}},
                config={"display_name": "test embeddings"},
            )
        else:
            batch = await client.aio.batches.create(
                model="test-model",
                src=[
                    {"contents": "first", "metadata": {"key": "first"}},
                    {"contents": "second", "metadata": {"key": "second"}},
                    {"contents": "third", "metadata": {"key": "third"}},
                ],
                config={"display_name": "test generation"},
            )
        assert batch.name.startswith("batches/batch_g2g_")
        assert batch.state == types.JobState.JOB_STATE_PENDING
        result = await client.aio.batches.get(name=batch.name)
        assert result.state == types.JobState.JOB_STATE_SUCCEEDED
        assert result.dest is not None
        if embedding:
            rows = result.dest.inlined_embed_content_responses
            assert rows[0].response.embedding.values == [0.0]
            assert rows[2].response.embedding.values == [2.0]
        else:
            rows = result.dest.inlined_responses
            assert rows[0].response.text == "row 0"
            assert rows[2].response.text == "row 2"
            assert [row.metadata["key"] for row in rows] == ["first", "second", "third"]
        assert rows[1].error.message == "one row rejected"
        assert [job.name async for job in await client.aio.batches.list()] == [
            batch.name
        ]
        again = await client.aio.batches.get(name=batch.name)
        assert again.dest == result.dest
        cancel = await http_client.post(f"/v1beta/{batch.name}:cancel")
        assert cancel.status_code == 501
        assert cancel.json()["error"]["status"] == "UNIMPLEMENTED"
    assert len(seen) == 3


async def test_duplicate_keys_rejected_before_native_submission():
    seen = []
    async with sdk_app(batch_backend(seen)) as (client, _):
        response = await client.post(
            "/v1beta/models/test-model:batchGenerateContent",
            json={
                "batch": {
                    "inputConfig": {
                        "requests": {
                            "requests": [
                                {
                                    "key": "same",
                                    "request": {
                                        "contents": [{"parts": [{"text": "hello"}]}]
                                    },
                                }
                            ]
                            * 2
                        }
                    }
                }
            },
        )
        assert response.status_code == 400, response.text
    assert not seen


async def test_google_sdk_file_batch_survives_restart_and_downloads_jsonl(tmp_path):
    import io
    from gpt2giga.storage.resources import ResourceStore

    seen = []
    async with sdk_app(batch_backend(seen)) as (http_client, app):
        old_store = app.state.resource_store
        app.state.resource_store = await ResourceStore.open(tmp_path)
        client = genai.Client(
            api_key="synthetic",
            http_options=types.HttpOptions(
                base_url="http://gateway.test",
                api_version="v1beta",
                httpx_async_client=http_client,
            ),
        )
        content = (
            "\n".join(
                json.dumps(
                    {"key": key, "request": {"contents": [{"parts": [{"text": key}]}]}}
                )
                for key in ("first", "second")
            )
            + "\n"
        ).encode()
        file = await client.aio.files.upload(
            file=io.BytesIO(content),
            config={"display_name": "input.jsonl", "mime_type": "application/jsonl"},
        )
        assert file.name.startswith("files/file_g2g_")
        batch = await client.aio.batches.create(model="test-model", src=file.name)
        await app.state.resource_store.aclose()
        app.state.resource_store = await ResourceStore.open(tmp_path)
        result = await client.aio.batches.get(name=batch.name)
        assert result.dest.file_name.startswith("files/file_g2g_")
        output = await client.aio.files.download(file=result.dest.file_name)
        rows = [json.loads(line) for line in output.splitlines()]
        assert [row["key"] for row in rows] == ["first", "second"]
        assert [row["metadata"]["key"] for row in rows] == ["first", "second"]
        assert rows[0]["response"]["candidates"][0]["content"]["parts"] == [
            {"text": "row 0"}
        ]
        assert rows[1]["error"]["message"] == "one row rejected"
        assert (
            await client.aio.batches.get(name=batch.name)
        ).dest.file_name == result.dest.file_name
        app.state.config.proxy_settings.resource_trusted_identity = "other-owner"
        assert (await http_client.get(f"/v1beta/{batch.name}")).status_code == 404
        assert (
            await http_client.get(f"/v1beta/{result.dest.file_name}:download")
        ).status_code == 404
        await app.state.resource_store.aclose()
        app.state.resource_store = old_store
    assert len(seen) == 3


async def test_concurrent_first_polls_publish_one_gemini_output_file():
    import asyncio
    import io
    from starlette.requests import Request
    from gpt2giga.app_state import get_resource_owner

    seen = []
    async with sdk_app(batch_backend(seen)) as (http_client, app):
        sdk = genai.Client(
            api_key="synthetic",
            http_options=types.HttpOptions(
                base_url="http://gateway.test",
                api_version="v1beta",
                httpx_async_client=http_client,
            ),
        )
        content = (
            json.dumps(
                {
                    "key": "first",
                    "request": {"contents": [{"parts": [{"text": "first"}]}]},
                }
            )
            + "\n"
        ).encode()
        file = await sdk.aio.files.upload(
            file=io.BytesIO(content),
            config={"display_name": "input.jsonl", "mime_type": "application/jsonl"},
        )
        batch = await sdk.aio.batches.create(model="test-model", src=file.name)
        first, second = await asyncio.gather(
            sdk.aio.batches.get(name=batch.name), sdk.aio.batches.get(name=batch.name)
        )
        assert first.dest.file_name == second.dest.file_name
        request = Request(
            {"type": "http", "method": "GET", "path": "/", "headers": [], "app": app}
        )
        files = await app.state.resource_store.list(get_resource_owner(request), "file")
        assert len(files) == 2  # One input and one shared immutable derived output.
        outputs = [record for record in files if record.metadata.get("downloadable")]
        assert len(outputs) == 1
        assert f"files/{outputs[0].public_id}" == first.dest.file_name
