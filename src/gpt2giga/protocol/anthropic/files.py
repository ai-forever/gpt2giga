"""Anthropic file metadata projection and explicit shared-route dispatch."""

from datetime import datetime, timezone

from fastapi import Request
from gpt2giga.constants import SUPPORTED_TEXT_MIME_TYPES


def is_anthropic_files(request: Request) -> bool:
    """Select Claude Files only from explicit protocol headers."""
    return bool(
        request.headers.get("anthropic-version")
        or request.headers.get("anthropic-beta")
    )


def anthropic_file(metadata: dict) -> dict:
    """Project only fields whose lifecycle the gateway implements."""
    return {
        "id": metadata["id"],
        "type": "file",
        "filename": metadata["filename"],
        "size_bytes": metadata["bytes"],
        "mime_type": metadata.get("mime_type", "application/octet-stream"),
        "created_at": datetime.fromtimestamp(
            metadata.get("created_at") or 0, timezone.utc
        )
        .isoformat()
        .replace("+00:00", "Z"),
        "downloadable": bool(metadata.get("downloadable", False)),
    }


async def resolve_anthropic_file_references(request: Request, data: dict) -> None:
    """Validate ownership and modality before converters emit native attachments."""
    from gpt2giga.app_state import get_resource_owner, get_resource_store
    from gpt2giga.common.client_params import ClientCompatibilityError
    from gpt2giga.common.files import file_not_found

    for message in data.get("messages", []):
        if not isinstance(message, dict) or not isinstance(
            message.get("content"), list
        ):
            continue
        for block in message["content"]:
            if not isinstance(block, dict) or block.get("type") not in {
                "document",
                "image",
            }:
                continue
            source = block.get("source", {})
            if not isinstance(source, dict) or source.get("type") != "file":
                continue
            if message.get("role") != "user":
                raise ClientCompatibilityError(
                    "File references require a user message.",
                    provider="anthropic",
                    param="messages",
                )
            file_id = source.get("file_id")
            if not isinstance(file_id, str) or not file_id:
                raise ClientCompatibilityError(
                    "A file_id is required.", provider="anthropic", param="messages"
                )
            resource = await get_resource_store(request).get(
                get_resource_owner(request), "file", file_id
            )
            if resource is None:
                raise file_not_found()
            metadata = resource.metadata
            mime = metadata.get("mime_type", "")
            if metadata.get("local") or not metadata.get("upstream_id"):
                raise ClientCompatibilityError(
                    "Batch files cannot be used as document attachments.",
                    provider="anthropic",
                    param="messages",
                )
            if (block["type"] == "image") != mime.startswith("image/"):
                raise ClientCompatibilityError(
                    "File MIME type does not match the content block.",
                    provider="anthropic",
                    param="messages",
                )
            if block["type"] == "document" and mime not in SUPPORTED_TEXT_MIME_TYPES:
                raise ClientCompatibilityError(
                    "The file MIME type is not supported as a document.",
                    provider="anthropic",
                    param="messages",
                )
            source["file_id"] = metadata["upstream_id"]
