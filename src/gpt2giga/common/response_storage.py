"""Opt-in immutable Responses snapshots and durable conversation items."""

import json
import uuid
import codecs
from copy import deepcopy
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from gpt2giga.app_state import (
    get_resource_owner,
    get_resource_store,
    get_gigachat_model_catalog_profile_id,
)
from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.streaming_response import closing_stream
from gpt2giga.logger import rquid_context
from gpt2giga.storage.resources import ResourceConflictError, ResourceNotFoundError


def gateway_storage_enabled(request: Request) -> bool:
    """Keep native continuation semantics as the default."""
    config = getattr(request.app.state, "config", None)
    settings = getattr(config, "proxy_settings", None)
    return getattr(settings, "responses_storage_mode", "native") == "gateway"


def require_gateway_storage(request: Request) -> None:
    """Do not advertise native thread IDs as immutable response objects."""
    if not gateway_storage_enabled(request):
        raise HTTPException(
            501, detail="Enable gateway Responses storage for this operation."
        )


async def owned_resource(request: Request, kind: str, public_id: str):
    """Return a live owner-scoped resource or a non-enumerating 404."""
    owners = {get_resource_owner(request), response_resource_owner(request)}
    registry = getattr(request.app.state, "provider_registry", None)
    if registry is not None:
        owners.update(
            get_resource_owner(request, profile=profile.profile_id)
            for profile in registry.config.profiles
            if profile.provider_kind.value == "gigachat"
        )
    for owner in owners:
        resource = await get_resource_store(request).get(owner, kind, public_id)
        if resource is not None:
            owners_by_id = getattr(request.state, "response_resource_owners", {})
            owners_by_id[(kind, public_id)] = owner
            request.state.response_resource_owners = owners_by_id
            return resource
    raise HTTPException(404, detail="Resource not found.")


def response_resource_owner(request: Request, resource=None) -> str:
    """Use the selected native profile, or the verified owner of a retrieved resource."""
    if resource is not None:
        cached = getattr(request.state, "response_resource_owners", {})
        owner = cached.get((resource.kind, resource.public_id))
        if owner is not None:
            return owner
    return get_resource_owner(
        request, profile=getattr(request.state, "response_provider_profile", None)
    )


def supported_items(value, *, output: bool = False) -> list[dict]:
    """Validate a replayable text/function subset, retaining exact item fields."""
    if isinstance(value, str):
        value = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": value}],
            }
        ]
    if not isinstance(value, list):
        raise ClientCompatibilityError(
            "Items must be an array or textual input.", param="input"
        )
    items = deepcopy(value)
    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ClientCompatibilityError(
                "Each item must be an object.", param="input"
            )
        kind = item.get("type", "message")
        if kind == "message":
            role = item.get("role")
            if not isinstance(role, str) or role not in {
                "system",
                "developer",
                "user",
                "assistant",
            }:
                raise ClientCompatibilityError(
                    "Unsupported message role.", param="input"
                )
            content = item.get("content", "")
            if isinstance(content, str):
                content = [
                    {
                        "type": "output_text"
                        if item.get("role") == "assistant"
                        else "input_text",
                        "text": content,
                    }
                ]
            if not isinstance(content, list) or any(
                not isinstance(part, dict)
                or not isinstance(part.get("type"), str)
                or part["type"] not in {"input_text", "output_text", "text"}
                or not isinstance(part.get("text"), str)
                for part in content
            ):
                raise ClientCompatibilityError(
                    "Gateway storage supports textual message parts only.",
                    param="input",
                )
            item["content"] = content
        elif kind == "function_call":
            if not all(
                isinstance(item.get(key), str)
                for key in ("call_id", "name", "arguments")
            ):
                raise ClientCompatibilityError(
                    "Invalid function call item.", param="input"
                )
        elif kind == "function_call_output":
            if not isinstance(item.get("call_id"), str) or not isinstance(
                item.get("output"), str
            ):
                raise ClientCompatibilityError(
                    "Function outputs must be textual.", param="input"
                )
        else:
            raise ClientCompatibilityError(
                "This item type cannot be durably replayed.", param="input"
            )
        item.setdefault("type", kind)
        item.setdefault(
            "id", ("msg_g2g_" if kind == "message" else "item_g2g_") + uuid.uuid4().hex
        )
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id.strip() or len(item_id) > 256:
            raise ClientCompatibilityError("Invalid item ID.", param="input")
        if item_id in seen_ids:
            raise ClientCompatibilityError("Duplicate item ID.", param="input")
        seen_ids.add(item_id)
    return items


