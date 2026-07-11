"""Local echo harness for UI and registry smoke tests."""

from __future__ import annotations

from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    attachment_warning_events,
)
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class EchoHarness(BaseHarness):
    """Return the prompt without touching the network."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="echo",
            title="Echo",
            kind="test",
            description="Local echo harness for tests and UI smoke checks",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_attachments=True,
            accepted_attachment_kinds=(
                "image",
                "text",
                "document",
                "binary",
                "workspace_file",
            ),
            attachment_transport=("metadata_only",),
            tags=("local", "test"),
        )

    def availability(self) -> Availability:
        return Availability.available("local harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        model = request.model or context.default_model
        attachment_summary = _attachment_summary(request)
        text = request.prompt
        if attachment_summary:
            text = f"{request.prompt}\n\nAttachments:\n{attachment_summary}"
        return HarnessResult(
            ok=True,
            text=text,
            raw={
                "model": model,
                "api_mode": request.api_mode.value,
                "capability": request.capability.value,
                "mode": request.mode,
                **attachment_raw_metadata(request),
            },
            events=(
                *attachment_warning_events(request),
                *_attachment_events(request),
            ),
            command=(
                "giga",
                "harness",
                "run",
                "echo",
                "--api-mode",
                request.api_mode.value,
                "--prompt",
                request.prompt,
            ),
        )


def _attachment_summary(request: HarnessRequest) -> str:
    lines: list[str] = []
    for attachment in request.attachments:
        filename = str(attachment.get("filename") or attachment.get("id") or "")
        kind = str(attachment.get("kind") or "attachment")
        mime_type = str(attachment.get("mime_type") or "application/octet-stream")
        size_bytes = int(attachment.get("size_bytes") or 0)
        if filename:
            lines.append(f"- {filename} ({kind}, {mime_type}, {size_bytes} bytes)")
    return "\n".join(lines)


def _attachment_events(request: HarnessRequest) -> tuple[HarnessEvent, ...]:
    return tuple(
        HarnessEvent(
            type="attachment",
            message=(
                "Echo received attachment "
                f"{attachment.get('filename') or attachment.get('id')}."
            ),
            payload={
                "id": attachment.get("id"),
                "kind": attachment.get("kind"),
                "filename": attachment.get("filename"),
            },
        )
        for attachment in request.attachments
    )
