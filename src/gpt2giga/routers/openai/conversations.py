"""Opt-in durable OpenAI Conversations over the shared resource store."""

import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from gpt2giga.app_state import get_resource_store
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.openai import conversation_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_CONVERSATIONS
from gpt2giga.common.response_storage import (
    owned_resource,
    paged_items,
    require_gateway_storage,
    supported_items,
    response_resource_owner,
)

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_CONVERSATIONS])


def _object(resource):
    return {
        "id": resource.public_id,
        "object": "conversation",
        "created_at": resource.metadata["created_at"],
        "metadata": resource.metadata.get("metadata", {}),
    }


def _metadata(value):
    if value is None:
        return {}
    if (
        not isinstance(value, dict)
        or len(value) > 16
        or any(
            not isinstance(k, str)
            or len(k) > 64
            or not isinstance(v, str)
            or len(v) > 512
            for k, v in value.items()
        )
    ):
        raise HTTPException(
            400,
            detail="Metadata requires at most 16 string pairs (64 character keys, 512 character values).",
        )
    return value


@router.post("/conversations", openapi_extra=conversation_openapi_extra(items=True))
@exceptions_handler
async def create_conversation(request: Request):
    """Create a conversation with supported textual/function items."""
    require_gateway_storage(request)
    data = await read_request_json(request)
    items = supported_items(data.get("items", []))
    resource = await get_resource_store(request).put(
        response_resource_owner(request),
        "conversation",
        "conv_g2g_" + uuid.uuid4().hex,
        {
            "created_at": int(time.time()),
            "metadata": _metadata(data.get("metadata")),
            "items": items,
            "revision": 0,
        },
    )
    return _object(resource)


@router.get("/conversations/{conversation_id}")
@exceptions_handler
async def retrieve_conversation(conversation_id: str, request: Request):
    """Retrieve owner-scoped conversation metadata."""
    require_gateway_storage(request)
    return _object(await owned_resource(request, "conversation", conversation_id))


@router.post(
    "/conversations/{conversation_id}", openapi_extra=conversation_openapi_extra()
)
@exceptions_handler
async def update_conversation(conversation_id: str, request: Request):
    """Update conversation metadata without rewriting its history."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "conversation", conversation_id)
    data = await read_request_json(request)
    updated = await get_resource_store(request).update(
        response_resource_owner(request, resource),
        "conversation",
        conversation_id,
        {"metadata": _metadata(data.get("metadata"))},
    )
    if updated is None:
        raise HTTPException(404, detail="Conversation not found.")
    return _object(updated)


@router.delete("/conversations/{conversation_id}")
@exceptions_handler
async def delete_conversation(conversation_id: str, request: Request):
    """Delete a conversation and its items; snapshots remain independent."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "conversation", conversation_id)
    await get_resource_store(request).delete(
        response_resource_owner(request, resource), "conversation", conversation_id
    )
    return {"id": conversation_id, "object": "conversation.deleted", "deleted": True}


@router.get("/conversations/{conversation_id}/items")
@exceptions_handler
async def list_items(conversation_id: str, request: Request):
    """Page stored conversation items."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "conversation", conversation_id)
    return paged_items(request, resource.metadata["items"])


@router.post(
    "/conversations/{conversation_id}/items",
    openapi_extra=conversation_openapi_extra(items=True),
)
@exceptions_handler
async def create_items(conversation_id: str, request: Request):
    """Append supported items atomically."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "conversation", conversation_id)
    data = await read_request_json(request)
    items = supported_items(data.get("items", []))

    def append(metadata):
        existing_ids = {item["id"] for item in metadata["items"]}
        if any(item["id"] in existing_ids for item in items):
            raise HTTPException(400, detail="Duplicate item ID.")
        return {
            **metadata,
            "items": metadata["items"] + items,
            "revision": metadata["revision"] + 1,
        }

    updated = await get_resource_store(request).update(
        response_resource_owner(request, resource),
        "conversation",
        conversation_id,
        append,
    )
    if updated is None:
        raise HTTPException(404, detail="Conversation not found.")
    return {
        "object": "list",
        "data": items,
        "has_more": False,
        "first_id": items[0]["id"] if items else None,
        "last_id": items[-1]["id"] if items else None,
    }


@router.get("/conversations/{conversation_id}/items/{item_id}")
@exceptions_handler
async def retrieve_item(conversation_id: str, item_id: str, request: Request):
    """Retrieve one item without crossing conversation or owner boundaries."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "conversation", conversation_id)
    for item in resource.metadata["items"]:
        if item["id"] == item_id:
            return item
    raise HTTPException(404, detail="Item not found.")


@router.delete("/conversations/{conversation_id}/items/{item_id}")
@exceptions_handler
async def delete_item(conversation_id: str, item_id: str, request: Request):
    """Delete one item atomically and return the updated conversation."""
    require_gateway_storage(request)
    resource = await owned_resource(request, "conversation", conversation_id)

    def remove(metadata):
        items = [item for item in metadata["items"] if item["id"] != item_id]
        if len(items) == len(metadata["items"]):
            raise HTTPException(404, detail="Item not found.")
        return {**metadata, "items": items, "revision": metadata["revision"] + 1}

    updated = await get_resource_store(request).update(
        response_resource_owner(request, resource),
        "conversation",
        conversation_id,
        remove,
    )
    if updated is None:
        raise HTTPException(404, detail="Conversation not found.")
    return _object(updated)
