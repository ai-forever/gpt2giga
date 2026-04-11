"""Anthropic message batch endpoints and helpers."""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request, Response

from gpt2giga.api.anthropic.openapi import anthropic_message_batches_openapi_extra
from gpt2giga.api.anthropic.request_adapter import (
    build_normalized_chat_request,
)
from gpt2giga.api.anthropic.response import (
    _anthropic_http_exception,
    _build_anthropic_response,
)
from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.features.batches import get_batches_service_from_state
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.batches.transforms import extract_batch_result_body, parse_jsonl
from gpt2giga.features.files.store import get_file_store
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["Anthropic"])


def _rfc3339_from_timestamp(timestamp: Optional[int]) -> Optional[str]:
    """Convert a Unix timestamp into Anthropic's RFC 3339 datetime format."""
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _build_anthropic_batch_request_counts(batch: Any, metadata: Dict[str, Any]) -> Dict:
    """Map GigaChat request counters onto Anthropic message batch counters."""
    request_counts = getattr(batch, "request_counts", None)
    total = getattr(request_counts, "total", None)
    if total is None:
        total = len(metadata.get("requests", []))

    status = getattr(batch, "status", None)
    failed = getattr(request_counts, "failed", None) or 0
    completed = getattr(request_counts, "completed", None)

    if status == "completed":
        succeeded = completed if completed is not None else max(total - failed, 0)
        errored = failed
        processing = max(total - succeeded - errored, 0)
    else:
        succeeded = 0
        errored = 0
        processing = total

    return {
        "canceled": 0,
        "errored": errored,
        "expired": 0,
        "processing": processing,
        "succeeded": succeeded,
    }


def _build_anthropic_batch_object(batch: Any, metadata: Dict[str, Any]) -> Dict:
    """Build an Anthropic-compatible message batch object."""
    batch_id = getattr(batch, "id_", "")
    created_at = getattr(batch, "created_at", None)
    processing_status = (
        "ended" if getattr(batch, "status", None) == "completed" else "in_progress"
    )
    output_file_id = getattr(batch, "output_file_id", None)

    expires_at = None
    if created_at is not None:
        expires_at = (
            (datetime.fromtimestamp(created_at, tz=timezone.utc) + timedelta(hours=24))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    results_url = None
    if processing_status == "ended" and output_file_id:
        results_url = f"/v1/messages/batches/{batch_id}/results"

    return {
        "id": batch_id,
        "type": "message_batch",
        "archived_at": metadata.get("archived_at"),
        "cancel_initiated_at": metadata.get("cancel_initiated_at"),
        "created_at": _rfc3339_from_timestamp(created_at),
        "ended_at": (
            _rfc3339_from_timestamp(getattr(batch, "updated_at", None))
            if processing_status == "ended"
            else None
        ),
        "expires_at": expires_at,
        "processing_status": processing_status,
        "request_counts": _build_anthropic_batch_request_counts(batch, metadata),
        "results_url": results_url,
    }


def _build_anthropic_batch_error(error: Any, request_id: str) -> Dict:
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


def _paginate_anthropic_batches(
    items: List[Dict[str, Any]],
    *,
    after_id: Optional[str],
    before_id: Optional[str],
    limit: int,
) -> tuple[List[Dict[str, Any]], bool]:
    """Apply Anthropic-style cursor pagination to batch listings."""
    if after_id:
        for index, item in enumerate(items):
            if item.get("id") == after_id:
                items = items[index + 1 :]
                break

    if before_id:
        for index, item in enumerate(items):
            if item.get("id") == before_id:
                items = items[:index]
                break

    return items[:limit], len(items) > limit


def _build_anthropic_batch_results(
    output_content_b64: str,
    batch_metadata: Dict[str, Any],
) -> bytes:
    """Transform a GigaChat batch output file into Anthropic batch results JSONL."""
    output_rows = parse_jsonl(base64.b64decode(output_content_b64))
    requests_by_id = {
        row.get("custom_id"): row.get("params", {})
        for row in batch_metadata.get("requests", [])
        if isinstance(row, dict) and row.get("custom_id")
    }

    result_lines = []
    for index, row in enumerate(output_rows):
        custom_id = row.get("custom_id") or row.get("id") or f"batch-request-{index}"
        request_id = str(row.get("request_id") or row.get("id") or custom_id)
        response = row.get("response")
        status_code = 200
        if isinstance(response, dict):
            status_code = int(response.get("status_code", 200))

        raw_body = extract_batch_result_body(row)
        error = row.get("error")
        if status_code >= 400 or (
            error
            and "result" not in row
            and "response" not in row
            and "body" not in row
        ):
            anthropic_result = {
                "type": "errored",
                "error": _build_anthropic_batch_error(error or raw_body, request_id),
            }
        else:
            params = requests_by_id.get(custom_id, {})
            message_payload = raw_body
            if not isinstance(message_payload, dict):
                message_payload = {
                    "choices": [
                        {
                            "message": {"content": str(raw_body)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {},
                }

            if (
                isinstance(message_payload, dict)
                and message_payload.get("type") == "message"
            ):
                anthropic_message = message_payload
            else:
                anthropic_message = _build_anthropic_response(
                    message_payload,
                    params.get("model", "unknown"),
                    request_id,
                )

            anthropic_result = {
                "type": "succeeded",
                "message": anthropic_message,
            }

        result_lines.append(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "result": anthropic_result,
                },
                ensure_ascii=False,
            )
        )

    return ("\n".join(result_lines) + ("\n" if result_lines else "")).encode("utf-8")


@router.post(
    "/messages/batches", openapi_extra=anthropic_message_batches_openapi_extra()
)
@exceptions_handler
async def create_message_batch(request: Request):
    """Anthropic Message Batches API compatible create endpoint."""
    data = await read_request_json(request)
    completion_window = data.get("completion_window", "24h")
    if completion_window is None:
        completion_window = "24h"
    if completion_window != "24h":
        return _anthropic_http_exception(
            400,
            "invalid_request_error",
            'Only `completion_window="24h"` is supported.',
        )
    requests_data = data.get("requests")
    if not isinstance(requests_data, list) or not requests_data:
        return _anthropic_http_exception(
            400,
            "invalid_request_error",
            "`requests` must be a non-empty array.",
        )

    seen_custom_ids = set()
    openai_rows = []
    stored_requests = []
    for index, batch_request in enumerate(requests_data, start=1):
        if not isinstance(batch_request, dict):
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"`requests[{index - 1}]` must be an object.",
            )

        custom_id = batch_request.get("custom_id")
        params = batch_request.get("params")
        if not isinstance(custom_id, str) or not custom_id:
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"`requests[{index - 1}].custom_id` must be a non-empty string.",
            )
        if custom_id in seen_custom_ids:
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"Duplicate `custom_id` detected: `{custom_id}`.",
            )
        if not isinstance(params, dict):
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"`requests[{index - 1}].params` must be an object.",
            )
        if params.get("stream"):
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                "Streaming requests are not supported inside message batches.",
            )

        seen_custom_ids.add(custom_id)
        openai_rows.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": to_backend_payload(
                    build_normalized_chat_request(
                        params,
                        logger=get_logger_from_state(request.app.state),
                    )
                ),
            }
        )
        stored_requests.append({"custom_id": custom_id, "params": params})

    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    record = await batches_service.create_batch_from_rows(
        openai_rows,
        endpoint="/v1/chat/completions",
        completion_window=completion_window,
        metadata={
            "api_format": "anthropic_messages",
            "requests": stored_requests,
        },
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    return _build_anthropic_batch_object(record["batch"], record["metadata"])


@router.get("/messages/batches")
@exceptions_handler
async def list_message_batches(
    request: Request,
    after_id: Optional[str] = Query(default=None),
    before_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=1000),
):
    """Anthropic Message Batches API compatible list endpoint."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    records = await batches_service.list_anthropic_batches(
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    data = [
        _build_anthropic_batch_object(record["batch"], record["metadata"])
        for record in records
    ]

    paged, has_more = _paginate_anthropic_batches(
        data,
        after_id=after_id,
        before_id=before_id,
        limit=limit,
    )
    return {
        "data": paged,
        "has_more": has_more,
        "first_id": paged[0]["id"] if paged else None,
        "last_id": paged[-1]["id"] if paged else None,
    }


@router.get("/messages/batches/{message_batch_id}")
@exceptions_handler
async def retrieve_message_batch(message_batch_id: str, request: Request):
    """Anthropic Message Batches API compatible retrieve endpoint."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    record = await batches_service.get_anthropic_batch(
        message_batch_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    if record is None:
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )
    return _build_anthropic_batch_object(record["batch"], record["metadata"])