def paged_items(request: Request, items: list[dict]) -> dict:
    """Page a stable ordered item list using item IDs."""
    order = request.query_params.get("order", "asc")
    if order not in {"asc", "desc"}:
        raise HTTPException(400, detail="Invalid order.")
    items = list(reversed(items)) if order == "desc" else list(items)
    after = request.query_params.get("after")
    if after:
        indices = [index for index, item in enumerate(items) if item["id"] == after]
        if not indices:
            raise HTTPException(400, detail="Invalid item cursor.")
        items = items[indices[0] + 1 :]
    try:
        limit = int(request.query_params.get("limit", 100))
        if not 1 <= limit <= 100:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(400, detail="Invalid limit.") from exc
    selected = items[:limit]
    return {
        "object": "list",
        "data": selected,
        "has_more": len(items) > limit,
        "first_id": selected[0]["id"] if selected else None,
        "last_id": selected[-1]["id"] if selected else None,
    }


@dataclass
class SnapshotTurn:
    response_id: str
    input_items: list[dict]
    store: bool
    conversation_id: str | None = None
    revision: int | None = None
    conversation_owner: str | None = None


async def prepare_snapshot(
    request: Request, data: dict
) -> tuple[dict, SnapshotTurn | None]:
    """Replay snapshot context without continuing a mutable upstream thread."""
    previous = data.get("previous_response_id")
    if isinstance(previous, str) and previous.startswith("resp_g2g_"):
        # Resolve even in native mode so a gateway ID never becomes a thread ID.
        prior = await owned_resource(request, "response", previous)
    else:
        prior = None
    if not gateway_storage_enabled(request):
        if prior is not None:
            raise ClientCompatibilityError(
                "Gateway snapshots require gateway storage mode.",
                param="previous_response_id",
            )
        return data, None
    if previous is not None and not isinstance(previous, str):
        raise ClientCompatibilityError(
            "previous_response_id must be a string.", param="previous_response_id"
        )
    if data.get("store") is not None and not isinstance(data["store"], bool):
        raise ClientCompatibilityError("store must be a boolean.", param="store")
    if previous and data.get("conversation"):
        raise ClientCompatibilityError(
            "conversation and previous_response_id are mutually exclusive.",
            param="conversation",
        )
    if previous and prior is None:
        # Previously issued native IDs retain their original continuation path.
        return data, None
    for key in ("background",):
        if data.get(key):
            raise ClientCompatibilityError(
                "Background execution is not supported.", param=key
            )
    tools = data.get("tools") or []
    if not isinstance(tools, list) or any(
        not isinstance(tool, dict) or tool.get("type") != "function" for tool in tools
    ):
        raise ClientCompatibilityError(
            "Gateway snapshots support custom function tools only.", param="tools"
        )
    if data.get("reasoning") or data.get("include"):
        raise ClientCompatibilityError(
            "Gateway snapshots cannot preserve reasoning or included provider artifacts.",
            param="include",
        )
    items = supported_items(data.get("input", []))
    history = []
    conversation_id = data.get("conversation")
    if isinstance(conversation_id, dict):
        conversation_id = conversation_id.get("id")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ClientCompatibilityError(
                "conversation requires an ID.", param="conversation"
            )
    elif conversation_id is not None and (
        not isinstance(conversation_id, str) or not conversation_id.strip()
    ):
        raise ClientCompatibilityError("Invalid conversation ID.", param="conversation")
    revision = None
    conversation_owner = None
    if conversation_id:
        conversation = await owned_resource(request, "conversation", conversation_id)
        history = conversation.metadata["items"]
        revision = conversation.metadata["revision"]
        conversation_owner = response_resource_owner(request, conversation)
    elif prior is not None:
        history = prior.metadata["input_items"] + prior.metadata["response"]["output"]
    expanded = deepcopy(data)
    expanded["input"] = deepcopy(history) + items
    input_ids = [item["id"] for item in expanded["input"]]
    if len(set(input_ids)) != len(input_ids):
        raise ClientCompatibilityError(
            "Duplicate item ID in replay context.", param="input"
        )
    for key in ("store", "previous_response_id", "conversation"):
        expanded.pop(key, None)
    # Disable unrelated in-memory session stitching for this exact replay.
    request.state.gateway_snapshot = True
    turn = SnapshotTurn(
        "resp_g2g_" + uuid.uuid4().hex,
        expanded["input"],
        data.get("store", True) is not False,
        conversation_id,
        revision,
        conversation_owner,
    )
    return expanded, turn


