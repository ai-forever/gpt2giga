"""Attachment models and storage for the Unified Harness cockpit."""

from gpt2giga_harness.attachments.limits import (
    AttachmentLimits,
    AttachmentValidationError,
    limits_from_project_settings,
)
from gpt2giga_harness.attachments.models import (
    AttachmentKind,
    AttachmentRenderPlan,
    HarnessAttachment,
    attachment_from_dict,
    attachment_to_dict,
    render_plan_from_dict,
    render_plan_to_dict,
)
from gpt2giga_harness.attachments.renderers import (
    render_attachments_for_harness,
    render_for_claude_code,
    render_for_codex_cli,
    render_for_direct_chat,
    render_for_echo,
    render_for_gemini_cli,
)
from gpt2giga_harness.attachments.store import (
    AttachmentNotFoundError,
    AttachmentSessionNotFoundError,
    FilesystemAttachmentStore,
)

__all__ = [
    "AttachmentKind",
    "AttachmentLimits",
    "AttachmentNotFoundError",
    "AttachmentRenderPlan",
    "AttachmentSessionNotFoundError",
    "AttachmentValidationError",
    "FilesystemAttachmentStore",
    "HarnessAttachment",
    "attachment_from_dict",
    "attachment_to_dict",
    "limits_from_project_settings",
    "render_attachments_for_harness",
    "render_for_claude_code",
    "render_for_codex_cli",
    "render_for_direct_chat",
    "render_for_echo",
    "render_for_gemini_cli",
    "render_plan_from_dict",
    "render_plan_to_dict",
]
