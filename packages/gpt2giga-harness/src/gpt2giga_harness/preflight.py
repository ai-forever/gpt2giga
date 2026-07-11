"""Pre-run safety and context budget checks for Unified Harness runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

from gpt2giga_harness.attachments.limits import (
    AttachmentLimits,
    is_denied_path,
    is_git_ignored,
)
from gpt2giga_harness.attachments.models import HarnessAttachment
from gpt2giga_harness.project_memory import ProjectMemoryEntry
from gpt2giga_harness.sessions.models import HarnessMessage

SAMPLE_BYTES = 65536
LARGE_ATTACHMENT_WARNING_BYTES = 1_000_000
CONTEXT_TOKEN_WARNING = 120_000
MAX_IMAGE_ATTACHMENTS_WARNING = 8
DEFAULT_MAX_HISTORY_MESSAGES = 20

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_BLOCK = "block"

ACTION_CONTINUE = "continue"
ACTION_EXCLUDE_ATTACHMENT = "exclude_attachment"
ACTION_SEND_PATH_ONLY = "send_path_only"

PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL | re.IGNORECASE,
)
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    \b
    (
      api[_-]?key
      | access[_-]?token
      | auth[_-]?token
      | refresh[_-]?token
      | token
      | client[_-]?secret
      | credentials
      | password
      | secret
    )
    \b
    \s*[:=]\s*
    ["']?
    [A-Za-z0-9_./+~=-]{12,}
    """,
)
TOKEN_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{24,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


class PreflightBlockedError(ValueError):
    """Raised when a preflight report contains hard-block findings."""

    def __init__(self, report: "HarnessPreflightReport") -> None:
        self.report = report
        super().__init__(format_preflight_block_message(report))


@dataclass(frozen=True)
class HarnessPreflightFinding:
    """One safety or budget finding from pre-run preflight."""

    id: str
    severity: str
    code: str
    message: str
    subject: str | None = None
    attachment_id: str | None = None
    workspace_path: str | None = None
    actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextBudgetEstimate:
    """Inspectable context-size estimate for a pending run."""

    prompt_chars: int
    prompt_tokens: int
    project_memory_count: int
    project_memory_chars: int
    project_memory_tokens: int
    previous_message_count: int
    included_previous_message_count: int
    previous_message_chars: int
    previous_message_tokens: int
    attached_file_count: int
    attached_file_bytes: int
    image_count: int
    image_bytes: int
    attachment_tokens: int
    total_estimated_tokens: int
    max_history_messages: int
    truncation_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessPreflightReport:
    """Complete pre-run safety report."""

    ok: bool
    hard_block: bool
    max_severity: str
    findings: tuple[HarnessPreflightFinding, ...]
    context_budget: ContextBudgetEstimate


def build_preflight_report(
    *,
    prompt: str,
    workspace: str | None,
    previous_messages: tuple[HarnessMessage, ...] = (),
    attachments: tuple[HarnessAttachment, ...] = (),
    project_memory: tuple[ProjectMemoryEntry, ...] = (),
    data_dir: str | Path | None = None,
    limits: AttachmentLimits | None = None,
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES,
) -> HarnessPreflightReport:
    """Build a redacted pre-run safety and budget report."""
    attachment_limits = limits or AttachmentLimits()
    findings: list[HarnessPreflightFinding] = []
    _extend_findings(
        findings,
        _scan_text(
            prompt,
            subject="prompt",
            source_label="Prompt",
            actions=(),
        ),
    )
    for message in previous_messages:
        _extend_findings(
            findings,
            _scan_text(
                message.content,
                subject=f"history:{message.role}",
                source_label="Previous chat message",
                actions=(),
            ),
        )
    for memory in project_memory:
        _extend_findings(
            findings,
            _scan_text(
                memory.text,
                subject=f"memory:{memory.id}",
                source_label="Project memory",
                actions=(),
            ),
        )
    for attachment in attachments:
        _extend_findings(
            findings,
            _scan_attachment(
                attachment,
                workspace=workspace,
                data_dir=data_dir,
                limits=attachment_limits,
            ),
        )
    budget = estimate_context_budget(
        prompt=prompt,
        previous_messages=previous_messages,
        attachments=attachments,
        project_memory=project_memory,
        max_history_messages=max_history_messages,
    )
    _extend_findings(findings, _budget_findings(budget))
    findings = _with_stable_ids(findings)
    hard_block = any(finding.severity == SEVERITY_BLOCK for finding in findings)
    return HarnessPreflightReport(
        ok=not hard_block,
        hard_block=hard_block,
        max_severity=_max_severity(findings),
        findings=tuple(findings),
        context_budget=budget,
    )


def estimate_context_budget(
    *,
    prompt: str,
    previous_messages: tuple[HarnessMessage, ...] = (),
    attachments: tuple[HarnessAttachment, ...] = (),
    project_memory: tuple[ProjectMemoryEntry, ...] = (),
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES,
) -> ContextBudgetEstimate:
    """Estimate token and byte pressure for the next run."""
    prompt_chars = len(prompt)
    memory_chars = sum(len(memory.text) for memory in project_memory)
    history_messages = tuple(
        message
        for message in previous_messages
        if message.role in {"user", "assistant"} and message.content
    )
    included_history_limit = max(max_history_messages - 1, 0)
    included_history = history_messages[-included_history_limit:]
    previous_message_chars = sum(len(message.content) for message in included_history)
    attached_file_count = len(attachments)
    attached_file_bytes = sum(
        max(attachment.size_bytes, 0) for attachment in attachments
    )
    image_attachments = tuple(
        attachment for attachment in attachments if attachment.kind == "image"
    )
    image_bytes = sum(max(attachment.size_bytes, 0) for attachment in image_attachments)
    attachment_tokens = sum(
        _attachment_token_estimate(attachment) for attachment in attachments
    )
    truncation_warnings: list[str] = []
    if len(history_messages) > included_history_limit:
        truncated = len(history_messages) - included_history_limit
        truncation_warnings.append(
            f"{truncated} earlier chat message(s) will be omitted from the run context."
        )
    total_tokens = (
        _estimate_tokens(prompt_chars)
        + _estimate_tokens(memory_chars)
        + _estimate_tokens(previous_message_chars)
        + attachment_tokens
    )
    return ContextBudgetEstimate(
        prompt_chars=prompt_chars,
        prompt_tokens=_estimate_tokens(prompt_chars),
        project_memory_count=len(project_memory),
        project_memory_chars=memory_chars,
        project_memory_tokens=_estimate_tokens(memory_chars),
        previous_message_count=len(history_messages),
        included_previous_message_count=len(included_history),
        previous_message_chars=previous_message_chars,
        previous_message_tokens=_estimate_tokens(previous_message_chars),
        attached_file_count=attached_file_count,
        attached_file_bytes=attached_file_bytes,
        image_count=len(image_attachments),
        image_bytes=image_bytes,
        attachment_tokens=attachment_tokens,
        total_estimated_tokens=total_tokens,
        max_history_messages=max_history_messages,
        truncation_warnings=tuple(truncation_warnings),
    )


def preflight_report_to_dict(report: HarnessPreflightReport) -> dict[str, Any]:
    """Serialize a preflight report for API responses and run metadata."""
    return {
        "ok": report.ok,
        "hard_block": report.hard_block,
        "max_severity": report.max_severity,
        "findings": [
            {
                "id": finding.id,
                "severity": finding.severity,
                "code": finding.code,
                "message": finding.message,
                "subject": finding.subject,
                "attachment_id": finding.attachment_id,
                "workspace_path": finding.workspace_path,
                "actions": list(finding.actions),
                "metadata": dict(finding.metadata),
            }
            for finding in report.findings
        ],
        "context_budget": context_budget_to_dict(report.context_budget),
    }


def context_budget_to_dict(budget: ContextBudgetEstimate) -> dict[str, Any]:
    """Serialize a context budget estimate."""
    return {
        "prompt_chars": budget.prompt_chars,
        "prompt_tokens": budget.prompt_tokens,
        "project_memory_count": budget.project_memory_count,
        "project_memory_chars": budget.project_memory_chars,
        "project_memory_tokens": budget.project_memory_tokens,
        "previous_message_count": budget.previous_message_count,
        "included_previous_message_count": budget.included_previous_message_count,
        "previous_message_chars": budget.previous_message_chars,
        "previous_message_tokens": budget.previous_message_tokens,
        "attached_file_count": budget.attached_file_count,
        "attached_file_bytes": budget.attached_file_bytes,
        "image_count": budget.image_count,
        "image_bytes": budget.image_bytes,
        "attachment_tokens": budget.attachment_tokens,
        "total_estimated_tokens": budget.total_estimated_tokens,
        "max_history_messages": budget.max_history_messages,
        "truncation_warnings": list(budget.truncation_warnings),
    }


def format_preflight_block_message(report: HarnessPreflightReport) -> str:
    """Return a safe, content-free error message for blocked runs."""
    codes = sorted(
        {
            finding.code
            for finding in report.findings
            if finding.severity == SEVERITY_BLOCK
        }
    )
    suffix = ", ".join(codes) if codes else "blocked context"
    return (
        "Preflight blocked this run before invoking a harness. "
        f"Remove or exclude blocked context first ({suffix})."
    )


def _scan_attachment(
    attachment: HarnessAttachment,
    *,
    workspace: str | None,
    data_dir: str | Path | None,
    limits: AttachmentLimits,
) -> list[HarnessPreflightFinding]:
    findings: list[HarnessPreflightFinding] = []
    subject = _attachment_subject(attachment)
    path = attachment.workspace_path or attachment.filename
    if _is_env_path(path):
        findings.append(
            _finding(
                SEVERITY_BLOCK,
                "env_file_attachment",
                "Attachment points at an .env-style file.",
                subject=subject,
                attachment_id=attachment.id,
                workspace_path=attachment.workspace_path,
                actions=_attachment_actions(attachment),
            )
        )
    if is_denied_path(path, limits):
        findings.append(
            _finding(
                SEVERITY_BLOCK,
                "denied_attachment_path",
                "Attachment path matches the safety deny list.",
                subject=subject,
                attachment_id=attachment.id,
                workspace_path=attachment.workspace_path,
                actions=_attachment_actions(attachment),
            )
        )
    workspace_root = _attachment_workspace_root(attachment, workspace)
    if (
        workspace_root is not None
        and attachment.workspace_path
        and limits.respect_gitignore
        and is_git_ignored(Path(workspace_root), attachment.workspace_path)
    ):
        findings.append(
            _finding(
                SEVERITY_BLOCK,
                "ignored_workspace_attachment",
                "Attachment points at a git-ignored workspace file.",
                subject=subject,
                attachment_id=attachment.id,
                workspace_path=attachment.workspace_path,
                actions=_attachment_actions(attachment),
            )
        )
    if attachment.size_bytes > LARGE_ATTACHMENT_WARNING_BYTES:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                "large_attachment",
                "Attachment is large enough to pressure the context budget.",
                subject=subject,
                attachment_id=attachment.id,
                workspace_path=attachment.workspace_path,
                actions=_attachment_actions(attachment, include_continue=True),
                metadata={"size_bytes": attachment.size_bytes},
            )
        )
    sample = _attachment_sample(
        attachment,
        workspace_root=workspace_root,
        data_dir=data_dir,
    )
    if sample is None:
        return findings
    text = _decode_sample(sample)
    _extend_findings(
        findings,
        _scan_text(
            text,
            subject=subject,
            source_label="Attachment content",
            attachment_id=attachment.id,
            workspace_path=attachment.workspace_path,
            actions=_attachment_actions(attachment),
        ),
    )
    return findings


