import subprocess

from fastapi.testclient import TestClient

from gpt2giga_harness.arena import FilesystemHarnessArenaStore, queue_arena
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.agents import render_starter_agent
from gpt2giga_harness.evals import (
    FilesystemHarnessEvalStore,
    load_eval_spec,
    queue_eval,
    sync_durable_eval_case,
)
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.project import init_project_config, resolve_project
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.models import JobAttemptStatus, JobStatus
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.structured import (
    DURABLE_STRUCTURED_ADMISSION_FIELD,
    DurableStructuredAdmissionError,
)
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga_harness.schedules import ScheduleService, load_schedule
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot
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
    WorkflowRepository,
    parse_workflow_definition,
)
from gpt2giga_harness.ui.app import create_app


def test_proven_structured_transport_is_worker_owned_and_retryable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "gpt2giga_harness.runtime.worker.DEFAULT_RETRY_BACKOFF_SECONDS", 0.0
    )
    harness = _StructuredHarness("recoverable", durable_approval=True, fail_once=True)
    registry, dispatcher, worker, runtime, payloads, sessions = _runtime(
        tmp_path, harness
    )
    session = sessions.create_session(title="structured")

    submitted = dispatcher.submit(
        session.id,
        {
            "harness_id": harness.harness_id,
            "prompt": "resume exactly",
            "execution_transport": ExecutionTransport.NATIVE_STRUCTURED.value,
            "max_attempts": 2,
        },
        idempotency_key="structured-recoverable",
    )

    stored = payloads.load(submitted.job.id)
    admission = stored[DURABLE_STRUCTURED_ADMISSION_FIELD]
    assert admission["transport"] == "native_structured"
    assert admission["retry_class"] == "structured_recoverable"
    assert worker.run_once() is True
    assert runtime.get_job(submitted.job.id).status is JobStatus.RETRY_WAIT
    assert worker.run_once() is True

    attempts = runtime.list_attempts(submitted.job.id)
    assert [item.status for item in attempts] == [
        JobAttemptStatus.FAILED,
        JobAttemptStatus.SUCCEEDED,
    ]
    assert [item.idempotency_class for item in attempts] == [
        "structured_recoverable",
        "structured_recoverable",
    ]
    assert harness.structured_calls == 2
    assert harness.legacy_calls == 0
    runs = sessions.list_runs(session.id)
    assert all(
        run.metadata["execution_transport"] == "native_structured" for run in runs
    )
    assert registry is worker.registry


def test_ambiguous_structured_turn_fails_closed_without_retry(tmp_path):
    harness = _StructuredHarness("ambiguous", durable_approval=False, fail_once=True)
    _, dispatcher, worker, runtime, _, sessions = _runtime(tmp_path, harness)
    session = sessions.create_session(title="ambiguous")
    submitted = dispatcher.submit(
        session.id,
        {
            "harness_id": harness.harness_id,
            "prompt": "do not duplicate",
            "execution_transport": "native_structured",
            "max_attempts": 3,
        },
        idempotency_key="structured-ambiguous",
    )

    assert worker.run_once() is True

    attempts = runtime.list_attempts(submitted.job.id)
    assert runtime.get_job(submitted.job.id).status is JobStatus.FAILED
    assert len(attempts) == 1
    assert attempts[0].idempotency_class == "structured_ambiguous"
    assert harness.structured_calls == 1
    assert worker.run_once() is False


def test_native_terminal_and_unproven_handoff_are_not_durable_admitted(tmp_path):
    harness = _StructuredHarness("eligible", durable_approval=True)
    _, dispatcher, _, _, _, sessions = _runtime(tmp_path, harness)
    session = sessions.create_session(title="blocked")

    try:
        dispatcher.submit(
            session.id,
            {
                "harness_id": harness.harness_id,
                "prompt": "terminal",
                "execution_transport": "native_terminal",
            },
            idempotency_key="terminal",
        )
    except DurableStructuredAdmissionError as exc:
        assert "synchronous" in str(exc)
    else:  # pragma: no cover - fail-closed contract
        raise AssertionError("native terminal was durable-admitted")

    unproven = _LegacyHarness()
    registry = HarnessRegistry()
    registry.register(unproven)
    runner = HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(data_dir=str(tmp_path / "handoff")),
        store=FilesystemHarnessSessionStore(tmp_path / "handoff"),
    )
    unproven_session = runner.create_session(title="handoff")
    unproven_dispatcher = DurableJobDispatcher(
        runtime_store=RuntimeCoordinationStore(tmp_path / "handoff"),
        payload_store=DurableJobPayloadStore(tmp_path / "handoff"),
        runner=runner,
    )
    try:
        unproven_dispatcher.submit(
            unproven_session.id,
            {
                "harness_id": "provider-handoff",
                "prompt": "open provider",
                "execution_transport": "native_structured",
            },
            idempotency_key="handoff",
        )
    except DurableStructuredAdmissionError as exc:
        assert "no proven" in str(exc)
    else:  # pragma: no cover - fail-closed contract
        raise AssertionError("provider handoff was mislabeled as structured")


