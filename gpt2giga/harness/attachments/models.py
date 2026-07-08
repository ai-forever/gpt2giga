"""Normalized attachment models for the Unified Harness cockpit."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class AttachmentKind(str, Enum):
    """Attachment categories understood by harness renderers."""

    IMAGE = "image"
    TEXT = "text"
    DOCUMENT = "document"
    BINARY = "binary"
    WORKSPACE_FILE = "workspace_file"


@dataclass(frozen=True)
class HarnessAttachment:
    """One durable attachment record associated with a harness session."""

    id: str
    session_id: str
    project_id: str | None
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    source: str
    storage_path: str | None = None
    workspace_path: str | None = None
    thumbnail_path: str | None = None
    extracted_text_path: str | None = None
    created_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttachmentRenderPlan:
    """Inspectable plan for passing attachments to a selected harness."""

    prompt_prefix: str = ""
    prompt_suffix: str = ""
    content_parts: tuple[Mapping[str, Any], ...] = ()
    cli_args: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def attachment_to_dict(attachment: HarnessAttachment) -> dict[str, Any]:
    """Serialize an attachment for JSONL storage and API responses."""
    return {
        "id": attachment.id,
        "session_id": attachment.session_id,
        "project_id": attachment.project_id,
        "kind": attachment.kind,
        "filename": attachment.filename,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "sha256": attachment.sha256,
        "source": attachment.source,
        "storage_path": attachment.storage_path,
        "workspace_path": attachment.workspace_path,
        "thumbnail_path": attachment.thumbnail_path,
        "extracted_text_path": attachment.extracted_text_path,
        "created_at": attachment.created_at,
        "metadata": dict(attachment.metadata),
    }


def attachment_from_dict(data: Mapping[str, Any]) -> HarnessAttachment:
    """Parse an attachment from JSON-compatible data."""
    return HarnessAttachment(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        project_id=_optional_text(data.get("project_id")),
        kind=str(data.get("kind") or AttachmentKind.BINARY.value),
        filename=str(data.get("filename") or "attachment"),
        mime_type=str(data.get("mime_type") or "application/octet-stream"),
        size_bytes=_int(data.get("size_bytes")),
        sha256=str(data.get("sha256") or ""),
        source=str(data.get("source") or "upload"),
        storage_path=_optional_text(data.get("storage_path")),
        workspace_path=_optional_text(data.get("workspace_path")),
        thumbnail_path=_optional_text(data.get("thumbnail_path")),
        extracted_text_path=_optional_text(data.get("extracted_text_path")),
        created_at=str(data.get("created_at") or ""),
        metadata=_mapping(data.get("metadata")),
    )


def render_plan_to_dict(plan: AttachmentRenderPlan) -> dict[str, Any]:
    """Serialize a render plan for tests and future inspector responses."""
    return {
        "prompt_prefix": plan.prompt_prefix,
        "prompt_suffix": plan.prompt_suffix,
        "content_parts": [dict(part) for part in plan.content_parts],
        "cli_args": list(plan.cli_args),
        "warnings": list(plan.warnings),
        "metadata": dict(plan.metadata),
    }


def render_plan_from_dict(data: Mapping[str, Any]) -> AttachmentRenderPlan:
    """Parse a render plan from JSON-compatible data."""
    content_parts = data.get("content_parts", ())
    cli_args = data.get("cli_args", ())
    warnings = data.get("warnings", ())
    return AttachmentRenderPlan(
        prompt_prefix=str(data.get("prompt_prefix") or ""),
        prompt_suffix=str(data.get("prompt_suffix") or ""),
        content_parts=tuple(
            dict(part) for part in content_parts if isinstance(part, Mapping)
        ),
        cli_args=tuple(str(item) for item in cli_args),
        warnings=tuple(str(item) for item in warnings),
        metadata=_mapping(data.get("metadata")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
