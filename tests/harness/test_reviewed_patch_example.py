import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gpt2giga_harness.agents import discover_agent_profiles
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.evals import (
    FilesystemHarnessEvalStore,
    load_eval_spec,
    run_eval,
)
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.workflows import (
    WorkflowCoordinator,
    discover_workflows,
    load_workflow,
)
from gpt2giga_harness.worktrees import review_run_diff


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SOURCE = REPOSITORY_ROOT / "examples" / "harness" / "issue-to-reviewed-patch"


class _ExampleCodexHarness(BaseHarness):
    def __init__(self) -> None:
        self.requests: list[HarnessRequest] = []

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Example Codex",
            kind="agent-cli",
            description="Hermetic reviewed-patch example adapter",
            capabilities=(
                HarnessCapability.AGENT_CLI,
                HarnessCapability.FILE_EDIT,
                HarnessCapability.SHELL,
            ),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("hermetic example adapter")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.requests.append(request)
        workspace = Path(request.workspace or "")
        if request.mode == "edit":
            source = workspace / "inventory.py"
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "return on_hand < reorder_at",
                    "return on_hand <= reorder_at",
                ),
                encoding="utf-8",
            )
            test_run = _focused_tests(workspace)
            return HarnessResult(
                ok=test_run.returncode == 0,
                text=(
                    "Implemented the equality boundary. "
                    "python -m unittest discover -s tests -v passed."
                ),
                error=test_run.stderr if test_run.returncode else None,
            )
        if "REVIEWED_PATCH_VERIFIED" in request.prompt:
            test_run = _focused_tests(workspace)
            fixed = "return on_hand <= reorder_at" in (
                workspace / "inventory.py"
            ).read_text(encoding="utf-8")
            if test_run.returncode == 0 and fixed:
                return HarnessResult(ok=True, text="REVIEWED_PATCH_VERIFIED")
            return HarnessResult(ok=True, text="verification failed")
        if "Review the isolated patch" in request.prompt:
            return HarnessResult(
                ok=True,
                text=(
                    "Approve: the retained one-line boundary patch is minimal, "
                    "and the focused unittest command passed."
                ),
            )
        return HarnessResult(
            ok=True,
            text=(
                "Plan: change only the equality comparison, run the focused "
                "unittest suite, retain the patch for explicit review."
            ),
        )


def test_reviewed_patch_example_runs_in_isolation_and_verifies_retained_patch(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    workspace = tmp_path / "reviewed-patch"
    shutil.copytree(EXAMPLE_SOURCE, workspace)
    readme = (workspace / "README.md").read_text(encoding="utf-8")
    assert "/api/workflows/issue-to-reviewed-patch/run" in readme
    assert "Run workflow" in readme
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.email", "harness-example@example.invalid")
    _git(workspace, "config", "user.name", "Harness Example")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "seed reviewed patch example")

    baseline = _focused_tests(workspace)
    assert baseline.returncode == 1
    assert "test_reorders_at_threshold" in baseline.stderr

    profiles, profile_errors = discover_agent_profiles(workspace)
    workflows, workflow_errors = discover_workflows(workspace)
    assert [profile.id for profile in profiles] == [
        "issue-planner",
        "patch-implementer",
        "patch-reviewer",
    ]
    assert profile_errors == ()
    assert [workflow.id for workflow in workflows] == ["issue-to-reviewed-patch"]
    assert workflow_errors == ()

    config = HarnessConfig(
        data_dir=str(tmp_path / "runtime"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    registry = create_default_registry(include_entry_points=False)
    harness = _ExampleCodexHarness()
    registry.register(harness)
    session_store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(
        registry=registry,
        config=config,
        store=session_store,
    )
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime_store,
        payload_store=DurableJobPayloadStore(config.data_dir),
        runner=runner,
    )
    project = resolve_project(workspace, data_dir=config.data_dir)
    coordinator = WorkflowCoordinator(
        project=project,
        runtime_store=runtime_store,
        runner=runner,
        dispatcher=dispatcher,
    )

    run = coordinator.start(
        load_workflow(workspace, "issue-to-reviewed-patch"),
        prompt=(workspace / "ISSUE.md").read_text(encoding="utf-8"),
    )
    worker = DurableJobWorker(
        config,
        registry=registry,
        worker_id="reviewed-patch-example-worker",
    )
    for _ in range(3):
        assert worker.run_once() is True

    final = coordinator.repository.get_run(run.id)
    steps = coordinator.repository.list_steps(run.id)
    assert final.status.value == "succeeded"
    assert [step.status for step in steps] == ["succeeded"] * 4

    implement_run = session_store.get_run(steps[1].outputs["run_id"])
    execution = implement_run.metadata["workspace_execution"]
    retained_worktree = Path(execution["worktree_path"])
    assert retained_worktree != workspace
    assert retained_worktree.is_dir()
    assert execution["changed_files"] == ["inventory.py"]
    assert "return on_hand <= reorder_at" in execution["patch"]
    review = review_run_diff(implement_run.metadata)
    assert len(review.source_sha) == 40
    assert len(review.patch_sha256) == 64
    assert review.changed_files == ("inventory.py",)

    reviewer_request = next(
        request
        for request in harness.requests
        if "Review the isolated patch" in request.prompt
    )
    assert "diff --git a/inventory.py b/inventory.py" in reviewer_request.prompt
    assert "python -m unittest discover -s tests -v passed" in (reviewer_request.prompt)

    eval_project = resolve_project(retained_worktree, data_dir=config.data_dir)
    eval_run = run_eval(
        runner=runner,
        eval_store=FilesystemHarnessEvalStore(config.data_dir),
        project=eval_project,
        spec=load_eval_spec(retained_worktree, "reviewed-patch-verification"),
        harness_ids=("codex-cli",),
    )
    assert eval_run.status == "passed"
    assert eval_run.summary["passed"] == 1
    assert eval_run.results[0].output_text == "REVIEWED_PATCH_VERIFIED"

    assert "return on_hand < reorder_at" in (workspace / "inventory.py").read_text(
        encoding="utf-8"
    )
    assert _git(workspace, "status", "--short").stdout == ""


def _focused_tests(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"),
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(workspace), *args),
        capture_output=True,
        text=True,
        check=True,
    )
