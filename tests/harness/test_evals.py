from pathlib import Path

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.evals import (
    FilesystemHarnessEvalStore,
    compare_eval_run_to_baseline,
    discover_eval_specs,
    eval_compatibility_matrix,
    evaluate_checks,
    eval_run_to_dict,
    load_eval_spec,
    protocol_conformance_matrix,
    run_eval,
)
from gpt2giga.harness.project import resolve_project
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.evals import EvalCheckSpec


def test_eval_spec_parse_and_run_echo(tmp_path):
    _write_eval(
        tmp_path,
        """
name: smoke
harnesses: [echo]
api_mode: v2
mode: read
cases:
  - id: explain
    prompt: "Explain FastAPI architecture"
    checks:
      - type: contains
        value: "FastAPI"
  - id: no_secret_leak
    prompt: "Do not leak token values"
    checks:
      - type: not_contains_regex
        value: "(?i)token="
""",
    )
    data_dir = tmp_path / "data"
    project = resolve_project(tmp_path, data_dir=data_dir, load_config_name=False)
    config = HarnessConfig(data_dir=str(data_dir))
    store = FilesystemHarnessSessionStore(data_dir)
    runner = HarnessSessionRunner(
        registry=create_default_registry(include_entry_points=False),
        config=config,
        store=store,
    )

    spec = load_eval_spec(tmp_path, "smoke")
    eval_run = run_eval(
        runner=runner,
        eval_store=FilesystemHarnessEvalStore(data_dir),
        project=project,
        spec=spec,
    )

    payload = eval_run_to_dict(eval_run)
    assert eval_run.status == "passed"
    assert payload["summary"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "errors": 0,
        "score": 1.0,
        "metrics": {
            "latency_seconds": payload["summary"]["metrics"]["latency_seconds"]
        },
        "flakes": 0,
        "flaky_targets": [],
    }
    assert [result["case_id"] for result in payload["results"]] == [
        "explain",
        "no_secret_leak",
    ]
    assert (Path(project.state_dir) / "eval-runs" / f"{eval_run.id}.json").exists()
    assert len(store.list_runs(eval_run.session_id)) == 2


def test_eval_checks_report_failure_without_crashing():
    checks = (
        EvalCheckSpec(type="contains", value="FastAPI"),
        EvalCheckSpec(type="not_contains_regex", value="token="),
        EvalCheckSpec(type="contains_regex", value="["),
    )

    results = evaluate_checks(checks, "Django token=value")

    assert [result.passed for result in results] == [False, False, False]
    assert "Invalid regex" in results[2].message


def test_discover_eval_specs_collects_parse_errors(tmp_path):
    _write_eval(
        tmp_path,
        """
name: ok
cases:
  - id: one
    prompt: hello
""",
        filename="ok.yaml",
    )
    _write_eval(
        tmp_path,
        """
name: broken
cases:
  - id: missing_prompt
""",
        filename="broken.yaml",
    )

    specs, errors = discover_eval_specs(tmp_path)

    assert [spec.name for spec in specs] == ["ok"]
    assert len(errors) == 1
    assert "must define prompt" in errors[0].message


def test_eval_matrix_filters_capabilities_and_tracks_repetitions(tmp_path):
    _write_eval(
        tmp_path,
        """
name: matrix
harnesses: [echo, codex-cli]
cases:
  - id: chat
    prompt: hello
    required_capability: chat_completions
    checks:
      - {type: contains, value: hello}
""",
        filename="matrix.yaml",
    )
    data_dir = tmp_path / "data"
    project = resolve_project(tmp_path, data_dir=data_dir, load_config_name=False)
    registry = create_default_registry(include_entry_points=False)
    runner = HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(data_dir=str(data_dir)),
        store=FilesystemHarnessSessionStore(data_dir),
    )
    spec = load_eval_spec(tmp_path, "matrix")

    assert eval_compatibility_matrix(spec, registry) == [
        {
            "case_id": "chat",
            "harness_id": "echo",
            "required_capability": "chat_completions",
            "capabilities": ["chat_completions"],
            "api_mode": "v2",
            "compatible": True,
        }
    ]

    eval_run = run_eval(
        runner=runner,
        eval_store=FilesystemHarnessEvalStore(data_dir),
        project=project,
        spec=spec,
        repetitions=2,
    )

    assert [(item.harness_id, item.repetition) for item in eval_run.results] == [
        ("echo", 1),
        ("echo", 2),
    ]
    assert eval_run.summary["flakes"] == 0
    assert eval_run.summary["metrics"]["latency_seconds"] >= 0


def test_eval_baseline_records_git_and_config_identity(tmp_path):
    _write_eval(tmp_path, "name: smoke\ncases:\n  - {id: one, prompt: hello}\n")
    data_dir = tmp_path / "data"
    project = resolve_project(tmp_path, data_dir=data_dir, load_config_name=False)
    registry = create_default_registry(include_entry_points=False)
    runner = HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(data_dir=str(data_dir)),
        store=FilesystemHarnessSessionStore(data_dir),
    )
    store = FilesystemHarnessEvalStore(data_dir)
    eval_run = run_eval(
        runner=runner,
        eval_store=store,
        project=project,
        spec=load_eval_spec(tmp_path, "smoke"),
    )

    baseline = store.pin_baseline(project, eval_run)
    comparison = compare_eval_run_to_baseline(eval_run, baseline)

    assert baseline["eval_run_id"] == eval_run.id
    assert len(baseline["config_hash"]) == 64
    assert comparison["score_delta"] == 0.0
    assert store.get_baseline(project, "smoke")["eval_run_id"] == eval_run.id


def test_protocol_conformance_matrix_uses_declared_harness_capabilities():
    cells = protocol_conformance_matrix(
        create_default_registry(include_entry_points=False)
    )

    openai_v2 = next(
        item
        for item in cells
        if item["fixture_id"] == "openai-chat" and item["api_mode"] == "v2"
    )
    responses_v2 = next(
        item
        for item in cells
        if item["fixture_id"] == "openai-responses" and item["api_mode"] == "v2"
    )
    assert openai_v2["runnable"] is True
    assert "echo" in openai_v2["compatible_harness_ids"]
    assert responses_v2["runnable"] is False


def _write_eval(tmp_path, text: str, *, filename: str = "smoke.yaml") -> Path:
    path = tmp_path / ".giga" / "evals" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path
