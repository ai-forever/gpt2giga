from datetime import datetime, timezone
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from gpt2giga_harness.agents import discover_agent_profiles
from gpt2giga_harness.attention import AttentionService
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.evals import (
    FilesystemHarnessEvalStore,
    compare_eval_run_to_baseline,
    load_eval_spec,
    run_eval,
)
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga_harness.schedules import (
    ScheduleService,
    build_schedule_definition,
    discover_schedules,
)
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
from gpt2giga_harness.workflows import discover_workflows


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SOURCE = (
    REPOSITORY_ROOT / "examples" / "harness" / "nightly-compatibility-guardian"
)
HARNESS_IDS = ("codex-cli", "claude-code", "gemini-cli")


class _CompatibilityHarness(BaseHarness):
    def __init__(self, harness_id: str) -> None:
        self.harness_id = harness_id
        self.regressed = False

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=f"Example {self.harness_id}",
            kind="agent-cli",
            description="Hermetic nightly compatibility adapter",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
            supports_streaming=True,
            supports_structured_events=True,
        )

    def availability(self) -> Availability:
        return Availability.available("hermetic compatibility adapter")

    def capability_probe(self) -> CliCapabilitySnapshot:
        return CliCapabilitySnapshot(
            harness_id=self.harness_id,
            status="supported",
            version="1.2.3",
            parsed_version="1.2.3",
            command=(self.harness_id,),
            capabilities={},
            event_schema=f"{self.harness_id}-events-v1",
            history_schema=f"{self.harness_id}-history-v1",
            native_event_schema="raw-terminal-v1",
            native_structured_events=False,
            evidence="hermetic example probe",
        )

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        if self.regressed:
            return HarnessResult(
                ok=True,
                text="compatibility failed; category=adapter",
            )
        return HarnessResult(
            ok=True,
            text="COMPAT_ROUTE_MODEL_OK COMPAT_TAXONOMY_OK",
        )


def test_nightly_guardian_runs_headless_and_surfaces_only_regression_attention(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    workspace = tmp_path / "nightly-guardian"
    shutil.copytree(EXAMPLE_SOURCE, workspace)
    readme = (workspace / "README.md").read_text(encoding="utf-8")
    assert "/api/workflows/nightly-compatibility-guardian/run" in readme
    assert "Run workflow" in readme
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.email", "harness-example@example.invalid")
    _git(workspace, "config", "user.name", "Harness Example")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "seed nightly compatibility example")

    profiles, profile_errors = discover_agent_profiles(workspace)
    workflows, workflow_errors = discover_workflows(workspace)
    spec = load_eval_spec(workspace, "nightly-compatibility")
    assert [profile.id for profile in profiles] == ["compatibility-triager"]
    assert profile_errors == ()
    assert [workflow.id for workflow in workflows] == ["nightly-compatibility-guardian"]
    assert workflow_errors == ()
    assert [step.condition for step in workflows[0].steps] == [
        "on_success",
        "on_failure",
        "always",
    ]
    assert discover_schedules(workspace) == ()
    assert set(spec.metadata["failure_taxonomy"]) == {
        "product",
        "adapter",
        "model",
        "environment",
    }

    config = HarnessConfig(
        data_dir=str(tmp_path / "runtime"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    registry = HarnessRegistry()
    harnesses = [_CompatibilityHarness(harness_id) for harness_id in HARNESS_IDS]
    registry.register_many(harnesses)
    session_store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(
        registry=registry,
        config=config,
        store=session_store,
    )
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    payload_store = DurableJobPayloadStore(config.data_dir)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime_store,
        payload_store=payload_store,
        runner=runner,
    )
    eval_store = FilesystemHarnessEvalStore(config.data_dir)
    project = resolve_project(workspace, data_dir=config.data_dir)
    schedule_source = (
        workspace / ".giga/schedule-sources/nightly-compatibility-guardian.yaml"
    )
    payload = yaml.safe_load(schedule_source.read_text(encoding="utf-8"))
    packaged_schedule = build_schedule_definition(project, payload)
    assert packaged_schedule.target_snapshot["model"] == "GigaChat-2-Max"
    assert packaged_schedule.target_snapshot["case_count"] == 2
    service = ScheduleService(
        runtime_store=runtime_store,
        runner=runner,
        dispatcher=dispatcher,
        eval_store=eval_store,
    )
    worker = DurableJobWorker(
        config,
        registry=registry,
        worker_id="nightly-compatibility-example-worker",
    )

    baseline_run = run_eval(
        runner=runner,
        eval_store=eval_store,
        project=project,
        spec=spec,
    )
    assert baseline_run.status == "passed"
    baseline = eval_store.pin_baseline(project, baseline_run)
    assert [item["binary_version"] for item in baseline["adapter_dimensions"]] == [
        "1.2.3",
        "1.2.3",
        "1.2.3",
    ]

    service.upsert(project, payload)
    service.test_now(project, "nightly-compatibility-guardian")
    _drain(worker, 6)
    service._sync_occurrences()  # noqa: SLF001
    tested = service.enable(project, "nightly-compatibility-guardian")
    assert tested["state"]["status"] == "active"

    _make_due(service, project.id)
    assert service.tick() == 1
    _drain(worker, 6)
    service._sync_occurrences()  # noqa: SLF001
    passing_run = eval_store.list_runs(project)[0]
    delta = compare_eval_run_to_baseline(passing_run, baseline)
    assert passing_run.status == "passed"
    assert delta is not None
    assert delta["dimensions_match"] is True
    assert delta["score_delta"] == 0.0
    assert (
        service.detail(project, "nightly-compatibility-guardian")["state"]["status"]
        == "active"
    )

    for harness in harnesses:
        harness.regressed = True
    _make_due(service, project.id)
    assert service.tick() == 1
    _drain(worker, 6)
    service._sync_occurrences()  # noqa: SLF001

    failed_run = eval_store.list_runs(project)[0]
    failed_delta = compare_eval_run_to_baseline(failed_run, baseline)
    assert failed_run.status == "failed"
    assert failed_delta is not None
    assert failed_delta["dimensions_match"] is True
    assert failed_delta["score_delta"] == -1.0
    detail = service.detail(project, "nightly-compatibility-guardian")
    assert detail["state"]["status"] == "needs_attention"
    assert detail["state"]["enabled"] == 0
    attention = AttentionService(
        runtime_store=runtime_store,
        schedule_service=service,
    ).list(project)
    assert attention["counts"]["schedule"] == 1
    assert "scheduled eval regression" in attention["items"][0]["summary"]
    assert _git(workspace, "status", "--short").stdout == ""


def _drain(worker: DurableJobWorker, count: int) -> None:
    for _ in range(count):
        assert worker.run_once() is True
    assert worker.run_once() is False


def _make_due(service: ScheduleService, project_id: str) -> None:
    with service.runtime_store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE schedule_states SET next_run_at = ? "
            "WHERE project_id = ? AND schedule_id = ?",
            (
                datetime.now(timezone.utc).isoformat(),
                project_id,
                "nightly-compatibility-guardian",
            ),
        )


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(workspace), *args),
        capture_output=True,
        text=True,
        check=True,
    )