def _scan_text(
    text: str,
    *,
    subject: str,
    source_label: str,
    attachment_id: str | None = None,
    workspace_path: str | None = None,
    actions: tuple[str, ...] = (),
) -> list[HarnessPreflightFinding]:
    if not text:
        return []
    findings: list[HarnessPreflightFinding] = []
    sample = text[:SAMPLE_BYTES]
    if PRIVATE_KEY_RE.search(sample):
        findings.append(
            _finding(
                SEVERITY_BLOCK,
                "private_key_material",
                f"{source_label} contains private key material.",
                subject=subject,
                attachment_id=attachment_id,
                workspace_path=workspace_path,
                actions=actions,
            )
        )
    if CREDENTIAL_ASSIGNMENT_RE.search(sample):
        findings.append(
            _finding(
                SEVERITY_BLOCK,
                "credential_value",
                f"{source_label} contains a credential-looking value.",
                subject=subject,
                attachment_id=attachment_id,
                workspace_path=workspace_path,
                actions=actions,
            )
        )
    if any(pattern.search(sample) for pattern in TOKEN_VALUE_PATTERNS):
        findings.append(
            _finding(
                SEVERITY_BLOCK,
                "token_value",
                f"{source_label} contains a token-looking value.",
                subject=subject,
                attachment_id=attachment_id,
                workspace_path=workspace_path,
                actions=actions,
            )
        )
    return findings


