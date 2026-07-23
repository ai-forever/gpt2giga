"""Side-effect-free permission simulation for one immutable execution route."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.mcp import (
    MCPTransport,
    ToolServerDescriptor,
    mcp_descriptor_to_dict,
)
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    permission_profile,
)
from gpt2giga_harness.types import HarnessCapability, HarnessSpec


PERMISSION_SIMULATION_SCHEMA_VERSION = 1
_HASH_LENGTH = 64


class PermissionDomain(str, Enum):
    """Stable operator-facing permission domains."""

    FILESYSTEM = "filesystem"
    COMMAND = "command"
    NETWORK = "network"
    SECRET = "secret"
    INTEGRATION = "integration"
    PROVIDER = "provider"
    GIT_GITHUB = "git_github"


class PermissionPrediction(str, Enum):
    """How confidently one effective permission can be predicted."""

    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    DENIED = "denied"
    UNKNOWN = "unknown"


class PermissionOccurrence(str, Enum):
    """When an action is expected to become relevant."""

    REQUIRED_BEFORE_START = "required_before_start"
    RUNTIME_DEPENDENT = "runtime_dependent"
    PROVIDER_OWNED = "provider_owned"


@dataclass(frozen=True)
class ExtensionPermissionContract:
    """Content-free capability summary for one selected extension."""

    identity_sha256: str
    transport: str
    capabilities: tuple[str, ...]
    secret_reference_count: int = 0

    def __post_init__(self) -> None:
        _validate_hash(self.identity_sha256, field_name="extension identity")
        if self.transport not in {"stdio", "streamable_http", "unknown"}:
            raise ValueError("extension transport is invalid")
        normalized = tuple(sorted(set(self.capabilities)))
        if any(not _safe_identity(value) for value in normalized):
            raise ValueError("extension capability is invalid")
        if self.secret_reference_count < 0:
            raise ValueError("extension secret_reference_count is invalid")
        object.__setattr__(self, "capabilities", normalized)

    def to_dict(self) -> dict[str, Any]:
        """Return the bounded content-free contract."""
        return {
            "identity_sha256": self.identity_sha256,
            "transport": self.transport,
            "capabilities": list(self.capabilities),
            "secret_reference_count": self.secret_reference_count,
        }


@dataclass(frozen=True)
class PermissionRouteSnapshot:
    """Immutable route identity consumed by one permission simulation."""

    harness_id: str
    harness_contract_sha256: str
    provider_route_sha256: str
    execution_transport: ExecutionTransport
    invocation_mode: str
    workspace_identity_sha256: str | None
    mode: str
    permission_profile: str
    origin: str
    extension_snapshot_sha256: str
    extension_count: int
    required_actions: tuple[PermissionAction, ...] = ()
    schema_version: int = PERMISSION_SIMULATION_SCHEMA_VERSION
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PERMISSION_SIMULATION_SCHEMA_VERSION:
            raise ValueError("unsupported permission route snapshot schema_version")
        for value, name in (
            (self.harness_id, "harness id"),
            (self.invocation_mode, "invocation mode"),
            (self.mode, "mode"),
            (self.permission_profile, "permission profile"),
            (self.origin, "origin"),
        ):
            if not _safe_identity(value):
                raise ValueError(f"permission route {name} is invalid")
        for value, name in (
            (self.harness_contract_sha256, "harness contract"),
            (self.provider_route_sha256, "provider route"),
            (self.extension_snapshot_sha256, "extension snapshot"),
        ):
            _validate_hash(value, field_name=name)
        if self.workspace_identity_sha256 is not None:
            _validate_hash(
                self.workspace_identity_sha256,
                field_name="workspace identity",
            )
        if not isinstance(self.execution_transport, ExecutionTransport):
            raise ValueError("permission route execution_transport is invalid")
        if self.extension_count < 0:
            raise ValueError("permission route extension_count is invalid")
        normalized = tuple(
            sorted(set(self.required_actions), key=lambda item: item.value)
        )
        if any(not isinstance(item, PermissionAction) for item in normalized):
            raise ValueError("permission route required_actions are invalid")
        object.__setattr__(self, "required_actions", normalized)
        object.__setattr__(
            self,
            "snapshot_hash",
            _json_hash(self.semantic_payload()),
        )

    def semantic_payload(self) -> dict[str, Any]:
        """Return the exact content-addressed route semantics."""
        return {
            "schema_version": self.schema_version,
            "harness_id": self.harness_id,
            "harness_contract_sha256": self.harness_contract_sha256,
            "provider_route_sha256": self.provider_route_sha256,
            "execution_transport": self.execution_transport.value,
            "invocation_mode": self.invocation_mode,
            "workspace_identity_sha256": self.workspace_identity_sha256,
            "mode": self.mode,
            "permission_profile": self.permission_profile,
            "origin": self.origin,
            "extension_snapshot_sha256": self.extension_snapshot_sha256,
            "extension_count": self.extension_count,
            "required_actions": [item.value for item in self.required_actions],
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the immutable public snapshot."""
        return {**self.semantic_payload(), "snapshot_hash": self.snapshot_hash}


