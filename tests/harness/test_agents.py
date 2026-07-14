from dataclasses import replace
from pathlib import Path

import pytest

from gpt2giga_harness.agents import (
    AgentOptionStatus,
    agent_execution_plan_to_dict,
    agent_profile_to_dict,
    agent_run_payload,
    apply_agent_run_overrides,
    build_agent_execution_plan,
    discover_agent_profiles,
    draft_agent_profile,
    load_agent_profile,
    parse_agent_profile,
    render_starter_agent,
)
from gpt2giga_harness.authoring import AuthoringConflictError, ProjectAuthoringService
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.project import init_project_config
from gpt2giga_harness.types import HarnessCapability, HarnessSpec


class _Harness:
    def __init__(self, harness_id, capabilities=None):
        self.harness_id = harness_id
        self.capabilities = capabilities or {}

    def spec(self):
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind="agent-cli",
            description="fixture",
            capabilities=(HarnessCapability.AGENT_CLI,),
        )

    def capability_probe(self):
        return CliCapabilitySnapshot(
            harness_id=self.harness_id,
            status="supported",
            version="fixture 1.0.0",
            parsed_version="1.0.0",
            command=("fixture",),
            capabilities=self.capabilities,
            event_schema="fixture",
            history_schema="fixture",
            evidence="fixture capability probe",
        )


def test_init_creates_six_valid_starter_agents(tmp_path):
    init_project_config(tmp_path)

    profiles, errors = discover_agent_profiles(tmp_path)

    assert errors == ()
    assert {profile.id for profile in profiles} == {
        "planner",
        "explorer",
        "implementer",
        "reviewer",
        "test-runner",
        "release-assistant",
    }
    assert load_agent_profile(tmp_path, "implementer").workspace_policy == "worktree"


def test_agent_profile_rejects_secret_literals_and_unsafe_paths():
    secret = render_starter_agent("planner") + "api_key: sk-secret-value\n"
    embedded_secret = render_starter_agent("planner").replace(
        "Create a concise", "Use sk-123456789-secret then create a concise"
    )
    unsafe = render_starter_agent("planner") + "context_selectors: [../private]\n"

    with pytest.raises(ValueError, match="Secret literals"):
        parse_agent_profile(secret)
    with pytest.raises(ValueError, match="Secret-looking"):
        parse_agent_profile(embedded_secret)
    with pytest.raises(ValueError, match="Unsafe path"):
        parse_agent_profile(unsafe)


def test_authoring_draft_is_redacted_atomic_and_conflict_safe(tmp_path):
    content = render_starter_agent("planner")
    draft = draft_agent_profile(tmp_path, "planner", content)
    assert draft.source_hash
    assert ".giga/agents/planner.yaml" in draft.redacted_diff

    service = ProjectAuthoringService(tmp_path)
    applied_hash = service.apply(draft)
    assert applied_hash == load_agent_profile(tmp_path, "planner").source_hash

    changed = content.replace("Planner", "Changed Planner")
    stale = draft_agent_profile(tmp_path, "planner", changed)
    path = tmp_path / ".giga" / "agents" / "planner.yaml"
    path.write_text(content + "description: concurrent\n", encoding="utf-8")
    with pytest.raises(AuthoringConflictError):
        service.apply(stale)


def test_authoring_rejects_escape_and_profile_filename_mismatch(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        ProjectAuthoringService(tmp_path).draft(
            "../agent.yaml",
            render_starter_agent("planner"),
            validate=parse_agent_profile,
        )
    with pytest.raises(ValueError, match="filename"):
        draft_agent_profile(tmp_path, "reviewer", render_starter_agent("planner"))


def test_agent_run_payload_captures_immutable_profile_snapshot(tmp_path):
    profile = parse_agent_profile(render_starter_agent("reviewer"))

    payload = agent_run_payload(
        profile,
        "Review this patch",
        workspace=str(tmp_path),
        harness=_Harness("codex-cli"),
        default_timeout_seconds=3600,
    )

    assert payload["agent_id"] == "reviewer"
    assert payload["agent_profile_snapshot"] == agent_profile_to_dict(profile)
    assert payload["max_attempts"] == 1
    assert payload["agent_execution_plan"]["queueable"] is True
    assert payload["agent_execution_plan"]["options"]["model"]["status"] == (
        "effective"
    )
    assert (
        payload["agent_execution_plan"]["options"]["budgets.timeout_seconds"][
            "effective"
        ]
        == 3600
    )
    assert payload["extra"]["memory_selectors"] == []
    assert payload["prompt"].endswith("Task:\nReview this patch")


@pytest.mark.parametrize(
    ("harness_id", "capabilities", "profile_patch", "expected_adapter_options"),
    (
        (
            "codex-cli",
            {"--config": True},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "high"},
        ),
        (
            "claude-code",
            {"--effort": True, "--allowedTools": True, "--disallowedTools": True},
            {
                "reasoning_effort": "medium",
                "allowed_tools": ("Read", "Bash(git status)"),
                "disallowed_tools": ("Edit",),
            },
            {
                "reasoning_effort": "medium",
                "allowed_tools": ["Read", "Bash(git status)"],
                "disallowed_tools": ["Edit"],
            },
        ),
        ("gemini-cli", {}, {}, {}),
    ),
)
def test_profile_options_resolve_to_version_proven_execution_plan(
    harness_id, capabilities, profile_patch, expected_adapter_options
):
    profile = replace(
        parse_agent_profile(render_starter_agent("reviewer")),
        harness_id=harness_id,
        **profile_patch,
    )

    plan = build_agent_execution_plan(
        profile,
        _Harness(harness_id, capabilities),
        default_timeout_seconds=900,
    )
    payload = agent_execution_plan_to_dict(plan)

    assert plan.queueable is True
    assert plan.adapter_options == expected_adapter_options
    assert plan.options["model"].status is AgentOptionStatus.EFFECTIVE
    assert plan.options["mode"].status is AgentOptionStatus.EFFECTIVE
    assert plan.options["budgets.max_attempts"].effective == 1
    assert payload["options"]["permission_profile"]["enforcement_source"] == (
        "harness_policy"
    )


