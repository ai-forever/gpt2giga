"""Per-harness attachment render plans for inspectable runs."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from gpt2giga_harness.attachments.models import (
    AttachmentKind,
    AttachmentRenderPlan,
    HarnessAttachment,
    attachment_to_dict,
)
from gpt2giga_harness.attachments.store import (
    FilesystemAttachmentStore,
)
from gpt2giga_harness.types import redact_secrets

DEFAULT_INLINE_TEXT_LIMIT = 200 * 1024


def render_attachments_for_harness(
    harness_id: str,
    attachments: Iterable[HarnessAttachment],
    store: FilesystemAttachmentStore,
    *,
    prompt: str = "",
    inline_text_limit: int = DEFAULT_INLINE_TEXT_LIMIT,
) -> AttachmentRenderPlan:
    """Return the inspectable render plan for one harness id."""
    renderers: dict[str, Callable[..., AttachmentRenderPlan]] = {
        "echo": render_for_echo,
        "direct-chat": render_for_direct_chat,
        "codex-cli": render_for_codex_cli,
        "claude-code": render_for_claude_code,
        "gemini-cli": render_for_gemini_cli,
    }
    renderer = renderers.get(harness_id)
    if renderer is None:
        return _plan(
            warnings=(f"{harness_id} has no attachment renderer.",),
            metadata={
                "transport": "unsupported",
                "attachments": [_summary(attachment) for attachment in attachments],
            },
        )
    return renderer(
        tuple(attachments),
        store,
        prompt=prompt,
        inline_text_limit=inline_text_limit,
    )


def render_for_echo(
    attachments: Iterable[HarnessAttachment],
    store: FilesystemAttachmentStore | None = None,
    *,
    prompt: str = "",
    inline_text_limit: int = DEFAULT_INLINE_TEXT_LIMIT,
) -> AttachmentRenderPlan:
    """Render metadata-only attachments for the local echo harness."""
    del store, prompt, inline_text_limit
    attachment_list = tuple(attachments)
    return _plan(
        metadata={
            "transport": "metadata_only",
            "attachments": [_summary(attachment) for attachment in attachment_list],
            "deliveries": [
                _delivery(attachment, transport="metadata_only")
                for attachment in attachment_list
            ],
        }
    )


def render_for_direct_chat(
    attachments: Iterable[HarnessAttachment],
    store: FilesystemAttachmentStore,
    *,
    prompt: str = "",
    inline_text_limit: int = DEFAULT_INLINE_TEXT_LIMIT,
) -> AttachmentRenderPlan:
    """Render OpenAI-style content parts and inline text for direct chat."""
    attachment_list = tuple(attachments)
    content_parts: list[Mapping[str, Any]] = []
    if prompt:
        content_parts.append({"type": "text", "text": prompt})
    prompt_blocks: list[str] = []
    warnings: list[str] = []
    deliveries: list[dict[str, Any]] = []
    for attachment in attachment_list:
        kind = _effective_kind(attachment)
        if kind == AttachmentKind.IMAGE.value and attachment.storage_path:
            data = store.read_blob(attachment.id)
            encoded = base64.b64encode(data).decode("ascii")
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{attachment.mime_type};base64,{encoded}"
                    },
                }
            )
            deliveries.append(
                _delivery(
                    attachment,
                    transport="openai_content_parts",
                    rich=True,
                    surfaces=("headless",),
                )
            )
            continue
        if kind == AttachmentKind.TEXT.value:
            block, warning = _inline_text_block(
                attachment,
                store,
                inline_text_limit=inline_text_limit,
            )
            if block:
                prompt_blocks.append(block)
            if warning:
                warnings.append(warning)
            deliveries.append(
                _delivery(
                    attachment,
                    transport="inline_text",
                    surfaces=("headless",),
                )
            )
            continue
        if attachment.kind == AttachmentKind.WORKSPACE_FILE.value:
            prompt_blocks.append(_workspace_reference(attachment))
            warnings.append(
                f"{attachment.filename} is referenced by workspace path only."
            )
            deliveries.append(
                _delivery(
                    attachment,
                    transport="prompt_path_reference",
                    surfaces=("headless",),
                )
            )
            continue
        warnings.append(
            f"{attachment.filename} is {kind}; direct-chat will use metadata only."
        )
        deliveries.append(
            _delivery(
                attachment,
                transport="metadata_only",
                surfaces=("headless",),
            )
        )
    return _plan(
        prompt_prefix="\n\n".join(prompt_blocks),
        content_parts=tuple(content_parts),
        warnings=tuple(warnings),
        metadata={
            "transport": "openai_content_parts",
            "attachments": [_summary(attachment) for attachment in attachment_list],
            "content_part_count": len(content_parts),
            "deliveries": deliveries,
        },
    )


def render_for_codex_cli(
    attachments: Iterable[HarnessAttachment],
    store: FilesystemAttachmentStore | None = None,
    *,
    prompt: str = "",
    inline_text_limit: int = DEFAULT_INLINE_TEXT_LIMIT,
) -> AttachmentRenderPlan:
    """Render images as CLI attachments and files as prompt path references."""
    del store, prompt, inline_text_limit
    attachment_list = tuple(attachments)
    referenced_files: list[HarnessAttachment] = []
    image_paths: list[str] = []
    warnings: list[str] = []
    deliveries: list[dict[str, Any]] = []
    for attachment in attachment_list:
        if _effective_kind(attachment) != AttachmentKind.IMAGE.value:
            referenced_files.append(attachment)
            deliveries.append(_path_delivery(attachment))
            continue
        image_path = _attachment_path(attachment)
        if image_path:
            image_paths.append(image_path)
            deliveries.append(
                _delivery(
                    attachment,
                    transport="cli_image_flag",
                    rich=True,
                    required_cli_capabilities=("--image",),
                    surfaces=("headless_one_shot", "native"),
                )
            )
            continue
        referenced_files.append(attachment)
        deliveries.append(_path_delivery(attachment))
        warnings.append(
            f"{attachment.filename} has no readable path for the Codex CLI image flag."
        )
    prefix, reference_warnings = _agent_reference_prefix(
        tuple(referenced_files),
        workspace_prefix="@",
        uploaded_label="Local attachment path",
        image_warning="Codex CLI will receive this image as a path reference only.",
        document_warning=(
            "Codex CLI will receive this document as a path reference only."
        ),
    )
    warnings.extend(reference_warnings)
    cli_args = tuple(
        item for image_path in image_paths for item in ("--image", image_path)
    )
    if image_paths and referenced_files:
        transport = "cli_image_flag_and_prompt_path_reference"
    elif image_paths:
        transport = "cli_image_flag"
    else:
        transport = "prompt_path_reference"
    return _plan(
        prompt_prefix=prefix,
        cli_args=cli_args,
        warnings=tuple(warnings),
        metadata={
            "transport": transport,
            "attachments": [_summary(attachment) for attachment in attachment_list],
            "image_count": len(image_paths),
            "deliveries": deliveries,
            "required_cli_capabilities": ["--image"] if image_paths else [],
        },
    )


def render_for_claude_code(
    attachments: Iterable[HarnessAttachment],
    store: FilesystemAttachmentStore | None = None,
    *,
    prompt: str = "",
    inline_text_limit: int = DEFAULT_INLINE_TEXT_LIMIT,
) -> AttachmentRenderPlan:
    """Render prompt and at-file references for Claude Code."""
    del store, prompt, inline_text_limit
    attachment_list = tuple(attachments)
    prefix, warnings = _agent_reference_prefix(
        attachment_list,
        workspace_prefix="@",
        uploaded_label="Local attachment path",
        image_warning="Claude Code will receive this attachment as a path reference.",
        document_warning=(
            "Claude Code will receive this document as a path reference only."
        ),
    )
    return _plan(
        prompt_prefix=prefix,
        warnings=tuple(warnings),
        metadata={
            "transport": "at_file_reference",
            "attachments": [_summary(attachment) for attachment in attachment_list],
            "deliveries": [
                _path_delivery(attachment) for attachment in attachment_list
            ],
        },
    )


def render_for_gemini_cli(
    attachments: Iterable[HarnessAttachment],
    store: FilesystemAttachmentStore | None = None,
    *,
    prompt: str = "",
    inline_text_limit: int = DEFAULT_INLINE_TEXT_LIMIT,
) -> AttachmentRenderPlan:
    """Render at-file references for Gemini CLI."""
    del store, prompt, inline_text_limit
    attachment_list = tuple(attachments)
    prefix, warnings = _agent_reference_prefix(
        attachment_list,
        workspace_prefix="@",
        uploaded_label="Local attachment path",
        image_warning="Gemini CLI will receive this image as a path reference only.",
        document_warning=(
            "Gemini CLI will receive this document as a path reference only."
        ),
    )
    return _plan(
        prompt_prefix=prefix,
        warnings=tuple(warnings),
        metadata={
            "transport": "at_file_reference",
            "attachments": [_summary(attachment) for attachment in attachment_list],
            "deliveries": [
                _path_delivery(attachment) for attachment in attachment_list
            ],
        },
    )


def _agent_reference_prefix(
    attachments: tuple[HarnessAttachment, ...],
    *,
    workspace_prefix: str,
    uploaded_label: str,
    image_warning: str,
    document_warning: str,
) -> tuple[str, list[str]]:
    lines: list[str] = []
    warnings: list[str] = []
    if attachments:
        lines.append("Attachments:")
    for attachment in attachments:
        if attachment.kind == AttachmentKind.WORKSPACE_FILE.value:
            reference = f"{workspace_prefix}{attachment.workspace_path}"
            lines.append(
                f"- {reference} ({attachment.mime_type}, {attachment.size_bytes} bytes)"
            )
            continue
        path = _local_path(attachment)
        lines.append(
            f"- {uploaded_label}: {path} ({attachment.filename}, "
            f"{attachment.mime_type}, {attachment.size_bytes} bytes)"
        )
        if _effective_kind(attachment) == AttachmentKind.IMAGE.value:
            warnings.append(image_warning)
        elif _effective_kind(attachment) == AttachmentKind.DOCUMENT.value:
            warnings.append(document_warning)
    return "\n".join(lines), warnings


def _inline_text_block(
    attachment: HarnessAttachment,
    store: FilesystemAttachmentStore,
    *,
    inline_text_limit: int,
) -> tuple[str, str | None]:
    payload = _read_attachment_text(attachment, store)
    warning = None
    if len(payload.encode("utf-8")) > inline_text_limit:
        encoded = payload.encode("utf-8")[:inline_text_limit]
        payload = encoded.decode("utf-8", errors="replace")
        warning = f"{attachment.filename} was truncated at {inline_text_limit} bytes."
    redacted = str(redact_secrets(payload))
    fence = _fence_language(attachment.filename)
    return (
        f"Attachment {attachment.filename} ({attachment.mime_type}):\n"
        f"```{fence}\n{redacted}\n```",
        warning,
    )


def _read_attachment_text(
    attachment: HarnessAttachment,
    store: FilesystemAttachmentStore,
) -> str:
    if attachment.storage_path:
        data = store.read_blob(attachment.id)
    else:
        path = _workspace_path(attachment)
        data = path.read_bytes()
    return data.decode("utf-8", errors="replace")


def _workspace_reference(attachment: HarnessAttachment) -> str:
    return (
        f"Workspace attachment {attachment.filename}: "
        f"@{attachment.workspace_path or attachment.filename}"
    )


def _workspace_path(attachment: HarnessAttachment) -> Path:
    root = Path(str(attachment.metadata.get("workspace_root") or "")).expanduser()
    relative = attachment.workspace_path or attachment.filename
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    resolved.relative_to(resolved_root)
    return resolved


def _local_path(attachment: HarnessAttachment) -> str:
    if attachment.storage_path:
        return str(Path(attachment.storage_path).expanduser().resolve())
    if attachment.workspace_path:
        return f"@{attachment.workspace_path}"
    return attachment.filename


def _attachment_path(attachment: HarnessAttachment) -> str:
    if attachment.storage_path:
        return str(Path(attachment.storage_path).expanduser().resolve())
    if attachment.workspace_path and attachment.metadata.get("workspace_root"):
        return str(_workspace_path(attachment))
    return ""


def _effective_kind(attachment: HarnessAttachment) -> str:
    if attachment.kind == AttachmentKind.WORKSPACE_FILE.value:
        detected = attachment.metadata.get("detected_kind")
        if isinstance(detected, str) and detected:
            return detected
    return attachment.kind


def _path_delivery(attachment: HarnessAttachment) -> dict[str, Any]:
    transport = (
        "at_file_reference"
        if attachment.kind == AttachmentKind.WORKSPACE_FILE.value
        else "prompt_path_reference"
    )
    return _delivery(
        attachment,
        transport=transport,
        surfaces=("headless", "headless_one_shot", "structured_thread", "native"),
    )


def _delivery(
    attachment: HarnessAttachment,
    *,
    transport: str,
    rich: bool = False,
    required_cli_capabilities: tuple[str, ...] = (),
    surfaces: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "attachment_id": attachment.id,
        "kind": _effective_kind(attachment),
        "transport": transport,
        "rich": rich,
        "required_cli_capabilities": list(required_cli_capabilities),
        "surfaces": list(surfaces),
    }


def _summary(attachment: HarnessAttachment) -> dict[str, Any]:
    payload = attachment_to_dict(attachment)
    payload.pop("storage_path", None)
    return payload


def _fence_language(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix if suffix in {"json", "md", "py", "sh", "toml", "txt", "yaml"} else ""


def _plan(
    *,
    prompt_prefix: str = "",
    prompt_suffix: str = "",
    content_parts: tuple[Mapping[str, Any], ...] = (),
    cli_args: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> AttachmentRenderPlan:
    return AttachmentRenderPlan(
        prompt_prefix=str(redact_secrets(prompt_prefix)),
        prompt_suffix=str(redact_secrets(prompt_suffix)),
        content_parts=tuple(redact_secrets(list(content_parts))),
        cli_args=tuple(str(item) for item in redact_secrets(list(cli_args))),
        warnings=tuple(str(item) for item in redact_secrets(list(warnings))),
        metadata=dict(redact_secrets(dict(metadata or {}))),
    )