@dataclass(frozen=True)
class PermissionOutcome:
    """One policy decision plus its truthful enforcement boundary."""

    domain: PermissionDomain
    action: PermissionAction | None
    prediction: PermissionPrediction
    occurrence: PermissionOccurrence
    policy_decision: PolicyDecision | None
    enforcement: EnforcementLevel
    control_owner: str
    reason_code: str
    capability_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize one content-free prediction."""
        return {
            "domain": self.domain.value,
            "action": self.action.value if self.action is not None else None,
            "prediction": self.prediction.value,
            "occurrence": self.occurrence.value,
            "policy_decision": (
                self.policy_decision.value if self.policy_decision is not None else None
            ),
            "enforcement": self.enforcement.value,
            "control_owner": self.control_owner,
            "reason_code": self.reason_code,
            "capability_sources": list(self.capability_sources),
        }


@dataclass(frozen=True)
class PermissionSimulation:
    """Reusable evidence for one side-effect-free permission calculation."""

    route_snapshot: PermissionRouteSnapshot
    outcomes: tuple[PermissionOutcome, ...]
    block_run: bool
    blocked_actions: tuple[PermissionAction, ...]
    approval_points: tuple[PermissionAction, ...]
    simulation_hash: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize bounded evidence without route values or secret material."""
        counts = {
            status.value: sum(outcome.prediction is status for outcome in self.outcomes)
            for status in PermissionPrediction
        }
        return {
            "schema_version": PERMISSION_SIMULATION_SCHEMA_VERSION,
            "simulation_hash": self.simulation_hash,
            "route_snapshot": self.route_snapshot.to_dict(),
            "summary": counts,
            "block_run": self.block_run,
            "blocked_actions": [item.value for item in self.blocked_actions],
            "approval_points": [item.value for item in self.approval_points],
            "outcomes": [item.to_dict() for item in self.outcomes],
            "content_free": True,
            "side_effect_free": True,
            "provider_safety_proven": False,
        }


@dataclass(frozen=True)
class _ActionRequirement:
    action: PermissionAction
    domain: PermissionDomain
    occurrence: PermissionOccurrence
    reason_code: str
    capability_sources: tuple[str, ...]


