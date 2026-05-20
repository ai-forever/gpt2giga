"""OpenAI embeddings endpoint."""

import base64
import struct
from typing import Any

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.openai import embeddings_openapi_extra
from gpt2giga.protocol.batches import transform_embedding_body

router = APIRouter(tags=["OpenAI"])


def _apply_encoding_format(response: Any, encoding_format: Any) -> Any:
    """Pack each embedding as base64 of little-endian float32 bytes when asked.

    GigaChat always returns float arrays, while OpenAI's Python and Node
    SDKs default to ``encoding_format='base64'`` on ``embeddings.create`` and
    decode the string back to floats client-side. Without honoring the
    field, the proxy silently breaks those clients.
    """
    if encoding_format != "base64":
        return response
    if hasattr(response, "model_dump"):
        response = response.model_dump()
    elif hasattr(response, "dict"):
        response = response.dict()
    if not isinstance(response, dict):
        return response
    items = response.get("data")
    if not isinstance(items, list):
        return response
    for item in items:
        if not isinstance(item, dict):
            continue
        embedding = item.get("embedding")
        if isinstance(embedding, list) and embedding:
            packed = struct.pack(f"<{len(embedding)}f", *embedding)
            item["embedding"] = base64.b64encode(packed).decode("ascii")
    return response


@router.post("/embeddings", openapi_extra=embeddings_openapi_extra())
@exceptions_handler
async def embeddings(request: Request):
    """Create embeddings."""
    data = await read_request_json(request)
    giga_client = get_gigachat_client(request)
    transformed = await transform_embedding_body(
        data, request.app.state.config.proxy_settings.embeddings
    )
    response = await giga_client.aembeddings(
        texts=transformed["input"], model=transformed["model"]
    )
    return _apply_encoding_format(response, data.get("encoding_format"))
