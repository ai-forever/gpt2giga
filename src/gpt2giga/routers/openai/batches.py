"""OpenAI batch submission, polling and durable result files."""

import json

from fastapi import APIRouter, Query, Request

from gpt2giga.app_state import (
    get_resource_store,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.files import file_content
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.openai import batches_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_BATCHES
from gpt2giga.protocol.batches import (
    _transform_chat_batch_result,
    _transform_responses_batch_result,
    get_batch_target,
    parse_jsonl,
)
from gpt2giga.protocol.embeddings import (
    apply_embedding_encoding_format,
    normalize_embedding_response,
)
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
)

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_BATCHES])


def _jsonl(rows):
    return (
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    ).encode()


async def _materialize(request: Request, resource):
    metadata = resource.metadata
    if (
        metadata["status"] not in TERMINAL
        or metadata.get("files_materialized")
        or metadata.get("submission_state") == "unknown"
    ):
        return resource
    originals = {row["id"]: row for row in metadata["rows"]}
    target = get_batch_target(metadata["endpoint"])
    successes, errors = [], []
    for row in metadata["results"]:
        key = row["id"]
        if row.get("expired") or "error" in row:
            error = row.get("error") or {
                "code": "batch_expired",
                "message": "Gateway result acceptance deadline elapsed.",
            }
            errors.append(
                {"id": key, "custom_id": key, "response": None, "error": error}
            )
            continue
        original = originals[key]["original"]
        raw = row["result"]
        if target.kind == "chat":
            body = _transform_chat_batch_result(
                raw, request.app.state.response_processor, key, original
            )
        elif target.kind == "responses":
            body = _transform_responses_batch_result(
                raw, request.app.state.response_processor, key, original
            )
        else:
            body = normalize_embedding_response(
                raw,
                model=metadata["model"],
                expected_count=len(originals[key]["request"]["input"]),
            )
            body = apply_embedding_encoding_format(
                body, original.get("encoding_format")
            )
        successes.append(
            {
                "id": key,
                "custom_id": key,
                "response": {
                    "status_code": 200,
                    "request_id": row.get("request_id", key),
                    "body": body,
                },
                "error": None,
            }
        )
    output_id = (
        await result_file(request, resource, "output", _jsonl(successes))
        if successes
        else None
    )
    error_id = (
        await result_file(request, resource, "errors", _jsonl(errors))
        if errors
        else None
    )
    return await get_resource_store(request).update(
        batch_owner(request, resource),
        "batch",
        resource.public_id,
        {
            "output_file_id": output_id,
            "error_file_id": error_id,
            "files_materialized": True,
        },
    )


async def batch_object(request: Request, resource):
    resource = await _materialize(request, resource)
    m = resource.metadata
    completed = sum("result" in row for row in m["results"])
    failed = sum("error" in row or row.get("expired", False) for row in m["results"])
    return {
        "id": resource.public_id,
        "object": "batch",
        "endpoint": m["endpoint"],
        "input_file_id": m["input_file_id"],
        "completion_window": "24h",
        "status": m["status"],
        "created_at": int(m["created_at"]),
        "expires_at": int(m["deadline"]),
        "completed_at": int(m["ended_at"]) if m["status"] == "completed" else None,
        "failed_at": int(m["ended_at"]) if m["status"] == "failed" else None,
        "expired_at": int(m["ended_at"]) if m["status"] == "expired" else None,
        "in_progress_at": None,
        "finalizing_at": None,
        "cancelling_at": None,
        "cancelled_at": None,
        "request_counts": {
            "total": len(m["rows"]),
            "completed": completed,
            "failed": failed,
        },
        "errors": {
            "object": "list",
            "data": [
                {
                    "code": "submission_outcome_unknown",
                    "message": "Submission outcome is unknown; inspect the upstream job before retrying.",
                }
            ],
        }
        if m.get("submission_state") == "unknown"
        else None,
        "metadata": m.get("metadata"),
        "output_file_id": m.get("output_file_id"),
        "error_file_id": m.get("error_file_id"),
    }


@router.post("/batches", openapi_extra=batches_openapi_extra())
@exceptions_handler
async def create_batch(request: Request):
    data = await read_request_json(request)
    if data.get("completion_window") not in {None, "24h"}:
        raise batch_error('Only completion_window="24h" is supported.')
    file_id = data.get("input_file_id")
    if not isinstance(file_id, str) or not file_id:
        raise batch_error("input_file_id is required.")
    target = get_batch_target(data.get("endpoint", ""))
    rows, model = await prepare_rows(
        request, parse_jsonl(await file_content(request, file_id)), target.endpoint
    )
    resource = await submit_batch(
        request,
        protocol="openai",
        method=target.method,
        model=model,
        rows=rows,
        metadata={
            "endpoint": target.endpoint,
            "input_file_id": file_id,
            "metadata": data.get("metadata"),
        },
    )
    return await batch_object(request, resource)


@router.get("/batches")
@exceptions_handler
async def list_batches(
    request: Request, after: str | None = None, limit: int = Query(20, ge=1, le=100)
):
    resources = await registered_batches(request, "openai", limit=limit, after=after)
    data = [await batch_object(request, r) for r in resources[:limit]]
    return {
        "object": "list",
        "data": data,
        "has_more": len(resources) > limit,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    }


@router.get("/batches/{batch_id}")
@exceptions_handler
async def retrieve_batch(batch_id: str, request: Request):
    return await batch_object(request, await poll_batch(request, batch_id, "openai"))


@router.post("/batches/{batch_id}/cancel")
@router.delete("/batches/{batch_id}")
@exceptions_handler
async def unsupported_batch_operation(batch_id: str, request: Request):
    await get_batch(request, batch_id, "openai")
    raise batch_error(
        "The GigaChat backend does not support batch cancellation or deletion.", 501
    )
