"""Reusable project agent profiles and safe authoring helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

import yaml

from gpt2giga_harness.authoring import ProjectAuthoringService, ProjectFileDraft
from gpt2giga_harness.runtime.policy import permission_profile
from gpt2giga_harness.safe_paths import resolve_operator_path, resolve_path_within
from gpt2giga_harness.types import parse_api_mode, redact_secrets


AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
AGENT_DIRECTORY = Path(".giga") / "agents"
ALLOWED_MODES = {"plan", "read", "edit"}
ALLOWED_WORKSPACE_POLICIES = {"auto", "current", "worktree", "temp_copy"}
SECRET_KEY_PARTS = ("secret", "token", "password", "api_key", "apikey", "credential")
NON_SECRET_PROFILE_KEYS = {"max_tokens"}


@dataclass(frozen=True)
class AgentBudgets:
    """Optional execution limits captured by a reusable profile."""

    timeout_seconds: int | None = None
    max_tokens: int | None = None
    max_attempts: int = 1
    max_concurrency: int = 1


class AgentOptionStatus(str, Enum):
    """Explain whether one requested profile option reaches execution."""

    EFFECTIVE = "effective"
    DELEGATED = "delegated"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class AgentOptionResolution:
    """Requested and effective value plus its enforcement boundary."""

    status: AgentOptionStatus
    requested: Any
    effective: Any
    enforcement_source: str
    detail: str


@dataclass(frozen=True)
class AgentExecutionPlan:
    """Redaction-safe operational interpretation of one AgentProfile."""

    schema_version: int
    harness_id: str
    invocation_mode: str
    options: Mapping[str, AgentOptionResolution]
    adapter_options: Mapping[str, Any]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    binary_version: str | None = None
    capability_evidence: str | None = None

    @property
    def queueable(self) -> bool:
        """Return whether the profile may be submitted without silent drift."""
        return not self.errors


@dataclass(frozen=True)
class AgentProfile:
    """Validated reusable role over an existing harness."""

    id: str
    title: str
    description: str
    schema_version: int
    harness_id: str
    instructions: str
    model: str | None = None
    reasoning_effort: str | None = None
    api_mode: str = "v2"
    invocation_mode: str = "headless"
    mode: str = "plan"
    workspace_policy: str = "auto"
    permission_profile: str = "interactive"
    prompt_files: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    memory_selectors: tuple[str, ...] = ()
    context_selectors: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    budgets: AgentBudgets = field(default_factory=AgentBudgets)
    expected_artifact: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    source_path: str | None = None
    source_hash: str | None = None


@dataclass(frozen=True)
class AgentProfileLoadError:
    """One invalid project profile discovered without hiding valid profiles."""

    path: str
    error: str


STARTER_AGENT_PROFILES: Mapping[str, Mapping[str, Any]] = {
    "planner": {
        "title": "Planner",
        "mode": "plan",
        "instructions": "Create a concise, evidence-backed implementation plan before changes.",
    },
    "explorer": {
        "title": "Explorer",
        "mode": "read",
        "instructions": "Explore the project and report concrete code paths, constraints, and risks.",
    },
    "implementer": {
        "title": "Implementer",
        "mode": "edit",
        "workspace_policy": "worktree",
        "instructions": "Implement the requested change in the smallest safe slice and verify it.",
    },
    "reviewer": {
        "title": "Reviewer",
        "mode": "read",
        "instructions": "Review changes for bugs, regressions, security risks, and missing tests.",
    },
    "test-runner": {
        "title": "Test Runner",
        "mode": "read",
        "instructions": "Run focused verification, diagnose failures, and report reproducible evidence.",
    },
    "release-assistant": {
        "title": "Release Assistant",
        "mode": "plan",
        "instructions": "Prepare release notes, compatibility checks, and a safe release checklist.",
    },
}


def parse_agent_profile(
    content: str, *, source_path: str | None = None
) -> AgentProfile:
    """Parse one strict, secret-free AgentProfile YAML document."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError("Invalid agent profile YAML") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Agent profile must be a YAML mapping")
    _reject_secret_literals(data)
    allowed = {
        "id",
        "title",
        "description",
        "schema_version",
        "harness_id",
        "instructions",
        "model",
        "reasoning_effort",
        "api_mode",
        "invocation_mode",
        "mode",
        "workspace_policy",
        "permission_profile",
        "prompt_files",
        "skills",
        "memory_selectors",
        "context_selectors",
        "tool_ids",
        "allowed_tools",
        "disallowed_tools",
        "budgets",
        "expected_artifact",
        "provenance",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"Unknown agent profile fields: {', '.join(unknown)}")
    agent_id = _required_text(data.get("id"), "id")
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise ValueError("Agent id must match ^[a-z][a-z0-9_-]{1,63}$")
    mode = str(data.get("mode") or "plan")
    if mode not in ALLOWED_MODES:
        raise ValueError(f"Unsupported agent mode: {mode}")
    workspace_policy = str(data.get("workspace_policy") or "auto")
    if workspace_policy not in ALLOWED_WORKSPACE_POLICIES:
        raise ValueError(f"Unsupported workspace policy: {workspace_policy}")
    api_mode = parse_api_mode(data.get("api_mode") or "v2").value
    invocation_mode = str(data.get("invocation_mode") or "headless")
    if invocation_mode not in {"headless", "native"}:
        raise ValueError(f"Unsupported invocation mode: {invocation_mode}")
    selected_permission = permission_profile(
        data.get("permission_profile") or "interactive"
    )
    budget_data = data.get("budgets") or {}
    if not isinstance(budget_data, Mapping):
        raise ValueError("Agent budgets must be a mapping")
    budgets = AgentBudgets(
        timeout_seconds=_optional_positive_int(
            budget_data.get("timeout_seconds"), "timeout_seconds"
        ),
        max_tokens=_optional_positive_int(budget_data.get("max_tokens"), "max_tokens"),
        max_attempts=_positive_int(budget_data.get("max_attempts", 1), "max_attempts"),
        max_concurrency=_positive_int(
            budget_data.get("max_concurrency", 1), "max_concurrency"
        ),
    )
    reasoning_effort = _optional_text(data.get("reasoning_effort"))
    if reasoning_effort not in {None, "none", "low", "medium", "high"}:
        raise ValueError("Unsupported reasoning_effort")
    return AgentProfile(
        id=agent_id,
        title=_required_text(data.get("title"), "title"),
        description=str(data.get("description") or "").strip(),
        schema_version=_positive_int(data.get("schema_version", 1), "schema_version"),
        harness_id=_required_text(data.get("harness_id"), "harness_id"),
        instructions=_required_text(data.get("instructions"), "instructions"),
        model=_optional_text(data.get("model")),
        reasoning_effort=reasoning_effort,
        api_mode=api_mode,
        invocation_mode=invocation_mode,
        mode=mode,
        workspace_policy=workspace_policy,
        permission_profile=selected_permission.id,
        prompt_files=_safe_paths(data.get("prompt_files"), "prompt_files"),
        skills=_text_tuple(data.get("skills"), "skills"),
        memory_selectors=_text_tuple(data.get("memory_selectors"), "memory_selectors"),
        context_selectors=_safe_paths(
            data.get("context_selectors"), "context_selectors"
        ),
        tool_ids=_text_tuple(data.get("tool_ids"), "tool_ids"),
        allowed_tools=_tool_selectors(data.get("allowed_tools"), "allowed_tools"),
        disallowed_tools=_tool_selectors(
            data.get("disallowed_tools"), "disallowed_tools"
        ),
        budgets=budgets,
        expected_artifact=_optional_text(data.get("expected_artifact")),
        provenance=dict(_profile_mapping(data.get("provenance"))),
        source_path=source_path,
        source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def discover_agent_profiles(
    project_root: str | Path,
) -> tuple[tuple[AgentProfile, ...], tuple[AgentProfileLoadError, ...]]:
    """Load all project profiles while reporting invalid files independently."""
    root = resolve_operator_path(project_root)
    directory = root / AGENT_DIRECTORY
    profiles: list[AgentProfile] = []
    errors: list[AgentProfileLoadError] = []
    for path in sorted((*directory.glob("*.yaml"), *directory.glob("*.yml"))):
        relative = path.relative_to(root).as_posix()
        try:
            profile = parse_agent_profile(
                path.read_text(encoding="utf-8"), source_path=relative
            )
            if path.stem != profile.id:
                raise ValueError("Agent filename must match its id")
            profiles.append(profile)
        except (OSError, ValueError) as exc:
            errors.append(AgentProfileLoadError(path=relative, error=str(exc)))
    return tuple(profiles), tuple(errors)


def load_agent_profile(project_root: str | Path, agent_id: str) -> AgentProfile:
    """Load one profile by safe id."""
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise KeyError(agent_id)
    root = resolve_operator_path(project_root)
    path = resolve_path_within(root, AGENT_DIRECTORY / f"{agent_id}.yaml")
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise KeyError(agent_id) from exc
    profile = parse_agent_profile(
        content, source_path=path.relative_to(root).as_posix()
    )
    if profile.id != agent_id:
        raise ValueError("Agent filename must match its id")
    return profile


def draft_agent_profile(
    project_root: str | Path,
    agent_id: str,
    content: str,
    *,
    expected_hash: str | None = None,
) -> ProjectFileDraft[AgentProfile]:
    """Validate and preview an agent profile through the shared authoring service."""
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise ValueError("Invalid agent id")
    relative = AGENT_DIRECTORY / f"{agent_id}.yaml"
    service = ProjectAuthoringService(project_root)
    draft = service.draft(
        relative,
        content,
        validate=lambda value: parse_agent_profile(
            value, source_path=relative.as_posix()
        ),
        expected_hash=expected_hash,
    )
    if draft.value.id != agent_id:
        raise ValueError("Agent filename must match its id")
    return draft


def agent_profile_to_dict(profile: AgentProfile) -> dict[str, Any]:
    """Serialize a profile or immutable run snapshot."""
    payload = asdict(profile)
    redacted = dict(redact_secrets(payload))
    budgets = redacted.get("budgets")
    if isinstance(budgets, Mapping):
        redacted["budgets"] = {
            **dict(budgets),
            "max_tokens": profile.budgets.max_tokens,
        }
    return redacted


def agent_execution_plan_to_dict(plan: AgentExecutionPlan) -> dict[str, Any]:
    """Serialize one immutable option plan without exposing probe commands."""
    payload = {
        "schema_version": plan.schema_version,
        "harness_id": plan.harness_id,
        "invocation_mode": plan.invocation_mode,
        "queueable": plan.queueable,
        "binary_version": plan.binary_version,
        "capability_evidence": plan.capability_evidence,
        "options": {
            name: {
                "status": resolution.status.value,
                "requested": resolution.requested,
                "effective": resolution.effective,
                "enforcement_source": resolution.enforcement_source,
                "detail": resolution.detail,
            }
            for name, resolution in plan.options.items()
        },
        "adapter_options": dict(plan.adapter_options),
        "errors": list(plan.errors),
        "warnings": list(plan.warnings),
    }
    redacted = dict(redact_secrets(payload))
    options = redacted.get("options")
    token_resolution = plan.options.get("budgets.max_tokens")
    if isinstance(options, Mapping) and token_resolution is not None:
        redacted["options"] = {
            **dict(options),
            "budgets.max_tokens": {
                "status": token_resolution.status.value,
                "requested": token_resolution.requested,
                "effective": token_resolution.effective,
                "enforcement_source": token_resolution.enforcement_source,
                "detail": token_resolution.detail,
            },
        }
    return redacted


def build_agent_execution_plan(
    profile: AgentProfile,
    harness: Any,
    *,
    default_timeout_seconds: float | None = None,
) -> AgentExecutionPlan:
    """Resolve requested profile fields against one adapter capability snapshot."""
    spec = harness.spec()
    if spec.id != profile.harness_id:
        raise ValueError(
            f"Agent profile harness {profile.harness_id} does not match {spec.id}"
        )
    options: dict[str, AgentOptionResolution] = {}
    adapter_options: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    def add(
        name: str,
        *,
        status: AgentOptionStatus,
        requested: Any,
        effective: Any,
        source: str,
        detail: str,
    ) -> None:
        options[name] = AgentOptionResolution(
            status=status,
            requested=requested,
            effective=effective,
            enforcement_source=source,
            detail=detail,
        )

    add(
        "instructions",
        status=AgentOptionStatus.EFFECTIVE,
        requested=profile.instructions,
        effective="prepended_to_user_prompt",
        source="harness_prompt",
        detail="Harness prepends the immutable role instructions to the submitted task.",
    )
    add(
        "model",
        status=AgentOptionStatus.EFFECTIVE,
        requested=profile.model,
        effective=profile.model or "runtime_default",
        source="adapter_cli",
        detail="The adapter pins the selected model through fixed argv or environment.",
    )
    add(
        "api_mode",
        status=AgentOptionStatus.EFFECTIVE,
        requested=profile.api_mode,
        effective=profile.api_mode,
        source="harness_proxy",
        detail="Harness selects and preflights the exact compatibility route.",
    )
    if profile.invocation_mode == "headless":
        add(
            "invocation_mode",
            status=AgentOptionStatus.EFFECTIVE,
            requested=profile.invocation_mode,
            effective="headless",
            source="durable_job",
            detail="Agent runs are submitted through the durable headless worker.",
        )
    else:
        message = "AgentProfile durable runs do not support native invocation mode."
        errors.append(message)
        add(
            "invocation_mode",
            status=AgentOptionStatus.UNSUPPORTED,
            requested=profile.invocation_mode,
            effective=None,
            source="unsupported",
            detail=message,
        )
    for name, requested, effective, source, detail in (
        (
            "mode",
            profile.mode,
            profile.mode,
            "harness_policy_and_adapter_cli",
            "Harness policy and the adapter permission mode both receive this value.",
        ),
        (
            "workspace_policy",
            profile.workspace_policy,
            profile.workspace_policy,
            "harness_workspace",
            "Harness prepares the effective workspace before process spawn.",
        ),
        (
            "permission_profile",
            profile.permission_profile,
            profile.permission_profile,
            "harness_policy",
            "The durable dispatcher resolves this named approval policy.",
        ),
    ):
        add(
            name,
            status=AgentOptionStatus.EFFECTIVE,
            requested=requested,
            effective=effective,
            source=source,
            detail=detail,
        )

    requested_timeout = profile.budgets.timeout_seconds
    add(
        "budgets.timeout_seconds",
        status=AgentOptionStatus.EFFECTIVE,
        requested=requested_timeout,
        effective=(
            requested_timeout
            if requested_timeout is not None
            else default_timeout_seconds or "runtime_default"
        ),
        source="durable_job_monitor",
        detail="The worker cancels the attempt after the effective wall-clock timeout.",
    )
    add(
        "budgets.max_attempts",
        status=AgentOptionStatus.EFFECTIVE,
        requested=profile.budgets.max_attempts,
        effective=profile.budgets.max_attempts,
        source="durable_job_retry",
        detail="The coordination store caps logical job attempts at this value.",
    )
    if profile.budgets.max_concurrency == 1:
        add(
            "budgets.max_concurrency",
            status=AgentOptionStatus.EFFECTIVE,
            requested=1,
            effective=1,
            source="single_agent_run",
            detail="A standalone AgentProfile run owns one durable child at a time.",
        )
    else:
        message = (
            "AgentProfile max_concurrency above 1 requires a Workflow or Schedule "
            "coordinator and cannot be applied to a standalone agent run."
        )
        errors.append(message)
        add(
            "budgets.max_concurrency",
            status=AgentOptionStatus.UNSUPPORTED,
            requested=profile.budgets.max_concurrency,
            effective=None,
            source="unsupported",
            detail=message,
        )
    if profile.budgets.max_tokens is None:
        add(
            "budgets.max_tokens",
            status=AgentOptionStatus.EFFECTIVE,
            requested=None,
            effective=None,
            source="not_requested",
            detail="No token limit was requested.",
        )
    else:
        message = (
            f"{profile.harness_id} does not expose a version-proven headless token "
            "limit; max_tokens cannot be enforced."
        )
        errors.append(message)
        add(
            "budgets.max_tokens",
            status=AgentOptionStatus.UNSUPPORTED,
            requested=profile.budgets.max_tokens,
            effective=None,
            source="unsupported",
            detail=message,
        )

    probe = None
    needs_probe = bool(
        profile.reasoning_effort or profile.allowed_tools or profile.disallowed_tools
    )
    if needs_probe:
        capability_probe = getattr(harness, "capability_probe", None)
        probe = capability_probe() if callable(capability_probe) else None
    probe_capabilities = (
        dict(probe.capabilities) if probe is not None and probe.compatible else {}
    )
    reasoning_token = {
        "codex-cli": "--config",
        "claude-code": "--effort",
    }.get(profile.harness_id)
    supported_reasoning = {
        "codex-cli": {"none", "low", "medium", "high"},
        "claude-code": {"low", "medium", "high"},
    }.get(profile.harness_id, set())
    if profile.reasoning_effort is None:
        add(
            "reasoning_effort",
            status=AgentOptionStatus.EFFECTIVE,
            requested=None,
            effective=None,
            source="not_requested",
            detail="No reasoning effort override was requested.",
        )
    elif (
        reasoning_token is not None
        and profile.reasoning_effort in supported_reasoning
        and probe_capabilities.get(reasoning_token)
    ):
        adapter_options["reasoning_effort"] = profile.reasoning_effort
        add(
            "reasoning_effort",
            status=AgentOptionStatus.EFFECTIVE,
            requested=profile.reasoning_effort,
            effective=profile.reasoning_effort,
            source="adapter_cli",
            detail=(
                "Applied through a fixed adapter option proven by the installed "
                "CLI capability probe."
            ),
        )
    else:
        version = getattr(probe, "version", None) or "unproven version"
        message = (
            f"{profile.harness_id} {version} cannot apply reasoning_effort="
            f"{profile.reasoning_effort!r} through a proven adapter option."
        )
        errors.append(message)
        add(
            "reasoning_effort",
            status=AgentOptionStatus.UNSUPPORTED,
            requested=profile.reasoning_effort,
            effective=None,
            source="unsupported",
            detail=message,
        )

    for field_name, values, token in (
        ("allowed_tools", profile.allowed_tools, "--allowedTools"),
        ("disallowed_tools", profile.disallowed_tools, "--disallowedTools"),
    ):
        if not values:
            add(
                field_name,
                status=AgentOptionStatus.EFFECTIVE,
                requested=[],
                effective=[],
                source="not_requested",
                detail=f"No {field_name} restriction was requested.",
            )
        elif profile.harness_id == "claude-code" and probe_capabilities.get(token):
            adapter_options[field_name] = list(values)
            add(
                field_name,
                status=AgentOptionStatus.EFFECTIVE,
                requested=list(values),
                effective=list(values),
                source="adapter_cli",
                detail=(
                    "Applied through a fixed Claude Code tool restriction flag proven "
                    "by the installed CLI capability probe."
                ),
            )
        else:
            version = getattr(probe, "version", None) or "unproven version"
            message = (
                f"{profile.harness_id} {version} cannot apply {field_name} through "
                "a proven safe adapter option."
            )
            errors.append(message)
            add(
                field_name,
                status=AgentOptionStatus.UNSUPPORTED,
                requested=list(values),
                effective=None,
                source="unsupported",
                detail=message,
            )

    deferred_fields = (
        ("prompt_files", profile.prompt_files),
        ("skills", profile.skills),
        ("memory_selectors", profile.memory_selectors),
        ("context_selectors", profile.context_selectors),
        ("tool_ids", profile.tool_ids),
    )
    for name, values in deferred_fields:
        if values:
            message = (
                f"{name} are preserved in provenance but are not materialized into "
                "the current headless adapter process."
            )
            warnings.append(message)
            add(
                name,
                status=AgentOptionStatus.UNSUPPORTED,
                requested=list(values),
                effective=None,
                source="provenance_only",
                detail=message,
            )
        else:
            add(
                name,
                status=AgentOptionStatus.EFFECTIVE,
                requested=[],
                effective=[],
                source="not_requested",
                detail=f"No {name} values were requested.",
            )
    add(
        "expected_artifact",
        status=(
            AgentOptionStatus.DELEGATED
            if profile.expected_artifact is not None
            else AgentOptionStatus.EFFECTIVE
        ),
        requested=profile.expected_artifact,
        effective=profile.expected_artifact,
        source=(
            "workflow_orchestration"
            if profile.expected_artifact is not None
            else "not_requested"
        ),
        detail=(
            "Workflow projection interprets this expected artifact; the external CLI "
            "does not enforce it."
            if profile.expected_artifact is not None
            else "No expected artifact contract was requested."
        ),
    )
    return AgentExecutionPlan(
        schema_version=1,
        harness_id=profile.harness_id,
        invocation_mode=profile.invocation_mode,
        options=options,
        adapter_options=adapter_options,
        errors=tuple(errors),
        warnings=tuple(warnings),
        binary_version=getattr(probe, "version", None),
        capability_evidence=getattr(probe, "evidence", None),
    )


def agent_run_payload(
    profile: AgentProfile,
    prompt: str,
    *,
    workspace: str,
    harness: Any,
    default_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Build a durable manual-run payload with an immutable redacted snapshot."""
    execution_plan = build_agent_execution_plan(
        profile,
        harness,
        default_timeout_seconds=default_timeout_seconds,
    )
    if not execution_plan.queueable:
        raise ValueError(
            "Agent profile options are not executable: "
            + "; ".join(execution_plan.errors)
        )
    execution_plan_payload = agent_execution_plan_to_dict(execution_plan)
    effective_prompt = (
        f"Agent role instructions:\n{profile.instructions}\n\nTask:\n{prompt.strip()}"
    )
    return {
        "prompt": effective_prompt,
        "harness_id": profile.harness_id,
        "model": profile.model,
        "api_mode": profile.api_mode,
        "invocation_mode": profile.invocation_mode,
        "mode": profile.mode,
        "workspace_policy": profile.workspace_policy,
        "workspace": workspace,
        "permission_profile": profile.permission_profile,
        "agent_id": profile.id,
        "agent_profile_snapshot": agent_profile_to_dict(profile),
        "agent_execution_plan": execution_plan_payload,
        "timeout_seconds": profile.budgets.timeout_seconds,
        "max_attempts": profile.budgets.max_attempts,
        "extra": {
            "agent_id": profile.id,
            "agent_execution_plan": execution_plan_payload,
            "agent_adapter_options": dict(execution_plan.adapter_options),
            "tool_ids": list(profile.tool_ids),
            "tool_bindings": [
                {
                    "server_id": server_id,
                    "enforcement": "provenance_only_until_headless_snapshot",
                    "observability": "opaque_unless_structured_adapter",
                }
                for server_id in profile.tool_ids
            ],
            "skills": list(profile.skills),
            "prompt_files": list(profile.prompt_files),
            "memory_selectors": list(profile.memory_selectors),
            "context_selectors": list(profile.context_selectors),
            "max_tokens": profile.budgets.max_tokens,
            "reasoning_effort": profile.reasoning_effort,
            "max_concurrency": profile.budgets.max_concurrency,
            "expected_artifact": profile.expected_artifact,
        },
    }


def apply_agent_run_overrides(
    payload: Mapping[str, Any],
    *,
    workspace_policy: str,
    permission_profile: str,
    timeout_seconds: int | float | None,
    max_attempts: int,
) -> dict[str, Any]:
    """Keep a persisted AgentProfile plan aligned with coordinator overrides."""
    prepared = dict(payload)
    prepared.update(
        {
            "workspace_policy": workspace_policy,
            "permission_profile": permission_profile,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
    )
    source_plan = payload.get("agent_execution_plan")
    if not isinstance(source_plan, Mapping):
        return prepared
    plan = dict(source_plan)
    source_options = plan.get("options")
    options = (
        {
            name: dict(value)
            for name, value in source_options.items()
            if isinstance(value, Mapping)
        }
        if isinstance(source_options, Mapping)
        else {}
    )
    for name, effective in (
        ("workspace_policy", workspace_policy),
        ("permission_profile", permission_profile),
        ("budgets.timeout_seconds", timeout_seconds),
        ("budgets.max_attempts", max_attempts),
    ):
        resolution = options.get(name)
        if resolution is None:
            continue
        resolution.update(
            {
                "status": AgentOptionStatus.EFFECTIVE.value,
                "effective": effective,
                "enforcement_source": "workflow_or_schedule_coordinator",
                "detail": (
                    "The coordinator overrides this value for the concrete child job "
                    "while preserving the profile request."
                ),
            }
        )
    plan["options"] = options
    prepared["agent_execution_plan"] = plan
    extra = dict(payload.get("extra") or {})
    extra["agent_execution_plan"] = plan
    prepared["extra"] = extra
    return prepared


def render_starter_agent(agent_id: str, *, harness_id: str = "codex-cli") -> str:
    """Render one deterministic starter AgentProfile YAML document."""
    item = STARTER_AGENT_PROFILES[agent_id]
    payload = {
        "id": agent_id,
        "title": item["title"],
        "description": f"Starter {item['title']} profile.",
        "schema_version": 1,
        "harness_id": harness_id,
        "instructions": item["instructions"],
        "api_mode": "v2",
        "invocation_mode": "headless",
        "mode": item["mode"],
        "workspace_policy": item.get("workspace_policy", "auto"),
        "permission_profile": "interactive",
        "tool_ids": [],
        "allowed_tools": [],
        "disallowed_tools": [],
        "budgets": {"max_attempts": 1, "max_concurrency": 1},
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _reject_secret_literals(value: Any, path: str = "profile") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower().replace("-", "_")
            if (
                name not in NON_SECRET_PROFILE_KEYS
                and any(part in name for part in SECRET_KEY_PARTS)
                and item
                not in (
                    None,
                    "",
                    [],
                )
            ):
                raise ValueError(
                    f"Secret literals are not allowed in agent profiles: {path}.{key}"
                )
            _reject_secret_literals(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_literals(item, f"{path}[{index}]")
    elif isinstance(value, str) and redact_secrets(value) != value:
        raise ValueError(
            f"Secret-looking values are not allowed in agent profiles: {path}"
        )


def _safe_paths(value: Any, field_name: str) -> tuple[str, ...]:
    paths = _text_tuple(value, field_name)
    for item in paths:
        path = PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or item.startswith("~"):
            raise ValueError(f"Unsafe path in {field_name}: {item}")
    return paths


def _text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _tool_selectors(value: Any, field_name: str) -> tuple[str, ...]:
    selectors = _text_tuple(value, field_name)
    for selector in selectors:
        if (
            len(selector) > 200
            or selector.startswith("-")
            or "\x00" in selector
            or "\n" in selector
            or "\r" in selector
        ):
            raise ValueError(f"Unsafe tool selector in {field_name}: {selector!r}")
    return selectors


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Agent {field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _profile_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Agent provenance must be a mapping")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if number < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return number


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    return None if value is None else _positive_int(value, field_name)
