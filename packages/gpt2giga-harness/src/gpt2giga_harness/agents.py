"""Reusable project agent profiles and safe authoring helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

import yaml

from gpt2giga_harness.authoring import ProjectAuthoringService, ProjectFileDraft
from gpt2giga_harness.runtime.policy import permission_profile
from gpt2giga_harness.types import parse_api_mode, redact_secrets


AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
AGENT_DIRECTORY = Path(".giga") / "agents"
ALLOWED_MODES = {"plan", "read", "edit"}
ALLOWED_WORKSPACE_POLICIES = {"auto", "current", "worktree", "temp_copy"}
SECRET_KEY_PARTS = ("secret", "token", "password", "api_key", "apikey", "credential")


@dataclass(frozen=True)
class AgentBudgets:
    """Optional execution limits captured by a reusable profile."""

    timeout_seconds: int | None = None
    max_tokens: int | None = None
    max_attempts: int = 1
    max_concurrency: int = 1


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
    root = Path(project_root).resolve()
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
    path = Path(project_root).resolve() / AGENT_DIRECTORY / f"{agent_id}.yaml"
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise KeyError(agent_id) from exc
    profile = parse_agent_profile(
        content, source_path=path.relative_to(Path(project_root).resolve()).as_posix()
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
    return redact_secrets(asdict(profile))


def agent_run_payload(
    profile: AgentProfile, prompt: str, *, workspace: str
) -> dict[str, Any]:
    """Build a durable manual-run payload with an immutable redacted snapshot."""
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
        "timeout_seconds": profile.budgets.timeout_seconds,
        "max_attempts": profile.budgets.max_attempts,
        "extra": {
            "agent_id": profile.id,
            "tool_ids": list(profile.tool_ids),
            "tool_bindings": [
                {
                    "server_id": server_id,
                    "enforcement": "delegated_to_cli_sandbox",
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
        "budgets": {"max_attempts": 1, "max_concurrency": 1},
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _reject_secret_literals(value: Any, path: str = "profile") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower().replace("-", "_")
            if any(part in name for part in SECRET_KEY_PARTS) and item not in (
                None,
                "",
                [],
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