def _budget_findings(
    budget: ContextBudgetEstimate,
) -> list[HarnessPreflightFinding]:
    findings: list[HarnessPreflightFinding] = []
    if budget.total_estimated_tokens > CONTEXT_TOKEN_WARNING:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                "context_budget_high",
                "Estimated context is high and may be truncated by the selected harness.",
                subject="context_budget",
                actions=(ACTION_CONTINUE,),
                metadata={"estimated_tokens": budget.total_estimated_tokens},
            )
        )
    for warning in budget.truncation_warnings:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                "history_truncation",
                warning,
                subject="history",
                actions=(ACTION_CONTINUE,),
            )
        )
    if budget.image_count > MAX_IMAGE_ATTACHMENTS_WARNING:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                "many_images",
                "Many images are attached to this run.",
                subject="attachments",
                actions=(ACTION_CONTINUE,),
                metadata={"image_count": budget.image_count},
            )
        )
    return findings


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    subject: str | None,
    attachment_id: str | None = None,
    workspace_path: str | None = None,
    actions: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> HarnessPreflightFinding:
    return HarnessPreflightFinding(
        id="",
        severity=severity,
        code=code,
        message=message,
        subject=subject,
        attachment_id=attachment_id,
        workspace_path=workspace_path,
        actions=tuple(dict.fromkeys(actions)),
        metadata=dict(metadata or {}),
    )