def test_native_workflow_step_reuses_structured_admission_across_retry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "gpt2giga_harness.runtime.worker.DEFAULT_RETRY_BACKOFF_SECONDS", 0.0
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    harness = _StructuredHarness(
        "workflow-structured", durable_approval=True, fail_once=True
    )
    profile_path = workspace / ".giga" / "agents" / "reviewer.yaml"
    profile_path.write_text(
        render_starter_agent("reviewer", harness_id=harness.harness_id).replace(
            "invocation_mode: headless", "invocation_mode: native"
        ),
        encoding="utf-8",
    )
    registry, dispatcher, worker, runtime, payloads, sessions = _runtime(
        tmp_path / "data", harness
    )
    runner = dispatcher.runner
    coordinator = WorkflowCoordinator(
        project=resolve_project(workspace, data_dir=tmp_path / "data"),
        runtime_store=runtime,
        runner=runner,
        dispatcher=dispatcher,
    )
    definition = parse_workflow_definition(
        """
id: native-retry
title: Native retry
version: 1
steps:
  - id: review
    kind: agent
    agent_id: reviewer
    retries: 1
"""
    )

    workflow = coordinator.start(definition, inputs={"prompt": "resume exactly"})
    step = coordinator.repository.list_steps(workflow.id)[0]
    stored = payloads.load(step.job_id)
    assert stored[DURABLE_STRUCTURED_ADMISSION_FIELD]["retry_class"] == (
        "structured_recoverable"
    )

    assert worker.run_once() is True
    assert runtime.get_job(step.job_id).status is JobStatus.RETRY_WAIT
    assert worker.run_once() is True

    final = WorkflowRepository(runtime).get_run(workflow.id)
    assert final.status.value == "succeeded"
    assert harness.structured_calls == 2
    assert harness.legacy_calls == 0
    assert len(set(harness.structured_session_ids)) == 1
    assert len(sessions.list_runs(workflow.session_id)) == 2


