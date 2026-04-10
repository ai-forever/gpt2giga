from types import SimpleNamespace

import pytest

from gpt2giga.app.dependencies import RuntimeProviders, RuntimeServices
from gpt2giga.features.chat.service import ChatService, get_chat_service_from_state


class FakeMapper:
    def __init__(self):
        self.prepared_with = None
        self.processed_with = None
        self.uses_v2_backend = False

    async def prepare_request(self, data, giga_client=None):
        self.prepared_with = (data, giga_client)
        return {"messages": data["messages"], "model": data["model"]}

    def process_response(self, giga_resp, gpt_model, response_id, request_data=None):
        self.processed_with = (giga_resp, gpt_model, response_id, request_data)
        return {
            "id": response_id,
            "model": gpt_model,
            "payload": giga_resp.payload,
            "request_model": request_data["model"],
        }


class FakeClient:
    def __init__(self):
        self.last_request = None
        self.last_request_v2 = None

    async def achat(self, chat):
        self.last_request = chat
        return SimpleNamespace(payload=chat)

    async def achat_v2(self, chat):
        self.last_request_v2 = chat
        return SimpleNamespace(payload=chat)


class LegacyRequestTransformer:
    def __init__(self):
        self.calls = []

    async def prepare_chat_completion(self, data, giga_client=None):
        self.calls.append((data, giga_client))
        return {"messages": data["messages"], "model": data["model"]}


class LegacyResponseProcessor:
    def process_response(self, giga_resp, gpt_model, response_id, request_data=None):
        return {
            "id": response_id,
            "model": gpt_model,
            "payload": giga_resp.payload,
            "request_model": request_data["model"],
        }

    def process_stream_chunk(
        self, giga_resp, gpt_model, response_id, request_data=None
    ):
        return {"id": response_id, "model": gpt_model, "payload": giga_resp}


class FakeMapperV2(FakeMapper):
    def __init__(self):
        super().__init__()
        self.uses_v2_backend = True


@pytest.mark.asyncio
async def test_chat_service_create_completion_uses_mapper_contract():
    mapper = FakeMapper()
    service = ChatService(mapper)
    giga_client = FakeClient()
    data = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]}

    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-1",
    )

    assert giga_client.last_request == {"messages": data["messages"], "model": "gpt-x"}
    assert mapper.prepared_with == (data, giga_client)
    assert mapper.processed_with[1:] == ("gpt-x", "resp-1", data)
    assert result["id"] == "resp-1"
    assert result["request_model"] == "gpt-x"


@pytest.mark.asyncio
async def test_get_chat_service_from_state_builds_from_legacy_runtime_services():
    transformer = LegacyRequestTransformer()
    response_processor = LegacyResponseProcessor()
    state = SimpleNamespace(
        request_transformer=transformer,
        response_processor=response_processor,
    )
    giga_client = FakeClient()
    data = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]}

    service = get_chat_service_from_state(state)
    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-legacy",
    )

    assert state.chat_service is service
    assert state.chat_mapper is service.mapper
    assert transformer.calls == [(data, giga_client)]
    assert result["id"] == "resp-legacy"
    assert result["payload"] == {"messages": data["messages"], "model": "gpt-x"}


@pytest.mark.asyncio
async def test_get_chat_service_from_state_builds_from_typed_runtime_dependencies():
    transformer = LegacyRequestTransformer()
    response_processor = LegacyResponseProcessor()
    state = SimpleNamespace(
        services=RuntimeServices(),
        providers=RuntimeProviders(
            request_transformer=transformer,
            response_processor=response_processor,
        ),
    )
    giga_client = FakeClient()
    data = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]}

    service = get_chat_service_from_state(state)
    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-typed",
    )

    assert state.services.chat is service
    assert state.providers.chat_mapper is service.mapper
    assert transformer.calls == [(data, giga_client)]
    assert result["id"] == "resp-typed"


@pytest.mark.asyncio
async def test_chat_service_create_completion_uses_v2_backend_when_mapper_requests_it():
    mapper = FakeMapperV2()
    service = ChatService(mapper)
    giga_client = FakeClient()
    data = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]}

    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-v2",
    )

    assert giga_client.last_request is None
    assert giga_client.last_request_v2 == {
        "messages": data["messages"],
        "model": "gpt-x",
    }
    assert result["id"] == "resp-v2"