@router.post("/messages/batches/{message_batch_id}/cancel")
@exceptions_handler
async def cancel_message_batch(message_batch_id: str, request: Request):
    """Surface the unsupported cancel capability with an Anthropic-style error."""
    batch_store = get_batch_store(request)
    metadata = batch_store.get(message_batch_id)
    if not metadata or metadata.get("api_format") != "anthropic_messages":
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )
    return _anthropic_http_exception(
        501,
        "api_error",
        "Message batch cancellation is not supported by the configured GigaChat backend.",
    )


@router.delete("/messages/batches/{message_batch_id}")
@exceptions_handler
async def delete_message_batch(message_batch_id: str, request: Request):
    """Surface the unsupported delete capability with an Anthropic-style error."""
    batch_store = get_batch_store(request)
    metadata = batch_store.get(message_batch_id)
    if not metadata or metadata.get("api_format") != "anthropic_messages":
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )
    return _anthropic_http_exception(
        501,
        "api_error",
        "Message batch deletion is not supported by the configured GigaChat backend.",
    )


@router.get("/messages/batches/{message_batch_id}/results")
@exceptions_handler
async def get_message_batch_results(message_batch_id: str, request: Request):
    """Anthropic Message Batches API compatible results endpoint."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    record = await batches_service.get_anthropic_batch(
        message_batch_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    if record is None:
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )
    batch = record["batch"]
    metadata = record["metadata"]
    if getattr(batch, "status", None) != "completed" or not batch.output_file_id:
        return _anthropic_http_exception(
            409,
            "invalid_request_error",
            "Results are not available until message batch processing has ended.",
        )

    file_response = await giga_client.aget_file_content(file_id=batch.output_file_id)
    content = _build_anthropic_batch_results(file_response.content, metadata)
    return Response(content=content, media_type="application/binary")
