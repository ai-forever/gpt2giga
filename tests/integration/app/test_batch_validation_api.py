from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.api.batches_validation import router
from gpt2giga.core.config.settings import ProxyConfig


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return data


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.config = ProxyConfig()
    app.state.gigachat_client = SimpleNamespace()
    app.state.logger = logger
    app.state.request_transformer = FakeRequestTransformer()
    return app


def test_batch_validation_route_validates_openai_rows():
    client = TestClient(make_app())

    response = client.post(
        "/batches/validate",
        json={
            "api_format": "openai",
            "requests": [
                {
                    "custom_id": "dup",
                    "url": "/v1/chat/completions",
                    "body": {"messages": []},
                },
                {
                    "custom_id": "dup",
                    "url": "/v1/chat/completions",
                    "body": {"messages": "bad"},
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["api_format"] == "openai"
    assert body["detected_format"] == "openai"
    assert body["summary"]["total_rows"] == 2
    assert {issue["code"] for issue in body["issues"]} >= {
        "duplicate_identifier",
        "missing_field",
    }


def test_batch_validation_route_validates_anthropic_rows():
    client = TestClient(make_app())

    response = client.post(
        "/batches/validate",
        json={
            "api_format": "anthropic",
            "requests": [
                {
                    "custom_id": "dup",
                    "params": {
                        "model": "claude-test",
                        "messages": [{"role": "user", "content": "Hello batch"}],
                    },
                },
                {
                    "custom_id": "dup",
                    "params": {
                        "model": "claude-test",
                        "messages": "bad",
                    },
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["api_format"] == "anthropic"
    assert body["detected_format"] == "anthropic"
    assert body["summary"]["total_rows"] == 2
    assert {issue["code"] for issue in body["issues"]} >= {
        "duplicate_identifier",
        "missing_field",
    }


def test_batch_validation_route_validates_gemini_rows():
    client = TestClient(make_app())

    response = client.post(
        "/batches/validate",
        json={
            "api_format": "gemini",
            "model": "models/gemini-2.5-flash",
            "requests": [
                {
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": "hello validate gemini"}],
                            }
                        ]
                    },
                    "metadata": {"label": "row-1"},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["api_format"] == "gemini"
    assert body["detected_format"] == "gemini"
    assert body["summary"]["total_rows"] == 1
    assert body["summary"]["error_count"] == 0
    assert body["summary"]["warning_count"] == 2
    assert {issue["code"] for issue in body["issues"]} == {
        "default_model_applied",
        "metadata_ignored",
    }


def test_batch_validation_route_reports_gigachat_row_limit():
    client = TestClient(make_app())

    response = client.post(
        "/batches/validate",
        json={
            "api_format": "openai",
            "requests": [
                {
                    "custom_id": f"row-{index}",
                    "url": "/v1/chat/completions",
                    "body": {"messages": []},
                }
                for index in range(101)
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["summary"]["total_rows"] == 101
    assert body["summary"]["error_count"] == 1
    assert body["issues"][0]["severity"] == "error"
    assert body["issues"][0]["code"] == "row_limit_exceeded"
    assert "does not support more than 100 batch rows" in body["issues"][0]["message"]


def test_batch_validation_route_requires_file_or_requests():
    client = TestClient(make_app())

    response = client.post(
        "/batches/validate",
        json={"api_format": "openai"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "`input_file_id` or `requests` is required for validation."
    )


def test_batch_validation_route_openapi_examples_include_api_format():
    app = make_app()

    schema = app.openapi()
    examples = schema["components"]["schemas"]["BatchValidateRequest"]["examples"]

    assert examples[0]["api_format"] == "openai"
    assert examples[1]["api_format"] == "anthropic"
    assert examples[2]["api_format"] == "gemini"