def test_scheduled_native_workflow_recovers_dispatch_and_keeps_policy_origin(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    harness = _StructuredHarness("scheduled-structured", durable_approval=True)
    profile_path = workspace / ".giga" / "agents" / "reviewer.yaml"
    profile_path.write_text(
        render_starter_agent("reviewer", harness_id=harness.harness_id).replace(
            "invocation_mode: headless", "invocation_mode: native"
        ),
        encoding="utf-8",
    )
    workflow_path = workspace / ".giga" / "workflows" / "scheduled-native.yaml"
    workflow_path.write_text(
        """
id: scheduled-native
title: Scheduled native
version: 1
steps:
  - {id: first, kind: agent, agent_id: reviewer}
  - {id: second, kind: agent, agent_id: reviewer, depends_on: [first]}
""".lstrip(),
        encoding="utf-8",
    )
    registry, dispatcher, worker, runtime, _, _ = _runtime(tmp_path / "data", harness)
    project = resolve_project(workspace, data_dir=tmp_path / "data")
    service = ScheduleService(
        runtime_store=runtime,
        runner=dispatcher.runner,
        dispatcher=dispatcher,
        eval_store=FilesystemHarnessEvalStore(tmp_path / "data"),
    )
    service.upsert(
        project,
        {
            "id": "native-workflow",
            "title": "Native workflow",
            "target": {"kind": "workflow", "id": "scheduled-native"},
            "cadence": {
                "kind": "once",
                "timezone": "Europe/Moscow",
                "start_at": "2099-07-18T10:00:00",
            },
            "workspace_policy": "worktree",
        },
    )
    definition = load_schedule(project.root, "native-workflow")
    schedule_key = service.detail(project, definition.id)["state"]["schedule_key"]
    occurrence = service._create_occurrence(  # noqa: SLF001
        definition,
        schedule_key=schedule_key,
        trigger="schedule",
        scheduled_for="2099-07-18T07:00:00+00:00",
    )
    claimed, granted = service._claim_dispatch(occurrence.id)  # noqa: SLF001
    assert granted is True
    first = service._dispatch_target(  # noqa: SLF001
        project, definition, claimed, dry_run=False
    )

    assert service.tick() == 1
    recovered = service._get_occurrence(occurrence.id)  # noqa: SLF001
    assert recovered.status == "queued"
    assert recovered.run_id == first[2]
    assert len(runtime.list_jobs()) == 1
    assert len(WorkflowRepository(runtime).list_runs()) == 1

    assert worker.run_once() is True
    jobs = runtime.list_jobs()
    assert len(jobs) == 2
    assert all(job.origin == "scheduled" for job in jobs)
    assert all(job.schedule_id == definition.id for job in jobs)
    assert worker.run_once() is True
    final = WorkflowRepository(runtime).get_run(recovered.run_id)
    assert final.status.value == "succeeded"
    assert harness.structured_calls == 2
    assert harness.legacy_calls == 0


def test_scheduled_native_preset_resumes_exact_destination_session(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    harness = _StructuredHarness("scheduled-preset", durable_approval=True)
    config_path = workspace / ".giga" / "harness.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """

[presets.native]
title = "Native preset"
harness = "scheduled-preset"
mode = "read"
invocation_mode = "native"
prompt = "resume native"
""",
        encoding="utf-8",
    )
    _, dispatcher, worker, runtime, payloads, _ = _runtime(tmp_path / "data", harness)
    project = resolve_project(workspace, data_dir=tmp_path / "data")
    destination = dispatcher.runner.create_session(
        title="Scheduled destination",
        workspace=project.root,
        default_harness_id=harness.harness_id,
    )
    service = ScheduleService(
        runtime_store=runtime,
        runner=dispatcher.runner,
        dispatcher=dispatcher,
        eval_store=FilesystemHarnessEvalStore(tmp_path / "data"),
    )
    service.upsert(
        project,
        {
            "id": "native-preset",
            "title": "Native preset",
            "target": {"kind": "preset", "id": "native"},
            "cadence": {
                "kind": "once",
                "timezone": "Europe/Moscow",
                "start_at": "2099-07-18T10:00:00",
            },
            "destination": "resume",
            "session_id": destination.id,
            "workspace_policy": "worktree",
        },
    )
    definition = load_schedule(project.root, "native-preset")
    schedule_key = service.detail(project, definition.id)["state"]["schedule_key"]
    occurrence = service._create_occurrence(  # noqa: SLF001
        definition,
        schedule_key=schedule_key,
        trigger="schedule",
        scheduled_for="2099-07-18T07:00:00+00:00",
    )
    queued = service._execute(  # noqa: SLF001
        project, definition, occurrence, dry_run=False
    )
    job_id = queued["occurrence"]["job_id"]

    stored = payloads.load(job_id)
    assert stored[DURABLE_STRUCTURED_ADMISSION_FIELD]["transport"] == (
        "native_structured"
    )
    assert worker.run_once() is True
    assert runtime.get_job(job_id).status is JobStatus.SUCCEEDED
    assert harness.structured_session_ids == [destination.id]
    assert harness.legacy_calls == 0


def test_native_arena_candidates_get_independent_sessions_and_worktrees(tmp_path):
    workspace = _init_git_repo(tmp_path / "workspace")
    data_dir = tmp_path / "data"
    first = _StructuredHarness("arena-native-a", durable_approval=True)
    second = _StructuredHarness("arena-native-b", durable_approval=True)
    registry = HarnessRegistry()
    registry.register(first)
    registry.register(second)
    config = HarnessConfig(data_dir=str(data_dir))
    sessions = FilesystemHarnessSessionStore(data_dir)
    runtime = RuntimeCoordinationStore(data_dir)
    payloads = DurableJobPayloadStore(data_dir)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=payloads,
        runner=runner,
    )
    arena_store = FilesystemHarnessArenaStore(data_dir)

    arena = queue_arena(
        runner=runner,
        dispatcher=dispatcher,
        arena_store=arena_store,
        payload={
            "prompt": "compare edits",
            "harness_ids": [first.harness_id, second.harness_id],
            "mode": "edit",
            "workspace": str(workspace),
            "execution_transport": "native_structured",
        },
    )

    assert arena.execution_transport is ExecutionTransport.NATIVE_STRUCTURED
    assert arena.workspace_policy == "worktree"
    assert len({child.session_id for child in arena.child_runs}) == 2
    jobs = runtime.list_jobs()
    assert len(jobs) == 2
    for job in jobs:
        stored = payloads.load(job.id)
        assert stored["workspace_policy"] == "worktree"
        assert stored[DURABLE_STRUCTURED_ADMISSION_FIELD]["transport"] == (
            "native_structured"
        )

    worker = DurableJobWorker(config, registry=registry, worker_id="arena-native")
    assert worker.run_once() is True
    assert worker.run_once() is True

    completed = arena_store.get(arena.id)
    runs = [sessions.get_run(child.run_id or "") for child in completed.child_runs]
    worktrees = {run.metadata["workspace_execution"]["worktree_path"] for run in runs}
    assert len(worktrees) == 2
    assert first.structured_session_ids != second.structured_session_ids
    assert first.legacy_calls == second.legacy_calls == 0

    source_child = completed.child_runs[0]
    client = TestClient(
        create_app(
            config,
            registry=registry,
            store=sessions,
            runtime_store=runtime,
        )
    )
    retried = client.post(
        f"/api/arena/runs/{arena.id}/children/{source_child.index}/retry"
    )
    assert retried.status_code == 200
    retried_child = retried.json()["arena"]["child_runs"][0]
    assert retried_child["session_id"] != source_child.session_id
    assert retried_child["session_id"] not in {
        child.session_id for child in completed.child_runs
    }
    assert worker.run_once() is True
    retried_run = sessions.get_run(retried_child["run_id"])
    assert retried_run.metadata["workspace_execution"]["worktree_path"] not in (
        worktrees
    )
    assert len(first.structured_session_ids) == 2
    assert len(second.structured_session_ids) == 1


def test_native_eval_cells_bind_evidence_and_new_sessions(tmp_path):
    workspace = _init_git_repo(tmp_path / "workspace")
    eval_path = workspace / ".giga" / "evals" / "native.yaml"
    eval_path.parent.mkdir(parents=True)
    eval_path.write_text(
        """
name: native
mode: edit
cases:
  - id: first
    prompt: first result
    checks: [{type: contains, value: first}]
  - id: second
    prompt: second result
    checks: [{type: contains, value: second}]
""".lstrip(),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    harness = _StructuredHarness("eval-native", durable_approval=True)
    _, dispatcher, worker, runtime, payloads, sessions = _runtime(data_dir, harness)
    project = resolve_project(workspace, data_dir=data_dir, load_config_name=False)
    eval_store = FilesystemHarnessEvalStore(data_dir)

    queued = queue_eval(
        runner=dispatcher.runner,
        dispatcher=dispatcher,
        eval_store=eval_store,
        project=project,
        spec=load_eval_spec(workspace, "native"),
        harness_ids=(harness.harness_id,),
        execution_transport="native_structured",
    )

    assert queued.metadata["execution_transport"] == "native_structured"
    assert len({result.session_id for result in queued.results}) == 2
    assert queued.session_id not in {result.session_id for result in queued.results}
    for job in runtime.list_jobs():
        stored = payloads.load(job.id)
        binding = stored["extra"]["eval_evidence_binding"]
        assert len(binding["binding_hash"]) == 64
        assert stored["workspace_policy"] == "worktree"

    assert worker.run_once() is True
    assert worker.run_once() is True

    completed = eval_store.get(project, queued.id)
    assert completed.status == "passed"
    assert len({result.session_id for result in completed.results}) == 2
    assert all(result.provenance["source_evidence"] for result in completed.results)
    assert all(result.provenance["native_session"] for result in completed.results)
    worktrees = {
        sessions.get_run(result.run_id or "").metadata["workspace_execution"][
            "worktree_path"
        ]
        for result in completed.results
    }
    assert len(worktrees) == 2

    first_result = completed.results[0]
    first_job = runtime.find_job_for_run(first_result.run_id or "")
    assert first_job is not None
    tampered = payloads.load(first_job.id)
    tampered["extra"]["eval_checks"][0]["value"] = "changed after submission"
    sync_durable_eval_case(
        str(data_dir),
        tampered,
        sessions.get_run(first_result.run_id or ""),
        first_result.output_text or "",
    )
    rejected = eval_store.get(project, queued.id).results[0]
    assert rejected.status == "error"
    assert "eval evidence changed" in (rejected.error or "")


def test_native_replay_queues_a_new_provider_session_with_source_provenance(tmp_path):
    data_dir = tmp_path / "data"
    harness = _StructuredHarness("replay-native", durable_approval=True)
    registry, dispatcher, worker, runtime, _, sessions = _runtime(data_dir, harness)
    source_session = dispatcher.runner.create_session(
        title="source",
        default_harness_id=harness.harness_id,
    )
    source = dispatcher.submit(
        source_session.id,
        {
            "harness_id": harness.harness_id,
            "prompt": "replay me",
            "execution_transport": "native_structured",
        },
        idempotency_key="source-native-replay",
    )
    assert worker.run_once() is True
    source_run = sessions.get_run(source.queued.run.id)

    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(data_dir)),
            registry=registry,
            store=sessions,
            runtime_store=runtime,
        )
    )
    response = client.post(f"/api/runs/{source_run.id}/replay")

    assert response.status_code == 200
    replay = response.json()
    assert replay["session"]["id"] != source_run.session_id
    assert replay["run"]["status"] == "queued"
    assert replay["replay"]["source"]["run_id"] == source_run.id
    assert replay["replay_request"]["execution_transport"] == "native_structured"

    assert worker.run_once() is True
    replay_run = sessions.get_run(replay["run"]["id"])
    provenance = replay_run.metadata["provenance"]
    assert provenance["request"]["extra"]["replay_source"]["run_id"] == (source_run.id)
    assert (
        provenance["execution"]["structured_session_link"]["external_session_id"]
        != source_run.metadata["structured_session_link"]["external_session_id"]
    )
    assert len(set(harness.structured_session_ids)) == 2


def _runtime(tmp_path, harness):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    registry.register(harness)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    payloads = DurableJobPayloadStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=payloads,
        runner=runner,
    )
    worker = DurableJobWorker(config, registry=registry, worker_id="structured-worker")
    return registry, dispatcher, worker, runtime, payloads, sessions


class _StructuredHarness(BaseHarness):
    def __init__(self, harness_id, *, durable_approval, fail_once=False):
        self.harness_id = harness_id
        self._durable_approval = durable_approval
        self._fail_once = fail_once
        self.structured_calls = 0
        self.legacy_calls = 0
        self.structured_session_ids = []

    def spec(self):
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind="test",
            description="structured runtime fixture",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
        )

    def availability(self):
        return Availability.available()

    def durable_structured_capabilities(self):
        return AdapterCapabilitySnapshot(
            adapter_id=self.harness_id,
            adapter_version="1.0",
            protocol="fixture-rpc",
            protocol_version="1",
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=self._durable_approval,
            interrupt=True,
            steer=False,
            resume=True,
            fork=False,
            session_list=False,
            session_close=False,
            native_auth=False,
            provider_ui_handoff=False,
            dynamic_model=False,
            dynamic_mcp=False,
            recovery_after_process_loss=True,
        )

    def run_durable_structured(self, request, context):
        del context
        self.structured_calls += 1
        self.structured_session_ids.append(request.session_id)
        if self._fail_once and self.structured_calls == 1:
            return HarnessResult(ok=False, text="", error="owner lost")
        return HarnessResult(
            ok=True,
            text=request.prompt,
            raw={
                "structured_session_link": {
                    "id": f"link-{request.session_id}",
                    "harness_session_id": request.session_id,
                    "harness_run_id": request.run_id,
                    "external_session_id": f"provider-{request.session_id}",
                    "link_hash": f"hash-{request.session_id}",
                }
            },
        )

    def run(self, request: HarnessRequest, context: HarnessContext):
        del request, context
        self.legacy_calls += 1
        return HarnessResult(ok=True, text="legacy")


class _LegacyHarness(BaseHarness):
    @classmethod
    def spec(cls):
        return HarnessSpec(
            id="provider-handoff",
            title="Provider handoff",
            kind="test",
            description="provider-owned action only",
            capabilities=(HarnessCapability.AGENT_CLI,),
        )

    def availability(self):
        return Availability.available()

    def run(self, request, context):
        del request, context
        return HarnessResult(ok=True, text="handoff")


def _init_git_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Harness Tests"],
        check=True,
    )
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path
