from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.middleware.observability import ObservabilityMiddleware
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.app.dependencies import get_runtime_providers
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.providers.gigachat import ResponseProcessor
from gpt2giga.api.openai import router


class FakeGigachat:
    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda *args, **kwargs: {
                    "choices": [{"delta": {"content": "hi"}}],
                    "usage": None,
                }
            )
            yield SimpleNamespace(
                model_dump=lambda *args, **kwargs: {
                    "model": "gpt-x",
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )

        return gen()

    def astream_v2(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda *args, **kwargs: {
                    "model": "gpt-x",
                    "created_at": 123,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "hi-v2"}],
                        }
                    ],
                    "usage": {
                        "input_tokens": 1,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )

        return gen()


class FakeRequestTransformer:
    @staticmethod
    def _payload(data):
        return data if isinstance(data, dict) else data.to_backend_payload()

    async def prepare_chat_completion(self, data):
        payload = self._payload(data)
        # имитируем наличие tools для ветки is_tool_call
        return {"model": payload.get("model", "giga"), "tools": payload.get("tools")}

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        payload = self._payload(data)
        return {
            "model": payload.get("model", "giga"),
            "messages": payload.get("messages", []),
            "tools": payload.get("tools"),
        }

    async def prepare_response(self, data):
        payload = self._payload(data)
        return {"model": payload.get("model", "giga"), "tools": payload.get("tools")}


def make_app(*, observability: bool = False):
    app = FastAPI()
    app.include_router(router)
    providers = get_runtime_providers(app.state)
    providers.gigachat_client = FakeGigachat()
    providers.response_processor = ResponseProcessor()
    providers.request_transformer = FakeRequestTransformer()
    app.state.config = (
        ProxyConfig.model_validate({"proxy": {"enable_telemetry": False}})
        if observability
        else ProxyConfig()
    )
    if observability:
        ensure_runtime_dependencies(app.state, config=app.state.config)
        app.add_middleware(ObservabilityMiddleware)
    return app


def test_chat_completions_stream_records_audit_metadata():
    app = make_app(observability=True)
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert resp.status_code == 200
    assert "data: [DONE]" in resp.text

    recent_requests = app.state.stores.recent_requests.recent()
    assert len(recent_requests) == 1
    event = recent_requests[0]
    assert event["endpoint"] == "/chat/completions"
    assert event["model"] == "gpt-x"
    assert event["token_usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }
    assert event["stream_duration_ms"] is not None
    assert event["stream_duration_ms"] >= 0