def extension_permission_contract(
    descriptor: ToolServerDescriptor | Mapping[str, Any],
) -> ExtensionPermissionContract:
    """Summarize one MCP descriptor without resolving or exposing its values."""
    if isinstance(descriptor, ToolServerDescriptor):
        serialized = mcp_descriptor_to_dict(descriptor)
        transport = descriptor.transport.value
        secret_count = len(descriptor.environment) + len(descriptor.headers)
    elif isinstance(descriptor, Mapping):
        serialized = dict(descriptor)
        transport = str(serialized.get("transport") or "unknown")
        environment = serialized.get("environment")
        headers = serialized.get("headers")
        secret_count = (len(environment) if isinstance(environment, Mapping) else 0) + (
            len(headers) if isinstance(headers, Mapping) else 0
        )
    else:
        raise TypeError("extension descriptor must be a descriptor or snapshot")
    capabilities = {
        "mcp.server.start",
        "mcp.tool.call",
        "provider_owned_approval",
    }
    if transport == MCPTransport.STDIO.value:
        capabilities.add("process.spawn")
    elif transport == MCPTransport.STREAMABLE_HTTP.value:
        capabilities.add("network.connect")
    if secret_count:
        capabilities.add("secret.reference")
    return ExtensionPermissionContract(
        identity_sha256=_json_hash(serialized),
        transport=transport,
        capabilities=tuple(capabilities),
        secret_reference_count=secret_count,
    )


def build_permission_simulation(
    *,
    spec: HarnessSpec,
    execution_transport: ExecutionTransport,
    invocation_mode: str,
    permission_profile_id: str,
    mode: str,
    workspace: str | Path | None,
    api_mode: str,
    model: str | None,
    extensions: Sequence[ExtensionPermissionContract] = (),
    required_actions: Sequence[PermissionAction | str] = (),
    origin: str = "interactive",
) -> PermissionSimulation:
    """Calculate effective permissions without consuming grants or causing I/O."""
    if not isinstance(spec, HarnessSpec):
        raise TypeError("permission simulation requires a HarnessSpec")
    selected_profile = permission_profile(permission_profile_id, origin=origin)
    parsed_required = tuple(PermissionAction(item) for item in required_actions)
    normalized_extensions = tuple(
        sorted(extensions, key=lambda item: item.identity_sha256)
    )
    if len({item.identity_sha256 for item in normalized_extensions}) != len(
        normalized_extensions
    ):
        raise ValueError("permission simulation extensions contain duplicates")
    route = PermissionRouteSnapshot(
        harness_id=spec.id,
        harness_contract_sha256=_json_hash(_harness_contract(spec)),
        provider_route_sha256=_json_hash(
            {"api_mode": str(api_mode), "model": str(model or "default")}
        ),
        execution_transport=execution_transport,
        invocation_mode=str(invocation_mode),
        workspace_identity_sha256=(
            hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()
            if workspace is not None
            else None
        ),
        mode=str(mode),
        permission_profile=selected_profile.id,
        origin=str(origin),
        extension_snapshot_sha256=_json_hash(
            {"extensions": [item.to_dict() for item in normalized_extensions]}
        ),
        extension_count=len(normalized_extensions),
        required_actions=parsed_required,
    )
    requirements = _requirements(
        spec,
        route,
        extensions=normalized_extensions,
    )
    engine = PolicyEngine()
    outcomes = [
        _resolve_requirement(engine, selected_profile, route, requirement)
        for requirement in requirements
    ]
    outcomes.extend(
        _unpredictable_outcomes(
            route,
            normalized_extensions,
            provider_route_required="local" not in spec.tags,
        )
    )
    normalized_outcomes = tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.domain.value,
                item.action.value if item.action is not None else "",
                item.reason_code,
            ),
        )
    )
    blocked_actions = tuple(
        sorted(
            {
                item.action
                for item in normalized_outcomes
                if item.action is not None
                and item.occurrence is PermissionOccurrence.REQUIRED_BEFORE_START
                and item.prediction is PermissionPrediction.DENIED
            },
            key=lambda item: item.value,
        )
    )
    approval_points = tuple(
        sorted(
            {
                item.action
                for item in normalized_outcomes
                if item.action is not None
                and item.prediction is PermissionPrediction.APPROVAL_REQUIRED
            },
            key=lambda item: item.value,
        )
    )
    semantic = {
        "schema_version": PERMISSION_SIMULATION_SCHEMA_VERSION,
        "route_snapshot_hash": route.snapshot_hash,
        "outcomes": [item.to_dict() for item in normalized_outcomes],
        "blocked_actions": [item.value for item in blocked_actions],
        "approval_points": [item.value for item in approval_points],
        "provider_safety_proven": False,
    }
    return PermissionSimulation(
        route_snapshot=route,
        outcomes=normalized_outcomes,
        block_run=bool(blocked_actions),
        blocked_actions=blocked_actions,
        approval_points=approval_points,
        simulation_hash=_json_hash(semantic),
    )


