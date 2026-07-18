import json

from fastapi.testclient import TestClient

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


def test_handoff_preview_api_returns_documented_plan_without_provider_state(
    tmp_path, monkeypatch
):
    registry = create_default_registry(include_entry_points=False)
    _install_ready_claude_probe(registry, monkeypatch)
    client = TestClient(
        create_app(HarnessConfig(data_dir=str(tmp_path)), registry=registry)
    )

    response = client.get(
        "/api/provider-handoffs/claude-code/preview",
        params={"action": "launch_new", "workspace": str(tmp_path)},
    )

    assert response.status_code == 200
    handoff = response.json()["handoff"]
    assert handoff["action"] == "launch_new"
    assert handoff["command"] == ["/opt/homebrew/bin/claude", "--remote-control"]
    assert handoff["workspace"] == str(tmp_path)
    assert handoff["ownership"] == "provider_owned"
    assert handoff["auth_prerequisite"] == "claude_ai_full_scope_login"
    assert handoff["external_process_may_open"] is True
    assert handoff["machine_executable"] is False
    assert handoff["durable"] is False
    assert handoff["queueable"] is False
    assert "session_url" not in json.dumps(handoff)
    assert "provider_session_id" not in handoff


def test_harness_projection_distinguishes_handoff_and_blocked_embedding(
    tmp_path, monkeypatch
):
    registry = create_default_registry(include_entry_points=False)
    _install_ready_claude_probe(registry, monkeypatch)
    client = TestClient(
        create_app(HarnessConfig(data_dir=str(tmp_path)), registry=registry)
    )

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    claude = next(
        item
        for item in response.json()["harnesses"]
        if item["spec"]["id"] == "claude-code"
    )
    assert claude["provider_handoff"]["provider_ui_handoff"] is True
    assert claude["provider_handoff"]["durable"] is False
    by_id = {item["id"]: item for item in claude["execution_surfaces"]}
    assert by_id["provider_handoff"]["status"] == "supported"
    assert by_id["native_terminal"]["status"] == "supported"
    assert by_id["one_shot"]["status"] == "supported"
    assert by_id["native_structured_embedded"]["status"] == "blocked"
    assert claude["workbench_transport"]["default"] == "native_structured"
    transport_by_id = {
        item["id"]: item for item in claude["workbench_transport"]["options"]
    }
    assert transport_by_id["native_structured"]["status"] == "blocked"
    assert transport_by_id["native_structured"]["provider_native_continuity"] is False
    direct = next(
        item
        for item in response.json()["harnesses"]
        if item["spec"]["id"] == "direct-chat"
    )
    assert direct["workbench_transport"]["default"] == "one_shot"


def test_handoff_preview_api_degrades_unknown_harness_and_platform(
    tmp_path, monkeypatch
):
    registry = create_default_registry(include_entry_points=False)
    _install_ready_claude_probe(registry, monkeypatch)
    client = TestClient(
        create_app(HarnessConfig(data_dir=str(tmp_path)), registry=registry)
    )

    missing = client.get(
        "/api/provider-handoffs/echo/preview",
        params={"action": "launch_new", "workspace": str(tmp_path)},
    )
    invalid = client.get(
        "/api/provider-handoffs/claude-code/preview",
        params={"action": "unknown", "workspace": str(tmp_path)},
    )

    assert missing.status_code == 404
    assert invalid.status_code == 422


def _install_ready_claude_probe(registry, monkeypatch):
    harness = registry.get("claude-code")
    snapshot = CliCapabilitySnapshot(
        harness_id="claude-code",
        status="supported",
        version="2.1.212 (Claude Code)",
        parsed_version="2.1.212",
        command=("/opt/homebrew/bin/claude",),
        capabilities={"--remote-control": True, "remote-control": True},
        event_schema="claude-stream-json-v1",
        history_schema="claude-project-jsonl-v1",
        warning=None,
        evidence="fixture",
        version_window_status="in_window",
        minimum_version="2.1.0",
        maximum_version_exclusive="2.2.0",
    )
    monkeypatch.setattr(harness, "capability_probe", lambda: snapshot)
