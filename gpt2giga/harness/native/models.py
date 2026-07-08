"""Core models for native harness session discovery and linking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class HarnessInvocationMode(str, Enum):
    """Describe how a harness should be invoked."""

    HEADLESS = "headless"
    NATIVE = "native"


class NativeSessionStatus(str, Enum):
    """Describe how a native session relates to gpt2giga history."""

    MANAGED_NATIVE = "managed_native"
    EXTERNAL_NATIVE = "external_native"
    IMPORTED = "imported"
    LINKED = "linked"
    READONLY = "readonly"


@dataclass(frozen=True)
class NativeSessionRef:
    """Cross-harness reference to a discovered or managed native session."""

    id: str
    harness_id: str
    native_session_id: str | None
    title: str
    workspace: str | None
    source: str
    status: NativeSessionStatus
    created_at: str | None
    updated_at: str | None
    message_count: int | None
    can_preview: bool
    can_import: bool
    can_resume: bool
    resume_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeTranscriptMessage:
    """Normalized message preview imported from a native CLI transcript."""

    role: str
    content: str
    created_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