def _requirements(
    spec: HarnessSpec,
    route: PermissionRouteSnapshot,
    *,
    extensions: Sequence[ExtensionPermissionContract],
) -> tuple[_ActionRequirement, ...]:
    requirements: dict[PermissionAction, _ActionRequirement] = {}

    def add(
        action: PermissionAction,
        domain: PermissionDomain,
        occurrence: PermissionOccurrence,
        reason_code: str,
        *sources: str,
    ) -> None:
        current = requirements.get(action)
        normalized_sources = tuple(sorted(set(sources)))
        if current is None or (
            current.occurrence is PermissionOccurrence.RUNTIME_DEPENDENT
            and occurrence is PermissionOccurrence.REQUIRED_BEFORE_START
        ):
            requirements[action] = _ActionRequirement(
                action=action,
                domain=domain,
                occurrence=occurrence,
                reason_code=reason_code,
                capability_sources=normalized_sources,
            )
            return
        requirements[action] = _ActionRequirement(
            action=current.action,
            domain=current.domain,
            occurrence=current.occurrence,
            reason_code=current.reason_code,
            capability_sources=tuple(
                sorted(set(current.capability_sources).union(normalized_sources))
            ),
        )

    capabilities = set(spec.capabilities)
    if route.workspace_identity_sha256 is not None:
        add(
            PermissionAction.WORKSPACE_READ,
            PermissionDomain.FILESYSTEM,
            PermissionOccurrence.REQUIRED_BEFORE_START,
            "workspace_route_selected",
            "harness.workspace",
        )
    if route.mode == "edit":
        add(
            PermissionAction.WORKSPACE_WRITE,
            PermissionDomain.FILESYSTEM,
            PermissionOccurrence.REQUIRED_BEFORE_START,
            "edit_route_selected",
            "route.mode.edit",
        )
    if (
        spec.kind == "agent-cli"
        or HarnessCapability.AGENT_CLI in capabilities
        or HarnessCapability.SHELL in capabilities
        or route.execution_transport is not ExecutionTransport.ONE_SHOT
    ):
        add(
            PermissionAction.PROCESS_SPAWN,
            PermissionDomain.COMMAND,
            PermissionOccurrence.REQUIRED_BEFORE_START,
            "harness_process_required",
            "harness.process",
        )
    if "local" not in spec.tags:
        add(
            PermissionAction.NETWORK_CONNECT,
            PermissionDomain.NETWORK,
            PermissionOccurrence.REQUIRED_BEFORE_START,
            "provider_route_required",
            "provider.route",
        )
    if route.workspace_identity_sha256 is not None:
        for action in (
            PermissionAction.GIT_APPLY,
            PermissionAction.GIT_BRANCH_CREATE,
            PermissionAction.GIT_COMMIT,
            PermissionAction.GIT_PUSH,
            PermissionAction.GITHUB_PULL_REQUEST_CREATE,
        ):
            add(
                action,
                PermissionDomain.GIT_GITHUB,
                PermissionOccurrence.RUNTIME_DEPENDENT,
                "runtime_git_intent_unknown",
                "workspace.git",
            )
    if extensions:
        add(
            PermissionAction.MCP_SERVER_START,
            PermissionDomain.INTEGRATION,
            PermissionOccurrence.RUNTIME_DEPENDENT,
            "selected_extension_server",
            "extension.mcp",
        )
        add(
            PermissionAction.MCP_TOOL_CALL,
            PermissionDomain.INTEGRATION,
            PermissionOccurrence.RUNTIME_DEPENDENT,
            "selected_extension_tool",
            "extension.mcp",
        )
        if any(item.transport == MCPTransport.STDIO.value for item in extensions):
            add(
                PermissionAction.PROCESS_SPAWN,
                PermissionDomain.COMMAND,
                PermissionOccurrence.REQUIRED_BEFORE_START,
                "stdio_extension_process",
                "extension.stdio",
            )
    for action in route.required_actions:
        add(
            action,
            _domain_for_action(action),
            PermissionOccurrence.REQUIRED_BEFORE_START,
            "explicit_route_requirement",
            "route.required_actions",
        )
    return tuple(requirements.values())


