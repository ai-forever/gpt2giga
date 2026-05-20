"""Tests for OpenAI ``encoding_format`` handling on /v1/embeddings."""

import base64
import struct

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.models.config import ProxyConfig
from gpt2giga.routers.openai import router as openai_router


class FakeClient:
    """Stand-in GigaChat client that always returns float arrays."""

    async def aembeddings(self, texts, model):
        return {
            "data": [
                {
                    "embedding": [0.0, 0.5, -0.5, 1.0],
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
    app.state.gigachat_client = FakeClient()
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
    raw = base64.b64decode(embedding)
    assert len(raw) == 4 * 4  # 4 floats × 4 bytes (float32)
    decoded = list(struct.unpack(f"<{len(raw) // 4}f", raw))
    assert decoded == [0.0, 0.5, -0.5, 1.0]
