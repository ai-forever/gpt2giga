from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.app.factory import create_app
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.api.admin import admin_api_router
from gpt2giga.api.openai import router as openai_router
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings
from gpt2giga.providers.gigachat import ResponseProcessor


class FakeLifespanGigaChat:
    def __init__(self):
        self.closed = False

    async def aget_models(self):
        return SimpleNamespace(data=[], object_="list")

    async def aclose(self):
        self.closed = True


class FakeStreamingGigaChat:
    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda **kwargs: {
                    "choices": [{"delta": {"content": "hello from stream"}}],
                    "usage": None,
                }
            )

        return gen()


class FakeUploadGigaChat:
    def __init__(self):
        self.uploads = []

    async def aupload_file(self, file, purpose):
        self.uploads.append((file, purpose))
        return SimpleNamespace(
            id_="file-1",
            bytes_=len(file[1]),
            created_at=123,
            filename=file[0],
            purpose=purpose,
        )


class FakeRequestTransformer:
    @staticmethod
    def _payload(data):
        return data if isinstance(data, dict) else data.to_backend_payload()

    async def prepare_chat_completion(self, data, giga_client=None):
        payload = self._payload(data)
        return {
            "model": payload.get("model", "GigaChat"),
            "messages": payload.get("messages", []),
        }

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        return await self.prepare_chat_completion(data, giga_client=giga_client)


def make_streaming_app():
    app = FastAPI()
    app.include_router(openai_router)
    ensure_runtime_dependencies(
        app.state,
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
    )
    app.state.providers.gigachat_client = FakeStreamingGigaChat()
    app.state.providers.response_processor = ResponseProcessor()
    app.state.providers.request_transformer = FakeRequestTransformer()
    return app


def make_upload_app():
    app = FastAPI()
    app.include_router(openai_router)
    ensure_runtime_dependencies(app.state, config=ProxyConfig())
    app.state.providers.gigachat_client = FakeUploadGigaChat()
    return app


def test_starlette_1_cors_preflight_smoke():
    app = create_app()
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://example.com"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_starlette_1_lifespan_and_app_state_smoke(monkeypatch):
    giga_client = FakeLifespanGigaChat()
    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.client.GigaChat",
        lambda **kwargs: giga_client,
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert app.state.providers.gigachat_client is giga_client
        assert hasattr(app.state, "config")
        assert hasattr(app.state, "services")
        assert hasattr(app.state, "stores")
        assert hasattr(app.state, "providers")

    assert giga_client.closed is True


def test_starlette_1_openai_streaming_smoke():
    app = make_streaming_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    ) as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert any("hello from stream" in line for line in lines)
    assert any("[DONE]" in line for line in lines)


def test_starlette_1_logs_sse_error_smoke(tmp_path):
    app = FastAPI()
    app.include_router(admin_api_router)
    app.state.config = ProxyConfig()
    app.state.config.proxy_settings.log_filename = str(tmp_path / "missing.log")
    client = TestClient(app)

    with client.stream("GET", "/admin/api/logs/stream") as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert "event: error" in lines
    assert "data: Log file not found." in lines


def test_starlette_1_multipart_upload_smoke():
    app = make_upload_app()
    giga_client = app.state.providers.gigachat_client
    client = TestClient(app)

    response = client.post(
        "/files",
        data={"purpose": "batch"},
        files={"file": ("input.jsonl", b'{"hello":"world"}\n', "application/json")},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "file-1"
    assert giga_client.uploads[0][1] == "general"
    assert app.state.stores.files["file-1"]["purpose"] == "batch"