async def _save_snapshot(request: Request, turn: SnapshotTurn, response: dict) -> None:
    if response.get("status") != "completed" or await request.is_disconnected():
        return
    try:
        output = supported_items(response.get("output", []), output=True)
    except ClientCompatibilityError as exc:
        raise HTTPException(
            502, detail="The upstream response contains unsupported stored output."
        ) from exc
    combined_ids = [item["id"] for item in turn.input_items + output]
    if len(set(combined_ids)) != len(combined_ids):
        raise HTTPException(
            502, detail="The upstream response contains duplicate item IDs."
        )
    response["output"] = output
    store, owner = get_resource_store(request), response_resource_owner(request)
    try:
        await store.commit_response(
            owner,
            turn.response_id,
            {
                "input_items": turn.input_items,
                "response": response,
                "provider_profile": getattr(
                    request.state, "response_provider_profile", None
                )
                or get_gigachat_model_catalog_profile_id(request),
            }
            if turn.store
            else None,
            conversation_id=turn.conversation_id,
            conversation_owner=turn.conversation_owner,
            expected_revision=turn.revision,
            conversation_items=turn.input_items + output,
        )
    except ResourceConflictError as exc:
        raise HTTPException(
            409,
            detail="Conversation changed during generation; retry with its current items.",
        ) from exc
    except ResourceNotFoundError as exc:
        raise HTTPException(404, detail="Conversation no longer exists.") from exc


async def finish_snapshot(request: Request, turn: SnapshotTurn | None, result):
    """Replace response IDs and persist only a confirmed completed response."""
    if turn is None:
        return result

    def project(response):
        response["id"] = turn.response_id
        response["store"] = turn.store
        if turn.conversation_id:
            response["conversation"] = {"id": turn.conversation_id}
        return response

    if isinstance(result, dict):
        project(result)
        await _save_snapshot(request, turn, result)
        return result
    if not isinstance(result, StreamingResponse):
        return result
    original = result.body_iterator

    async def projected_events():
        buffer = ""
        decoder = codecs.getincrementaldecoder("utf-8")()
        async with closing_stream(original):
            async for chunk in original:
                buffer += (
                    decoder.decode(chunk) if isinstance(chunk, bytes) else str(chunk)
                )
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    lines = frame.splitlines()
                    for index, line in enumerate(lines):
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        event = json.loads(line[6:])
                        if isinstance(event.get("response"), dict):
                            project(event["response"])
                        if "response_id" in event:
                            event["response_id"] = turn.response_id
                        if event.get("type") == "response.completed":
                            await _save_snapshot(request, turn, event["response"])
                        lines[index] = "data: " + json.dumps(event, ensure_ascii=False)
                    yield "\n".join(lines) + "\n\n"
            if buffer:
                yield buffer

    async def events():
        sequence = 0
        projected = projected_events()
        try:
            async with closing_stream(projected):
                async for frame in projected:
                    for line in frame.splitlines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            event = json.loads(line[6:])
                            sequence = event.get("sequence_number", sequence) + 1
                    yield frame
        except Exception:
            # Headers are already sent. Preserve the SSE contract and expose no
            # stored prompt, schema, SQL, filesystem path, or upstream details.
            event = {
                "type": "error",
                "code": "response_storage_error",
                "message": "The response could not be completed or stored.",
                "param": None,
                "sequence_number": sequence,
                "response_id": turn.response_id,
            }
            request_id = rquid_context.get()
            if request_id:
                event["request_id"] = request_id
            yield "event: error\ndata: " + json.dumps(event) + "\n\n"

    result.body_iterator = events()
    return result
