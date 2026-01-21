from types import SimpleNamespace

from fastapi import FastAPI

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.api_router import router


class FakeGigachat:
    async def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                dict=lambda: {"choices": [{"delta": {"content": "hi"}}], "usage": None}
            )

        return gen()


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data):
        # имитируем наличие tools для ветки is_tool_call
        return {"model": data.get("model", "giga"), "tools": data.get("tools")}

    async def prepare_response(self, data):
        return {"model": data.get("model", "giga"), "tools": data.get("tools")}


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    return app
