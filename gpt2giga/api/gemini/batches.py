"""Gemini Batch API compatible routes and serializers."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from gpt2giga.api.gemini.request import (
    GeminiAPIError,
    model_resource_name,
    normalize_file_name,
    normalize_model_name,
    read_gemini_request_json,
)
from gpt2giga.api.gemini.response import (
    build_generate_content_response,
    gemini_exceptions_handler,
)
from gpt2giga.api.tags import PROVIDER_GEMINI, TAG_BATCHES, provider_tag
from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.features.batches import get_batches_service_from_state
from gpt2giga.features.batches.store import get_batch_store
from gpt2giga.features.batches.transforms import extract_batch_result_body, parse_jsonl
from gpt2giga.features.files.store import get_file_store
from gpt2giga.providers.gemini import gemini_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=[provider_tag(TAG_BATCHES, PROVIDER_GEMINI)])

_GENERATE_CONTENT_BATCH_TYPE = (
    "type.googleapis.com/google.ai.generativelanguage.v1beta.GenerateContentBatch"
)
_BATCH_STATE_MAP = {
    "created": "BATCH_STATE_PENDING",
    "in_progress": "BATCH_STATE_RUNNING",
    "completed": "BATCH_STATE_SUCCEEDED",
    "failed": "BATCH_STATE_FAILED",
    "cancelled": "BATCH_STATE_CANCELLED",
    "expired": "BATCH_STATE_EXPIRED",
}


def _timestamp_to_rfc3339(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _batch_state(batch: Any) -> str:
    return _BATCH_STATE_MAP.get(getattr(batch, "status", None), "BATCH_STATE_RUNNING")


def _batch_stats(batch: Any, metadata: dict[str, Any]) -> dict[str, str]:
    request_counts = getattr(batch, "request_counts", None)
    total = getattr(request_counts, "total", None)
    if total is None:
        total = len(metadata.get("requests", []))
    completed = getattr(request_counts, "completed", None) or 0
    failed = getattr(request_counts, "failed", None) or 0
    pending = max(int(total or 0) - int(completed) - int(failed), 0)
    return {
        "requestCount": str(total or 0),
        "successfulRequestCount": str(completed),
        "failedRequestCount": str(failed),
        "pendingRequestCount": str(pending),
    }


def _build_input_config(metadata: dict[str, Any]) -> dict[str, Any]:
    input_file_id = metadata.get("input_file_id")
    if isinstance(input_file_id, str) and input_file_id:
        return {"fileName": f"files/{input_file_id}"}

    stored_requests = metadata.get("requests") or []
    return {
        "requests": {
            "requests": [
                {
                    **({"key": request_item["key"]} if "key" in request_item else {}),
                    "request": request_item.get("request", {}),
                    **(
                        {"metadata": request_item["metadata"]}
                        if "metadata" in request_item
                        else {}
                    ),
                }
                for request_item in stored_requests
                if isinstance(request_item, dict)
            ]
        }
    }


def build_gemini_generate_content_batch(
    batch: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build a Gemini GenerateContentBatch resource."""
    payload: dict[str, Any] = {
        "@type": _GENERATE_CONTENT_BATCH_TYPE,
        "model": model_resource_name(metadata.get("model") or "unknown"),
        "name": f"batches/{getattr(batch, 'id_', '')}",
        "displayName": metadata.get("display_name") or getattr(batch, "id_", ""),
        "inputConfig": _build_input_config(metadata),
        "createTime": _timestamp_to_rfc3339(getattr(batch, "created_at", None)),
        "updateTime": _timestamp_to_rfc3339(getattr(batch, "updated_at", None)),
        "batchStats": _batch_stats(batch, metadata),
        "state": _batch_state(batch),
        "priority": str(metadata.get("priority", 0)),
    }
    if payload["state"] in {
        "BATCH_STATE_SUCCEEDED",
        "BATCH_STATE_FAILED",
        "BATCH_STATE_CANCELLED",
        "BATCH_STATE_EXPIRED",
    }:
        payload["endTime"] = _timestamp_to_rfc3339(getattr(batch, "updated_at", None))
    output_file_id = getattr(batch, "output_file_id", None)
    if output_file_id:
        payload["output"] = {"responsesFile": f"files/{output_file_id}"}
    return payload


