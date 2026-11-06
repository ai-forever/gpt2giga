"""Immutable response snapshots and Conversations through the official SDK."""

import json

import httpx2
import pytest
from openai import AsyncOpenAI, NotFoundError

from gpt2giga.storage.resources import ResourceStore
from test_sdk_alpha_boundaries import sdk_app


def chat_response(text="answer"):
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "created": 100,
        "model": "test-model",
        "object": "chat.completion",
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }


async def test_sdk_snapshot_restart_branch_and_delete(tmp_path):
    seen = []

    def handle(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert "storage" not in payload
        return httpx2.Response(200, json=chat_response(f"answer-{len(seen)}"))

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        old_store = app.state.resource_store
        app.state.resource_store = await ResourceStore.open(tmp_path)
        sdk = AsyncOpenAI(
            api_key="test", base_url="http://gateway.test/v1", http_client=http
        )
        first = await sdk.responses.create(
            model="test-model", input="first", store=True
        )
        assert first.id.startswith("resp_g2g_")
        assert first.store is True
        await app.state.resource_store.aclose()
        app.state.resource_store = await ResourceStore.open(tmp_path)
        retrieved = await sdk.responses.retrieve(first.id)
        assert retrieved.model_dump() == first.model_dump()
        inputs = await sdk.responses.input_items.list(first.id)
        assert inputs.data[0].content[0].text == "first"
        second = await sdk.responses.create(
            model="test-model", input="second", previous_response_id=first.id
        )
        branch = await sdk.responses.create(
            model="test-model", input="branch", previous_response_id=first.id
        )
        assert len({first.id, second.id, branch.id}) == 3
        assert second.previous_response_id == first.id
        assert branch.previous_response_id == first.id
        assert [m["content"] for m in seen[1]["messages"]] == [
            "first",
            "answer-1",
            "second",
        ]
        assert [m["content"] for m in seen[2]["messages"]] == [
            "first",
            "answer-1",
            "branch",
        ]
        await sdk.responses.delete(first.id)
        with pytest.raises(NotFoundError):
            await sdk.responses.retrieve(first.id)
        assert (await sdk.responses.retrieve(second.id)).id == second.id
        ephemeral = await sdk.responses.create(
            model="test-model", input="ephemeral", store=False
        )
        with pytest.raises(NotFoundError):
            await sdk.responses.retrieve(ephemeral.id)
        await app.state.resource_store.aclose()
        app.state.resource_store = old_store


async def test_sdk_conversation_items_and_responses_after_restart(tmp_path):
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=chat_response())

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        old_store = app.state.resource_store
        app.state.resource_store = await ResourceStore.open(tmp_path)
        sdk = AsyncOpenAI(
            api_key="test", base_url="http://gateway.test/v1", http_client=http
        )
        conversation = await sdk.conversations.create(
            items=[{"type": "message", "role": "user", "content": "seed"}],
            metadata={"topic": "test"},
        )
        first = await sdk.responses.create(
            model="test-model", input="first", conversation=conversation.id
        )
        assert first.conversation.id == conversation.id
        await app.state.resource_store.aclose()
        app.state.resource_store = await ResourceStore.open(tmp_path)
        await sdk.responses.create(
            model="test-model", input="second", conversation=conversation.id
        )
        assert [m["content"] for m in seen[1]["messages"]] == [
            "seed\nfirst",
            "answer",
            "second",
        ]
        items = await sdk.conversations.items.list(conversation.id)
        assert len(items.data) == 5
        item = await sdk.conversations.items.retrieve(
            items.data[0].id, conversation_id=conversation.id
        )
        assert item.id == items.data[0].id
        await sdk.conversations.items.delete(item.id, conversation_id=conversation.id)
        assert len((await sdk.conversations.items.list(conversation.id)).data) == 4
        updated = await sdk.conversations.update(
            conversation.id, metadata={"topic": "changed"}
        )
        assert updated.metadata == {"topic": "changed"}
        await sdk.conversations.delete(conversation.id)
        with pytest.raises(NotFoundError):
            await sdk.conversations.retrieve(conversation.id)
        await app.state.resource_store.aclose()
        app.state.resource_store = old_store


@pytest.mark.parametrize("mode", ["native", "gateway"])
async def test_unknown_gateway_id_never_becomes_native_thread(mode):
    def handle(request):
        pytest.fail("Unknown snapshot cannot dispatch")

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = mode
        response = await http.post(
            "/v2/responses",
            json={
                "model": "test-model",
                "input": "hello",
                "previous_response_id": "resp_g2g_unknown",
            },
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "extra",
    [
        {
            "input": [
                {"role": "user", "content": [{"type": "input_file", "file_id": "x"}]}
            ]
        },
        {"background": True},
        {"tools": [{"type": "web_search"}]},
        {"tools": {"type": "function"}},
        {"tools": [42]},
        {"store": "false"},
        {"previous_response_id": {"id": "wrong"}},
        {"input": [{"role": [], "content": "wrong"}]},
        {"input": [{"role": "user", "content": [{"type": [], "text": "wrong"}]}]},
    ],
)
async def test_snapshot_unsupported_inputs_rejected_before_dispatch(extra):
    def handle(request):
        pytest.fail("Unsupported input cannot dispatch")

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            "/v1/responses", json={"model": "test-model", "input": "hello", **extra}
        )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "items",
    [
        [{"id": [], "role": "user", "content": "x"}],
        [
            {"id": "same", "role": "user", "content": "x"},
            {"id": "same", "role": "user", "content": "y"},
        ],
    ],
)
async def test_conversation_invalid_and_duplicate_item_ids_rejected(items):
    async with sdk_app(lambda _: pytest.fail("No upstream call")) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        created = await http.post("/v1/conversations", json={"items": items})
        assert created.status_code == 400
        conversation = await http.post("/v1/conversations", json={})
        appended = await http.post(
            f"/v1/conversations/{conversation.json()['id']}/items",
            json={"items": items},
        )
        assert appended.status_code == 400


