from types import SimpleNamespace

import pytest

from gpt2giga.app.dependencies import (
    RuntimeProviders,
    RuntimeServices,
    get_request_transformer_from_state,
    get_response_processor_from_state,
    get_runtime_providers,
    get_runtime_services,
)


class _FakeTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return data

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        return data

    async def prepare_response(self, data, giga_client=None):
        return data

    async def prepare_response_v2(
        self,
        data,
        giga_client=None,
        response_store=None,
    ):
        return data


class _FakeResponseProcessor:
    def process_response(
        self,
        giga_resp,
        gpt_model,
        response_id,
        request_data=None,
    ):
        return {"id": response_id}

    def process_response_v2(
        self,
        giga_resp,
        gpt_model,
        response_id,
        request_data=None,
    ):
        return {"id": response_id}

    def process_response_api(
        self,
        data,
        giga_resp,
        gpt_model,
        response_id,
    ):
        return {"id": response_id}

    def process_response_api_v2(
        self,
        data,
        giga_resp,
        gpt_model,
        response_id,
        response_store=None,
    ):
        return {"id": response_id}


def test_get_runtime_services_initializes_typed_container():
    state = SimpleNamespace()

    services = get_runtime_services(state)

    assert services.chat is None
    assert state.services is services


def test_get_runtime_providers_initializes_typed_container():
    state = SimpleNamespace()

    providers = get_runtime_providers(state)

    assert providers.request_transformer is None
    assert state.providers is providers


def test_runtime_provider_accessors_prefer_typed_container_values():
    transformer = _FakeTransformer()
    processor = _FakeResponseProcessor()
    state = SimpleNamespace(
        services=RuntimeServices(),
        providers=RuntimeProviders(
            request_transformer=transformer,
            response_processor=processor,
        ),
    )

    assert get_request_transformer_from_state(state) is transformer
    assert get_response_processor_from_state(state) is processor


def test_runtime_provider_accessors_raise_when_dependencies_missing():
    state = SimpleNamespace(providers=RuntimeProviders())

    with pytest.raises(RuntimeError, match="Request transformer is not configured."):
        get_request_transformer_from_state(state)

    with pytest.raises(RuntimeError, match="Response processor is not configured."):
        get_response_processor_from_state(state)
