"""Core dataclasses for Unified Harness implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class HarnessCapability(str, Enum):
    """Describe a capability a harness can execute."""

    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"
    AGENT_CLI = "agent_cli"
    FILE_EDIT = "file_edit"
    SHELL = "shell"


class GigaChatApiMode(str, Enum):
    """Explicit GigaChat Chat Completions backend contract."""

    V1 = "v1"
    V2 = "v2"


class AvailabilityStatus(str, Enum):
    """Availability state reported by harnesses."""

    AVAILABLE = "available"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True)
class Availability:
    """Represent whether a harness can run in the current environment."""

    status: AvailabilityStatus
    reason: str = ""
    detail: str | None = None

    @classmethod
    def available(cls, reason: str = "available") -> "Availability":
        return cls(status=AvailabilityStatus.AVAILABLE, reason=reason)

    @classmethod
    def missing(cls, reason: str, detail: str | None = None) -> "Availability":
        return cls(
            status=AvailabilityStatus.MISSING,
            reason=reason,
            detail=detail,
        )

    @classmethod
    def error(cls, reason: str, detail: str | None = None) -> "Availability":
        return cls(status=AvailabilityStatus.ERROR, reason=reason, detail=detail)


@dataclass(frozen=True)
class HarnessSpec:
    """Metadata shown in CLI and UI."""

    id: str
    title: str
    kind: str
    description: str
    capabilities: tuple[HarnessCapability, ...]
    supports_model_selection: bool = True
    supports_api_mode_selection: bool = True
    supports_streaming: bool = False
    supports_workspace: bool = False
    default_api_mode: GigaChatApiMode = GigaChatApiMode.V2
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HarnessRequest:
    """Normalized user request passed to any harness."""

    prompt: str
    model: str | None = None
    api_mode: GigaChatApiMode = GigaChatApiMode.V2
    capability: HarnessCapability = HarnessCapability.CHAT_COMPLETIONS
    mode: str = "plan"
    stream: bool = False
    workspace: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessEvent:
    """Optional normalized event emitted by a harness."""

    type: str
    message: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessResult:
    """Normalized harness output."""

    ok: bool
    text: str
    raw: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[HarnessEvent, ...] = ()
    command: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class HarnessContext:
    """Safe execution context shared with harnesses."""

    proxy_url: str
    api_key: str | None = None
    default_model: str | None = None
    timeout_seconds: float = 60.0
    extra_env: Mapping[str, str] = field(default_factory=dict)

    def api_base_url(self, api_mode: GigaChatApiMode) -> str:
        """Return proxy URL with the explicit v1/v2 API prefix."""
        return f"{self.proxy_url.rstrip('/')}/{api_mode.value}"


SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credentials",
    "password",
    "secret",
    "token",
)
REDACTED = "<redacted>"


def parse_api_mode(value: str | GigaChatApiMode | None) -> GigaChatApiMode:
    """Parse a CLI/UI API mode value."""
    if isinstance(value, GigaChatApiMode):
        return value
    if value is None or not str(value).strip():
        return GigaChatApiMode.V2
    return GigaChatApiMode(str(value).strip().lower())


def parse_capability(
    value: str | HarnessCapability | None,
) -> HarnessCapability:
    """Parse a CLI/UI capability value."""
    if isinstance(value, HarnessCapability):
        return value
    if value is None or not str(value).strip():
        return HarnessCapability.CHAT_COMPLETIONS
    return HarnessCapability(str(value).strip().lower())


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-looking mapping values."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_KEY_PARTS):
                redacted[str(key)] = REDACTED
            else:
                redacted[str(key)] = redact_secrets(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def availability_to_dict(availability: Availability) -> dict[str, Any]:
    """Serialize availability for JSON output."""
    return {
        "status": availability.status.value,
        "reason": availability.reason,
        "detail": availability.detail,
    }


def spec_to_dict(spec: HarnessSpec) -> dict[str, Any]:
    """Serialize a harness spec for JSON output."""
    return {
        "id": spec.id,
        "title": spec.title,
        "kind": spec.kind,
        "description": spec.description,
        "capabilities": [capability.value for capability in spec.capabilities],
        "supports_model_selection": spec.supports_model_selection,
        "supports_api_mode_selection": spec.supports_api_mode_selection,
        "supports_streaming": spec.supports_streaming,
        "supports_workspace": spec.supports_workspace,
        "default_api_mode": spec.default_api_mode.value,
        "tags": list(spec.tags),
    }


def event_to_dict(event: HarnessEvent) -> dict[str, Any]:
    """Serialize a harness event for JSON output."""
    return {
        "type": event.type,
        "message": event.message,
        "payload": redact_secrets(dict(event.payload)),
    }


def result_to_dict(result: HarnessResult) -> dict[str, Any]:
    """Serialize a harness result without exposing secrets."""
    return {
        "ok": result.ok,
        "text": result.text,
        "raw": redact_secrets(dict(result.raw)),
        "events": [event_to_dict(event) for event in result.events],
        "command": list(result.command),
        "error": result.error,
    }
