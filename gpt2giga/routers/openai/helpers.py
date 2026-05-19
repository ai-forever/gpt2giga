"""Shared helpers for OpenAI-compatible API routes."""

from typing import Any, Optional

from fastapi import Request

from gpt2giga.app_state import get_batch_store, get_gigachat_client
from gpt2giga.common.tools import convert_tool_to_giga_functions
from gpt2giga.protocol.batches import infer_openai_file_purpose


def _paginate_items(
    items: list, after: Optional[str], limit: Optional[int]
) -> tuple[list, bool]:
    """Apply simple cursor pagination."""
    if after:
        for index, item in enumerate(items):
            if item.get("id") == after:
                items = items[index + 1 :]
                break
    if limit is None:
        return items, False
    return items[:limit], len(items) > limit


def _serialize_file_object(file_obj, stored_metadata: Optional[dict] = None) -> dict:
    """Normalize a GigaChat file object into the OpenAI-compatible response shape."""
    stored_metadata = stored_metadata or {}
    purpose = infer_openai_file_purpose(
        getattr(file_obj, "purpose", None), stored_metadata.get("purpose")
    )
    return {
        "id": getattr(file_obj, "id_", ""),
        "object": "file",
        "bytes": getattr(file_obj, "bytes_", 0),
        "created_at": getattr(file_obj, "created_at", None),
        "filename": getattr(file_obj, "filename", ""),
        "purpose": purpose,
        "status": stored_metadata.get("status", "processed"),
        "expires_at": stored_metadata.get("expires_at"),
        "status_details": stored_metadata.get("status_details"),
    }


def populate_giga_functions(data: dict, logger) -> None:
    """Populate GigaChat-compatible function definitions when tools are present."""
    if "tools" not in data and "functions" not in data:
        return
    data["functions"] = convert_tool_to_giga_functions(data)
    if logger:
        logger.debug(f"Functions count: {len(data['functions'])}")


def resolve_response_model(
    requested_model: str, chat_messages: Any, config: Any
) -> str:
    """Resolve the model name that should be reported to OpenAI-compatible clients."""
    payload_model = (
        chat_messages.get("model")
        if isinstance(chat_messages, dict)
        else getattr(chat_messages, "model", None)
    )
    if payload_model:
        return str(payload_model)

    configured_model = getattr(
        getattr(config, "gigachat_settings", None), "model", None
    )
    if configured_model:
        return str(configured_model)

    return requested_model


async def _load_batch_output_content(request: Request, file_id: str) -> bytes:
    """Load file content and post-process batch output files when needed."""
    giga_client = get_gigachat_client(request)
    file_response = await giga_client.aget_file_content(file_id=file_id)
    batch_store = get_batch_store(request)
    matching_batch = next(
        (
            meta
            for meta in batch_store.values()
            if meta.get("output_file_id") == file_id
        ),
        None,
    )
    if matching_batch:
        input_file = await giga_client.aget_file_content(
            file_id=matching_batch["input_file_id"]
        )
        from gpt2giga.protocol.batches import transform_batch_output_file

        return await transform_batch_output_file(
            file_response.content,
            batch_metadata=matching_batch,
            input_content_b64=input_file.content,
            response_processor=request.app.state.response_processor,
        )

    import base64

    return base64.b64decode(file_response.content)
