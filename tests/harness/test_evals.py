from pathlib import Path

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.evals import (
    FilesystemHarnessEvalStore,
    discover_eval_specs,
    evaluate_checks,
    eval_run_to_dict,
    load_eval_spec,
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


def _write_eval(tmp_path, text: str, *, filename: str = "smoke.yaml") -> Path:
    path = tmp_path / ".giga" / "evals" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path
