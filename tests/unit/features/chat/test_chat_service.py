from types import SimpleNamespace

import pytest

from gpt2giga.app.dependencies import RuntimeProviders, RuntimeServices
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.core.contracts import NormalizedChatRequest, NormalizedMessage
from gpt2giga.features.chat.service import ChatService, get_chat_service_from_state


def _get_model(data):
    return data.model if hasattr(data, "model") else data["model"]


def _get_messages(data):
    if hasattr(data, "messages"):
        return [message.to_openai_message() for message in data.messages]
    return data["messages"]


class FakeMapper:
    def __init__(self):
        self.prepared_with = None
        self.processed_with = None
        self.uses_v2_backend = False

    async def prepare_request(self, data, giga_client=None):
        self.prepared_with = (data, giga_client)
        return {"messages": _get_messages(data), "model": _get_model(data)}

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
        return SimpleNamespace(
            payload={
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "ok-v2"}],
                    }
                ],
                "finish_reason": "stop",
            }
        )


class LegacyRequestTransformer:
    def __init__(self):
        self.calls = []
        self.calls_v2 = []

    async def prepare_chat_completion(self, data, giga_client=None):
        self.calls.append((data, giga_client))
        return {"messages": _get_messages(data), "model": _get_model(data)}

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        self.calls_v2.append((data, giga_client))
        messages = _get_messages(data)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": str(messages[0]["content"])}],
                }
            ],
            "model": _get_model(data),
        }


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

    def process_response_v2(self, giga_resp, gpt_model, response_id, request_data=None):
        normalized = self.normalize_chat_v2_response(giga_resp)
        return {
            "id": response_id,
            "model": gpt_model,
            "payload": normalized,
            "request_model": request_data["model"],
        }

    def process_stream_chunk_v2(
        self, giga_resp, gpt_model, response_id, request_data=None
    ):
        return {"id": response_id, "model": gpt_model, "payload": giga_resp}

    def normalize_chat_v2_response(self, giga_resp):
        payload = giga_resp.payload
        message = (payload.get("messages") or [{}])[0]
        text_part = (message.get("content") or [{"text": ""}])[0]
        return {
            "choices": [
                {
                    "message": {
                        "role": message.get("role", "assistant"),
                        "content": text_part.get("text", ""),
                    },
                    "finish_reason": payload.get("finish_reason", "stop"),
                }
            ]
        }


class FakeMapperV2(FakeMapper):
    def __init__(self):
        super().__init__()
        self.uses_v2_backend = True


@pytest.mark.asyncio
async def test_chat_service_create_completion_uses_mapper_contract():
    mapper = FakeMapper()
    service = ChatService(mapper)
    giga_client = FakeClient()
    data = NormalizedChatRequest(
        model="gpt-x",
        messages=[NormalizedMessage(role="user", content="hi")],
    )

    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-1",
    )

    assert giga_client.last_request == {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "gpt-x",
    }
    assert mapper.prepared_with == (data, giga_client)
    assert mapper.processed_with[1:] == (
        "gpt-x",
        "resp-1",
        {
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert result["id"] == "resp-1"
    assert result["request_model"] == "gpt-x"


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
        response_id="resp-legacy",
    )

    assert state.services.chat is service
    assert state.providers.chat_mapper is service.mapper
    assert transformer.calls == [(data, giga_client)]
    assert result["id"] == "resp-legacy"
    assert result["payload"] == {"messages": data["messages"], "model": "gpt-x"}


@pytest.mark.asyncio
async def test_chat_service_create_completion_uses_v2_backend_when_mapper_requests_it():
    mapper = FakeMapperV2()
    service = ChatService(mapper)
    giga_client = FakeClient()
    data = NormalizedChatRequest(
        model="gpt-x",
        messages=[NormalizedMessage(role="user", content="hi")],
    )

    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-v2",
    )

    assert giga_client.last_request is None
    assert giga_client.last_request_v2 == {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "gpt-x",
    }
    assert result["id"] == "resp-v2"


@pytest.mark.asyncio
async def test_get_chat_service_from_state_respects_v2_mode_from_config():
    transformer = LegacyRequestTransformer()
    response_processor = LegacyResponseProcessor()
    state = SimpleNamespace(
        services=RuntimeServices(),
        providers=RuntimeProviders(
            request_transformer=transformer,
            response_processor=response_processor,
        ),
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}}),
    )
    giga_client = FakeClient()
    data = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]}

    service = get_chat_service_from_state(state)
    result = await service.create_completion(
        data,
        giga_client=giga_client,
        response_id="resp-v2-config",
    )

    assert service.backend_mode == "v2"
    assert giga_client.last_request is None
    assert giga_client.last_request_v2["model"] == "gpt-x"
    assert giga_client.last_request_v2["messages"][0]["content"][0]["text"] == "hi"
    assert transformer.calls_v2 == [(data, giga_client)]
    assert result["id"] == "resp-v2-config"


def test_get_chat_service_from_state_ignores_responses_override():
    transformer = LegacyRequestTransformer()
    response_processor = LegacyResponseProcessor()
    state = SimpleNamespace(
        services=RuntimeServices(),
        providers=RuntimeProviders(
            request_transformer=transformer,
            response_processor=response_processor,
        ),
        config=ProxyConfig.model_validate(
            {
                "proxy": {
                    "gigachat_api_mode": "v1",
                    "gigachat_responses_api_mode": "v2",
                }
            }
        ),
    )

    service = get_chat_service_from_state(state)

    assert service.backend_mode == "v1"
