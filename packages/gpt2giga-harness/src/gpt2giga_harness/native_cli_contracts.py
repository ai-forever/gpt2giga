"""Execution-free contracts for provider-native CLI routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
import re
from typing import Any, Mapping, Sequence


class CapabilityLevel(str, Enum):
    """Provider-native capability level selected for an invocation."""

    NATIVE_PASSTHROUGH = "native_passthrough"
    MANAGED_HANDOFF = "managed_handoff"
    STRUCTURED_WORKBENCH = "structured_workbench"


class RouteReason(str, Enum):
    """Stable, content-free reason for a route decision."""

    NATIVE_OWNED = "native_owned"
    MANAGED_HANDOFF = "managed_handoff"
    STRUCTURED_ADMITTED = "structured_admitted"


class NativeCommandClass(str, Enum):
    """Reviewed command family without raw argument retention."""

    HUMAN_ROOT = "human_root"
    HUMAN_PROMPT = "human_prompt"
    HUMAN_RESUME = "human_resume"
    HUMAN_FORK = "human_fork"
    HUMAN_CONTROL = "human_control"
    HEADLESS = "headless"
    PROTOCOL = "protocol"
    ADMINISTRATION = "administration"
    EXTERNAL_UI = "external_ui"
    METADATA = "metadata"
    UNKNOWN_NATIVE = "unknown_native"


class NativeOutputFamily(str, Enum):
    """Provider-owned native output family."""

    TERMINAL = "terminal"
    TEXT = "text"
    JSON = "json"
    JSONL = "jsonl"
    PROTOCOL_BYTES = "protocol_bytes"
    UNKNOWN = "unknown"


class VersionEvidenceStatus(str, Enum):
    """Admission status for structured integration evidence."""

    ABSENT = "absent"
    UNPARSED = "unparsed"
    BELOW_WINDOW = "below_window"
    IN_WINDOW = "in_window"
    ABOVE_WINDOW = "above_window"


class HumanIntentMatcher(str, Enum):
    """Closed matcher vocabulary for affirmative human intents."""

    EMPTY = "empty"
    POSITIONAL_PROMPT = "positional_prompt"
    CODEX_RESUME = "codex_resume"
    CODEX_FORK = "codex_fork"
    CLAUDE_CONTINUE = "claude_continue"
    CLAUDE_RESUME = "claude_resume"
    CLAUDE_CONTROL = "claude_control"
    GEMINI_INTERACTIVE = "gemini_interactive"
    GEMINI_RESUME = "gemini_resume"


class CapabilityImplementation(str, Enum):
    """Owner of one contextual capability implementation."""

    NATIVE = "native"
    HARNESS_MANAGED = "harness_managed"
    DERIVED = "derived"
    HANDOFF = "handoff"
    UNSUPPORTED = "unsupported"


class CapabilityState(str, Enum):
    """Truthful state of one contextual capability."""

    READY = "ready"
    DEGRADED = "degraded"
    EXPERIMENTAL = "experimental"
    BLOCKED = "blocked"


class CapabilityEffectScope(str, Enum):
    """When a capability change takes effect."""

    LIVE = "live"
    NEXT_TURN = "next_turn"
    NEXT_RUN = "next_run"
    NEW_SESSION = "new_session"


@dataclass(frozen=True)
class NativeNamespaceSpec:
    """Version-independent L0 namespace and process-resolution contract."""

    namespace: str
    executable: str
    provider_home_markers: tuple[str, ...]
    provider_config_markers: tuple[str, ...]
    posix_strategy: str = "exec_replace"
    windows_executable_strategy: str = "create_process_inherited_console"
    windows_shim_strategy: str = "reviewed_cmd_token_encoder"
    discovery_authorizes_execution: bool = False
    discovery_authorizes_mutation: bool = False

    def __post_init__(self) -> None:
        if self.namespace not in {"codex", "claude", "gemini"}:
            raise ValueError("only reviewed native namespaces may be reserved")
        if self.namespace != self.executable:
            raise ValueError("native namespace must preserve executable identity")
        if self.discovery_authorizes_execution or self.discovery_authorizes_mutation:
            raise ValueError("native discovery cannot grant authority")


@dataclass(frozen=True)
class IntegrationVersionWindow:
    """Reviewed half-open semantic-version interval for L2 only."""

    minimum: str
    maximum_exclusive: str

    def status(self, version: str | None) -> VersionEvidenceStatus:
        """Classify version evidence without changing L0 eligibility."""
        if version is None:
            return VersionEvidenceStatus.ABSENT
        parsed = _release_tuple(version)
        if parsed is None:
            return VersionEvidenceStatus.UNPARSED
        if parsed < _required_release_tuple(self.minimum):
            return VersionEvidenceStatus.BELOW_WINDOW
        if parsed >= _required_release_tuple(self.maximum_exclusive):
            return VersionEvidenceStatus.ABOVE_WINDOW
        return VersionEvidenceStatus.IN_WINDOW


@dataclass(frozen=True)
class UpstreamEvidence:
    """Immutable official reference supporting a semantic review window."""

    repository: str
    release_tag: str
    release_url: str
    reviewed_on: str
    commit: str


@dataclass(frozen=True)
class HumanIntentPattern:
    """One ordered, affirmative, lossless human-intent shape."""

    pattern_id: str
    matcher: HumanIntentMatcher
    command_class: NativeCommandClass
    precedence: int

    def __post_init__(self) -> None:
        if not self.pattern_id or self.precedence < 0:
            raise ValueError("human intent patterns require stable IDs and precedence")


@dataclass(frozen=True)
class ContextualCapability:
    """One capability declaration evaluated against the current context."""

    capability_id: str
    implementation: CapabilityImplementation
    state: CapabilityState
    effect_scope: CapabilityEffectScope
    allowed_transports: tuple[str, ...]
    required_process_owners: tuple[str, ...]
    native_label: str
    evidence_ref: str
    limitation: str | None = None
    remediation: str | None = None


@dataclass(frozen=True)
class WorkbenchIntegrationSpec:
    """Versioned L1/L2 semantic integration contract."""

    namespace: str
    harness_id: str
    version_window: IntegrationVersionWindow
    evidence: UpstreamEvidence
    intent_patterns: tuple[HumanIntentPattern, ...]
    structured_transport: str | None
    event_decoder: str | None
    l1_fallback: str
    capture_help_paths: tuple[tuple[str, ...], ...]
    isolated_variables: tuple[str, ...]
    capabilities: tuple[ContextualCapability, ...]

    def __post_init__(self) -> None:
        if self.namespace not in NATIVE_NAMESPACE_SPECS:
            raise ValueError("integration requires a reviewed native namespace")
        pattern_ids = [pattern.pattern_id for pattern in self.intent_patterns]
        if len(pattern_ids) != len(set(pattern_ids)):
            raise ValueError("human intent pattern IDs must be unique")
        if tuple(
            sorted(pattern.precedence for pattern in self.intent_patterns)
        ) != tuple(pattern.precedence for pattern in self.intent_patterns):
            raise ValueError("human intent patterns must be ordered by precedence")


@dataclass(frozen=True)
class RouteDecision:
    """Content-free classification result with no process authority."""

    namespace: str
    level: CapabilityLevel
    reason: RouteReason
    command_class: NativeCommandClass
    output_family: NativeOutputFamily
    version_evidence: VersionEvidenceStatus
    intent_pattern_id: str | None
    l0_eligible: bool = True
    execution_authorized: bool = False


@dataclass(frozen=True)
class CapabilityContext:
    """Runtime facts used to evaluate a capability without provider content."""

    version: str | None
    transport: str
    process_owner: str
    session_generation: int
    policy_allows: bool


@dataclass(frozen=True)
class CapabilityEvaluation:
    """Content-free evaluation of one contextual capability."""

    capability_id: str
    state: CapabilityState
    reason: str


NATIVE_NAMESPACE_SPECS: Mapping[str, NativeNamespaceSpec] = MappingProxyType(
    {
        "codex": NativeNamespaceSpec(
            namespace="codex",
            executable="codex",
            provider_home_markers=("CODEX_HOME",),
            provider_config_markers=("config.toml",),
        ),
        "claude": NativeNamespaceSpec(
            namespace="claude",
            executable="claude",
            provider_home_markers=("CLAUDE_CONFIG_DIR",),
            provider_config_markers=(".claude.json", "settings.json"),
        ),
        "gemini": NativeNamespaceSpec(
            namespace="gemini",
            executable="gemini",
            provider_home_markers=("GEMINI_CLI_HOME",),
            provider_config_markers=("settings.json",),
        ),
    }
)


def _pattern(
    pattern_id: str,
    matcher: HumanIntentMatcher,
    command_class: NativeCommandClass,
    precedence: int,
) -> HumanIntentPattern:
    return HumanIntentPattern(pattern_id, matcher, command_class, precedence)


def _capability(
    capability_id: str,
    implementation: CapabilityImplementation,
    state: CapabilityState,
    effect_scope: CapabilityEffectScope,
    transports: tuple[str, ...],
    owners: tuple[str, ...],
    native_label: str,
    evidence_ref: str,
    *,
    limitation: str | None = None,
    remediation: str | None = None,
) -> ContextualCapability:
    return ContextualCapability(
        capability_id=capability_id,
        implementation=implementation,
        state=state,
        effect_scope=effect_scope,
        allowed_transports=transports,
        required_process_owners=owners,
        native_label=native_label,
        evidence_ref=evidence_ref,
        limitation=limitation,
        remediation=remediation,
    )


WORKBENCH_INTEGRATION_SPECS: Mapping[str, WorkbenchIntegrationSpec] = MappingProxyType(
    {
        "codex": WorkbenchIntegrationSpec(
            namespace="codex",
            harness_id="codex-cli",
            version_window=IntegrationVersionWindow("0.144.0", "0.145.0"),
            evidence=UpstreamEvidence(
                repository="openai/codex",
                release_tag="rust-v0.144.5",
                release_url=(
                    "https://github.com/openai/codex/releases/tag/rust-v0.144.5"
                ),
                reviewed_on="2026-07-21",
                commit="87db9bc18ba5bc82c1cb4e4381b44f693ee35623",
            ),
            intent_patterns=(
                _pattern(
                    "codex.root",
                    HumanIntentMatcher.EMPTY,
                    NativeCommandClass.HUMAN_ROOT,
                    10,
                ),
                _pattern(
                    "codex.resume",
                    HumanIntentMatcher.CODEX_RESUME,
                    NativeCommandClass.HUMAN_RESUME,
                    20,
                ),
                _pattern(
                    "codex.fork",
                    HumanIntentMatcher.CODEX_FORK,
                    NativeCommandClass.HUMAN_FORK,
                    30,
                ),
            ),
            structured_transport="app-server",
            event_decoder="codex-app-server-v1",
            l1_fallback="provider_terminal_handoff",
            capture_help_paths=((), ("app-server",)),
            isolated_variables=("HOME", "CODEX_HOME"),
            capabilities=(
                _capability(
                    "session.resume.native",
                    CapabilityImplementation.HARNESS_MANAGED,
                    CapabilityState.READY,
                    CapabilityEffectScope.NEW_SESSION,
                    ("app-server",),
                    ("harness",),
                    "resume",
                    "codex-0.144-app-server",
                ),
                _capability(
                    "turn.steer",
                    CapabilityImplementation.HARNESS_MANAGED,
                    CapabilityState.READY,
                    CapabilityEffectScope.LIVE,
                    ("app-server",),
                    ("harness",),
                    "steer",
                    "codex-0.144-app-server",
                ),
            ),
        ),
        "claude": WorkbenchIntegrationSpec(
            namespace="claude",
            harness_id="claude-code",
            version_window=IntegrationVersionWindow("2.1.0", "2.2.0"),
            evidence=UpstreamEvidence(
                repository="anthropics/claude-code",
                release_tag="v2.1.212",
                release_url=(
                    "https://github.com/anthropics/claude-code/releases/tag/v2.1.212"
                ),
                reviewed_on="2026-07-21",
                commit="67f390c9a0b1440d369aebe2ff6a5023db35bf8e",
            ),
            intent_patterns=(
                _pattern(
                    "claude.root",
                    HumanIntentMatcher.EMPTY,
                    NativeCommandClass.HUMAN_ROOT,
                    10,
                ),
                _pattern(
                    "claude.prompt",
                    HumanIntentMatcher.POSITIONAL_PROMPT,
                    NativeCommandClass.HUMAN_PROMPT,
                    20,
                ),
                _pattern(
                    "claude.continue",
                    HumanIntentMatcher.CLAUDE_CONTINUE,
                    NativeCommandClass.HUMAN_RESUME,
                    30,
                ),
                _pattern(
                    "claude.resume",
                    HumanIntentMatcher.CLAUDE_RESUME,
                    NativeCommandClass.HUMAN_RESUME,
                    40,
                ),
                _pattern(
                    "claude.control",
                    HumanIntentMatcher.CLAUDE_CONTROL,
                    NativeCommandClass.HUMAN_CONTROL,
                    50,
                ),
            ),
            structured_transport=None,
            event_decoder=None,
            l1_fallback="provider_terminal_handoff",
            capture_help_paths=((),),
            isolated_variables=("HOME", "CLAUDE_CONFIG_DIR"),
            capabilities=(
                _capability(
                    "session.resume.native",
                    CapabilityImplementation.HANDOFF,
                    CapabilityState.DEGRADED,
                    CapabilityEffectScope.NEW_SESSION,
                    ("provider-terminal",),
                    ("provider",),
                    "--resume",
                    "claude-2.1-native",
                    limitation="No admitted durable structured transport.",
                    remediation="Use the visible provider-terminal handoff.",
                ),
            ),
        ),
        "gemini": WorkbenchIntegrationSpec(
            namespace="gemini",
            harness_id="gemini-cli",
            version_window=IntegrationVersionWindow("0.46.0", "0.47.0"),
            evidence=UpstreamEvidence(
                repository="google-gemini/gemini-cli",
                release_tag="v0.46.0",
                release_url=(
                    "https://github.com/google-gemini/gemini-cli/releases/tag/v0.46.0"
                ),
                reviewed_on="2026-07-21",
                commit="85b0c55c126a4992b51d140e357ae9db5f9c2d7f",
            ),
            intent_patterns=(
                _pattern(
                    "gemini.root",
                    HumanIntentMatcher.EMPTY,
                    NativeCommandClass.HUMAN_ROOT,
                    10,
                ),
                _pattern(
                    "gemini.prompt",
                    HumanIntentMatcher.POSITIONAL_PROMPT,
                    NativeCommandClass.HUMAN_PROMPT,
                    20,
                ),
                _pattern(
                    "gemini.interactive",
                    HumanIntentMatcher.GEMINI_INTERACTIVE,
                    NativeCommandClass.HUMAN_PROMPT,
                    30,
                ),
                _pattern(
                    "gemini.resume",
                    HumanIntentMatcher.GEMINI_RESUME,
                    NativeCommandClass.HUMAN_RESUME,
                    40,
                ),
            ),
            structured_transport="acp",
            event_decoder="gemini-acp-v1",
            l1_fallback="provider_terminal_handoff",
            capture_help_paths=((),),
            isolated_variables=("HOME", "GEMINI_CLI_HOME"),
            capabilities=(
                _capability(
                    "session.resume.native",
                    CapabilityImplementation.HARNESS_MANAGED,
                    CapabilityState.EXPERIMENTAL,
                    CapabilityEffectScope.NEW_SESSION,
                    ("acp",),
                    ("harness",),
                    "--resume",
                    "gemini-0.46-acp",
                ),
                _capability(
                    "control.policy.set",
                    CapabilityImplementation.HARNESS_MANAGED,
                    CapabilityState.EXPERIMENTAL,
                    CapabilityEffectScope.NEXT_TURN,
                    ("acp",),
                    ("harness",),
                    "--policy",
                    "gemini-0.46-acp",
                ),
            ),
        ),
    }
)


_METADATA_FLAGS = frozenset({"--help", "-h", "--version"})
_ADMIN_PREFIXES = {
    "codex": frozenset(
        {
            "apply",
            "archive",
            "completion",
            "debug",
            "delete",
            "doctor",
            "execpolicy",
            "features",
            "login",
            "logout",
            "mcp",
            "plugin",
            "unarchive",
            "update",
        }
    ),
    "claude": frozenset(
        {
            "agents",
            "attach",
            "auth",
            "background",
            "doctor",
            "gateway",
            "install",
            "logs",
            "mcp",
            "plugin",
            "project",
            "setup-token",
            "ultrareview",
            "update",
        }
    ),
    "gemini": frozenset({"extensions", "mcp", "skills", "update"}),
}
_EXTERNAL_PREFIXES = {
    "codex": frozenset({"app", "cloud", "remote-control"}),
    "claude": frozenset({"cloud", "remote-control", "teleport"}),
    "gemini": frozenset(),
}


def classify_native_route(
    namespace: str,
    suffix: Sequence[str],
    *,
    version: str | None = None,
    stdin_is_tty: bool = True,
    stdout_is_tty: bool = True,
    structured_transport_ready: bool = True,
) -> RouteDecision:
    """Classify one provider suffix without retaining or authorizing it."""
    if namespace not in NATIVE_NAMESPACE_SPECS:
        raise KeyError(f"unknown native CLI namespace: {namespace}")
    argv = tuple(suffix)
    if any(not isinstance(token, str) or "\x00" in token for token in argv):
        raise ValueError("native CLI suffix must contain NUL-free strings")
    integration = WORKBENCH_INTEGRATION_SPECS[namespace]
    version_status = integration.version_window.status(version)

    native_class = _native_owned_class(namespace, argv, stdin_is_tty, stdout_is_tty)
    if native_class is not None:
        return _native_decision(namespace, native_class, argv, version_status)

    pattern = _match_human_intent(integration, argv)
    if pattern is None or not (stdin_is_tty and stdout_is_tty):
        return _native_decision(
            namespace,
            NativeCommandClass.UNKNOWN_NATIVE,
            argv,
            version_status,
        )

    if (
        version_status is VersionEvidenceStatus.IN_WINDOW
        and integration.structured_transport is not None
        and structured_transport_ready
    ):
        return RouteDecision(
            namespace=namespace,
            level=CapabilityLevel.STRUCTURED_WORKBENCH,
            reason=RouteReason.STRUCTURED_ADMITTED,
            command_class=pattern.command_class,
            output_family=NativeOutputFamily.TERMINAL,
            version_evidence=version_status,
            intent_pattern_id=pattern.pattern_id,
        )
    return RouteDecision(
        namespace=namespace,
        level=CapabilityLevel.MANAGED_HANDOFF,
        reason=RouteReason.MANAGED_HANDOFF,
        command_class=pattern.command_class,
        output_family=NativeOutputFamily.TERMINAL,
        version_evidence=version_status,
        intent_pattern_id=pattern.pattern_id,
    )


def evaluate_contextual_capability(
    integration: WorkbenchIntegrationSpec,
    capability: ContextualCapability,
    context: CapabilityContext,
) -> CapabilityEvaluation:
    """Evaluate one capability against version, transport, owner, and policy."""
    if capability not in integration.capabilities:
        raise ValueError("capability is not declared by the integration")
    if not context.policy_allows:
        return CapabilityEvaluation(
            capability.capability_id, CapabilityState.BLOCKED, "policy_denied"
        )
    if context.session_generation < 1:
        return CapabilityEvaluation(
            capability.capability_id,
            CapabilityState.BLOCKED,
            "session_generation_unavailable",
        )
    if (
        integration.version_window.status(context.version)
        is not VersionEvidenceStatus.IN_WINDOW
    ):
        return CapabilityEvaluation(
            capability.capability_id, CapabilityState.DEGRADED, "version_not_admitted"
        )
    if context.transport not in capability.allowed_transports:
        return CapabilityEvaluation(
            capability.capability_id, CapabilityState.BLOCKED, "transport_mismatch"
        )
    if context.process_owner not in capability.required_process_owners:
        return CapabilityEvaluation(
            capability.capability_id, CapabilityState.BLOCKED, "process_owner_mismatch"
        )
    return CapabilityEvaluation(
        capability.capability_id, capability.state, "context_admitted"
    )


def native_namespace_spec_to_dict(spec: NativeNamespaceSpec) -> dict[str, Any]:
    """Serialize a version-independent namespace contract."""
    return {
        "namespace": spec.namespace,
        "executable": spec.executable,
        "provider_home_markers": list(spec.provider_home_markers),
        "provider_config_markers": list(spec.provider_config_markers),
        "process_strategies": {
            "posix": spec.posix_strategy,
            "windows_executable": spec.windows_executable_strategy,
            "windows_shim": spec.windows_shim_strategy,
        },
        "discovery_authorizes_execution": spec.discovery_authorizes_execution,
        "discovery_authorizes_mutation": spec.discovery_authorizes_mutation,
    }


def workbench_integration_spec_to_dict(
    spec: WorkbenchIntegrationSpec,
) -> dict[str, Any]:
    """Serialize semantic evidence without native invocation content."""
    return {
        "namespace": spec.namespace,
        "harness_id": spec.harness_id,
        "version_window": {
            "minimum": spec.version_window.minimum,
            "maximum_exclusive": spec.version_window.maximum_exclusive,
        },
        "evidence": {
            "repository": spec.evidence.repository,
            "release_tag": spec.evidence.release_tag,
            "release_url": spec.evidence.release_url,
            "reviewed_on": spec.evidence.reviewed_on,
            "commit": spec.evidence.commit,
        },
        "intent_patterns": [
            {
                "pattern_id": pattern.pattern_id,
                "matcher": pattern.matcher.value,
                "command_class": pattern.command_class.value,
                "precedence": pattern.precedence,
            }
            for pattern in spec.intent_patterns
        ],
        "structured_transport": spec.structured_transport,
        "event_decoder": spec.event_decoder,
        "l1_fallback": spec.l1_fallback,
        "capture_help_classes": [
            "root" if not path else ".".join(path) for path in spec.capture_help_paths
        ],
        "isolated_variables": list(spec.isolated_variables),
        "capabilities": [
            {
                "capability_id": capability.capability_id,
                "implementation": capability.implementation.value,
                "state": capability.state.value,
                "effect_scope": capability.effect_scope.value,
                "allowed_transports": list(capability.allowed_transports),
                "required_process_owners": list(capability.required_process_owners),
                "native_label": capability.native_label,
                "evidence_ref": capability.evidence_ref,
                "limitation": capability.limitation,
                "remediation": capability.remediation,
            }
            for capability in spec.capabilities
        ],
    }


def route_decision_to_dict(decision: RouteDecision) -> dict[str, Any]:
    """Serialize only content-free route metadata."""
    return {
        "namespace": decision.namespace,
        "level": decision.level.value,
        "reason": decision.reason.value,
        "command_class": decision.command_class.value,
        "output_family": decision.output_family.value,
        "version_evidence": decision.version_evidence.value,
        "intent_pattern_id": decision.intent_pattern_id,
        "l0_eligible": decision.l0_eligible,
        "execution_authorized": decision.execution_authorized,
    }


def _native_owned_class(
    namespace: str,
    argv: tuple[str, ...],
    stdin_is_tty: bool,
    stdout_is_tty: bool,
) -> NativeCommandClass | None:
    if any(_option_name(token) in _METADATA_FLAGS for token in argv):
        return NativeCommandClass.METADATA
    first = argv[0] if argv else None
    if first in {"help", "version", "completion"}:
        return NativeCommandClass.METADATA
    if namespace == "codex":
        if first in {"exec", "e", "review", "sandbox"}:
            return NativeCommandClass.HEADLESS
        if first in {"app-server", "mcp-server"}:
            return NativeCommandClass.PROTOCOL
    elif namespace == "claude":
        if _has_option(argv, "--print", "-p"):
            return NativeCommandClass.HEADLESS
        if first == "daemon":
            return NativeCommandClass.PROTOCOL
    elif namespace == "gemini":
        if _has_option(argv, "--prompt", "-p") or not (stdin_is_tty and stdout_is_tty):
            return NativeCommandClass.HEADLESS
        if first == "acp" or _has_option(argv, "--experimental-acp", "--acp"):
            return NativeCommandClass.PROTOCOL
        if _has_option(argv, "--list-sessions", "--delete-session"):
            return NativeCommandClass.ADMINISTRATION
    if first in _ADMIN_PREFIXES[namespace]:
        return NativeCommandClass.ADMINISTRATION
    if first in _EXTERNAL_PREFIXES[namespace]:
        return NativeCommandClass.EXTERNAL_UI
    return None


def _match_human_intent(
    integration: WorkbenchIntegrationSpec,
    argv: tuple[str, ...],
) -> HumanIntentPattern | None:
    for pattern in integration.intent_patterns:
        if _matches(pattern.matcher, argv):
            return pattern
    return None


def _matches(matcher: HumanIntentMatcher, argv: tuple[str, ...]) -> bool:
    if matcher is HumanIntentMatcher.EMPTY:
        return not argv
    if matcher is HumanIntentMatcher.POSITIONAL_PROMPT:
        return len(argv) == 1 and bool(argv[0]) and not argv[0].startswith("-")
    if matcher is HumanIntentMatcher.CODEX_RESUME:
        return (
            len(argv) == 2
            and argv[0] == "resume"
            and (argv[1] == "--last" or not argv[1].startswith("-"))
        )
    if matcher is HumanIntentMatcher.CODEX_FORK:
        return len(argv) == 2 and argv[0] == "fork" and not argv[1].startswith("-")
    if matcher is HumanIntentMatcher.CLAUDE_CONTINUE:
        return argv in {("-c",), ("--continue",)}
    if matcher is HumanIntentMatcher.CLAUDE_RESUME:
        base = (
            len(argv) == 2
            and argv[0] in {"-r", "--resume"}
            and not argv[1].startswith("-")
        )
        fork = (
            len(argv) == 3
            and argv[0] == "--fork-session"
            and argv[1] in {"-r", "--resume"}
            and not argv[2].startswith("-")
        )
        return base or fork
    if matcher is HumanIntentMatcher.CLAUDE_CONTROL:
        return (
            len(argv) == 2
            and argv[0] in {"--permission-mode", "--sandbox"}
            and not argv[1].startswith("-")
        )
    if matcher is HumanIntentMatcher.GEMINI_INTERACTIVE:
        return (
            len(argv) == 2
            and argv[0] in {"-i", "--prompt-interactive"}
            and bool(argv[1])
        )
    if matcher is HumanIntentMatcher.GEMINI_RESUME:
        return (
            len(argv) == 2
            and argv[0] in {"-r", "--resume"}
            and not argv[1].startswith("-")
        )
    return False


def _native_decision(
    namespace: str,
    command_class: NativeCommandClass,
    argv: tuple[str, ...],
    version_status: VersionEvidenceStatus,
) -> RouteDecision:
    return RouteDecision(
        namespace=namespace,
        level=CapabilityLevel.NATIVE_PASSTHROUGH,
        reason=RouteReason.NATIVE_OWNED,
        command_class=command_class,
        output_family=_output_family(namespace, argv, command_class),
        version_evidence=version_status,
        intent_pattern_id=None,
    )


def _output_family(
    namespace: str,
    argv: tuple[str, ...],
    command_class: NativeCommandClass,
) -> NativeOutputFamily:
    if command_class is NativeCommandClass.PROTOCOL:
        return NativeOutputFamily.PROTOCOL_BYTES
    if command_class is NativeCommandClass.UNKNOWN_NATIVE:
        return NativeOutputFamily.UNKNOWN
    if namespace == "codex" and _has_option(argv, "--json"):
        return (
            NativeOutputFamily.JSONL
            if argv[:1] in {("exec",), ("e",)}
            else NativeOutputFamily.JSON
        )
    output_format = _option_value(argv, "--output-format")
    if output_format == "stream-json":
        return NativeOutputFamily.JSONL
    if output_format == "json":
        return NativeOutputFamily.JSON
    return NativeOutputFamily.TEXT


def _has_option(argv: tuple[str, ...], *options: str) -> bool:
    return any(_option_name(token) in options for token in argv)


def _option_name(token: str) -> str:
    return token.split("=", 1)[0]


def _option_value(argv: tuple[str, ...], option: str) -> str | None:
    for index, token in enumerate(argv):
        if token.startswith(f"{option}="):
            return token.split("=", 1)[1]
        if token == option and index + 1 < len(argv):
            return argv[index + 1]
    return None


_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)")


def _release_tuple(version: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.search(version)
    if match is None:
        return None
    parts = [int(part) for part in match.group(1).split(".")]
    parts.extend(0 for _ in range(3 - len(parts)))
    return parts[0], parts[1], parts[2]


def _required_release_tuple(version: str) -> tuple[int, int, int]:
    parsed = _release_tuple(version)
    if parsed is None:  # pragma: no cover - constants are covered structurally.
        raise ValueError(f"invalid integration version boundary: {version}")
    return parsed


__all__ = [
    "CapabilityContext",
    "CapabilityEffectScope",
    "CapabilityEvaluation",
    "CapabilityImplementation",
    "CapabilityLevel",
    "CapabilityState",
    "ContextualCapability",
    "HumanIntentMatcher",
    "HumanIntentPattern",
    "IntegrationVersionWindow",
    "NATIVE_NAMESPACE_SPECS",
    "NativeCommandClass",
    "NativeNamespaceSpec",
    "NativeOutputFamily",
    "RouteDecision",
    "RouteReason",
    "UpstreamEvidence",
    "VersionEvidenceStatus",
    "WORKBENCH_INTEGRATION_SPECS",
    "WorkbenchIntegrationSpec",
    "classify_native_route",
    "evaluate_contextual_capability",
    "native_namespace_spec_to_dict",
    "route_decision_to_dict",
    "workbench_integration_spec_to_dict",
]