def _attachment_actions(
    attachment: HarnessAttachment,
    *,
    include_continue: bool = False,
) -> tuple[str, ...]:
    actions: list[str] = [ACTION_EXCLUDE_ATTACHMENT]
    if attachment.workspace_path:
        actions.append(ACTION_SEND_PATH_ONLY)
    if include_continue:
        actions.append(ACTION_CONTINUE)
    return tuple(actions)


def _attachment_subject(attachment: HarnessAttachment) -> str:
    if attachment.workspace_path:
        return f"@{attachment.workspace_path}"
    return attachment.filename or attachment.id


def _attachment_workspace_root(
    attachment: HarnessAttachment,
    workspace: str | None,
) -> str | None:
    metadata_root = attachment.metadata.get("workspace_root")
    if metadata_root is not None:
        return str(metadata_root)
    return workspace


def _attachment_sample(
    attachment: HarnessAttachment,
    *,
    workspace_root: str | None,
    data_dir: str | Path | None,
) -> bytes | None:
    path: Path | None = None
    if attachment.storage_path:
        candidate = Path(attachment.storage_path).expanduser().resolve()
        if data_dir is not None:
            data_root = Path(data_dir).expanduser().resolve()
            if not _is_relative_to(candidate, data_root):
                return None
        path = candidate
    elif attachment.workspace_path and workspace_root:
        root = Path(workspace_root).expanduser().resolve()
        candidate = (root / attachment.workspace_path).resolve()
        if not _is_relative_to(candidate, root):
            return None
        path = candidate
    if path is None or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            return handle.read(SAMPLE_BYTES)
    except OSError:
        return None


def _decode_sample(sample: bytes) -> str:
    if not sample:
        return ""
    return sample.decode("utf-8", errors="ignore")


def _is_env_path(path: str | None) -> bool:
    if not path:
        return False
    normalized = path.replace("\\", "/").strip().lower()
    parts = PurePosixPath(normalized).parts
    return any(part == ".env" or part.startswith(".env.") for part in parts)


def _attachment_token_estimate(attachment: HarnessAttachment) -> int:
    if attachment.kind == "image":
        return 0
    estimated_chars = min(max(attachment.size_bytes, 0), SAMPLE_BYTES)
    return _estimate_tokens(estimated_chars)


def _estimate_tokens(chars: int) -> int:
    if chars <= 0:
        return 0
    return (chars + 3) // 4


def _max_severity(findings: list[HarnessPreflightFinding]) -> str:
    severities = {finding.severity for finding in findings}
    if SEVERITY_BLOCK in severities:
        return SEVERITY_BLOCK
    if SEVERITY_WARNING in severities:
        return SEVERITY_WARNING
    return SEVERITY_INFO


def _with_stable_ids(
    findings: list[HarnessPreflightFinding],
) -> tuple[HarnessPreflightFinding, ...]:
    result: list[HarnessPreflightFinding] = []
    for index, finding in enumerate(findings, start=1):
        result.append(
            HarnessPreflightFinding(
                id=f"preflight_{index}",
                severity=finding.severity,
                code=finding.code,
                message=finding.message,
                subject=finding.subject,
                attachment_id=finding.attachment_id,
                workspace_path=finding.workspace_path,
                actions=finding.actions,
                metadata=finding.metadata,
            )
        )
    return tuple(result)


def _extend_findings(
    target: list[HarnessPreflightFinding],
    items: list[HarnessPreflightFinding] | tuple[HarnessPreflightFinding, ...],
) -> None:
    target.extend(items)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
