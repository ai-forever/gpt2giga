"""Helpers for applying attachment render plans inside harnesses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gpt2giga.harness.types import HarnessEvent, HarnessRequest, redact_secrets


def request_render_plan(request: HarnessRequest) -> Mapping[str, Any]:
    """Return the attachment render plan from the typed field or legacy extra."""
    if isinstance(request.attachment_render_plan, Mapping):
        return dict(request.attachment_render_plan)
    value = request.extra.get("attachment_render_plan")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def prompt_with_attachments(request: HarnessRequest) -> str:
    """Return the request prompt with rendered attachment prompt blocks applied."""
    plan = request_render_plan(request)
    if not plan:
        return request.prompt
    return _join_text(
        _text(plan.get("prompt_prefix")),
        request.prompt,
        _text(plan.get("prompt_suffix")),
    )


def cli_args_from_attachments(request: HarnessRequest) -> tuple[str, ...]:
    """Return safe CLI args supplied by an attachment renderer."""
    plan = request_render_plan(request)
    args = plan.get("cli_args", ())
    if not isinstance(args, list | tuple):
        return ()
    return tuple(str(item) for item in redact_secrets(list(args)))


def attachment_warnings(request: HarnessRequest) -> tuple[str, ...]:
    """Return user-facing attachment rendering warnings."""
    plan = request_render_plan(request)
    warnings = plan.get("warnings", ())
    if not isinstance(warnings, list | tuple):
        return ()
    return tuple(str(item) for item in redact_secrets(list(warnings)))


def attachment_raw_metadata(request: HarnessRequest) -> dict[str, Any]:
    """Return redacted attachment metadata suitable for harness raw output."""
    payload: dict[str, Any] = {}
    if request.attachments:
        payload["attachments"] = [
            dict(attachment) for attachment in request.attachments
        ]
    plan = request_render_plan(request)
    if plan:
        payload["attachment_render_plan"] = dict(redact_secrets(dict(plan)))
    warnings = attachment_warnings(request)
    if warnings:
        payload["attachment_warnings"] = list(warnings)
    return payload


def attachment_warning_events(request: HarnessRequest) -> tuple[HarnessEvent, ...]:
    """Return normalized events for attachment render warnings."""
    return tuple(
        HarnessEvent(
            type="attachment_warning",
            message=warning,
            payload={"warning": warning},
        )
        for warning in attachment_warnings(request)
    )


def _join_text(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(redact_secrets(str(value))).strip()
