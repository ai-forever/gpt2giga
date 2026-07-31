import json

import gigachat

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.model_concurrency import ModelConcurrencyTimeoutError
from gpt2giga.logger import rquid_context
from gpt2giga.providers.gigachat.model_resolution import UpstreamModelRequiredError


async def test_exceptions_handler_renders_openai_model_concurrency_timeout() -> None:
    @exceptions_handler
    async def boom():
        raise ModelConcurrencyTimeoutError("GigaChat-Max", 5)

    response = await boom()

    assert response.status_code == 429
    assert json.loads(response.body) == {
        "error": {
            "message": "Concurrency limit reached for the requested model",
            "type": "rate_limit_error",
            "param": "model",
            "code": "model_concurrency_limit",
        }
    }


async def test_exceptions_handler_renders_anthropic_model_concurrency_timeout() -> None:
    token = rquid_context.set("rq-model-limit")

    @exceptions_handler
    async def boom():
        raise ModelConcurrencyTimeoutError(
            "GigaChat-Pro",
            1,
            provider="anthropic",
        )

    try:
        response = await boom()
    finally:
        rquid_context.reset(token)

    assert response.status_code == 429
    assert json.loads(response.body) == {
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": "Concurrency limit reached for the requested model",
            "code": "model_concurrency_limit",
        },
        "request_id": "rq-model-limit",
    }


async def test_exceptions_handler_renders_domain_model_required_error() -> None:
    @exceptions_handler
    async def boom():
        raise UpstreamModelRequiredError()

    response = await boom()

    assert response.status_code == 400
    assert json.loads(response.body) == {
        "error": {
            "message": UpstreamModelRequiredError.message,
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_required",
        }
    }


async def test_exceptions_handler_maps_sdk_model_not_specified_error() -> None:
    @exceptions_handler
    async def boom():
        raise gigachat.exceptions.ModelNotSpecifiedError()

    response = await boom()

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "model_required"
    assert "GIGACHAT_MODEL" in json.loads(response.body)["error"]["message"]