def build_gemini_batch_operation(
    batch: Any, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Build a Gemini long-running operation for a batch."""
    batch_payload = build_gemini_generate_content_batch(batch, metadata)
    state = batch_payload["state"]
    done = state in {
        "BATCH_STATE_SUCCEEDED",
        "BATCH_STATE_FAILED",
        "BATCH_STATE_CANCELLED",
        "BATCH_STATE_EXPIRED",
    }
    operation: dict[str, Any] = {
        "name": batch_payload["name"],
        "metadata": batch_payload,
        "done": done,
    }
    if not done:
        return operation
    if state == "BATCH_STATE_SUCCEEDED":
        operation["response"] = batch_payload
        return operation

    status_code = 1 if state == "BATCH_STATE_CANCELLED" else 13
    operation["error"] = {
        "code": status_code,
        "message": f"Batch finished with state {state}.",
    }
    return operation


def build_gemini_batch_output_file(
    output_content_b64: str,
    *,
    batch_metadata: dict[str, Any],
) -> bytes:
    """Transform a GigaChat batch output file into Gemini batch-results JSONL."""
    output_rows = parse_jsonl(base64.b64decode(output_content_b64))
    stored_requests = batch_metadata.get("requests") or []

    lines: list[str] = []
    for index, row in enumerate(output_rows):
        request_item = (
            stored_requests[index] if index < len(stored_requests) else {}
        ) or {}
        request_payload = request_item.get("request", {})
        request_metadata = request_item.get("metadata")
        error = row.get("error")

        if (
            error
            and "result" not in row
            and "response" not in row
            and "body" not in row
        ):
            transformed_row = {
                **({"key": request_item["key"]} if "key" in request_item else {}),
                **(
                    {"metadata": request_metadata}
                    if request_metadata is not None
                    else {}
                ),
                "error": _normalize_batch_error(error),
            }
        else:
            raw_body = extract_batch_result_body(row)
            if isinstance(raw_body, dict) and raw_body.get("candidates"):
                gemini_response = raw_body
            else:
                response_model = request_payload.get("model", "unknown")
                response_id = (
                    row.get("request_id") or row.get("id") or f"batch-request-{index}"
                )
                if not isinstance(raw_body, dict):
                    raw_body = {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": str(raw_body),
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {},
                    }
                gemini_response = build_generate_content_response(
                    raw_body,
                    normalize_model_name(response_model),
                    str(response_id),
                    request_data=request_payload,
                )
            transformed_row = {
                **({"key": request_item["key"]} if "key" in request_item else {}),
                **(
                    {"metadata": request_metadata}
                    if request_metadata is not None
                    else {}
                ),
                "response": gemini_response,
            }

        lines.append(json.dumps(transformed_row, ensure_ascii=False))

    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _normalize_batch_error(error: Any) -> dict[str, Any]:
    if isinstance(error, dict):
        nested_error = error.get("error")
        if isinstance(nested_error, dict):
            message = nested_error.get("message") or error.get("message")
            code = nested_error.get("code", error.get("code", 13))
        else:
            message = error.get("message")
            code = error.get("code", 13)
        return {
            "code": int(code)
            if isinstance(code, int | str) and str(code).isdigit()
            else 13,
            "message": message or json.dumps(error, ensure_ascii=False),
        }
    return {"code": 13, "message": str(error)}


def _build_batch_rows(
    requests_payload: list[dict[str, Any]],
    *,
    model: str,
    logger: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    stored_requests: list[dict[str, Any]] = []
    for index, request_item in enumerate(requests_payload, start=1):
        if not isinstance(request_item, dict):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each batch request must be an object.",
            )
        request_payload = request_item.get("request")
        if not isinstance(request_payload, dict):
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="Each batch request must include an object `request`.",
            )
        request_payload = dict(request_payload)
        request_payload["model"] = normalize_model_name(
            request_payload.get("model") or model
        )
        normalized_request = gemini_provider_adapters.chat.build_normalized_request(
            request_payload,
            logger=logger,
        )
        rows.append(
            {
                "custom_id": f"gemini-batch-request-{index}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": to_backend_payload(normalized_request),
            }
        )
        stored_item = {"request": request_payload}
        request_key = request_item.get("key")
        if isinstance(request_key, str) and request_key.strip():
            stored_item["key"] = request_key.strip()
        if "metadata" in request_item:
            stored_item["metadata"] = request_item["metadata"]
        stored_requests.append(stored_item)
    return rows, stored_requests


async def _load_batch_requests_from_file(
    file_id: str,
    *,
    giga_client: Any,
    model: str,
    logger: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    file_response = await giga_client.aget_file_content(file_id=file_id)
    try:
        file_rows = parse_jsonl(base64.b64decode(file_response.content))
    except Exception as exc:  # pragma: no cover - defensive parsing
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=f"Batch input file is not valid JSONL: {exc}",
        ) from exc
    return _build_batch_rows(file_rows, model=model, logger=logger)


def _filter_gemini_batch_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record["metadata"].get("api_format") == "gemini_generate_content"
    ]


def _paginate_operations(
    operations: list[dict[str, Any]],
    *,
    page_token: str | None,
    page_size: int,
) -> tuple[list[dict[str, Any]], str | None]:
    if page_token:
        normalized_token = page_token.strip()
        for index, operation in enumerate(operations):
            if operation.get("name") == normalized_token or operation.get("name") == (
                f"batches/{normalized_token}"
            ):
                operations = operations[index + 1 :]
                break
    page = operations[:page_size]
    next_page_token = page[-1]["name"] if len(operations) > page_size else None
    return page, next_page_token


@router.post("/models/{model}:batchGenerateContent")
@gemini_exceptions_handler
async def batch_generate_content(model: str, request: Request):
    """Create a Gemini generateContent batch job."""
    data = await read_gemini_request_json(request)
    batch_payload = data.get("batch")
    if not isinstance(batch_payload, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`batch` must be an object.",
        )

    normalized_model = normalize_model_name(model)
    body_model = normalize_model_name(batch_payload.get("model") or normalized_model)
    if body_model != normalized_model:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=(
                f"Request model `{batch_payload.get('model')}` does not match route model "
                f"`{model_resource_name(model)}`."
            ),
        )

    display_name = batch_payload.get("displayName") or batch_payload.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`batch.displayName` is required.",
        )

    input_config = batch_payload.get("inputConfig")
    if not isinstance(input_config, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`batch.inputConfig` must be an object.",
        )

    logger = get_logger_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    input_file_id: str | None = None
    if isinstance(input_config.get("requests"), dict):
        inlined_requests = input_config["requests"].get("requests")
        if not isinstance(inlined_requests, list) or not inlined_requests:
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message="`batch.inputConfig.requests.requests` must be a non-empty array.",
            )
        rows, stored_requests = _build_batch_rows(
            inlined_requests,
            model=normalized_model,
            logger=logger,
        )
    else:
        file_name = input_config.get("fileName") or input_config.get("file_name")
        if not isinstance(file_name, str) or not file_name.strip():
            raise GeminiAPIError(
                status_code=400,
                status="INVALID_ARGUMENT",
                message=(
                    "`batch.inputConfig` must include either `requests` or `fileName`."
                ),
            )
        input_file_id = normalize_file_name(file_name)
        rows, stored_requests = await _load_batch_requests_from_file(
            input_file_id,
            giga_client=giga_client,
            model=normalized_model,
            logger=logger,
        )

    batches_service = get_batches_service_from_state(request.app.state)
    metadata: dict[str, Any] = {
        "api_format": "gemini_generate_content",
        "display_name": display_name,
        "model": normalized_model,
        "priority": batch_payload.get("priority", 0),
        "requests": stored_requests,
    }
    if input_file_id:
        metadata["input_file_id"] = input_file_id
    record = await batches_service.create_batch_from_rows(
        rows,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata=metadata,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    return build_gemini_batch_operation(record["batch"], record["metadata"])


@router.get("/batches")
@gemini_exceptions_handler
async def list_batches(
    request: Request,
    pageSize: int = Query(default=50, ge=1, le=1000),
    pageToken: str | None = Query(default=None),
    filter: str | None = Query(default=None),
):
    """List Gemini batch operations."""
    del filter  # Unsupported by the proxy; accepted for wire compatibility.
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    records = await batches_service.list_batch_records(
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    operations = [
        build_gemini_batch_operation(record["batch"], record["metadata"])
        for record in _filter_gemini_batch_records(records)
    ]
    page, next_page_token = _paginate_operations(
        operations,
        page_token=pageToken,
        page_size=pageSize,
    )
    payload: dict[str, Any] = {"operations": page}
    if next_page_token:
        payload["nextPageToken"] = next_page_token
    return payload


@router.get("/batches/{batch_id}")
@gemini_exceptions_handler
async def get_batch(batch_id: str, request: Request):
    """Get a Gemini batch operation."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    record = await batches_service.get_batch_record(
        batch_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    if (
        record is None
        or record["metadata"].get("api_format") != "gemini_generate_content"
    ):
        raise GeminiAPIError(
            status_code=404,
            status="NOT_FOUND",
            message=f"Batch `batches/{batch_id}` not found.",
        )
    return build_gemini_batch_operation(record["batch"], record["metadata"])


@router.post("/batches/{batch_id}:cancel")
@gemini_exceptions_handler
async def cancel_batch(batch_id: str, request: Request):
    """Surface unsupported Gemini batch cancellation."""
    metadata = get_batch_store(request).get(batch_id)
    if not metadata or metadata.get("api_format") != "gemini_generate_content":
        raise GeminiAPIError(
            status_code=404,
            status="NOT_FOUND",
            message=f"Batch `batches/{batch_id}` not found.",
        )
    raise GeminiAPIError(
        status_code=501,
        status="UNIMPLEMENTED",
        message="Batch cancellation is not supported by the configured GigaChat backend.",
    )


@router.delete("/batches/{batch_id}")
@gemini_exceptions_handler
async def delete_batch(batch_id: str, request: Request):
    """Surface unsupported Gemini batch deletion."""
    metadata = get_batch_store(request).get(batch_id)
    if not metadata or metadata.get("api_format") != "gemini_generate_content":
        raise GeminiAPIError(
            status_code=404,
            status="NOT_FOUND",
            message=f"Batch `batches/{batch_id}` not found.",
        )
    raise GeminiAPIError(
        status_code=501,
        status="UNIMPLEMENTED",
        message="Batch deletion is not supported by the configured GigaChat backend.",
    )


@router.get("/batches/{batch_id}:download")
@gemini_exceptions_handler
async def download_batch_results(batch_id: str, request: Request):
    """Return Gemini batch results as JSONL for local testing/debugging."""
    giga_client = get_gigachat_client(request)
    batches_service = get_batches_service_from_state(request.app.state)
    record = await batches_service.get_batch_record(
        batch_id,
        giga_client=giga_client,
        batch_store=get_batch_store(request),
        file_store=get_file_store(request),
    )
    if (
        record is None
        or record["metadata"].get("api_format") != "gemini_generate_content"
    ):
        raise GeminiAPIError(
            status_code=404,
            status="NOT_FOUND",
            message=f"Batch `batches/{batch_id}` not found.",
        )
    batch = record["batch"]
    if getattr(batch, "status", None) != "completed" or not getattr(
        batch, "output_file_id", None
    ):
        raise GeminiAPIError(
            status_code=409,
            status="FAILED_PRECONDITION",
            message="Batch results are not available until processing has completed.",
        )
    file_response = await giga_client.aget_file_content(file_id=batch.output_file_id)
    content = build_gemini_batch_output_file(
        file_response.content,
        batch_metadata=record["metadata"],
    )
    return Response(content=content, media_type="application/json")
