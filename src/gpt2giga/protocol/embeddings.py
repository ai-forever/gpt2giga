"""Helpers for OpenAI-compatible embeddings payloads."""

import base64
import copy
import functools
import struct
from typing import Any, Dict, List, Optional

import anyio
import tiktoken
from fastapi import HTTPException

from gpt2giga.common.client_params import extract_gigachat_response_metadata


def _invalid_request(message: str, *, param: Optional[str] = None) -> None:
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": param,
                "code": None,
            }
        },
    )


def validate_embedding_request(data: Dict[str, Any]) -> None:
    """Validate the OpenAI-compatible embeddings request body."""
    if "input" not in data:
        _invalid_request("`input` is required.", param="input")

    model = data.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        _invalid_request("`model` must be a non-empty string.", param="model")

    _validate_embedding_input(data["input"])


async def transform_embedding_body(
    data: Dict[str, Any], embeddings_model: str, *, pass_model: bool = False
) -> Dict[str, Any]:
    """Transform an OpenAI embeddings request into a GigaChat payload."""
    validate_embedding_request(data)
    openai_model = data.get("model")
    if isinstance(openai_model, str):
        openai_model = openai_model.strip()
    model = openai_model if pass_model and openai_model else embeddings_model
    normalized_inputs = await _normalize_embedding_inputs(
        data["input"], openai_model or model
    )
    transformed = {
        "input": normalized_inputs,
        "model": model,
    }
    return transformed


def normalize_embedding_response(
    response: Any, model: Optional[str] = None
) -> Dict[str, Any]:
    """Shape a GigaChat embeddings response like OpenAI's response envelope."""
    body = _to_dict(response)
    if not isinstance(body, dict):
        body = {}

    raw_data = body.get("data")
    if not isinstance(raw_data, list):
        raw_data = []

    data = []
    item_prompt_tokens = 0
    for index, raw_item in enumerate(raw_data):
        item = _to_dict(raw_item)
        if not isinstance(item, dict):
            item = {}

        usage = _to_dict(item.get("usage"))
        if isinstance(usage, dict):
            item_prompt_tokens += _int_or_zero(usage.get("prompt_tokens"))

        data.append(
            {
                "object": "embedding",
                "embedding": item.get("embedding", []),
                "index": _embedding_index(item.get("index"), index),
            }
        )

    top_usage = _to_dict(body.get("usage"))
    if isinstance(top_usage, dict):
        prompt_tokens = _int_or_zero(top_usage.get("prompt_tokens"))
        total_tokens = _int_or_zero(top_usage.get("total_tokens"), prompt_tokens)
    else:
        prompt_tokens = item_prompt_tokens
        total_tokens = item_prompt_tokens

    result = {
        "object": "list",
        "data": data,
        "model": _non_empty_string(body.get("model")) or _non_empty_string(model) or "",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "total_tokens": total_tokens,
        },
    }
    response_metadata = extract_gigachat_response_metadata(body.get("x_headers"))
    if response_metadata:
        result["metadata"] = response_metadata
    return result


def apply_embedding_encoding_format(response: Any, encoding_format: Any) -> Any:
    """Pack embeddings as base64 float32 bytes when requested."""
    if encoding_format != "base64":
        return response
    response = _to_dict(response)
    if not isinstance(response, dict):
        return response
    items = response.get("data")
    if not isinstance(items, list):
        return response
    for item in items:
        if not isinstance(item, dict):
            continue
        embedding = item.get("embedding")
        if isinstance(embedding, list):
            packed = struct.pack(f"<{len(embedding)}f", *embedding)
            item["embedding"] = base64.b64encode(packed).decode("ascii")
    return response


def _validate_embedding_input(inputs: Any) -> None:
    if isinstance(inputs, str):
        if inputs == "":
            _invalid_request("`input` must not contain empty strings.", param="input")
        return

    if not isinstance(inputs, list):
        _invalid_request(
            "`input` must be a string, an array of strings, an array of token ids, "
            "or an array of token id arrays.",
            param="input",
        )

    if not inputs:
        _invalid_request("`input` must be a non-empty string or array.", param="input")
    if len(inputs) > 2048:
        _invalid_request(
            "`input` arrays must contain 2048 items or fewer.", param="input"
        )

    if all(isinstance(item, str) for item in inputs):
        if any(item == "" for item in inputs):
            _invalid_request("`input` must not contain empty strings.", param="input")
        return

    if _is_token_id_list(inputs):
        return

    if all(isinstance(item, list) for item in inputs):
        for row in inputs:
            if not row:
                _invalid_request(
                    "`input` token arrays must not be empty.",
                    param="input",
                )
            if len(row) > 2048:
                _invalid_request(
                    "`input` token arrays must contain 2048 token ids or fewer.",
                    param="input",
                )
            if not _is_token_id_list(row):
                _invalid_request(
                    "`input` token arrays must contain only non-negative integers.",
                    param="input",
                )
        return

    _invalid_request(
        "`input` arrays must not mix strings, token ids, and token id arrays.",
        param="input",
    )


async def _normalize_embedding_inputs(inputs: Any, model: Optional[str]) -> List[str]:
    if isinstance(inputs, str):
        return [inputs]

    if _is_token_id_list(inputs):
        return [await _decode_token_ids(inputs, model)]

    if all(isinstance(row, str) for row in inputs):
        return list(inputs)

    return [await _decode_token_ids(row, model) for row in inputs]


async def _decode_token_ids(token_ids: List[int], model: Optional[str]) -> str:
    if not isinstance(model, str) or not model.strip():
        _invalid_request(
            "Token id inputs require `model` so the proxy can decode tokens before "
            "forwarding to GigaChat.",
            param="model",
        )

    try:
        encoder = await anyio.to_thread.run_sync(
            functools.partial(tiktoken.encoding_for_model, model)
        )
    except (AttributeError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": (
                        f"Token id inputs require a model known to tiktoken; `{model}` "
                        "cannot be decoded. Send text input instead."
                    ),
                    "type": "invalid_request_error",
                    "param": "model",
                    "code": None,
                }
            },
        ) from exc

    try:
        return encoder.decode(token_ids)
    except Exception as exc:  # pragma: no cover - depends on tiktoken internals.
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Could not decode token id input.",
                    "type": "invalid_request_error",
                    "param": "input",
                    "code": None,
                }
            },
        ) from exc


def _is_token_id_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_token_id(item) for item in value)


def _is_token_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _to_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(by_alias=True, exclude_none=True)
        except TypeError:
            return value.model_dump()
    if hasattr(value, "dict"):
        try:
            return value.dict(by_alias=True, exclude_none=True)
        except TypeError:
            return value.dict()
    return value


def _int_or_zero(value: Any, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def _embedding_index(value: Any, fallback: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


def _non_empty_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None
