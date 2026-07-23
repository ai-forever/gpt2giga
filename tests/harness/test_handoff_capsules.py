import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness import cli
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.handoff_capsules import (
    HandoffCapsule,
    HandoffCapsuleError,
)
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyResolution,
)
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.ui.app import create_app


def test_handoff_capsule_api_and_cli_are_content_free_and_truthful(
    tmp_path, monkeypatch, capsys
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.name", "Fixture")
    _git(workspace, "config", "user.email", "fixture@example.test")
    tracked = workspace / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "base")
    data_dir = tmp_path / "data"
    app = create_app(HarnessConfig(data_dir=data_dir))
    client = TestClient(app)
    source = client.post(
        "/api/sessions/run",
        json={
            "harness_id": "echo",
            "prompt": "prompt-canary-must-not-leak",
            "workspace": str(workspace),
        },
    )
    assert source.status_code == 200
    run_id = source.json()["run"]["id"]
    run = app.state.harness_session_store.get_run(run_id)
    app.state.harness_session_store.update_run(
        run.id,
        metadata={
            **dict(run.metadata),
            "workspace_execution": {
                "patch": "patch-canary-must-not-leak",
                "changed_files": ["tracked.txt"],
                "untracked_files": [],
                "worktree_path": str(workspace),
                "truncated": False,
            },
            "managed_mcp_snapshot": {
                "snapshot_id": "mcp_fixture",
                "snapshot_hash": "a" * 64,
                "server_ids": ["private-tool-canary"],
            },
        },
    )
    app.state.harness_session_store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=run.session_id,
            run_id=run.id,
            type="input_requested",
            message="question-canary-must-not-leak",
            payload={
                "request_id": "question_1",
                "question": "question-canary-must-not-leak",
            },
            created_at=utc_now(),
        )
    )
    app.state.harness_runtime_store.create_approval_request(
        PolicyResolution(
            action=PermissionAction.PROCESS_SPAWN,
            decision=PolicyDecision.ASK,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
            policy_source="fixture",
        ),
        PolicyContext(
            session_id=run.session_id,
            run_id=run.id,
            reason="approval-canary-must-not-leak",
            preview={"secret": "approval-canary-must-not-leak"},
        ),
    )

    response = client.get(
        f"/api/runs/{run_id}/handoff-capsule",
        params={"target_harness_id": "codex-cli"},
    )

    assert response.status_code == 200
    capsule = response.json()["capsule"]
    serialized = json.dumps(capsule, sort_keys=True)
    for canary in (
        "prompt-canary",
        "patch-canary",
        "private-tool-canary",
        "question-canary",
        "approval-canary",
    ):
        assert canary not in serialized
    assert capsule["content_free"] is True
    assert capsule["summary"]["pending_approval_count"] == 1
    assert capsule["summary"]["unresolved_question_count"] == 1
    assert capsule["diff_and_artifacts"]["diff"]["changed_file_count"] == 1
    assert capsule["tool_extension_snapshot"]["snapshot_sha256"] == "a" * 64
    assert capsule["continuity"] == {
        "native_session_identity_preserved": False,
        "provider_session_identity_preserved": False,
        "harness_session_identity_preserved": False,
        "source_native_session_present": False,
        "claim": "evidence_handoff_only",
    }
    assert HandoffCapsule.from_dict(capsule).to_dict() == capsule
    repeated = client.get(
        f"/api/runs/{run_id}/handoff-capsule",
        params={"target_harness_id": "codex-cli"},
    ).json()["capsule"]
    assert repeated["capsule_sha256"] == capsule["capsule_sha256"]

    tampered = {**capsule, "continuity": {**capsule["continuity"]}}
    tampered["continuity"]["native_session_identity_preserved"] = True
    with pytest.raises(HandoffCapsuleError, match="cannot preserve"):
        HandoffCapsule.from_dict(tampered)

    same = client.get(
        f"/api/runs/{run_id}/handoff-capsule",
        params={"target_harness_id": "echo"},
    )
    assert same.status_code == 409

    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))
    assert (
        cli.main(
            [
                "handoff",
                "capsule",
                run_id,
                "--target-harness",
                "codex-cli",
                "--json",
            ]
        )
        == 0
    )
    cli_capsule = json.loads(capsys.readouterr().out)["capsule"]
    assert cli_capsule["capsule_sha256"] == capsule["capsule_sha256"]


def _git(workspace, *args):
    subprocess.run(
        ("git", "-C", str(workspace), *args),
        check=True,
        capture_output=True,
        text=True,
    )
