"""Anthropic Message Batches backed by durable native GigaChat jobs."""

import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, Response

from gpt2giga.app_state import get_resource_store
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.files import file_content
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.anthropic import anthropic_message_batches_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_ANTHROPIC_MESSAGE_BATCHES
from gpt2giga.protocol.anthropic.params import validate_anthropic_version
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)
from gpt2giga.protocol.anthropic.response import _build_anthropic_response
from gpt2giga.providers.gigachat.batches import (
    TERMINAL,
    batch_error,
    batch_owner,
    create_batch as submit_batch,
    get_batch,
    list_batches as registered_batches,
    poll_batch,
    prepare_rows,
    result_file,
    validate_batch_body,
)

router = APIRouter(tags=[OPENAPI_TAG_ANTHROPIC_MESSAGE_BATCHES])


def _rfc3339_from_timestamp(timestamp):
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
        if timestamp is not None
        else None
    )


def _build_anthropic_batch_error(error, request_id: str) -> dict:
    """Normalize a batch error payload to Anthropic's error response schema."""
    if (
        isinstance(error, dict)
        and error.get("type") == "error"
        and isinstance(error.get("error"), dict)
    ):
        return {
            "type": "error",
            "error": {
                "type": error["error"].get("type", "api_error"),
                "message": error["error"].get("message", "Unknown batch error."),
            },
            "request_id": error.get("request_id") or request_id,
        }

    if isinstance(error, dict):
        nested_error = error.get("error")
        if isinstance(nested_error, dict):
            error_type = nested_error.get("type", error.get("type", "api_error"))
            message = nested_error.get("message") or error.get("message")
        else:
            error_type = error.get("type", "api_error")
            message = error.get("message")
        if message is None:
            message = json.dumps(error, ensure_ascii=False)
    else:
        error_type = "api_error"
        message = str(error)

    return {
        "type": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
        "request_id": request_id,
    }


def batch_object(request: Request, resource):
    m = resource.metadata
    ended = m["status"] in TERMINAL
    succeeded = sum("result" in row for row in m["results"])
    errored = sum("error" in row for row in m["results"])
    expired = sum(row.get("expired", False) for row in m["results"])
    prefix = request.url.path.split("/messages/batches", 1)[0]
    return {
        "id": resource.public_id,
        "type": "message_batch",
        "archived_at": None,
        "cancel_initiated_at": None,
        "created_at": _rfc3339_from_timestamp(m["created_at"]),
        "ended_at": _rfc3339_from_timestamp(m.get("ended_at")),
        "expires_at": _rfc3339_from_timestamp(m["deadline"]),
        "processing_status": "ended" if ended else "in_progress",
        "request_counts": {
            "canceled": 0,
            "errored": errored,
            "expired": expired,
            "processing": len(m["rows"]) - succeeded - errored - expired,
            "succeeded": succeeded,
        },
        "results_url": str(request.base_url).rstrip("/")
        + f"{prefix}/messages/batches/{resource.public_id}/results"
        if ended
        else None,
    }


@router.post(
    "/messages/batches", openapi_extra=anthropic_message_batches_openapi_extra()
)
@exceptions_handler
async def create_message_batch(request: Request):
    data = await read_request_json(request)
    if data.get("completion_window") not in {None, "24h"}:
        raise batch_error("Only completion_window=24h is supported.")
    inputs = data.get("requests")
    if not isinstance(inputs, list) or not inputs:
        raise batch_error("requests must be a non-empty array.")
    rows = []
    for row in inputs:
        if not isinstance(row, dict) or not isinstance(row.get("params"), dict):
            raise batch_error("Each request must contain params.")
        custom_id = row.get("custom_id")
        if not isinstance(custom_id, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}", custom_id
        ):
            raise batch_error(
                "custom_id must contain 1–64 letters, digits, hyphens or underscores."
            )
        params = row["params"]
        validate_anthropic_version(params, request.headers.get("anthropic-version"))
        validate_batch_body(params)
        rows.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": _build_openai_data_from_anthropic_request(
                    params, request.app.state.logger
                ),
            }
        )
    native_rows, model = await prepare_rows(request, rows, "/v1/chat/completions")
    for native, original in zip(native_rows, inputs):
        native["original"] = original["params"]
    resource = await submit_batch(
        request,
        protocol="anthropic",
        method="chat_completions",
        model=model,
        rows=native_rows,
    )
    return batch_object(request, resource)


@router.get("/messages/batches")
@exceptions_handler
async def list_message_batches(
    request: Request,
    after_id: str | None = None,
    before_id: str | None = None,
    limit: int = Query(20, ge=1, le=1000),
):
    resources = await registered_batches(request, "anthropic")
    for cursor, before in ((after_id, False), (before_id, True)):
        if cursor:
            matches = [i for i, r in enumerate(resources) if r.public_id == cursor]
            if not matches:
                raise batch_error("Invalid batch cursor.")
            resources = (
                resources[: matches[0]] if before else resources[matches[0] + 1 :]
            )
    data = [batch_object(request, r) for r in resources[:limit]]
    return {
        "data": data,
        "has_more": len(resources) > limit,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    }


@router.get("/messages/batches/{message_batch_id}")
@exceptions_handler
async def retrieve_message_batch(message_batch_id: str, request: Request):
    return batch_object(
        request, await poll_batch(request, message_batch_id, "anthropic")
    )


@router.post("/messages/batches/{message_batch_id}/cancel")
@router.delete("/messages/batches/{message_batch_id}")
@exceptions_handler
async def unsupported_message_batch_operation(message_batch_id: str, request: Request):
    await get_batch(request, message_batch_id, "anthropic")
    raise batch_error(
        "The GigaChat backend does not support batch cancellation or deletion.", 501
    )


@router.get("/messages/batches/{message_batch_id}/results")
@exceptions_handler
async def get_message_batch_results(message_batch_id: str, request: Request):
    resource = await poll_batch(request, message_batch_id, "anthropic")
    if resource.metadata["status"] not in TERMINAL:
        raise batch_error("Results are not available while processing.", 409)
    file_id = resource.metadata.get("results_file_id")
    if file_id is None:
        originals = {row["id"]: row["original"] for row in resource.metadata["rows"]}
        rows = []
        for item in resource.metadata["results"]:
            key = item["id"]
            if item.get("expired"):
                result = {"type": "expired"}
            elif "error" in item:
                result = {
                    "type": "errored",
                    "error": _build_anthropic_batch_error(item["error"], key),
                }
            else:
                result = {
                    "type": "succeeded",
                    "message": _build_anthropic_response(
                        item["result"],
                        originals[key].get("model", resource.metadata["model"]),
                        item.get("request_id", key),
                    ),
                }
            rows.append({"custom_id": key, "result": result})
        content = (
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
        ).encode()
        file_id = await result_file(request, resource, "results", content)
        await get_resource_store(request).update(
            batch_owner(request, resource),
            "batch",
            message_batch_id,
            {"results_file_id": file_id},
        )
    return Response(
        await file_content(request, file_id), media_type="application/x-jsonlines"
    )