async def test_gateway_snapshots_reject_external_execution_before_dispatch(monkeypatch):
    import importlib
    from gpt2giga.app.responses_mode import (
        ResponsesExecutionMode,
        ResponsesExecutionSelection,
    )

    module = importlib.import_module("gpt2giga.routers.openai.responses")
    calls = []

    def select(state, *, requested_model):
        calls.append(requested_model)
        return ResponsesExecutionSelection(
            mode=ResponsesExecutionMode.NORMALIZED_BRIDGE, reason="external"
        )

    monkeypatch.setattr(module, "select_responses_execution", select)
    async with sdk_app(lambda _: pytest.fail("No external dispatch")) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            "/v1/responses", json={"model": "external", "input": "hello"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "unsupported_provider"
        assert calls == ["external"]
        from starlette.requests import Request
        from gpt2giga.app_state import get_resource_owner

        request = Request({"type": "http", "app": app, "headers": []})
        assert (
            await app.state.resource_store.list(get_resource_owner(request), "response")
            == []
        )


async def test_snapshot_selected_profile_namespace_retrieve_delete(monkeypatch):
    import importlib
    from types import SimpleNamespace
    from gpt2giga.app.responses_mode import (
        ResponsesExecutionMode,
        ResponsesExecutionSelection,
    )
    from gpt2giga.providers.profiles import ProviderKind

    module = importlib.import_module("gpt2giga.routers.openai.responses")
    monkeypatch.setattr(
        module,
        "select_responses_execution",
        lambda *args, **kwargs: ResponsesExecutionSelection(
            mode=ResponsesExecutionMode.NATIVE_GIGACHAT,
            reason="native",
            route=SimpleNamespace(profile_id="selected-profile"),
        ),
    )
    async with sdk_app(lambda _: httpx2.Response(200, json=chat_response())) as (
        http,
        app,
    ):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        app.state.provider_registry = SimpleNamespace(
            default_profile_id="default-profile",
            resolve=lambda _: SimpleNamespace(
                profile_id="selected-profile",
                provider_kind=ProviderKind.GIGACHAT,
                public_alias="test-model",
                upstream_model="test-model",
                config_revision="fixture",
                capability_profile="fixture",
                execution_context=lambda: {},
            ),
            config=SimpleNamespace(
                profiles=[
                    SimpleNamespace(
                        profile_id="selected-profile",
                        provider_kind=ProviderKind.GIGACHAT,
                    ),
                    SimpleNamespace(
                        profile_id="other-profile", provider_kind=ProviderKind.GIGACHAT
                    ),
                ]
            ),
        )
        response = await http.post(
            "/v1/responses", json={"model": "test-model", "input": "hello"}
        )
        assert response.status_code == 200, response.text
        snapshot_id = response.json()["id"]
        assert (await http.get(f"/v1/responses/{snapshot_id}")).status_code == 200
        assert (await http.delete(f"/v1/responses/{snapshot_id}")).status_code == 200
        assert (await http.get(f"/v1/responses/{snapshot_id}")).status_code == 404


async def test_snapshot_stream_storage_failure_emits_safe_terminal_error(monkeypatch):
    from gpt2giga.storage.resources import ResourceStoreError

    async def fail_commit(*args, **kwargs):
        raise ResourceStoreError("private stored prompt and SQLite path")

    monkeypatch.setattr(ResourceStore, "commit_response", fail_commit)

    def handle(request):
        chunks = [
            {"choices": [{"index": 0, "delta": {"content": "answer"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        for chunk in chunks:
            chunk.update(
                created=100, model="test-model", object="chat.completion.chunk"
            )
        wire = (
            "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        )
        return httpx2.Response(
            200, text=wire, headers={"content-type": "text/event-stream"}
        )

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            "/v1/responses",
            json={"model": "test-model", "input": "hello", "stream": True},
        )
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == "response_storage_error"
        assert not any(event["type"] == "response.completed" for event in events)
        assert "private stored prompt" not in response.text
        assert (
            await http.get(f"/v1/responses/{events[-1]['response_id']}")
        ).status_code == 404


@pytest.mark.parametrize("failure", [False, True])
async def test_stream_snapshot_published_only_after_terminal_success(failure):
    def handle(request):
        first = {
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "answer"}}
            ],
            "created": 100,
            "model": "test-model",
            "object": "chat.completion.chunk",
        }
        last = {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "created": 100,
            "model": "test-model",
            "object": "chat.completion.chunk",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        wire = f"data: {json.dumps(first)}\n\n"
        if not failure:
            wire += f"data: {json.dumps(last)}\n\ndata: [DONE]\n\n"
        return httpx2.Response(
            200, text=wire, headers={"content-type": "text/event-stream"}
        )

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            "/v1/responses",
            json={"model": "test-model", "input": "hello", "stream": True},
        )
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        completed = [event for event in events if event["type"] == "response.completed"]
        created = next(event for event in events if event["type"] == "response.created")
        snapshot_id = created["response"]["id"]
        assert snapshot_id.startswith("resp_g2g_")
        retrieved = await http.get(f"/v1/responses/{snapshot_id}")
        if failure:
            assert completed == []
            assert retrieved.status_code == 404
        else:
            assert len(completed) == 1
            assert retrieved.status_code == 200
            assert retrieved.json()["output"] == completed[0]["response"]["output"]


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("container", [None, "extra_body", "additional_fields"])
@pytest.mark.parametrize("field", ["storage", "assistant_id", "attachments"])
async def test_snapshot_rejects_native_state_before_sdk(mode, container, field):
    extra = {
        field: {"thread_id": "native-thread"} if field == "storage" else "native-id"
    }
    if container:
        extra = {container: extra}
    async with sdk_app(
        lambda _: pytest.fail("Snapshot must reject before SDK I/O")
    ) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            f"/{mode}/responses",
            json={"model": "test-model", "input": "hello", **extra},
        )
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("mode", ["v1", "v2"])
async def test_snapshot_rejects_attachment_header_before_sdk(mode):
    async with sdk_app(
        lambda _: pytest.fail("Snapshot must reject before SDK I/O")
    ) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            f"/{mode}/responses",
            headers={"x-gpt2giga-attachment-ids": "native-file"},
            json={"model": "test-model", "input": "hello"},
        )
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("mode", ["v1", "v2"])
async def test_snapshot_function_replay_retains_context_and_opaque_state(mode):
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        if mode == "v1":
            result = chat_response()
            if len(seen) == 1:
                result["choices"][0].update(
                    finish_reason="function_call",
                    message={
                        "role": "assistant",
                        "content": "",
                        "function_call": {"name": "lookup", "arguments": {"x": 1}},
                        "functions_state_id": "opaque-state",
                    },
                )
        else:
            result = {
                "messages": [{"role": "assistant", "content": [{"text": "done"}]}],
                "finish_reason": "stop",
                "model": "test-model",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
            if len(seen) == 1:
                result.update(
                    finish_reason="function_call",
                    messages=[
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "function_call": {
                                        "id": "call-opaque",
                                        "name": "lookup",
                                        "arguments": {"x": 1},
                                    }
                                }
                            ],
                            "tools_state_id": "opaque-state",
                        }
                    ],
                )
        return httpx2.Response(200, json=result)

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        first = await http.post(
            f"/{mode}/responses",
            json={
                "model": "test-model",
                "input": "lookup one",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {"type": "object"},
                    }
                ],
            },
        )
        assert first.status_code == 200, first.text
        response = first.json()
        call = next(
            item for item in response["output"] if item["type"] == "function_call"
        )
        second = await http.post(
            f"/{mode}/responses",
            json={
                "model": "test-model",
                "previous_response_id": response["id"],
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": "found",
                    }
                ],
            },
        )
    assert second.status_code == 200, second.text
    assert second.json()["previous_response_id"] == response["id"]
    assert len(seen) == 2
    messages = seen[1]["messages"]
    assert len(messages) == 3
    if mode == "v1":
        assert messages[0]["content"] == "lookup one"
        assert messages[1]["function_call"]["arguments"] == {"x": 1}
        assert messages[2]["role"] == "function"
    else:
        assert messages[0]["content"] == [{"text": "lookup one"}]
        assert messages[1]["tools_state_id"] == "opaque-state"
        assert messages[1]["content"][0]["function_call"]["id"] == "call-opaque"
        assert messages[2]["tools_state_id"] == "opaque-state"
        assert messages[2]["content"][0]["function_result"]["id"] == "call-opaque"


async def test_gateway_mode_preserves_issued_native_continuation_with_state():
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "messages": [{"role": "assistant", "content": [{"text": "ok"}]}],
                "finish_reason": "stop",
                "model": "test-model",
                "thread_id": "native-thread",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    async with sdk_app(handle) as (http, app):
        app.state.config.proxy_settings.responses_storage_mode = "gateway"
        response = await http.post(
            "/v2/responses",
            json={
                "model": "test-model",
                "input": "continue",
                "previous_response_id": "resp_native-thread",
                "extra_body": {"storage": {"thread_id": "native-thread"}},
            },
        )
    assert response.status_code == 200, response.text
    assert not response.json()["id"].startswith("resp_g2g_")
    assert seen[0]["storage"]["thread_id"] == "native-thread"
