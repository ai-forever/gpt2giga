from unittest.mock import MagicMock

from fastapi import FastAPI

from gpt2giga.app.dependencies import (
    get_runtime_providers,
    get_runtime_services,
)
from gpt2giga.app.wiring import wire_runtime_services
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


class _FakeGigaChatClient:
    async def aclose(self) -> None:
        return None


def test_wire_runtime_services_populates_provider_helpers_and_feature_services(
    monkeypatch,
):
    app = FastAPI()
    config = ProxyConfig(proxy=ProxySettings())
    logger = MagicMock()

    def fake_create_app_gigachat_client(app: FastAPI, *, settings):
        providers = get_runtime_providers(app.state)
        providers.gigachat_client = _FakeGigaChatClient()
        return providers.gigachat_client

    monkeypatch.setattr(
        "gpt2giga.app.wiring.create_app_gigachat_client",
        fake_create_app_gigachat_client,
    )

    wire_runtime_services(app, config=config, logger=logger)

    providers = get_runtime_providers(app.state)
    services = get_runtime_services(app.state)

    assert providers.gigachat_client is not None
    assert providers.attachment_processor is not None
    assert providers.request_transformer is not None
    assert providers.response_processor is not None
    assert providers.chat_mapper is not None
    assert providers.chat_mapper.backend_mode == config.proxy_settings.chat_backend_mode
    assert providers.embeddings_mapper is not None
    assert providers.models_mapper is not None

    assert services.chat is not None
    assert services.embeddings is not None
    assert services.models is not None
    assert services.files is not None
    assert services.batches is not None
    assert services.files_batches is not None
    assert services.responses is not None
