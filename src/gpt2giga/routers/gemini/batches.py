"""Gemini asynchronous batch facade over durable native GigaChat jobs."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Request

from gpt2giga.app_state import (
    get_gigachat_client,
    get_resource_store,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.files import file_content, stored_file
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import update_request_context
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_BATCHES
from gpt2giga.openapi_specs.gemini import gemini_batches_openapi_extra
from gpt2giga.protocol.batches import parse_jsonl
from gpt2giga.protocol.embeddings import normalize_embedding_response
from gpt2giga.protocols.gemini import (
    GeminiProtocolAdapter,
    normalized_chat_response_to_gemini,
)
from gpt2giga.providers.gigachat.adapter import (
    normalized_chat_to_openai_payload,
    gigachat_response_to_normalized,
)
from gpt2giga.providers.gigachat.batches import (
    TERMINAL,
    batch_owner,
    batch_error,
    create_batch,
    poll_batch,
    result_file,
    list_batches as native_list_batches,
    resolve_batch_model,
    validate_batch_body,
)
from gpt2giga.routers.gemini.embeddings import _content_text
from gpt2giga.routers.gemini.files import _file_id, _rfc3339, resolve_file_references
from gpt2giga.storage.resources import Resource

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_BATCHES])
operations_router = APIRouter(tags=[OPENAPI_TAG_GEMINI_BATCHES])


def _context() -> None:
    update_request_context(metadata={"protocol": "gemini", "api_format": "batches"})


@operations_router.post(
    "/models/{model}:batchGenerateContent",
    openapi_extra=gemini_batches_openapi_extra(create=True),
)
@exceptions_handler
async def batch_generate_content(model: str, request: Request):
    """Submit Gemini generation rows as one actual native batch."""
    return await _create(request, model, embeddings=False)


@operations_router.post(
    "/models/{model}:asyncBatchEmbedContent",
    openapi_extra=gemini_batches_openapi_extra(create=True),
)
@exceptions_handler
async def batch_embed_content(model: str, request: Request):
    """Submit one asynchronous native embedding batch."""
    return await _create(request, model, embeddings=True)


async def _create(request: Request, model: str, *, embeddings: bool):
    _context()
    data = await read_request_json(request)
    batch = data.get("batch")
    if not isinstance(batch, dict):
        raise batch_error("A batch object is required.")
    if batch.get("webhookConfig") or batch.get("outputConfig"):
        raise batch_error("Webhook and external output destinations are unsupported.")
    source = batch.get("inputConfig") or batch.get("input_config")
    if not isinstance(source, dict):
        raise batch_error("batch.inputConfig is required.")
    file_name = source.get("fileName") or source.get("file_name")
    if file_name:
        if not isinstance(file_name, str):
            raise batch_error("Batch file name must be a string.")
        file_id = _file_id(file_name)
        file = await stored_file(request, file_id)
        if file is None or not file.metadata.get("local"):
            raise batch_error("Batch input must be an owned local JSONL file.")
        entries = parse_jsonl(await file_content(request, file_id))
    else:
        entries = source.get("requests")
        if isinstance(entries, dict):
            entries = entries.get("requests")
    if not isinstance(entries, list) or not entries:
        raise batch_error("A non-empty batch input is required.")
    native_model = resolve_batch_model(
        request, model.removeprefix("models/"), embeddings=embeddings
    )
    adapter = GeminiProtocolAdapter()
    rows = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("request"), dict):
            raise batch_error("Each batch entry must contain a request object.")
        body = dict(entry["request"])
        supplied_model = body.get("model")
        if (
            supplied_model
            and resolve_batch_model(
                request,
                str(supplied_model).removeprefix("models/"),
                embeddings=embeddings,
            )
            != native_model
        ):
            raise batch_error("A batch cannot mix upstream models.")
        validate_batch_body(body)
        row_metadata = entry.get("metadata", {})
        if not isinstance(row_metadata, dict):
            raise batch_error("Batch row metadata must be an object.")
        key = entry.get("key", row_metadata.get("key", f"row-{index}"))
        if embeddings:
            native = {
                "model": native_model,
                "input": [_content_text(body.get("content"), param="content")],
            }
        else:
            normalized = adapter.generate_content_to_normalized(
                body, model=native_model, stream=False
            )
            if any(tool.kind.value == "hosted" for tool in normalized.tools):
                raise batch_error("Hosted tools are not supported in batches.")
            await resolve_file_references(request, normalized)
            public = normalized_chat_to_openai_payload(normalized)
            native = await request.app.state.request_transformer.prepare_chat(
                public, get_gigachat_client(request)
            )
            native["model"] = native_model
        rows.append(
            {
                "id": key,
                "request": native,
                "original": body,
                "metadata": {
                    **row_metadata,
                    **({"key": entry["key"]} if "key" in entry else {}),
                },
            }
        )
    resource = await create_batch(
        request,
        protocol="gemini",
        method="embedder" if embeddings else "chat_completions",
        model=native_model,
        rows=rows,
        metadata={
            "display_name": batch.get("displayName") or batch.get("display_name"),
            "file_input": bool(file_name),
        },
    )
    return await _operation(resource, request)


@router.get("/batches", openapi_extra=gemini_batches_openapi_extra(create=False))
@exceptions_handler
async def list_batches(request: Request):
    """List registered Gemini jobs as Operations, with SDK pagination."""
    _context()
    records = await native_list_batches(request, "gemini")
    try:
        limit = int(request.query_params.get("pageSize", "100"))
    except ValueError as exc:
        raise batch_error("pageSize must be an integer.") from exc
    if not 1 <= limit <= 100:
        raise batch_error("pageSize must be between 1 and 100.")
    token = request.query_params.get("pageToken")
    ids = [resource.public_id for resource in records]
    if token is not None and token not in ids:
        raise batch_error("Invalid pageToken.")
    start = ids.index(token) + 1 if token else 0
    page = records[start : start + limit]
    result = {"operations": [await _operation(resource, request) for resource in page]}
    if start + limit < len(records):
        result["nextPageToken"] = page[-1].public_id
    return result


@router.get(
    "/batches/{batch_id}", openapi_extra=gemini_batches_openapi_extra(create=False)
)
@exceptions_handler
async def get_batch(batch_id: str, request: Request):
    """Poll the existing native job and return its observed result."""
    _context()
    return await _operation(await poll_batch(request, batch_id, "gemini"), request)


@router.post("/batches/{batch_id}:cancel")
@router.delete("/batches/{batch_id}")
@exceptions_handler
async def cancel_batch(batch_id: str, request: Request):
    """Do not claim a backend job was cancelled or deleted locally."""
    _context()
    raise batch_error("GigaChat does not support batch cancellation or deletion.", 501)


async def _operation(resource: Resource, request: Request) -> dict[str, Any]:
    data = resource.metadata
    status = data["status"]
    metadata = {
        "displayName": data.get("display_name") or resource.public_id,
        "model": f"models/{data['model']}",
        "state": {
            "validating": "JOB_STATE_PENDING",
            "in_progress": "JOB_STATE_RUNNING",
            "completed": "JOB_STATE_SUCCEEDED",
            "failed": "JOB_STATE_FAILED",
            "expired": "JOB_STATE_EXPIRED",
        }[status],
        "createTime": _rfc3339(data["created_at"]),
        "updateTime": _rfc3339(data.get("ended_at", data["created_at"])),
    }
    if data.get("ended_at"):
        metadata["endTime"] = _rfc3339(data["ended_at"])
    if status in TERMINAL:
        output = data.get("gemini_output")
        if output is None:
            responses = [
                _project_result(result, row, data, request)
                for result, row in zip(data["results"], data["rows"], strict=True)
            ]
            if data.get("file_input"):
                content = (
                    "\n".join(
                        json.dumps({"key": row["id"], **item}, ensure_ascii=False)
                        for row, item in zip(data["rows"], responses, strict=True)
                    )
                    + "\n"
                ).encode()
                file_id = await result_file(request, resource, "gemini_output", content)
                output = {"responsesFile": f"files/{file_id}"}
            else:
                field = (
                    "inlinedEmbedContentResponses"
                    if data["method"] == "embedder"
                    else "inlinedResponses"
                )
                output = {field: {"inlinedResponses": responses}}
            await get_resource_store(request).update(
                batch_owner(request, resource),
                "batch",
                resource.public_id,
                {"gemini_output": output},
            )
        metadata["output"] = output
    return {
        "name": f"batches/{resource.public_id}",
        "metadata": metadata,
        "done": status in TERMINAL,
    }


def _project_result(result: dict, row: dict, data: dict, request: Request) -> dict:
    metadata = {**row.get("metadata", {}), "key": row["id"]}
    if result.get("error") or result.get("expired"):
        error = result.get("error")
        message = (
            error.get("message", "The upstream batch item failed.")
            if isinstance(error, dict)
            else "The upstream batch item failed."
        )
        return {"metadata": metadata, "error": {"code": 13, "message": message}}
    if data["method"] == "embedder":
        embedding = normalize_embedding_response(
            result["result"], model=data["model"], expected_count=1
        )
        response = {"embedding": {"values": embedding["data"][0]["embedding"]}}
    else:
        normalized = GeminiProtocolAdapter().generate_content_to_normalized(
            row["original"], model=data["model"]
        )
        raw = request.app.state.response_processor.process_response(
            SimpleNamespace(model_dump=lambda: result["result"]),
            data["model"],
            result["id"],
            request_data=row["request"],
        )
        response = normalized_chat_response_to_gemini(
            gigachat_response_to_normalized(
                raw, request=normalized, effective_model=data["model"]
            ),
            requested_model=data["model"],
        )
    return {"metadata": metadata, "response": response}