@pytest.mark.parametrize(
    "profile",
    (
        replace(
            parse_agent_profile(render_starter_agent("reviewer")),
            harness_id="gemini-cli",
            reasoning_effort="high",
        ),
        replace(
            parse_agent_profile(render_starter_agent("reviewer")),
            budgets=replace(
                parse_agent_profile(render_starter_agent("reviewer")).budgets,
                max_tokens=512,
            ),
        ),
        replace(
            parse_agent_profile(render_starter_agent("reviewer")),
            budgets=replace(
                parse_agent_profile(render_starter_agent("reviewer")).budgets,
                max_concurrency=2,
            ),
        ),
    ),
)
def test_unsupported_profile_options_fail_before_queueing(profile):
    harness = _Harness(profile.harness_id)

    with pytest.raises(ValueError, match="not executable"):
        agent_run_payload(profile, "Review", workspace=".", harness=harness)


def test_profile_warns_when_context_and_managed_tools_are_provenance_only():
    profile = replace(
        parse_agent_profile(render_starter_agent("reviewer")),
        context_selectors=("src",),
        tool_ids=("reviewed-mcp",),
    )

    plan = build_agent_execution_plan(profile, _Harness("codex-cli"))

    assert plan.queueable is True
    assert plan.options["context_selectors"].status is AgentOptionStatus.UNSUPPORTED
    assert plan.options["tool_ids"].status is AgentOptionStatus.UNSUPPORTED
    assert len(plan.warnings) == 2


def test_workflow_overrides_preserve_requested_and_record_effective_values():
    profile = parse_agent_profile(render_starter_agent("reviewer"))
    payload = agent_run_payload(
        profile,
        "Review",
        workspace=".",
        harness=_Harness("codex-cli"),
    )

    overridden = apply_agent_run_overrides(
        payload,
        workspace_policy="worktree",
        permission_profile="unattended",
        timeout_seconds=30,
        max_attempts=3,
    )
    options = overridden["agent_execution_plan"]["options"]

    assert options["workspace_policy"]["requested"] == "auto"
    assert options["workspace_policy"]["effective"] == "worktree"
    assert options["permission_profile"]["effective"] == "unattended"
    assert options["budgets.timeout_seconds"]["effective"] == 30
    assert options["budgets.max_attempts"]["effective"] == 3
    assert (
        overridden["extra"]["agent_execution_plan"]
        == overridden["agent_execution_plan"]
    )


def test_profile_parses_token_budget_and_rejects_flag_shaped_tool_selector():
    content = render_starter_agent("reviewer").replace(
        "budgets:\n",
        "budgets:\n  max_tokens: 512\n",
    )
    profile = parse_agent_profile(content)
    assert profile.budgets.max_tokens == 512
    assert agent_profile_to_dict(profile)["budgets"]["max_tokens"] == 512

    unsafe = render_starter_agent("reviewer").replace(
        "allowed_tools: []",
        "allowed_tools: [--dangerously-skip-permissions]",
    )
    with pytest.raises(ValueError, match="Unsafe tool selector"):
        parse_agent_profile(unsafe)


def test_discovery_keeps_valid_profiles_when_one_is_invalid(tmp_path):
    directory = tmp_path / ".giga" / "agents"
    directory.mkdir(parents=True)
    (directory / "planner.yaml").write_text(
        render_starter_agent("planner"), encoding="utf-8"
    )
    (directory / "broken.yaml").write_text("id: broken\n", encoding="utf-8")

    profiles, errors = discover_agent_profiles(tmp_path)

    assert [profile.id for profile in profiles] == ["planner"]
    assert len(errors) == 1
    assert Path(errors[0].path).name == "broken.yaml"
