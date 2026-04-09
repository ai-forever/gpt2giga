from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.api.openai import router as openai_router
from gpt2giga.api.system import logs_api_router


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
    async def prepare_chat_completion(self, data, giga_client=None):
        return {
            "model": data.get("model", "GigaChat"),
            "messages": data.get("messages", []),
        }


def make_streaming_app():
    app = FastAPI()
    app.include_router(openai_router)
    app.state.gigachat_client = FakeStreamingGigaChat()
    app.state.response_processor = ResponseProcessor()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    return app


def make_upload_app():
    app = FastAPI()
    app.include_router(openai_router)
    app.state.gigachat_client = FakeUploadGigaChat()
    app.state.config = ProxyConfig()
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
        "gpt2giga.api_server.GigaChat",
        lambda **kwargs: giga_client,
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert app.state.gigachat_client is giga_client
        assert hasattr(app.state, "config")

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
    app.include_router(logs_api_router)
    app.state.config = ProxyConfig()
    app.state.config.proxy_settings.log_filename = str(tmp_path / "missing.log")
    client = TestClient(app)

    with client.stream("GET", "/logs/stream") as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert "event: error" in lines
    assert "data: Log file not found." in lines


def test_starlette_1_multipart_upload_smoke():
    app = make_upload_app()
    giga_client = app.state.gigachat_client
    client = TestClient(app)

    response = client.post(
        "/files",
        data={"purpose": "batch"},
        files={"file": ("input.jsonl", b'{"hello":"world"}\n', "application/json")},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "file-1"
    assert giga_client.uploads[0][1] == "general"
    assert app.state.file_metadata_store["file-1"]["purpose"] == "batch"