def _resolve_requirement(
    engine: PolicyEngine,
    profile: Any,
    route: PermissionRouteSnapshot,
    requirement: _ActionRequirement,
) -> PermissionOutcome:
    enforcement, owner = _enforcement_boundary(route, requirement)
    resolution = engine.resolve(
        requirement.action,
        profile=profile,
        context=PolicyContext(
            reason=requirement.reason_code,
            enforcement_owner=owner,
        ),
        enforcement=enforcement,
        consume_grant=False,
    )
    prediction = {
        PolicyDecision.ALLOW: PermissionPrediction.ALLOWED,
        PolicyDecision.ASK: PermissionPrediction.APPROVAL_REQUIRED,
        PolicyDecision.DENY: PermissionPrediction.DENIED,
    }[resolution.decision]
    return PermissionOutcome(
        domain=requirement.domain,
        action=requirement.action,
        prediction=prediction,
        occurrence=requirement.occurrence,
        policy_decision=resolution.decision,
        enforcement=resolution.enforcement,
        control_owner=owner,
        reason_code=requirement.reason_code,
        capability_sources=requirement.capability_sources,
    )


def _unpredictable_outcomes(
    route: PermissionRouteSnapshot,
    extensions: Sequence[ExtensionPermissionContract],
    *,
    provider_route_required: bool,
) -> list[PermissionOutcome]:
    outcomes: list[PermissionOutcome] = []
    if provider_route_required:
        outcomes.extend(
            (
                PermissionOutcome(
                    domain=PermissionDomain.SECRET,
                    action=None,
                    prediction=PermissionPrediction.UNKNOWN,
                    occurrence=PermissionOccurrence.PROVIDER_OWNED,
                    policy_decision=None,
                    enforcement=EnforcementLevel.ADVISORY_OR_UNOBSERVABLE,
                    control_owner="secret_reference_resolver_or_provider",
                    reason_code="secret_values_not_read_during_simulation",
                    capability_sources=("provider.authentication_reference",),
                ),
                PermissionOutcome(
                    domain=PermissionDomain.PROVIDER,
                    action=None,
                    prediction=PermissionPrediction.UNKNOWN,
                    occurrence=PermissionOccurrence.PROVIDER_OWNED,
                    policy_decision=None,
                    enforcement=EnforcementLevel.ADVISORY_OR_UNOBSERVABLE,
                    control_owner="selected_provider_runtime",
                    reason_code="provider_behavior_not_proven",
                    capability_sources=(
                        f"transport.{route.execution_transport.value}",
                    ),
                ),
            )
        )
    if extensions:
        outcomes.append(
            PermissionOutcome(
                domain=PermissionDomain.INTEGRATION,
                action=None,
                prediction=PermissionPrediction.UNKNOWN,
                occurrence=PermissionOccurrence.PROVIDER_OWNED,
                policy_decision=None,
                enforcement=EnforcementLevel.ADVISORY_OR_UNOBSERVABLE,
                control_owner="selected_extension_targets",
                reason_code="extension_runtime_behavior_not_proven",
                capability_sources=("extension.capability_snapshot",),
            )
        )
    if any(item.secret_reference_count for item in extensions):
        outcomes.append(
            PermissionOutcome(
                domain=PermissionDomain.SECRET,
                action=None,
                prediction=PermissionPrediction.UNKNOWN,
                occurrence=PermissionOccurrence.RUNTIME_DEPENDENT,
                policy_decision=None,
                enforcement=EnforcementLevel.ADVISORY_OR_UNOBSERVABLE,
                control_owner="extension_secret_reference_resolver",
                reason_code="extension_secret_resolution_runtime_dependent",
                capability_sources=("extension.secret.reference",),
            )
        )
    return outcomes


