import base64
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException

from gpt2giga.providers.gigachat.embeddings_mapper import transform_embedding_body


@dataclass(frozen=True)
class BatchTarget:
    """Describe how an OpenAI batch endpoint maps to GigaChat."""

    endpoint: str
    method: str
    kind: str


_BATCH_TARGETS = {
    "/v1/chat/completions": BatchTarget(
        endpoint="/v1/chat/completions",
        method="chat_completions",
        kind="chat",
    ),
    "/chat/completions": BatchTarget(
        endpoint="/v1/chat/completions",
        method="chat_completions",
        kind="chat",
    ),
    "/v1/embeddings": BatchTarget(
        endpoint="/v1/embeddings",
        method="embedder",
        kind="embeddings",
    ),
    "/embeddings": BatchTarget(
        endpoint="/v1/embeddings",
        method="embedder",
        kind="embeddings",
    ),
}

BATCH_CHAT_V2_FALLBACK_WARNING = (
    "Batching currently supports only `/v1/chat/completions` on the GigaChat v1 "
    "backend. `GPT2GIGA_GIGACHAT_API_MODE=v2` will fall back to v1 for this batch."
)

_BATCH_STATUS_MAP = {
    "created": "validating",
    "in_progress": "in_progress",
    "completed": "completed",
}


def get_batch_target(endpoint: str) -> BatchTarget:
    """Resolve an OpenAI batch endpoint to a GigaChat batch target."""
    target = _BATCH_TARGETS.get(endpoint)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": (
                        "Unsupported batch endpoint. Supported values are "
                        "`/v1/chat/completions` and `/v1/embeddings`."
                    ),
                    "type": "invalid_request_error",
                    "param": "endpoint",
                    "code": None,
                }
            },
        )
    return target


def get_batch_warnings(*, target: BatchTarget, gigachat_api_mode: str) -> list[str]:
    """Return compatibility warnings for a batch request."""
    if target.kind == "chat" and gigachat_api_mode == "v2":
        return [BATCH_CHAT_V2_FALLBACK_WARNING]
    return []


def map_openai_file_purpose(purpose: str) -> str:
    """Map an OpenAI file purpose to the closest GigaChat purpose."""
    if purpose == "assistants":
        return "assistant"
    return "general"


def infer_openai_file_purpose(
    gigachat_purpose: Optional[str],
    stored_purpose: Optional[str] = None,
) -> str:
    """Infer the OpenAI-visible file purpose."""
    if stored_purpose:
        return stored_purpose
    if gigachat_purpose == "assistant":
        return "assistants"
    return "user_data"


def _resolve_batch_model(body: dict[str, Any], giga_client: Any) -> Optional[str]:
    """Resolve the model to include in transformed batch rows."""
    request_model = body.get("model")
    if isinstance(request_model, str) and request_model.strip():
        return request_model

    settings = getattr(giga_client, "_settings", None)
    configured_model = getattr(settings, "model", None)
    if isinstance(configured_model, str) and configured_model.strip():
        return configured_model

    return None


