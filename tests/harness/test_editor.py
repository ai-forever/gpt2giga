import pytest

from gpt2giga.harness.editor import (
    EditorOpenError,
    build_open_diff_plan,
    build_open_file_plan,
    editor_open_plan_to_dict,
    execute_editor_plan,
)
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.types import GigaChatApiMode, HarnessCapability


def test_editor_file_plan_uses_shell_free_goto_command(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "app.py"
    source.write_text("print('ok')\n", encoding="utf-8")

    plan = build_open_file_plan(
        workspace,
        "app.py",
        command="code --reuse-window",
        line=7,
    )
    result = execute_editor_plan(plan, dry_run=True)
    payload = editor_open_plan_to_dict(result)

    assert payload["kind"] == "file"
    assert payload["target_path"] == str(source)
    assert payload["command"][:3] == ["code", "--reuse-window", "--goto"]
    assert payload["command"][3].endswith("app.py:7:1")
    assert payload["dry_run"] is True
    assert payload["executed"] is False


def test_editor_file_plan_rejects_workspace_escape(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("", encoding="utf-8")

    with pytest.raises(EditorOpenError, match="inside the workspace"):
        build_open_file_plan(workspace, outside, command="code")


def test_editor_rejects_unsupported_command(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    with pytest.raises(EditorOpenError, match="Unsupported editor command"):
        build_open_file_plan(workspace, "app.py", command="python -c print")


def test_editor_diff_plan_writes_transparent_patch_file(tmp_path):
    store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = store.create_session(title="Diff", workspace=str(tmp_path))
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="edit",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="edit",
        workspace=str(tmp_path),
        status="succeeded",
        metadata={
            "workspace_execution": {
                "policy": "worktree",
                "patch": "diff --git a/app.py b/app.py\n",
                "changed_files": ["app.py"],
            }
        },
    )

    plan = build_open_diff_plan(run, data_dir=tmp_path / "data", command="code")

    assert plan.kind == "diff"
    assert plan.target_path.endswith(f"{run.id}.diff")
    assert "diff --git a/app.py b/app.py" in (
        tmp_path / "data" / "editor" / "diffs" / f"{run.id}.diff"
    ).read_text(encoding="utf-8")