def _enforcement_boundary(
    route: PermissionRouteSnapshot,
    requirement: _ActionRequirement,
) -> tuple[EnforcementLevel, str]:
    if requirement.action in {
        PermissionAction.MCP_SERVER_START,
        PermissionAction.MCP_TOOL_CALL,
    }:
        return (
            EnforcementLevel.DELEGATED_TO_CLI_SANDBOX,
            "harness_policy_and_extension_target",
        )
    if requirement.domain in {
        PermissionDomain.FILESYSTEM,
        PermissionDomain.COMMAND,
        PermissionDomain.GIT_GITHUB,
    } and route.execution_transport in {
        ExecutionTransport.NATIVE_STRUCTURED,
        ExecutionTransport.NATIVE_TERMINAL,
    }:
        return (
            EnforcementLevel.DELEGATED_TO_CLI_SANDBOX,
            "harness_policy_and_provider_cli",
        )
    return EnforcementLevel.ENFORCED_BY_HARNESS, "harness_policy"


def _domain_for_action(action: PermissionAction) -> PermissionDomain:
    if action in {
        PermissionAction.WORKSPACE_READ,
        PermissionAction.WORKSPACE_WRITE,
    }:
        return PermissionDomain.FILESYSTEM
    if action is PermissionAction.PROCESS_SPAWN:
        return PermissionDomain.COMMAND
    if action is PermissionAction.NETWORK_CONNECT:
        return PermissionDomain.NETWORK
    if action in {
        PermissionAction.MCP_SERVER_START,
        PermissionAction.MCP_TOOL_CALL,
    }:
        return PermissionDomain.INTEGRATION
    if action in {
        PermissionAction.GIT_COMMIT,
        PermissionAction.GIT_PUSH,
        PermissionAction.GITHUB_PULL_REQUEST_CREATE,
        PermissionAction.GIT_APPLY,
        PermissionAction.GIT_BRANCH_CREATE,
    }:
        return PermissionDomain.GIT_GITHUB
    return PermissionDomain.PROVIDER


def _harness_contract(spec: HarnessSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "kind": spec.kind,
        "capabilities": sorted(item.value for item in spec.capabilities),
        "supports_workspace": spec.supports_workspace,
        "supports_native_sessions": spec.supports_native_sessions,
        "supports_streaming": spec.supports_streaming,
        "supports_structured_events": spec.supports_structured_events,
        "tags": sorted(spec.tags),
        "adapter_capabilities": {
            key: {
                "status": value.status.value,
                "detail_sha256": hashlib.sha256(
                    value.detail.encode("utf-8")
                ).hexdigest(),
            }
            for key, value in sorted(spec.adapter_capabilities.items())
        },
    }


def _json_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_hash(value: str, *, field_name: str) -> None:
    if len(value) != _HASH_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256")


def _safe_identity(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 256
        and all(character.isalnum() or character in "._:/@+~-" for character in value)
    )


__all__ = [
    "ExtensionPermissionContract",
    "PermissionDomain",
    "PermissionOccurrence",
    "PermissionOutcome",
    "PermissionPrediction",
    "PermissionRouteSnapshot",
    "PermissionSimulation",
    "build_permission_simulation",
    "extension_permission_contract",
]
