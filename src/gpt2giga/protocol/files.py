"""Public file metadata serialization shared by resource handlers."""

from typing import Optional

from gpt2giga.protocol.batches import infer_openai_file_purpose


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
