from pathlib import Path

import pytest

from gpt2giga_harness.agents import (
    agent_profile_to_dict,
    agent_run_payload,
    discover_agent_profiles,
    draft_agent_profile,
    load_agent_profile,
    parse_agent_profile,
    render_starter_agent,
)
from gpt2giga_harness.authoring import AuthoringConflictError, ProjectAuthoringService
from gpt2giga_harness.project import init_project_config


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

    payload = agent_run_payload(profile, "Review this patch", workspace=str(tmp_path))

    assert payload["agent_id"] == "reviewer"
    assert payload["agent_profile_snapshot"] == agent_profile_to_dict(profile)
    assert payload["max_attempts"] == 1
    assert payload["extra"]["memory_selectors"] == []
    assert payload["prompt"].endswith("Task:\nReview this patch")


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