async def transform_batch_input_file(
    content: bytes,
    *,
    target: BatchTarget,
    request_transformer: Any,
    giga_client: Any,
    embeddings_model: str,
    gigachat_api_mode: str = "v1",
) -> bytes:
    """Transform OpenAI JSONL batch input into GigaChat `{id, request}` JSONL."""
    transformed_lines = []
    for line_number, row in enumerate(parse_jsonl(content), start=1):
        body = row.get("body")
        if not isinstance(body, dict):
            raise _batch_line_error(
                line_number, "Each batch line must contain an object `body`."
            )

        row_target = get_batch_target(str(row.get("url", target.endpoint)))
        if row_target.kind != target.kind:
            raise _batch_line_error(
                line_number,
                "All batch lines must target the same endpoint family as the batch.",
            )

        method = str(row.get("method", "POST")).upper()
        if method != "POST":
            raise _batch_line_error(
                line_number,
                "Only `POST` batch lines are supported.",
            )

        if target.kind == "chat":
            transformed_body = await request_transformer.prepare_chat_completion(
                body, giga_client
            )
            batch_model = _resolve_batch_model(body, giga_client)
            if batch_model and "model" not in transformed_body:
                transformed_body["model"] = batch_model
        elif target.kind == "responses":
            if gigachat_api_mode == "v1":
                transformed_body = await request_transformer.prepare_response(
                    body, giga_client
                )
            else:
                transformed_body = await request_transformer.prepare_response_v2(
                    body, giga_client
                )
                if hasattr(transformed_body, "model_dump"):
                    transformed_body = transformed_body.model_dump(
                        exclude_none=True,
                        by_alias=True,
                    )
            batch_model = _resolve_batch_model(body, giga_client)
            if batch_model and "model" not in transformed_body:
                transformed_body["model"] = batch_model
        else:
            transformed_body = await transform_embedding_body(body, embeddings_model)

        custom_id = (
            row.get("custom_id") or row.get("id") or f"batch-request-{line_number}"
        )
        transformed_lines.append(
            json.dumps(
                {
                    "id": custom_id,
                    "request": transformed_body,
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(transformed_lines) + ("\n" if transformed_lines else "")).encode(
        "utf-8"
    )


def build_openai_batch_object(batch: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    """Build an OpenAI-compatible batch object."""
    target = _BATCH_TARGETS.get(
        metadata.get("endpoint"),
        BatchTarget(
            endpoint="/v1/chat/completions",
            method="chat_completions",
            kind="chat",
        ),
    )
    status = _BATCH_STATUS_MAP.get(getattr(batch, "status", None), "in_progress")
    created_at = getattr(batch, "created_at", None)
    updated_at = getattr(batch, "updated_at", None)
    request_counts = getattr(batch, "request_counts", None)

    return {
        "id": getattr(batch, "id_", ""),
        "object": "batch",
        "endpoint": metadata.get("endpoint", target.endpoint),
        "errors": None,
        "input_file_id": metadata.get("input_file_id", ""),
        "completion_window": metadata.get("completion_window", "24h"),
        "status": status,
        "created_at": created_at,
        "in_progress_at": updated_at if status == "in_progress" else None,
        "finalizing_at": None,
        "completed_at": updated_at if status == "completed" else None,
        "failed_at": None,
        "expired_at": None,
        "expires_at": None,
        "cancelling_at": None,
        "cancelled_at": None,
        "request_counts": (
            request_counts.model_dump()
            if hasattr(request_counts, "model_dump")
            else None
        ),
        "metadata": metadata.get("metadata"),
        "model": metadata.get("model"),
        "output_file_id": getattr(batch, "output_file_id", None),
        "error_file_id": None,
    }


async def transform_batch_output_file(
    output_content_b64: str,
    *,
    batch_metadata: dict[str, Any],
    input_content_b64: str,
    response_processor: Any,
) -> bytes:
    """Transform a GigaChat batch output file into OpenAI batch output JSONL."""
    output_rows = parse_jsonl(base64.b64decode(output_content_b64))
    input_rows = parse_jsonl(base64.b64decode(input_content_b64))
    input_map = {
        (row.get("custom_id") or row.get("id") or f"batch-request-{index}"): row
        for index, row in enumerate(input_rows)
    }
    target = get_batch_target(batch_metadata["endpoint"])

    result_lines = []
    for index, row in enumerate(output_rows):
        custom_id = row.get("custom_id") or row.get("id") or f"batch-request-{index}"
        source_row = input_map.get(
            custom_id, input_rows[index] if index < len(input_rows) else {}
        )
        original_body = source_row.get("body", {})
        error = row.get("error")
        if error and "result" not in row and "response" not in row:
            transformed_row = {
                "id": row.get("id", custom_id),
                "custom_id": custom_id,
                "response": None,
                "error": error,
            }
        else:
            raw_body = extract_batch_result_body(row)
            if target.kind == "chat":
                transformed_body = _transform_chat_batch_result(
                    raw_body, response_processor, custom_id, original_body
                )
            elif target.kind == "responses":
                transformed_body = _transform_responses_batch_result(
                    raw_body, response_processor, custom_id, original_body
                )
            else:
                transformed_body = raw_body

            transformed_row = {
                "id": row.get("id", custom_id),
                "custom_id": custom_id,
                "response": {
                    "status_code": _extract_batch_status_code(row),
                    "request_id": row.get("request_id") or row.get("id") or custom_id,
                    "body": transformed_body,
                },
                "error": error,
            }
        result_lines.append(json.dumps(transformed_row, ensure_ascii=False))

    return ("\n".join(result_lines) + ("\n" if result_lines else "")).encode("utf-8")


def _transform_chat_batch_result(
    raw_body: Any,
    response_processor: Any,
    response_id: str,
    request_body: dict[str, Any],
) -> Any:
    if isinstance(raw_body, dict) and raw_body.get("object") == "chat.completion":
        return raw_body
    if not isinstance(raw_body, dict):
        return raw_body
    model = request_body.get("model", "GigaChat")
    if "messages" in raw_body and "choices" not in raw_body:
        return response_processor.process_response_v2(
            SimpleNamespace(model_dump=lambda **_: raw_body),
            model,
            str(response_id),
            request_data=request_body,
        )
    return response_processor.process_response(
        SimpleNamespace(model_dump=lambda **_: raw_body),
        model,
        str(response_id),
        request_data=request_body,
    )


def _transform_responses_batch_result(
    raw_body: Any,
    response_processor: Any,
    response_id: str,
    request_body: dict[str, Any],
) -> Any:
    if isinstance(raw_body, dict) and raw_body.get("object") == "response":
        return raw_body
    if not isinstance(raw_body, dict):
        return raw_body
    model = request_body.get("model", "GigaChat")
    if "messages" in raw_body and "choices" not in raw_body:
        return response_processor.process_response_api_v2(
            request_body,
            SimpleNamespace(model_dump=lambda **_: raw_body),
            model,
            str(response_id),
        )
    return response_processor.process_response_api(
        request_body,
        SimpleNamespace(model_dump=lambda **_: raw_body),
        model,
        str(response_id),
    )


def extract_batch_result_body(row: dict[str, Any]) -> Any:
    """Extract the response payload body from a raw batch output row."""
    response = row.get("response")
    if isinstance(response, dict):
        return response.get("body", response)
    if "result" in row:
        return row["result"]
    if "body" in row:
        return row["body"]
    return row


def _extract_batch_status_code(row: dict[str, Any]) -> int:
    response = row.get("response")
    if isinstance(response, dict):
        return int(response.get("status_code", 200))
    return 200


def _batch_line_error(line_number: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": f"Invalid batch input on line {line_number}: {message}",
                "type": "invalid_request_error",
                "param": "input_file_id",
                "code": None,
            }
        },
    )


def parse_jsonl(content: bytes) -> list[dict[str, Any]]:
    """Parse a UTF-8 JSONL payload into a list of objects."""
    rows: list[dict[str, Any]] = []
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _batch_line_error(1, "Input file must be UTF-8 encoded JSONL.") from exc

    for line_number, raw_line in enumerate(decoded.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _batch_line_error(line_number, f"Invalid JSON: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise _batch_line_error(line_number, "Each JSONL line must be an object.")
        rows.append(parsed)
    return rows
