from pathlib import Path
import subprocess

import pytest
import yaml

from gpt2giga_harness.agents import render_starter_agent
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project import init_project_config, resolve_project
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.workflows import (
    WorkflowCoordinator,
    WorkflowRepository,
    discover_workflows,
    load_workflow,
    parse_workflow_definition,
    workflow_plan,
)
from gpt2giga_harness.workflow_catalog import (
    duplicate_workflow,
    merge_workflow_form,
    save_workflow,
    workflow_history,
    workflow_source,
    workflow_templates,
)


def _config(tmp_path: Path) -> HarnessConfig:
    return HarnessConfig(
        data_dir=str(tmp_path / "data"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )


def _coordinator(tmp_path: Path) -> tuple[WorkflowCoordinator, HarnessConfig]:
    config = _config(tmp_path)
    registry = create_default_registry()
    session_store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(registry=registry, config=config, store=session_store)
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime_store,
        payload_store=DurableJobPayloadStore(config.data_dir),
        runner=runner,
    )
    project = resolve_project(tmp_path, data_dir=config.data_dir)
    return (
        WorkflowCoordinator(
            project=project,
            runtime_store=runtime_store,
            runner=runner,
            dispatcher=dispatcher,
        ),
        config,
    )


def test_parse_workflow_supports_all_step_kinds_and_dependency_plan() -> None:
    definition = parse_workflow_definition(
        """
id: all-kinds
title: All kinds
schema_version: 1
version: 1.2.3
budgets: {max_concurrency: 4, max_steps: 6}
steps:
  - {id: agent, kind: agent, agent_id: reviewer}
  - {id: arena, kind: arena, harness_ids: [echo], depends_on: [agent]}
  - {id: eval, kind: eval, eval_id: smoke, depends_on: [agent]}
  - {id: approval, kind: approval, action: external.write, depends_on: [arena]}
  - {id: transform, kind: transform, transform: select, select: [prompt], depends_on: [eval]}
  - {id: join, kind: join, depends_on: [approval, transform]}
"""
    )

    assert {step.kind.value for step in definition.steps} == {
        "agent",
        "arena",
        "eval",
        "approval",
        "transform",
        "join",
    }
    assert workflow_plan(definition)["levels"] == [
        ["agent"],
        ["arena", "eval"],
        ["approval", "transform"],
        ["join"],
    ]


