"""Tests for OpenAI ``encoding_format`` handling on /v1/embeddings."""

import base64
import json
import struct

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import OpenAI

from gpt2giga.api.openai import router as openai_router
from gpt2giga.app.dependencies import get_runtime_providers
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.features.batches.transforms import transform_batch_output_file


class FakeClient:
    """Stand-in GigaChat client that always returns float arrays."""

    async def aembeddings(self, texts, model):
        return {
            "x_headers": {"x-request-id": "secret-upstream-header"},
            "data": [
                {
                    "embedding": [0.0, 0.5, -0.5, 1.0],
                    "usage": {"prompt_tokens": 4},
                    "index": 0,
                    "object": "embedding",
                }
            ],
            "model": model,
            "object": "list",
        }


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(openai_router)
    get_runtime_providers(app.state).gigachat_client = FakeClient()
    app.state.config = ProxyConfig()
    return app


def test_embeddings_default_encoding_returns_floats():
    """Without ``encoding_format`` the response keeps float arrays."""
    client = TestClient(_make_app())
    resp = client.post("/embeddings", json={"input": "hello"})
    assert resp.status_code == 200
    embedding = resp.json()["data"][0]["embedding"]
    assert isinstance(embedding, list)
    assert embedding == [0.0, 0.5, -0.5, 1.0]


def test_embeddings_response_uses_openai_envelope():
    """GigaChat-specific fields are converted to the OpenAI response shape."""
    client = TestClient(_make_app())
    resp = client.post("/embeddings", json={"input": "hello"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["object"] == "list"
    assert body["model"] == "EmbeddingsGigaR"
    assert body["usage"] == {"prompt_tokens": 4, "total_tokens": 4}
    assert "x_headers" not in body
    assert "object_" not in body
    assert body["data"][0]["object"] == "embedding"
    assert "usage" not in body["data"][0]


def test_embeddings_explicit_float_returns_floats():
    """Explicit ``encoding_format='float'`` keeps float arrays."""
    client = TestClient(_make_app())
    resp = client.post(
        "/embeddings",
        json={"input": "hello", "encoding_format": "float"},
    )
    assert resp.status_code == 200
    embedding = resp.json()["data"][0]["embedding"]
    assert isinstance(embedding, list)
    assert embedding == [0.0, 0.5, -0.5, 1.0]


def test_embeddings_base64_returns_base64_string():
    """``encoding_format='base64'`` packs floats as little-endian float32 bytes
    and base64-encodes them, matching the OpenAI API contract.

    The OpenAI Python and Node SDKs default to ``encoding_format='base64'``
    on ``embeddings.create`` and decode the string back to floats client-side.
    Without honoring the field, callers silently receive corrupt data.
    """
    client = TestClient(_make_app())
    resp = client.post(
        "/embeddings",
        json={"input": "hello", "encoding_format": "base64"},
    )
    assert resp.status_code == 200
    embedding = resp.json()["data"][0]["embedding"]
    assert isinstance(embedding, str)
    assert "object_" not in resp.json()
    assert resp.json()["data"][0]["object"] == "embedding"
    raw = base64.b64decode(embedding)
    assert len(raw) == 4 * 4  # 4 floats × 4 bytes (float32)
    decoded = list(struct.unpack(f"<{len(raw) // 4}f", raw))
    assert decoded == [0.0, 0.5, -0.5, 1.0]


def test_openai_python_sdk_default_encoding_roundtrips_base64():
    """The OpenAI Python SDK sends base64 by default and decodes it client-side."""
    test_client = TestClient(_make_app())
    openai_client = OpenAI(
        api_key="test",
        base_url=str(test_client.base_url),
        http_client=test_client,
    )

    response = openai_client.embeddings.create(
        model="EmbeddingsGigaR",
        input="hello",
    )

    assert response.object == "list"
    assert response.data[0].object == "embedding"
    assert response.data[0].embedding == [0.0, 0.5, -0.5, 1.0]
    assert response.usage.prompt_tokens == 4
    assert response.usage.total_tokens == 4


@pytest.mark.asyncio
async def test_embedding_batch_output_honors_base64_encoding_format():
    """Batch embeddings output mirrors direct endpoint base64 encoding."""
    input_line = {
        "custom_id": "embed-1",
        "method": "POST",
        "url": "/v1/embeddings",
        "body": {
            "input": "hello",
            "model": "EmbeddingsGigaR",
            "encoding_format": "base64",
        },
    }
    output_line = {
        "id": "embed-1",
        "response": {
            "status_code": 200,
            "body": {
                "data": [
                    {
                        "embedding": [0.0, 0.5, -0.5, 1.0],
                        "usage": {"prompt_tokens": 4},
                        "index": 0,
                        "object": "embedding",
                    }
                ],
                "model": "EmbeddingsGigaR",
                "object": "list",
            },
        },
    }

    result = await transform_batch_output_file(
        base64.b64encode((json.dumps(output_line) + "\n").encode("utf-8")).decode(
            "ascii"
        ),
        batch_metadata={"endpoint": "/v1/embeddings"},
        input_content_b64=base64.b64encode(
            (json.dumps(input_line) + "\n").encode("utf-8")
        ).decode("ascii"),
        response_processor=object(),
    )

    transformed_line = json.loads(result.decode("utf-8").strip())
    body = transformed_line["response"]["body"]
    embedding = body["data"][0]["embedding"]
    assert isinstance(embedding, str)
    assert body["object"] == "list"
    assert body["usage"] == {"prompt_tokens": 4, "total_tokens": 4}
    assert body["data"][0]["object"] == "embedding"
    assert "usage" not in body["data"][0]
    raw = base64.b64decode(embedding)
    assert len(raw) == 4 * 4
    assert list(struct.unpack(f"<{len(raw) // 4}f", raw)) == [0.0, 0.5, -0.5, 1.0]
