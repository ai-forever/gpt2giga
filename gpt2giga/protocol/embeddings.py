"""Helpers for OpenAI-compatible embeddings payloads."""

import base64
import struct
from typing import Any


def apply_embedding_encoding_format(response: Any, encoding_format: Any) -> Any:
    """Pack embeddings as base64 float32 bytes when requested."""
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