@pytest.mark.parametrize(
    "steps,error",
    [
        (
            "- {id: aa, kind: join, depends_on: [bb]}\n  - {id: bb, kind: join, depends_on: [aa]}",
            "cycle",
        ),
        ("- {id: aa, kind: agent}", "requires agent_id"),
        (
            "- {id: aa, kind: transform, transform: shell}",
            "identity, select, or template",
        ),
    ],
)
def test_parse_workflow_rejects_unsafe_or_invalid_graphs(
    steps: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        parse_workflow_definition(
            f"id: invalid\ntitle: Invalid\nversion: 1\nsteps:\n  {steps}\n"
        )


def test_project_init_installs_valid_review_team(tmp_path: Path) -> None:
    init_project_config(tmp_path)

    definition = load_workflow(tmp_path, "review-team")
    definitions, errors = discover_workflows(tmp_path)

    assert definition.budgets.max_concurrency == 3
    assert [item.id for item in definitions] == ["review-team"]
    assert errors == ()


def test_workflow_catalog_saves_history_and_preserves_unknown_builder_fields(
    tmp_path: Path,
) -> None:
    init_project_config(tmp_path)
    original = workflow_source(tmp_path, "review-team")
    original_hash = load_workflow(tmp_path, "review-team").source_hash
    source_with_future_fields = original + "future_ui:\n  color: blue\n"

    saved = save_workflow(
        tmp_path,
        source_with_future_fields,
        expected_hash=original_hash,
        form={
            "title": "Review Team 2",
            "steps": [
                {**step, "title": f"Step {step['id']}"}
                for step in yaml.safe_load(original)["steps"]
            ],
        },
    )

    assert saved.title == "Review Team 2"
    assert "future_ui:" in workflow_source(tmp_path, "review-team")
    assert workflow_history(tmp_path, "review-team")[0].source_hash == original_hash


def test_workflow_catalog_duplicate_and_templates_are_valid(tmp_path: Path) -> None:
    init_project_config(tmp_path)

    copied = duplicate_workflow(tmp_path, "review-team", "review-team-copy")
    templates = workflow_templates()

    assert copied.id == "review-team-copy"
    assert copied.version == "1.0.0"
    assert [item["id"] for item in templates] == [
        "plan-implement-test-review",
        "diagnose-fix-regression",
        "issue-patch-pr-draft",
    ]
    assert all(item["plan"]["step_count"] >= 3 for item in templates)


def test_merge_workflow_form_keeps_unknown_step_fields() -> None:
    merged = merge_workflow_form(
        """
id: future-flow
title: Future
version: '1'
future_ui: {color: blue}
steps:
  - id: value
    kind: transform
    transform: identity
    future_hint: compact
""",
        {
            "title": "Edited",
            "steps": [{"id": "value", "kind": "transform", "transform": "identity"}],
        },
    )

    assert "future_ui:" in merged
    assert "future_hint: compact" in merged
    assert "title: Edited" in merged


def test_safe_transform_and_join_workflow_completes_without_child_jobs(
    tmp_path: Path,
) -> None:
    coordinator, _ = _coordinator(tmp_path)
    definition = parse_workflow_definition(
        """
id: local-flow
title: Local flow
schema_version: 1
version: 1
inputs: {prompt: default}
steps:
  - id: select
    kind: transform
    transform: select
    select: [prompt]
  - id: joined
    kind: join
    depends_on: [select]
"""
    )

    run = coordinator.start(definition, inputs={"prompt": "hello"})
    steps = coordinator.repository.list_steps(run.id)

    assert run.status.value == "succeeded"
    assert [item.status for item in steps] == ["succeeded", "succeeded"]
    assert steps[0].outputs == {"prompt": "hello"}
    assert steps[1].outputs == {"select": {"prompt": "hello"}}


def test_agent_step_queues_durable_job_and_worker_advances_workflow(
    tmp_path: Path,
) -> None:
    init_project_config(tmp_path)
    agent_path = tmp_path / ".giga" / "agents" / "reviewer.yaml"
    agent_path.write_text(
        render_starter_agent("reviewer", harness_id="echo"), encoding="utf-8"
    )
    coordinator, config = _coordinator(tmp_path)
    definition = parse_workflow_definition(
        """
id: worker-flow
title: Worker flow
schema_version: 1
version: 1
steps:
  - {id: review, kind: agent, agent_id: reviewer, prompt: "Review ${prompt}"}
  - {id: joined, kind: join, depends_on: [review]}
"""
    )

    run = coordinator.start(definition, inputs={"prompt": "the change"})
    queued = coordinator.repository.list_steps(run.id)[0]
    assert queued.status == "queued"
    assert queued.job_id

    worker = DurableJobWorker(config, worker_id="workflow-test-worker")
    assert worker.run_once() is True

    final = WorkflowRepository(worker.runtime_store).get_run(run.id)
    steps = WorkflowRepository(worker.runtime_store).list_steps(run.id)
    assert final.status.value == "succeeded"
    assert [item.status for item in steps] == ["succeeded", "succeeded"]
    assert steps[0].artifact_refs[0]["type"] == "harness_run"


def test_review_team_fans_out_bounded_handoffs_and_synthesizes(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    for agent_id in ("planner", "reviewer", "test-runner"):
        (tmp_path / ".giga" / "agents" / f"{agent_id}.yaml").write_text(
            render_starter_agent(agent_id, harness_id="echo"), encoding="utf-8"
        )
    coordinator, config = _coordinator(tmp_path)

    run = coordinator.start(
        load_workflow(tmp_path, "review-team"), prompt="Review the parser"
    )
    worker = DurableJobWorker(config, worker_id="team-worker")
    assert worker.run_once() is True

    fanned_out = coordinator.repository.list_steps(run.id)
    assert [item.status for item in fanned_out[1:4]] == ["queued"] * 3
    assert (
        len(
            {
                coordinator.runtime_store.get_job(item.job_id).id
                for item in fanned_out[1:4]
            }
        )
        == 3
    )

    for _ in range(4):
        assert worker.run_once() is True

    final = coordinator.repository.get_run(run.id)
    steps = coordinator.repository.list_steps(run.id)
    synthesis_run = coordinator.runner.store.get_run(steps[-1].outputs["run_id"])

    assert final.status.value == "succeeded"
    assert all(item.status == "succeeded" for item in steps)
    assert all(item.outputs.get("summary") for item in steps)
    assert "Bounded dependency handoffs:" in synthesis_run.prompt
    assert '"step_id": "security"' in synthesis_run.prompt
    assert all(len(item.outputs["summary"]) <= 8_000 for item in steps)
    assert all(item.outputs["agent"]["mode"] in {"plan", "read"} for item in steps)


def test_agent_team_forces_edit_profile_into_its_own_worktree(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    (tmp_path / ".giga" / "agents" / "implementer.yaml").write_text(
        render_starter_agent("implementer", harness_id="echo"), encoding="utf-8"
    )
    subprocess.run(("git", "init", str(tmp_path)), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(tmp_path), "config", "user.email", "test@example.com"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(tmp_path), "config", "user.name", "Test User"),
        check=True,
    )
    subprocess.run(("git", "-C", str(tmp_path), "add", ".giga"), check=True)
    subprocess.run(("git", "-C", str(tmp_path), "commit", "-m", "initial"), check=True)
    coordinator, config = _coordinator(tmp_path)
    definition = parse_workflow_definition(
        """
id: unsafe-team
title: Unsafe team
version: 1
steps:
  - {id: edit, kind: agent, agent_id: implementer}
"""
    )

    run = coordinator.start(definition, prompt="change the project")
    worker = DurableJobWorker(config, worker_id="edit-team-worker")
    assert worker.run_once() is True

    step = coordinator.repository.list_steps(run.id)[0]
    child_run = coordinator.runner.store.get_run(step.outputs["run_id"])
    execution = child_run.metadata["workspace_execution"]
    assert execution["policy"] == "worktree"
    assert execution["worktree_path"] != str(tmp_path)
    assert Path(execution["worktree_path"]).exists()


def test_cancel_propagates_to_queued_child_job(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    agent_path = tmp_path / ".giga" / "agents" / "reviewer.yaml"
    agent_path.write_text(
        render_starter_agent("reviewer", harness_id="echo"), encoding="utf-8"
    )
    coordinator, _ = _coordinator(tmp_path)
    definition = parse_workflow_definition(
        """
id: cancel-flow
title: Cancel flow
schema_version: 1
version: 1
steps:
  - {id: review, kind: agent, agent_id: reviewer}
"""
    )
    run = coordinator.start(definition, inputs={"prompt": "cancel me"})
    job_id = coordinator.repository.list_steps(run.id)[0].job_id

    canceled = coordinator.cancel(run.id)

    assert canceled.status.value == "canceled"
    assert coordinator.runtime_store.get_job(job_id).cancel_requested_at
    assert coordinator.repository.list_steps(run.id)[0].status == "canceled"


def test_runtime_export_includes_redacted_workflow_coordination(tmp_path: Path) -> None:
    coordinator, _ = _coordinator(tmp_path)
    definition = parse_workflow_definition(
        """
id: export-flow
title: Export
version: 1
steps:
  - {id: value, kind: transform, transform: identity}
"""
    )
    coordinator.start(definition, inputs={"token": "Bearer secret-value"})

    exported = coordinator.runtime_store.export()

    assert len(exported["workflow_runs"]) == 1
    assert len(exported["workflow_step_attempts"]) == 1
    assert "secret-value" not in str(exported)
