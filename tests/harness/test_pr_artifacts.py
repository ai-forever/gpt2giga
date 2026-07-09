from gpt2giga.harness.pr_artifacts import build_pr_artifact, pr_artifact_to_dict
from gpt2giga.harness.sessions.models import HarnessRun
from gpt2giga.harness.types import GigaChatApiMode, HarnessCapability


def test_pr_artifact_uses_diff_result_and_test_output():
    run = HarnessRun(
        id="run_test",
        session_id="sess_test",
        harness_id="echo",
        status="succeeded",
        prompt="fix the failing test",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="edit",
        workspace="/tmp/project",
        created_at="2026-07-09T00:00:00Z",
        updated_at="2026-07-09T00:00:01Z",
        metadata={
            "workspace_execution": {
                "policy": "worktree",
                "patch": "diff --git a/app.py b/app.py\n",
                "changed_files": ["app.py"],
                "untracked_files": ["tests/test_app.py"],
                "test_output": "1 passed",
            }
        },
    )

    artifact = build_pr_artifact(run, result_text="Implemented the fix.")
    payload = pr_artifact_to_dict(artifact)

    assert artifact.title == "Update app.py and related files"
    assert artifact.branch_name_suggestion.startswith("giga/update-app.py")
    assert artifact.patch.startswith("diff --git")
    assert artifact.changed_files == ("app.py",)
    assert artifact.untracked_files == ("tests/test_app.py",)
    assert artifact.test_output == "1 passed"
    assert "Implemented the fix." in artifact.body
    assert payload["changed_files"] == ["app.py"]
