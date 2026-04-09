from types import SimpleNamespace

import pytest

from gpt2giga.app.dependencies import RuntimeProviders, RuntimeServices
from gpt2giga.features.responses.service import (
    ResponsesService,
    get_responses_service_from_state,
)
from gpt2giga.features.responses.store import get_response_store_from_state


class FakeRequestPreparer:
    def __init__(self):
        self.prepared_with = None

    async def prepare_response_v2(self, data, giga_client=None, response_store=None):
        self.prepared_with = (data, giga_client, response_store)
        return {
            "model": data["model"],
            "messages": [{"role": "user", "content": [{"text": data["input"]}]}],
        }


class FakeResponseProcessor:
    def __init__(self):
        self.processed_with = None

    def process_response_api_v2(
        self,
        data,
        giga_resp,
        gpt_model,
        response_id,
        response_store=None,
    ):
        self.processed_with = (
            data,
            giga_resp,
            gpt_model,
            response_id,
            response_store,
        )
        return {
            "id": f"resp_{response_id}",
            "model": gpt_model,
            "payload": giga_resp.payload,
            "request_model": data["model"],
        }


class FakeClient:
    def __init__(self):
        self.last_request = None

    async def achat_v2(self, chat):
        self.last_request = chat
        return SimpleNamespace(payload=chat)


@pytest.mark.asyncio
async def test_responses_service_create_response_uses_runtime_contracts():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    service = ResponsesService(request_preparer, response_processor)
    giga_client = FakeClient()
    response_store = {}
    data = {"model": "gpt-x", "input": "hi"}

    result = await service.create_response(
        data,
        giga_client=giga_client,
        response_id="resp-1",
        response_store=response_store,
    )

    assert giga_client.last_request == {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
    }
    assert request_preparer.prepared_with == (data, giga_client, response_store)
    assert response_processor.processed_with[2:] == ("gpt-x", "resp-1", response_store)
    assert result["id"] == "resp_resp-1"
    assert result["request_model"] == "gpt-x"


@pytest.mark.asyncio
async def test_get_responses_service_from_state_builds_from_legacy_runtime_services():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    state = SimpleNamespace(
        request_transformer=request_preparer,
        response_processor=response_processor,
    )
    giga_client = FakeClient()
    response_store = {}
    data = {"model": "gpt-x", "input": "hi"}

    service = get_responses_service_from_state(state)
    result = await service.create_response(
        data,
        giga_client=giga_client,
        response_id="resp-legacy",
        response_store=response_store,
    )

    assert state.responses_service is service
    assert request_preparer.prepared_with == (data, giga_client, response_store)
    assert result["id"] == "resp_resp-legacy"
    assert result["payload"]["model"] == "gpt-x"


@pytest.mark.asyncio
async def test_get_responses_service_from_state_builds_from_typed_runtime_dependencies():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    state = SimpleNamespace(
        services=RuntimeServices(),
        providers=RuntimeProviders(
            request_transformer=request_preparer,
            response_processor=response_processor,
        ),
    )
    giga_client = FakeClient()
    response_store = {}
    data = {"model": "gpt-x", "input": "hi"}

    service = get_responses_service_from_state(state)
    result = await service.create_response(
        data,
        giga_client=giga_client,
        response_id="resp-typed",
        response_store=response_store,
    )

    assert state.services.responses is service
    assert request_preparer.prepared_with == (data, giga_client, response_store)
    assert result["id"] == "resp_resp-typed"


def test_get_response_store_from_state_creates_and_reuses_store():
    state = SimpleNamespace()

    first = get_response_store_from_state(state)
    second = get_response_store_from_state(state)

    assert first is second
    assert state.response_metadata_store is first
    assert state.stores.responses is first
