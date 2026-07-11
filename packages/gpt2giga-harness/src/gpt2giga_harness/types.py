"""Core dataclasses for Unified Harness implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
import re
from typing import Any, Callable, Mapping

from gpt2giga_harness.native.models import HarnessInvocationMode


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


class HarnessEventType(str, Enum):
    """Stable event names stored and streamed for harness runs."""

    RUN_STARTED = "run_started"
    MESSAGE_DELTA = "message_delta"
    STDOUT_DELTA = "stdout_delta"
    STDERR_DELTA = "stderr_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_FINISHED = "tool_call_finished"
    USAGE = "usage"
    FILE_CHANGED = "file_changed"
    RAW_REQUEST = "raw_request"
    RAW_RESPONSE = "raw_response"
    WARNING = "warning"
    ERROR = "error"
    MESSAGE_COMPLETED = "message_completed"
    CANCEL_REQUESTED = "cancel_requested"
    RUN_CANCELED = "run_canceled"
    RUN_FINISHED = "run_finished"


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
    icon: str | None = None
    supports_model_selection: bool = True
    supports_api_mode_selection: bool = True
    supports_streaming: bool = False
    supports_structured_events: bool = False
    supports_cancellation: bool = False
    supports_workspace: bool = False
    supports_attachments: bool = False
    accepted_attachment_kinds: tuple[str, ...] = field(default_factory=tuple)
    attachment_transport: tuple[str, ...] = field(default_factory=tuple)
    supports_native_sessions: bool = False
    supports_external_history: bool = False
    default_invocation_mode: HarnessInvocationMode = HarnessInvocationMode.HEADLESS
    default_api_mode: GigaChatApiMode = GigaChatApiMode.V2
    tags: tuple[str, ...] = field(default_factory=tuple)
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessChatMessage:
    """Chat message passed to chat-capable harnesses."""

    role: str
    content: str


@dataclass(frozen=True)
class HarnessRequest:
    """Normalized user request passed to any harness."""

    prompt: str
    model: str | None = None
    api_mode: GigaChatApiMode = GigaChatApiMode.V2
    capability: HarnessCapability = HarnessCapability.CHAT_COMPLETIONS
    mode: str = "plan"
    invocation_mode: HarnessInvocationMode = HarnessInvocationMode.HEADLESS
    stream: bool = False
    workspace: str | None = None
    messages: tuple[HarnessChatMessage, ...] = ()
    attachments: tuple[Mapping[str, Any], ...] = ()
    attachment_render_plan: Mapping[str, Any] | None = None
    session_id: str | None = None
    run_id: str | None = None
    native_session_id: str | None = None
    cancel_event: Any | None = None
    event_sink: Callable[["HarnessEvent"], None] | None = None
    process_sink: Callable[[Mapping[str, Any]], None] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessEvent:
    """Optional normalized event emitted by a harness."""

    type: str
    message: str
    payload: Mapping[str, Any] = field(default_factory=dict)


def emit_event(request: HarnessRequest, event: HarnessEvent) -> bool:
    """Publish a live event when the caller supplied an event sink.

    Return ``True`` when the event was delivered. Harnesses can keep the event in
    ``HarnessResult.events`` when this returns ``False`` so direct CLI callers
    retain the same final event visibility without duplicating live UI events.
    """
    if request.event_sink is None:
        return False
    request.event_sink(event)
    return True


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
    auto_start_proxy: bool = False
    proxy_start_timeout_seconds: float = 15.0
    extra_env: Mapping[str, str] = field(default_factory=dict)

    def api_base_url(self, api_mode: GigaChatApiMode) -> str:
        """Return proxy URL with the explicit v1/v2 API prefix."""
        return f"{self.proxy_url.rstrip('/')}/{api_mode.value}"


SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
)
SAFE_NUMERIC_USAGE_KEYS = frozenset(
    {
        "cached_input_tokens",
        "cached_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "reasoning_output_tokens",
        "reasoning_tokens",
        "thoughts_tokens",
        "tool_tokens",
        "total_tokens",
    }
)
SAFE_USAGE_DETAIL_KEYS = frozenset(
    {
        "completion_tokens_details",
        "input_tokens_details",
        "output_tokens_details",
        "prompt_tokens_details",
    }
)
REDACTED = "<redacted>"
SECRET_ENV_NAMES = (
    "GIGACHAT_CREDENTIALS",
    "GIGACHAT_ACCESS_TOKEN",
    "GPT2GIGA_API_KEY",
    "GPT2GIGA_HARNESS_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_-]{8,}"),
    re.compile(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)
_SECRET_TEXT_KEY = (
    r"[A-Za-z0-9_.-]*(?:api[_-]?key|authorization|cookie|credentials|"
    r"database[_-]?url|db[_-]?url|password|passwd|private[_-]?key|secret|token)"
    r"[A-Za-z0-9_.-]*"
)
_SECRET_JSON_VALUE_PATTERN = re.compile(
    rf"(?P<prefix>[\"']?{_SECRET_TEXT_KEY}[\"']?\s*:\s*)"
    rf"(?P<quote>[\"'])(?P<value>[^\r\n]*?)(?P=quote)",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf"(?P<prefix>\b{_SECRET_TEXT_KEY}\s*(?:=|:\s+)\s*)"
    rf"(?:(?P<quote>[\"'])(?P<quoted>[^\r\n]*?)(?P=quote)|"
    rf"(?P<bare>[^\s&,;\r\n]+))",
    re.IGNORECASE,
)
_URL_CREDENTIALS_PATTERN = re.compile(
    r"\b(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+@)",
    re.IGNORECASE,
)


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
    redaction_hook = getattr(value, "__gpt2giga_redacted__", None)
    if callable(redaction_hook):
        return redaction_hook()
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if _is_safe_numeric_usage(key_text, item):
                redacted[str(key)] = item
            elif key_text in SAFE_USAGE_DETAIL_KEYS and isinstance(item, Mapping):
                redacted[str(key)] = redact_secrets(item)
            elif any(part in key_text for part in SECRET_KEY_PARTS):
                redacted[str(key)] = REDACTED
            else:
                redacted[str(key)] = redact_secrets(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value)
    return value


def _is_safe_numeric_usage(key: str, value: Any) -> bool:
    return (
        key in SAFE_NUMERIC_USAGE_KEYS
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def availability_to_dict(availability: Availability) -> dict[str, Any]:
    """Serialize availability for JSON output."""
    return {
        "status": availability.status.value,
        "reason": availability.reason,
        "detail": availability.detail,
    }


def spec_to_dict(spec: HarnessSpec) -> dict[str, Any]:
    """Serialize a harness spec for JSON output."""
    capabilities = list(spec_capability_values(spec))
    config_schema = _safe_mapping(getattr(spec, "config_schema", {}))
    metadata = _safe_mapping(getattr(spec, "metadata", {}))
    accepted_attachment_kinds = _string_values(
        getattr(spec, "accepted_attachment_kinds", ())
    )
    attachment_transport = _string_values(getattr(spec, "attachment_transport", ()))
    default_invocation_mode = _enum_text(
        getattr(spec, "default_invocation_mode", None),
        HarnessInvocationMode.HEADLESS.value,
    )
    default_api_mode = _enum_text(
        getattr(spec, "default_api_mode", None),
        GigaChatApiMode.V2.value,
    )
    tags = _string_values(getattr(spec, "tags", ()))
    return {
        "id": _optional_text(spec.id) or "",
        "title": _optional_text(spec.title) or "",
        "kind": _optional_text(spec.kind) or "",
        "description": _optional_text(spec.description) or "",
        "icon": _optional_text(getattr(spec, "icon", None)),
        "capabilities": capabilities,
        "supports_model_selection": spec.supports_model_selection,
        "supports_api_mode_selection": spec.supports_api_mode_selection,
        "supports_streaming": spec.supports_streaming,
        "supports_structured_events": spec.supports_structured_events,
        "supports_cancellation": spec.supports_cancellation,
        "supports_workspace": spec.supports_workspace,
        "supports_attachments": spec.supports_attachments,
        "accepted_attachment_kinds": accepted_attachment_kinds,
        "attachment_transport": attachment_transport,
        "supports_native_sessions": spec.supports_native_sessions,
        "supports_external_history": spec.supports_external_history,
        "default_invocation_mode": default_invocation_mode,
        "default_api_mode": default_api_mode,
        "tags": tags,
        "config_schema": config_schema,
        "metadata": metadata,
        "plugin_metadata": {
            "display_name": _optional_text(spec.title) or "",
            "description": _optional_text(spec.description) or "",
            "icon": _optional_text(getattr(spec, "icon", None)),
            "kind": _optional_text(spec.kind) or "",
            "capabilities": capabilities,
            "supports": {
                "model_selection": spec.supports_model_selection,
                "api_mode_selection": spec.supports_api_mode_selection,
                "streaming": spec.supports_streaming,
                "structured_events": spec.supports_structured_events,
                "cancellation": spec.supports_cancellation,
                "workspace": spec.supports_workspace,
                "attachments": spec.supports_attachments,
                "native_sessions": spec.supports_native_sessions,
                "external_history": spec.supports_external_history,
                "headless": True,
                "native": spec.supports_native_sessions,
            },
            "attachments": {
                "supported": spec.supports_attachments,
                "accepted_kinds": accepted_attachment_kinds,
                "transport": attachment_transport,
            },
            "config_schema": config_schema,
            "metadata": metadata,
        },
    }


def spec_capability_values(spec: HarnessSpec) -> tuple[str, ...]:
    """Return known capability values from a spec, ignoring unknown plugin fields."""
    values: list[str] = []
    for capability in getattr(spec, "capabilities", ()):
        value = _capability_value(capability)
        if value is not None and value not in values:
            values.append(value)
    return tuple(values)


def _capability_value(value: Any) -> str | None:
    if isinstance(value, HarnessCapability):
        return value.value
    if isinstance(value, str):
        try:
            return HarnessCapability(value).value
        except ValueError:
            return None
    return None


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(redact_secrets(dict(value)))


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _enum_text(value: Any, default: str) -> str:
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    if isinstance(value, str) and value:
        return value
    return default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


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
        "text": redact_secrets(result.text),
        "raw": redact_secrets(dict(result.raw)),
        "events": [event_to_dict(event) for event in result.events],
        "command": redact_secrets(list(result.command)),
        "error": redact_secrets(result.error),
    }


def _redact_secret_text(text: str) -> str:
    redacted = text
    for name in SECRET_ENV_NAMES:
        value = os.getenv(name)
        if value and value != "0":
            redacted = redacted.replace(value, REDACTED)
    redacted = _SECRET_JSON_VALUE_PATTERN.sub(_redacted_assignment, redacted)
    redacted = _SECRET_ASSIGNMENT_PATTERN.sub(_redacted_assignment, redacted)
    redacted = _URL_CREDENTIALS_PATTERN.sub(
        lambda match: f"{match.group('scheme')}{REDACTED}@",
        redacted,
    )
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def _redacted_assignment(match: re.Match[str]) -> str:
    quote = match.groupdict().get("quote") or ""
    return f"{match.group('prefix')}{quote}{REDACTED}{quote}"
