"""Gemini-compatible Batch API handlers.

These routes are intentionally not mounted by ``gpt2giga.api.gemini.routes`` yet.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from gpt2giga.app_state import get_batch_store
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.gemini import gemini_batches_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_BATCHES

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_BATCHES])


@router.post(
    "/models/{model}:batchGenerateContent",
    openapi_extra=gemini_batches_openapi_extra(create=True),
)
@exceptions_handler
async def batch_generate_content(model: str, request: Request):
    """Create Gemini-compatible batch metadata for generateContent requests."""
    data = await read_request_json(request)
    batch_payload = data.get("batch")
    if not isinstance(batch_payload, dict):
        raise _invalid_batch("`batch` is required.", param="batch")

    store = get_batch_store(request)
    batch_id = f"batches/{len(store) + 1}"
    batch = _batch_metadata(
        name=batch_id,
        model=model.removeprefix("models/"),
        display_name=batch_payload.get("displayName")
        or batch_payload.get("display_name")
        or batch_id,
        input_config=batch_payload.get("inputConfig")
        or batch_payload.get("input_config")
        or {},
        output_config=batch_payload.get("outputConfig")
        or batch_payload.get("output_config")
        or {},
        state="JOB_STATE_PENDING",
    )
    store[batch_id] = batch
    return _operation(batch)


@router.get("/batches", openapi_extra=gemini_batches_openapi_extra(create=False))
@exceptions_handler
async def list_batches(request: Request):
    """List Gemini-compatible batch metadata."""
    return {"batches": list(get_batch_store(request).values()), "nextPageToken": ""}


@router.get(
    "/batches/{batch_id:path}",
    openapi_extra=gemini_batches_openapi_extra(create=False),
)
@exceptions_handler
async def get_batch(batch_id: str, request: Request):
    """Return Gemini-compatible batch metadata."""
    name = _batch_name(batch_id)
    batch = get_batch_store(request).get(name)
    if batch is None:
        raise _not_found(name)
    return batch


@router.post("/batches/{batch_id:path}:cancel")
@exceptions_handler
async def cancel_batch(batch_id: str, request: Request):
    """Cancel Gemini-compatible batch metadata."""
    name = _batch_name(batch_id)
    store = get_batch_store(request)
    batch = store.get(name)
    if batch is None:
        raise _not_found(name)
    batch = {**batch, "state": "JOB_STATE_CANCELLED", "updateTime": _rfc3339_now()}
    store[name] = batch
    return _operation(batch, done=True)


def _batch_metadata(
    *,
    name: str,
    model: str,
    display_name: Any,
    input_config: Any,
    output_config: Any,
    state: str,
) -> dict[str, Any]:
    now = _rfc3339_now()
    return {
        "name": name,
        "model": f"models/{model}",
        "displayName": str(display_name),
        "inputConfig": input_config if isinstance(input_config, dict) else {},
        "outputConfig": output_config if isinstance(output_config, dict) else {},
        "state": state,
        "createTime": now,
        "updateTime": now,
        "batchStats": {
            "requestCount": "0",
            "successfulRequestCount": "0",
            "failedRequestCount": "0",
        },
    }


def _operation(batch: dict[str, Any], *, done: bool = False) -> dict[str, Any]:
    return {
        "name": f"operations/{batch['name']}",
        "metadata": {"batch": batch},
        "done": done,
        "response": {"batch": batch} if done else None,
    }


def _batch_name(value: str) -> str:
    return value if value.startswith("batches/") else f"batches/{value}"


def _invalid_batch(message: str, *, param: str) -> HTTPException:
    return HTTPException(
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


def _not_found(name: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "message": f"Batch `{name}` not found.",
                "type": "not_found_error",
                "param": "name",
                "code": None,
            }
        },
    )


def _rfc3339_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
