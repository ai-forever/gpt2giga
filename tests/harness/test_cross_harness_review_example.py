import shutil
import subprocess
from pathlib import Path

import pytest

from gpt2giga_harness.agents import discover_agent_profiles
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.evals import FilesystemHarnessEvalStore, load_eval_spec, run_eval
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.registry import HarnessRegistry
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
    workflow_plan,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SOURCE = REPOSITORY_ROOT / "examples" / "harness" / "cross-harness-review-team"
HARNESS_IDS = ("codex-cli", "claude-code", "gemini-cli")


class _ReviewHarness(BaseHarness):
    def __init__(
        self, harness_id: str, requests: list[tuple[str, HarnessRequest]]
    ) -> None:
        self.harness_id = harness_id
        self.requests = requests
        self.fail_security = False

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=f"Example {self.harness_id}",
            kind="agent-cli",
            description="Hermetic cross-harness review adapter",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("hermetic cross-harness review adapter")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.requests.append((self.harness_id, request))
        if "CROSS_HARNESS_REVIEW_VERIFIED" in request.prompt:
            return HarnessResult(ok=True, text="CROSS_HARNESS_REVIEW_VERIFIED")
        if "Synthesize the retained cross-harness evidence for:" in request.prompt:
            return HarnessResult(
                ok=True,
                text=(
                    "SYNTHESIS_COMPLETE citations=explore,security,tests,maintainability"
                ),
            )
        if "Perform a security review for:" in request.prompt:
            if self.fail_security:
                return HarnessResult(
                    ok=False, text="", error="security reviewer failed"
                )
            return HarnessResult(
                ok=True, text="SECURITY_REPORT path and policy evidence"
            )
        if "Review test coverage for:" in request.prompt:
            return HarnessResult(ok=True, text="TEST_REPORT negative and race coverage")
        if "Review maintainability for:" in request.prompt:
            return HarnessResult(
                ok=True, text="MAINTAINABILITY_REPORT ownership evidence"
            )
        return HarnessResult(ok=True, text="EXPLORER_REPORT ownership and trust flow")


def test_cross_harness_review_team_retains_fanout_and_partial_failure_evidence(
    tmp_path: Path,
) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    workspace = tmp_path / "cross-harness-review"
    shutil.copytree(EXAMPLE_SOURCE, workspace)
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.email", "harness-example@example.invalid")
    _git(workspace, "config", "user.name", "Harness Example")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "seed cross-harness review example")

    profiles, profile_errors = discover_agent_profiles(workspace)
    workflows, workflow_errors = discover_workflows(workspace)
    assert [profile.id for profile in profiles] == [
        "maintainability-reviewer",
        "review-explorer",
        "review-synthesizer",
        "security-reviewer",
        "test-reviewer",
    ]
    assert profile_errors == ()
    assert {profile.harness_id for profile in profiles} == set(HARNESS_IDS)
    assert all(profile.mode == "read" for profile in profiles)
    assert all(profile.workspace_policy == "current" for profile in profiles)
    assert [workflow.id for workflow in workflows] == ["cross-harness-review-team"]
    assert workflow_errors == ()
    definition = workflows[0]
    assert workflow_plan(definition)["levels"] == [
        ["explore", "security", "tests", "maintainability"],
        ["synthesize"],
    ]
    assert definition.budgets.max_concurrency == 4
    assert definition.steps[-1].condition == "always"

    config = HarnessConfig(
        data_dir=str(tmp_path / "runtime"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    registry = HarnessRegistry()
    requests: list[tuple[str, HarnessRequest]] = []
    harnesses = [_ReviewHarness(harness_id, requests) for harness_id in HARNESS_IDS]
    registry.register_many(harnesses)
    session_store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(registry=registry, config=config, store=session_store)
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
    worker = DurableJobWorker(
        config,
        registry=registry,
        worker_id="cross-harness-review-example-worker",
    )

    successful = coordinator.start(
        load_workflow(workspace, "cross-harness-review-team"),
        prompt=(workspace / "REVIEW_TASK.md").read_text(encoding="utf-8"),
    )
    queued = coordinator.repository.list_steps(successful.id)
    assert [step.status for step in queued[:4]] == ["queued"] * 4
    assert queued[-1].status == "pending"
    for _ in range(5):
        assert worker.run_once() is True

    final = coordinator.repository.get_run(successful.id)
    steps = coordinator.repository.list_steps(successful.id)
    assert final.status.value == "succeeded"
    assert [step.status for step in steps] == ["succeeded"] * 5
    assert len({step.job_id for step in steps[:4]}) == 4
    assert len({step.outputs["run_id"] for step in steps[:4]}) == 4
    assert [step.outputs["agent"]["harness_id"] for step in steps] == [
        "codex-cli",
        "claude-code",
        "gemini-cli",
        "codex-cli",
        "codex-cli",
    ]
    for step in steps:
        child_run = session_store.get_run(step.outputs["run_id"])
        execution = child_run.metadata["workspace_execution"]
        assert execution["policy"] == "current"
        assert execution["source_workspace"] == str(workspace)
        assert execution["effective_workspace"] is None
        assert execution["worktree_path"] is None
        assert step.artifact_refs[0] == {
            "type": "harness_run",
            "id": step.outputs["run_id"],
        }

    synthesis_request = next(
        request
        for _, request in reversed(requests)
        if "synthesize" in request.prompt.lower()
    )
    assert "Bounded dependency handoffs:" in synthesis_request.prompt
    for step_id in ("explore", "security", "tests", "maintainability"):
        assert f'"step_id": "{step_id}"' in synthesis_request.prompt
    assert synthesis_request.prompt.count('"type": "harness_run"') == 4

    eval_run = run_eval(
        runner=runner,
        eval_store=FilesystemHarnessEvalStore(config.data_dir),
        project=project,
        spec=load_eval_spec(workspace, "cross-harness-review-contract"),
        harness_ids=("codex-cli",),
    )
    assert eval_run.status == "passed"
    assert eval_run.summary["passed"] == 1
    assert eval_run.results[0].output_text == "CROSS_HARNESS_REVIEW_VERIFIED"

    claude = next(item for item in harnesses if item.harness_id == "claude-code")
    claude.fail_security = True
    failed = coordinator.start(
        load_workflow(workspace, "cross-harness-review-team"),
        prompt="Review the same bounded task and preserve partial evidence.",
    )
    for _ in range(5):
        assert worker.run_once() is True

    failed_final = coordinator.repository.get_run(failed.id)
    failed_steps = coordinator.repository.list_steps(failed.id)
    assert failed_final.status.value == "failed"
    assert [step.status for step in failed_steps] == [
        "succeeded",
        "failed",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    security_step = failed_steps[1]
    assert security_step.error_summary == "security reviewer failed"
    assert security_step.artifact_refs[0]["type"] == "harness_run"
    assert "SYNTHESIS_COMPLETE" in failed_steps[-1].outputs["summary"]
    failed_synthesis_request = next(
        request
        for _, request in reversed(requests)
        if "synthesize" in request.prompt.lower()
    )
    assert f'"run_id": "{security_step.outputs["run_id"]}"' in (
        failed_synthesis_request.prompt
    )
    assert _git(workspace, "status", "--short").stdout == ""


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(workspace), *args),
        capture_output=True,
        text=True,
        check=True,
    )
