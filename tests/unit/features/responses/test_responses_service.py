from types import SimpleNamespace

import pytest

from gpt2giga.app.dependencies import RuntimeProviders, RuntimeServices
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.core.contracts import NormalizedResponsesRequest
from gpt2giga.features.responses.service import (
    ResponsesService,
    get_responses_service_from_state,
)
from gpt2giga.features.responses.store import get_response_store_from_state


class FakeRequestPreparer:
    def __init__(self):
        self.prepared_with = None
        self.legacy_prepared_with = None

    async def prepare_response(self, data, giga_client=None):
        self.legacy_prepared_with = (data, giga_client)
        return {
            "model": data.model if hasattr(data, "model") else data["model"],
            "messages": [
                {
                    "role": "user",
                    "content": data.input if hasattr(data, "input") else data["input"],
                }
            ],
            "backend": "v1",
        }

    async def prepare_response_v2(self, data, giga_client=None, response_store=None):
        self.prepared_with = (data, giga_client, response_store)
        return {
            "model": data.model if hasattr(data, "model") else data["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": data.input
                            if hasattr(data, "input")
                            else data["input"]
                        }
                    ],
                }
            ],
            "backend": "v2",
        }


class FakeResponseProcessor:
    def __init__(self):
        self.processed_with = None
        self.legacy_processed_with = None

    def process_response_api(
        self,
        data,
        giga_resp,
        gpt_model,
        response_id,
    ):
        self.legacy_processed_with = (
            data,
            giga_resp,
            gpt_model,
            response_id,
        )
        return {
            "id": f"resp_{response_id}",
            "model": gpt_model,
            "payload": giga_resp.payload,
            "request_model": data["model"],
            "backend": "v1",
        }

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
        self.last_legacy_request = None

    async def achat(self, chat):
        self.last_legacy_request = chat
        return SimpleNamespace(payload=chat)

    async def achat_v2(self, chat):
        self.last_request = chat
        return SimpleNamespace(payload=chat)

    async def aget_file_content(self, file_id):
        return SimpleNamespace(content=f"b64:{file_id}")


@pytest.mark.asyncio
async def test_responses_service_create_response_uses_runtime_contracts():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    service = ResponsesService(
        request_preparer,
        response_processor,
        backend_mode="v2",
    )
    giga_client = FakeClient()
    response_store = {}
    data = NormalizedResponsesRequest(model="gpt-x", input="hi")

    result = await service.create_response(
        data,
        giga_client=giga_client,
        response_id="resp-1",
        response_store=response_store,
    )

    assert giga_client.last_request == {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        "backend": "v2",
    }
    assert request_preparer.prepared_with == (data, giga_client, response_store)
    assert response_processor.processed_with[0] == {
        "model": "gpt-x",
        "input": "hi",
        "stream": False,
    }
    assert response_processor.processed_with[2:] == ("gpt-x", "resp-1", response_store)
    assert result["id"] == "resp_resp-1"
    assert result["request_model"] == "gpt-x"


@pytest.mark.asyncio
async def test_responses_service_reuses_stored_model_for_thread_continuation():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    service = ResponsesService(
        request_preparer,
        response_processor,
        backend_mode="v2",
    )
    giga_client = FakeClient()
    response_store = {"resp_prev": {"thread_id": "thread-9", "model": "gpt-x"}}
    data = NormalizedResponsesRequest(
        model=None,
        input="hi",
        options={"previous_response_id": "resp_prev"},
    )

    result = await service.create_response(
        data,
        giga_client=giga_client,
        response_id="resp-2",
        response_store=response_store,
    )

    assert request_preparer.prepared_with == (data, giga_client, response_store)
    assert response_processor.processed_with[0]["model"] == "gpt-x"
    assert response_processor.processed_with[2:] == ("gpt-x", "resp-2", response_store)
    assert result["request_model"] == "gpt-x"


@pytest.mark.asyncio
async def test_responses_service_hydrates_image_generation_results():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()

    def process_response_api_v2(*args, **kwargs):
        return {
            "id": "resp_resp-img",
            "model": "gpt-x",
            "output": [
                {
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": "file-img-1",
                }
            ],
        }

    response_processor.process_response_api_v2 = process_response_api_v2
    service = ResponsesService(
        request_preparer,
        response_processor,
        backend_mode="v2",
    )

    result = await service.create_response(
        {"model": "gpt-x", "input": "draw"},
        giga_client=FakeClient(),
        response_id="resp-img",
        response_store={},
    )

    assert result["output"][0]["result"] == "b64:file-img-1"


@pytest.mark.asyncio
async def test_get_responses_service_from_state_builds_from_legacy_runtime_services():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    state = SimpleNamespace(
        request_transformer=request_preparer,
        response_processor=response_processor,
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}}),
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
async def test_responses_service_create_response_uses_legacy_contracts_in_v1_mode():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    service = ResponsesService(
        request_preparer,
        response_processor,
        backend_mode="v1",
    )
    giga_client = FakeClient()
    data = {"model": "gpt-x", "input": "hi"}

    result = await service.create_response(
        data,
        giga_client=giga_client,
        response_id="resp-v1",
        response_store={},
    )

    assert giga_client.last_legacy_request == {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "backend": "v1",
    }
    assert request_preparer.legacy_prepared_with == (data, giga_client)
    assert response_processor.legacy_processed_with[2:] == ("gpt-x", "resp-v1")
    assert result["backend"] == "v1"
    assert result["id"] == "resp_resp-v1"


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
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}}),
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


def test_get_responses_service_from_state_respects_v1_mode_from_config():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    state = SimpleNamespace(
        request_transformer=request_preparer,
        response_processor=response_processor,
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v1"}}),
    )

    service = get_responses_service_from_state(state)

    assert service.backend_mode == "v1"


def test_get_responses_service_from_state_prefers_responses_override_from_config():
    request_preparer = FakeRequestPreparer()
    response_processor = FakeResponseProcessor()
    state = SimpleNamespace(
        request_transformer=request_preparer,
        response_processor=response_processor,
        config=ProxyConfig.model_validate(
            {
                "proxy": {
                    "gigachat_api_mode": "v1",
                    "gigachat_responses_api_mode": "v2",
                }
            }
        ),
    )

    service = get_responses_service_from_state(state)

    assert service.backend_mode == "v2"


def test_get_response_store_from_state_creates_and_reuses_store():
    state = SimpleNamespace()

    first = get_response_store_from_state(state)
    second = get_response_store_from_state(state)

    assert first is second
    assert state.response_metadata_store is first
    assert state.stores.responses is first
