from gpt2giga.harness.project import ProjectToolProfile
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.tool_profiles import (
    build_tool_profile_statuses,
    tool_profile_status_to_dict,
)


def test_tool_profile_status_generates_redacted_dry_run_previews():
    registry = create_default_registry(include_entry_points=False)
    profile = ProjectToolProfile(
        enabled=True,
        title="GitHub",
        description="Project tracker",
        harnesses=("codex-cli", "claude-code"),
        config={"header": "Bearer abcdefghijk", "readonly": True},
    )

    statuses = build_tool_profile_statuses(
        {"github": profile},
        registry,
        include_previews=True,
    )

    payload = tool_profile_status_to_dict(statuses[0])

    assert payload["profile"]["config"]["header"] == "<redacted>"
    assert [item["harness_id"] for item in payload["harnesses"]] == [
        "codex-cli",
        "claude-code",
    ]
    assert {item["status"] for item in payload["harnesses"]} == {"ready"}
    codex_preview = payload["harnesses"][0]["preview"]
    assert codex_preview["mcp_servers"]["github"]["config"]["header"] == "<redacted>"
    claude_preview = payload["harnesses"][1]["preview"]
    assert "mcpServers" in claude_preview


def test_tool_profile_status_reports_disabled_and_unsupported_targets():
    registry = create_default_registry(include_entry_points=False)
    profile = ProjectToolProfile(
        enabled=False,
        title="Internal",
        harnesses=("direct-chat", "missing-cli"),
    )

    statuses = build_tool_profile_statuses(
        {"internal": profile},
        registry,
        include_previews=True,
    )

    payload = tool_profile_status_to_dict(statuses[0])

    by_harness = {item["harness_id"]: item for item in payload["harnesses"]}
    assert by_harness["direct-chat"]["status"] == "disabled"
    assert by_harness["missing-cli"]["status"] == "missing"
    assert payload["warnings"] == []
