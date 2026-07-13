"""Local eval and benchmark runs for project harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import yaml

from gpt2giga_harness.project import HarnessProject
from gpt2giga_harness.runtime.worker import DurableJobDispatcher
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.models import HarnessRun
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    parse_api_mode,
    parse_capability,
    spec_capability_values,
)

EVALS_RELATIVE_DIR = Path(".giga") / "evals"
EVAL_RUNS_DIR = "eval-runs"
EVAL_BASELINES_DIR = "eval-baselines"
DEFAULT_EVAL_HARNESSES = ("echo",)
MAX_EVAL_REPETITIONS = 20
EVAL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CHECK_TYPES = {
    "contains",
    "not_contains",
    "contains_regex",
    "not_contains_regex",
    "equals",
}


class EvalSpecNotFoundError(FileNotFoundError):
    """Raised when a project eval spec is missing."""


class EvalRunNotFoundError(KeyError):
    """Raised when an eval run cannot be found."""


@dataclass(frozen=True)
class EvalCheckSpec:
    """One deterministic check in an eval case."""

    type: str
    value: str
    name: str | None = None
    case_sensitive: bool = True


@dataclass(frozen=True)
class EvalCaseSpec:
    """One prompt case from an eval spec."""

    id: str
    prompt: str
    harnesses: tuple[str, ...] = ()
    checks: tuple[EvalCheckSpec, ...] = ()
    required_capability: HarnessCapability | None = None


@dataclass(frozen=True)
class HarnessEvalSpec:
    """Parsed `.giga/evals/*.yaml` spec."""

    name: str
    path: str
    description: str | None = None
    harnesses: tuple[str, ...] = ()
    model: str | None = None
    api_mode: GigaChatApiMode = GigaChatApiMode.V2
    mode: str = "plan"
    workspace_policy: str = "current"
    cases: tuple[EvalCaseSpec, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalSpecLoadError:
    """Safe parse error for a project eval spec."""

    path: str
    message: str


@dataclass(frozen=True)
class EvalCheckResult:
    """One evaluated check result."""

    type: str
    value: str
    passed: bool
    message: str
    name: str | None = None


@dataclass(frozen=True)
class EvalCaseRunResult:
    """Result for one case/harness pair."""

    case_id: str
    harness_id: str
    status: str
    ok: bool
    score: float
    checks: tuple[EvalCheckResult, ...] = ()
    session_id: str | None = None
    run_id: str | None = None
    output_text: str | None = None
    error: str | None = None
    repetition: int = 1
    target_type: str = "harness"
    target_id: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessEvalRun:
    """Persisted eval run scorecard."""

    id: str
    spec_name: str
    spec_path: str
    project_id: str
    project_root: str
    project_name: str
    session_id: str
    status: str
    model: str | None
    api_mode: GigaChatApiMode
    mode: str
    workspace_policy: str
    harness_ids: tuple[str, ...]
    created_at: str
    updated_at: str
    results: tuple[EvalCaseRunResult, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class FilesystemHarnessEvalStore:
    """Persist eval scorecards under a project state directory."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()

    def save(self, project: HarnessProject, eval_run: HarnessEvalRun) -> HarnessEvalRun:
        """Persist one eval run."""
        directory = self._project_runs_dir(project)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{eval_run.id}.json"
        with exclusive_file_lock(path):
            _write_json_atomic(path, eval_run_to_dict(eval_run))
        return eval_run

    def upsert_result(
        self, eval_run_id: str, result: EvalCaseRunResult
    ) -> HarnessEvalRun:
        """Process-safely replace one case/harness result and recompute summary."""
        path = self._find_run_path(eval_run_id)
        with exclusive_file_lock(path):
            eval_run = eval_run_from_dict(_read_json(path))
            results = [
                item
                for item in eval_run.results
                if _result_identity(item) != _result_identity(result)
            ]
            results.append(result)
            order = {
                _result_identity(item): index
                for index, item in enumerate(eval_run.results)
            }
            results.sort(key=lambda item: order.get(_result_identity(item), len(order)))
            updated = replace(
                eval_run,
                status=_eval_run_status(results, expected_count=len(results)),
                updated_at=utc_now(),
                results=tuple(results),
                summary=_eval_summary(results),
            )
            _write_json_atomic(path, eval_run_to_dict(updated))
        return updated

    def get(self, project: HarnessProject, eval_run_id: str) -> HarnessEvalRun:
        """Return one eval run for a project."""
        path = self._project_runs_dir(project) / f"{eval_run_id}.json"
        try:
            return eval_run_from_dict(_read_json(path))
        except FileNotFoundError as exc:
            raise EvalRunNotFoundError(eval_run_id) from exc

    def get_any(self, eval_run_id: str) -> HarnessEvalRun:
        """Return an eval run by scanning project eval-run directories."""
        for path in sorted(
            self.data_dir.glob(f"projects/*/{EVAL_RUNS_DIR}/{eval_run_id}.json")
        ):
            try:
                return eval_run_from_dict(_read_json(path))
            except (OSError, ValueError):
                continue
        raise EvalRunNotFoundError(eval_run_id)

    def list_runs(
        self,
        project: HarnessProject,
        *,
        limit: int = 20,
    ) -> tuple[HarnessEvalRun, ...]:
        """List recent eval runs for a project."""
        runs: list[HarnessEvalRun] = []
        for path in sorted(self._project_runs_dir(project).glob("*.json")):
            try:
                runs.append(eval_run_from_dict(_read_json(path)))
            except (OSError, ValueError):
                continue
        runs.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(runs[: max(limit, 0)])

    def pin_baseline(
        self, project: HarnessProject, eval_run: HarnessEvalRun
    ) -> Mapping[str, Any]:
        """Pin an immutable scorecard snapshot with source/config identities."""
        directory = Path(project.state_dir).expanduser() / EVAL_BASELINES_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_safe_eval_name(eval_run.spec_name)}.json"
        payload = {
            "spec_name": eval_run.spec_name,
            "eval_run_id": eval_run.id,
            "pinned_at": utc_now(),
            "git_sha": _git_sha(project.root),
            "config_hash": _eval_config_hash(eval_run),
            "summary": dict(eval_run.summary),
            "results": [eval_case_result_to_dict(item) for item in eval_run.results],
        }
        with exclusive_file_lock(path):
            _write_json_atomic(path, payload)
        return payload

    def get_baseline(
        self, project: HarnessProject, spec_name: str
    ) -> Mapping[str, Any] | None:
        """Return the pinned baseline for one eval spec, if present."""
        path = (
            Path(project.state_dir).expanduser()
            / EVAL_BASELINES_DIR
            / f"{_safe_eval_name(spec_name)}.json"
        )
        try:
            return _read_json(path)
        except FileNotFoundError:
            return None

    def _project_runs_dir(self, project: HarnessProject) -> Path:
        return Path(project.state_dir).expanduser() / EVAL_RUNS_DIR

    def _find_run_path(self, eval_run_id: str) -> Path:
        paths = sorted(
            self.data_dir.glob(f"projects/*/{EVAL_RUNS_DIR}/{eval_run_id}.json")
        )
        if not paths:
            raise EvalRunNotFoundError(eval_run_id)
        return paths[0]


def discover_eval_specs(
    project_root: str | Path,
) -> tuple[tuple[HarnessEvalSpec, ...], tuple[EvalSpecLoadError, ...]]:
    """Load all project eval specs, collecting parse errors safely."""
    specs: list[HarnessEvalSpec] = []
    errors: list[EvalSpecLoadError] = []
    for path in _eval_spec_paths(project_root):
        try:
            specs.append(load_eval_spec(project_root, path.stem))
        except (OSError, ValueError) as exc:
            errors.append(EvalSpecLoadError(path=str(path), message=str(exc)))
    specs.sort(key=lambda spec: spec.name)
    return tuple(specs), tuple(errors)


def load_eval_spec(project_root: str | Path, name: str) -> HarnessEvalSpec:
    """Load one project eval spec by safe name."""
    spec_name = _safe_eval_name(name)
    path = _resolve_eval_spec_path(project_root, spec_name)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalSpecNotFoundError(spec_name) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid eval YAML: {path.name}") from exc
    return eval_spec_from_mapping(_mapping(data), path=path)


def run_eval(
    *,
    runner: HarnessSessionRunner,
    eval_store: FilesystemHarnessEvalStore,
    project: HarnessProject,
    spec: HarnessEvalSpec,
    harness_ids: tuple[str, ...] = (),
    model: str | None = None,
    api_mode: GigaChatApiMode | str | None = None,
    mode: str | None = None,
    workspace_policy: str | None = None,
    dry_run: bool = False,
    repetitions: int = 1,
) -> HarnessEvalRun:
    """Run a project eval spec against selected harnesses."""
    selected_harnesses = _selected_harnesses(
        harness_ids or spec.harnesses or DEFAULT_EVAL_HARNESSES
    )
    repetitions = _bounded_repetitions(repetitions)
    compatible_cells = _compatible_case_harnesses(
        runner, spec, selected_harnesses, bool(harness_ids)
    )
    if not compatible_cells:
        raise ValueError("Eval matrix has no capability-compatible cells")
    effective_model = model or spec.model
    effective_api_mode = parse_api_mode(api_mode or spec.api_mode)
    effective_mode = mode or spec.mode
    effective_workspace_policy = workspace_policy or spec.workspace_policy
    session = runner.create_session(
        title=f"Eval: {spec.name}",
        workspace=project.root,
        default_harness_id=selected_harnesses[0],
        default_model=effective_model,
        default_api_mode=effective_api_mode,
        default_mode=effective_mode,
    )
    now = utc_now()
    eval_run = HarnessEvalRun(
        id=new_id("eval"),
        spec_name=spec.name,
        spec_path=spec.path,
        project_id=project.id,
        project_root=project.root,
        project_name=project.name,
        session_id=session.id,
        status="running",
        model=effective_model,
        api_mode=effective_api_mode,
        mode=effective_mode,
        workspace_policy=effective_workspace_policy,
        harness_ids=selected_harnesses,
        created_at=now,
        updated_at=now,
        metadata={
            "dry_run": dry_run,
            "repetitions": repetitions,
            "config_hash": _spec_config_hash(spec, selected_harnesses, repetitions),
        },
    )
    eval_store.save(project, eval_run)
    results: list[EvalCaseRunResult] = []
    for case, harness_id in compatible_cells:
        for repetition in range(1, repetitions + 1):
            result = _run_eval_case(
                runner=runner,
                eval_run=eval_run,
                case=case,
                harness_id=harness_id,
                model=effective_model,
                api_mode=effective_api_mode,
                mode=effective_mode,
                workspace=project.root,
                workspace_policy=effective_workspace_policy,
                dry_run=dry_run,
            )
            results.append(
                replace(
                    result,
                    repetition=repetition,
                    target_id=harness_id,
                ),
            )
            eval_run = replace(
                eval_run,
                status="running",
                updated_at=utc_now(),
                results=tuple(results),
                summary=_eval_summary(results),
            )
            eval_store.save(project, eval_run)
    eval_run = replace(
        eval_run,
        status=_eval_run_status(results, expected_count=len(results)),
        updated_at=utc_now(),
        results=tuple(results),
        summary=_eval_summary(results),
    )
    return eval_store.save(project, eval_run)


def queue_eval(
    *,
    runner: HarnessSessionRunner,
    dispatcher: DurableJobDispatcher,
    eval_store: FilesystemHarnessEvalStore,
    project: HarnessProject,
    spec: HarnessEvalSpec,
    harness_ids: tuple[str, ...] = (),
    model: str | None = None,
    api_mode: GigaChatApiMode | str | None = None,
    mode: str | None = None,
    workspace_policy: str | None = None,
    dry_run: bool = False,
    repetitions: int = 1,
    origin: str = "manual",
    schedule_id: str | None = None,
) -> HarnessEvalRun:
    """Queue every eval case/harness pair as a durable job."""
    selected_harnesses = _selected_harnesses(
        harness_ids or spec.harnesses or DEFAULT_EVAL_HARNESSES
    )
    repetitions = _bounded_repetitions(repetitions)
    compatible_cells = _compatible_case_harnesses(
        runner, spec, selected_harnesses, bool(harness_ids)
    )
    if not compatible_cells:
        raise ValueError("Eval matrix has no capability-compatible cells")
    effective_model = model or spec.model
    effective_api_mode = parse_api_mode(api_mode or spec.api_mode)
    effective_mode = mode or spec.mode
    effective_workspace_policy = workspace_policy or spec.workspace_policy
    if origin == "scheduled":
        effective_workspace_policy = "worktree"
    session = runner.create_session(
        title=f"Eval: {spec.name}",
        workspace=project.root,
        default_harness_id=selected_harnesses[0],
        default_model=effective_model,
        default_api_mode=effective_api_mode,
        default_mode=effective_mode,
    )
    now = utc_now()
    eval_run = HarnessEvalRun(
        id=new_id("eval"),
        spec_name=spec.name,
        spec_path=spec.path,
        project_id=project.id,
        project_root=project.root,
        project_name=project.name,
        session_id=session.id,
        status="running",
        model=effective_model,
        api_mode=effective_api_mode,
        mode=effective_mode,
        workspace_policy=effective_workspace_policy,
        harness_ids=selected_harnesses,
        created_at=now,
        updated_at=now,
        metadata={
            "dry_run": dry_run,
            "durable": True,
            "repetitions": repetitions,
            "config_hash": _spec_config_hash(spec, selected_harnesses, repetitions),
        },
    )
    eval_store.save(project, eval_run)
    queued_results: list[EvalCaseRunResult] = []
    for case, harness_id in compatible_cells:
        for repetition in range(1, repetitions + 1):
            payload = {
                "harness_id": harness_id,
                "prompt": case.prompt,
                "model": effective_model,
                "api_mode": effective_api_mode.value,
                "mode": effective_mode,
                "workspace": project.root,
                "workspace_policy": effective_workspace_policy,
                "dry_run": dry_run,
                "permission_profile": "unattended" if origin == "scheduled" else None,
                "schedule_id": schedule_id,
                "extra": {
                    "isolated_history": True,
                    "eval_run_id": eval_run.id,
                    "eval_case_id": case.id,
                    "eval_spec": eval_run.spec_name,
                    "eval_repetition": repetition,
                    "eval_target_type": "harness",
                    "eval_target_id": harness_id,
                    "eval_checks": [
                        {
                            "type": check.type,
                            "value": check.value,
                            "name": check.name,
                            "case_sensitive": check.case_sensitive,
                        }
                        for check in case.checks
                    ],
                },
            }
            submission = dispatcher.submit(
                session.id,
                payload,
                idempotency_key=(
                    f"eval:{eval_run.id}:{case.id}:{harness_id}:{repetition}"
                ),
                origin=origin,
            )
            queued_results.append(
                EvalCaseRunResult(
                    case_id=case.id,
                    harness_id=harness_id,
                    status="queued",
                    ok=False,
                    score=0.0,
                    session_id=session.id,
                    run_id=submission.queued.run.id,
                    repetition=repetition,
                    target_id=harness_id,
                )
            )
    eval_run = replace(
        eval_run,
        results=tuple(queued_results),
        summary=_eval_summary(queued_results),
        updated_at=utc_now(),
    )
    return eval_store.save(project, eval_run)


def sync_durable_eval_case(
    data_dir: str,
    payload: Mapping[str, Any],
    run: HarnessRun,
    result_text: str,
) -> None:
    """Project one finished durable run into its eval scorecard."""
    extra = payload.get("extra")
    if not isinstance(extra, Mapping) or not extra.get("eval_run_id"):
        return
    checks = _parse_checks(extra.get("eval_checks"))
    check_results = (
        evaluate_checks(checks, result_text) if run.status == "succeeded" else ()
    )
    passed = run.status == "succeeded" and all(item.passed for item in check_results)
    score = (
        sum(1 for item in check_results if item.passed) / len(check_results)
        if check_results
        else (1.0 if passed else 0.0)
    )
    status = (
        "passed" if passed else ("failed" if run.status == "succeeded" else "error")
    )
    FilesystemHarnessEvalStore(data_dir).upsert_result(
        str(extra["eval_run_id"]),
        EvalCaseRunResult(
            case_id=str(extra.get("eval_case_id") or "case"),
            harness_id=run.harness_id,
            status=status,
            ok=passed,
            score=score,
            checks=check_results,
            session_id=run.session_id,
            run_id=run.id,
            output_text=_redacted_text(result_text),
            error=(None if passed else run.error or "One or more checks failed."),
            repetition=_positive_int(extra.get("eval_repetition"), 1),
            target_type=str(extra.get("eval_target_type") or "harness"),
            target_id=str(extra.get("eval_target_id") or run.harness_id),
            metrics=_run_metrics(run),
        ),
    )


def eval_spec_from_mapping(
    data: Mapping[str, Any],
    *,
    path: Path,
) -> HarnessEvalSpec:
    """Parse an eval spec mapping."""
    name = _optional_text(data.get("name")) or path.stem
    _safe_eval_name(name)
    cases = _parse_cases(data.get("cases"))
    if not cases:
        raise ValueError("Eval spec must contain at least one case")
    return HarnessEvalSpec(
        name=name,
        path=str(path),
        description=_optional_text(data.get("description")),
        harnesses=_string_tuple(data.get("harnesses")),
        model=_optional_text(data.get("model")),
        api_mode=parse_api_mode(data.get("api_mode")),
        mode=_optional_text(data.get("mode")) or "plan",
        workspace_policy=_optional_text(data.get("workspace_policy")) or "current",
        cases=cases,
        metadata=_mapping(data.get("metadata")),
    )


def evaluate_checks(
    checks: tuple[EvalCheckSpec, ...],
    output_text: str,
) -> tuple[EvalCheckResult, ...]:
    """Evaluate deterministic checks against output text."""
    return tuple(_evaluate_check(check, output_text) for check in checks)


def eval_spec_to_dict(
    spec: HarnessEvalSpec,
    *,
    include_cases: bool = True,
) -> dict[str, Any]:
    """Serialize an eval spec without exposing secret-looking values."""
    payload = {
        "name": spec.name,
        "path": spec.path,
        "description": spec.description,
        "harnesses": list(spec.harnesses),
        "model": spec.model,
        "api_mode": spec.api_mode.value,
        "mode": spec.mode,
        "workspace_policy": spec.workspace_policy,
        "case_count": len(spec.cases),
        "metadata": dict(redact_for_storage(dict(spec.metadata))),
    }
    if include_cases:
        payload["cases"] = [
            {
                "id": case.id,
                "prompt": _redacted_text(case.prompt),
                "harnesses": list(case.harnesses),
                "required_capability": (
                    case.required_capability.value
                    if case.required_capability is not None
                    else None
                ),
                "checks": [
                    {
                        "name": check.name,
                        "type": check.type,
                        "value": _redacted_text(check.value),
                        "case_sensitive": check.case_sensitive,
                    }
                    for check in case.checks
                ],
            }
            for case in spec.cases
        ]
    return payload


def eval_run_to_dict(eval_run: HarnessEvalRun) -> dict[str, Any]:
    """Serialize an eval run."""
    return {
        "id": eval_run.id,
        "spec_name": eval_run.spec_name,
        "spec_path": eval_run.spec_path,
        "project_id": eval_run.project_id,
        "project_root": eval_run.project_root,
        "project_name": eval_run.project_name,
        "session_id": eval_run.session_id,
        "status": eval_run.status,
        "model": eval_run.model,
        "api_mode": eval_run.api_mode.value,
        "mode": eval_run.mode,
        "workspace_policy": eval_run.workspace_policy,
        "harness_ids": list(eval_run.harness_ids),
        "created_at": eval_run.created_at,
        "updated_at": eval_run.updated_at,
        "results": [eval_case_result_to_dict(result) for result in eval_run.results],
        "summary": dict(eval_run.summary),
        "metadata": dict(redact_for_storage(dict(eval_run.metadata))),
    }


def eval_run_from_dict(data: Mapping[str, Any]) -> HarnessEvalRun:
    """Parse a persisted eval run."""
    return HarnessEvalRun(
        id=str(data["id"]),
        spec_name=str(data["spec_name"]),
        spec_path=str(data.get("spec_path") or ""),
        project_id=str(data.get("project_id") or ""),
        project_root=str(data.get("project_root") or ""),
        project_name=str(data.get("project_name") or ""),
        session_id=str(data.get("session_id") or ""),
        status=str(data.get("status") or "failed"),
        model=_optional_text(data.get("model")),
        api_mode=parse_api_mode(data.get("api_mode")),
        mode=str(data.get("mode") or "plan"),
        workspace_policy=str(data.get("workspace_policy") or "current"),
        harness_ids=tuple(str(item) for item in data.get("harness_ids", ())),
        created_at=str(data["created_at"]),
        updated_at=str(data.get("updated_at") or data["created_at"]),
        results=tuple(
            eval_case_result_from_dict(item) for item in data.get("results", ())
        ),
        summary=_mapping(data.get("summary")),
        metadata=_mapping(data.get("metadata")),
    )


def eval_case_result_to_dict(result: EvalCaseRunResult) -> dict[str, Any]:
    """Serialize one eval case/harness result."""
    return {
        "case_id": result.case_id,
        "harness_id": result.harness_id,
        "status": result.status,
        "ok": result.ok,
        "score": result.score,
        "checks": [eval_check_result_to_dict(check) for check in result.checks],
        "session_id": result.session_id,
        "run_id": result.run_id,
        "output_text": _redacted_text(result.output_text),
        "error": _redacted_text(result.error),
        "repetition": result.repetition,
        "target_type": result.target_type,
        "target_id": result.target_id or result.harness_id,
        "metrics": dict(redact_for_storage(dict(result.metrics))),
    }


def eval_case_result_from_dict(data: Mapping[str, Any]) -> EvalCaseRunResult:
    """Parse one persisted eval case/harness result."""
    return EvalCaseRunResult(
        case_id=str(data["case_id"]),
        harness_id=str(data["harness_id"]),
        status=str(data.get("status") or "failed"),
        ok=bool(data.get("ok")),
        score=float(data.get("score") or 0.0),
        checks=tuple(
            eval_check_result_from_dict(item) for item in data.get("checks", ())
        ),
        session_id=_optional_text(data.get("session_id")),
        run_id=_optional_text(data.get("run_id")),
        output_text=_optional_text(data.get("output_text")),
        error=_optional_text(data.get("error")),
        repetition=_positive_int(data.get("repetition"), 1),
        target_type=str(data.get("target_type") or "harness"),
        target_id=_optional_text(data.get("target_id")) or str(data["harness_id"]),
        metrics=_mapping(data.get("metrics")),
    )


def eval_check_result_to_dict(result: EvalCheckResult) -> dict[str, Any]:
    """Serialize one check result."""
    return {
        "name": result.name,
        "type": result.type,
        "value": _redacted_text(result.value),
        "passed": result.passed,
        "message": result.message,
    }


def eval_check_result_from_dict(data: Mapping[str, Any]) -> EvalCheckResult:
    """Parse one persisted check result."""
    return EvalCheckResult(
        name=_optional_text(data.get("name")),
        type=str(data["type"]),
        value=str(data.get("value") or ""),
        passed=bool(data.get("passed")),
        message=str(data.get("message") or ""),
    )


def eval_spec_load_error_to_dict(error: EvalSpecLoadError) -> dict[str, str]:
    """Serialize a safe eval spec load error."""
    return {"path": error.path, "message": error.message}


def _run_eval_case(
    *,
    runner: HarnessSessionRunner,
    eval_run: HarnessEvalRun,
    case: EvalCaseSpec,
    harness_id: str,
    model: str | None,
    api_mode: GigaChatApiMode,
    mode: str,
    workspace: str,
    workspace_policy: str,
    dry_run: bool,
) -> EvalCaseRunResult:
    try:
        result = runner.run_in_session(
            eval_run.session_id,
            {
                "harness_id": harness_id,
                "prompt": case.prompt,
                "model": model,
                "api_mode": api_mode.value,
                "mode": mode,
                "workspace": workspace,
                "workspace_policy": workspace_policy,
                "dry_run": dry_run,
                "extra": {
                    "isolated_history": True,
                    "eval_run_id": eval_run.id,
                    "eval_case_id": case.id,
                    "eval_spec": eval_run.spec_name,
                },
            },
        )
    except Exception as exc:
        return EvalCaseRunResult(
            case_id=case.id,
            harness_id=harness_id,
            status="error",
            ok=False,
            score=0.0,
            error=_redacted_text(str(exc)),
        )
    if not result.result.ok:
        return EvalCaseRunResult(
            case_id=case.id,
            harness_id=harness_id,
            session_id=result.session.id,
            run_id=result.run.id,
            status="error",
            ok=False,
            score=0.0,
            output_text=_redacted_text(result.result.text),
            error=_redacted_text(result.result.error or "Harness run failed"),
            metrics=_run_metrics(result.run),
        )
    check_results = evaluate_checks(case.checks, result.result.text)
    passed = all(check.passed for check in check_results)
    if not check_results:
        passed = True
    score = (
        sum(1 for check in check_results if check.passed) / len(check_results)
        if check_results
        else 1.0
    )
    return EvalCaseRunResult(
        case_id=case.id,
        harness_id=harness_id,
        session_id=result.session.id,
        run_id=result.run.id,
        status="passed" if passed else "failed",
        ok=passed,
        score=score,
        checks=check_results,
        output_text=_redacted_text(result.result.text),
        error=None if passed else "One or more checks failed.",
        metrics=_run_metrics(result.run),
    )


def _evaluate_check(check: EvalCheckSpec, output_text: str) -> EvalCheckResult:
    if check.type not in CHECK_TYPES:
        return EvalCheckResult(
            name=check.name,
            type=check.type,
            value=check.value,
            passed=False,
            message=f"Unsupported check type: {check.type}",
        )
    haystack = output_text if check.case_sensitive else output_text.lower()
    needle = check.value if check.case_sensitive else check.value.lower()
    if check.type == "contains":
        passed = needle in haystack
        return _check_result(
            check, passed, "expected text found", "expected text missing"
        )
    if check.type == "not_contains":
        passed = needle not in haystack
        return _check_result(
            check, passed, "forbidden text absent", "forbidden text found"
        )
    if check.type == "equals":
        passed = haystack == needle
        return _check_result(
            check, passed, "text matched exactly", "text did not match exactly"
        )
    flags = 0 if check.case_sensitive else re.IGNORECASE
    try:
        matched = re.search(check.value, output_text, flags=flags) is not None
    except re.error as exc:
        return EvalCheckResult(
            name=check.name,
            type=check.type,
            value=check.value,
            passed=False,
            message=f"Invalid regex: {exc}",
        )
    if check.type == "contains_regex":
        return _check_result(check, matched, "regex matched", "regex did not match")
    return _check_result(
        check,
        not matched,
        "forbidden regex absent",
        "forbidden regex matched",
    )


def _check_result(
    check: EvalCheckSpec,
    passed: bool,
    passed_message: str,
    failed_message: str,
) -> EvalCheckResult:
    return EvalCheckResult(
        name=check.name,
        type=check.type,
        value=check.value,
        passed=passed,
        message=passed_message if passed else failed_message,
    )


def _parse_cases(value: Any) -> tuple[EvalCaseSpec, ...]:
    if not isinstance(value, list):
        return ()
    cases: list[EvalCaseSpec] = []
    for index, item in enumerate(value, start=1):
        data = _mapping(item)
        case_id = _optional_text(data.get("id")) or f"case_{index}"
        prompt = _optional_text(data.get("prompt"))
        if prompt is None:
            raise ValueError(f"Eval case {case_id} must define prompt")
        cases.append(
            EvalCaseSpec(
                id=case_id,
                prompt=prompt,
                harnesses=_string_tuple(data.get("harnesses")),
                checks=_parse_checks(data.get("checks")),
                required_capability=(
                    parse_capability(data.get("required_capability"))
                    if data.get("required_capability")
                    else None
                ),
            )
        )
    return tuple(cases)


def _parse_checks(value: Any) -> tuple[EvalCheckSpec, ...]:
    if not isinstance(value, list):
        return ()
    checks: list[EvalCheckSpec] = []
    for item in value:
        data = _mapping(item)
        check_type = _optional_text(data.get("type"))
        if check_type is None:
            raise ValueError("Eval check must define type")
        check_value = data.get("value")
        if check_value is None:
            raise ValueError(f"Eval check {check_type} must define value")
        checks.append(
            EvalCheckSpec(
                type=check_type,
                value=str(check_value),
                name=_optional_text(data.get("name")),
                case_sensitive=bool(data.get("case_sensitive", True)),
            )
        )
    return tuple(checks)


def _eval_spec_paths(project_root: str | Path) -> tuple[Path, ...]:
    directory = Path(project_root).expanduser().resolve() / EVALS_RELATIVE_DIR
    if not directory.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
        )
    )


def _resolve_eval_spec_path(project_root: str | Path, name: str) -> Path:
    directory = Path(project_root).expanduser().resolve() / EVALS_RELATIVE_DIR
    candidates = (
        directory / f"{name}.yaml",
        directory / f"{name}.yml",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise EvalSpecNotFoundError(name)


def _safe_eval_name(name: str) -> str:
    text = str(name).strip()
    if not text or not EVAL_NAME_RE.match(text):
        raise ValueError(
            "Eval names may only contain letters, numbers, dots, underscores, and hyphens"
        )
    return text.removesuffix(".yaml").removesuffix(".yml")


def _selected_harnesses(harness_ids: tuple[str, ...]) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(_optional_text(item) for item in harness_ids))
    selected = tuple(item for item in selected if item is not None)
    if not selected:
        raise ValueError("Eval must select at least one harness")
    return selected


def _case_harnesses(
    case: EvalCaseSpec,
    selected_harnesses: tuple[str, ...],
    override_harnesses: bool,
) -> tuple[str, ...]:
    if override_harnesses or not case.harnesses:
        return selected_harnesses
    return _selected_harnesses(case.harnesses)


def _compatible_case_harnesses(
    runner: HarnessSessionRunner,
    spec: HarnessEvalSpec,
    selected_harnesses: tuple[str, ...],
    override_harnesses: bool,
) -> list[tuple[EvalCaseSpec, str]]:
    cells: list[tuple[EvalCaseSpec, str]] = []
    for case in spec.cases:
        for harness_id in _case_harnesses(case, selected_harnesses, override_harnesses):
            capabilities = spec_capability_values(
                runner.registry.get(harness_id).spec()
            )
            if (
                case.required_capability is not None
                and case.required_capability.value not in capabilities
            ):
                continue
            cells.append((case, harness_id))
    return cells


def _eval_run_status(
    results: list[EvalCaseRunResult],
    *,
    expected_count: int,
) -> str:
    if len(results) < expected_count:
        return "running"
    if any(result.status in {"queued", "running", "retry_wait"} for result in results):
        return "running"
    if results and all(result.status == "passed" for result in results):
        return "passed"
    return "failed"


def _eval_summary(results: list[EvalCaseRunResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.status == "passed")
    failed = sum(1 for result in results if result.status == "failed")
    errors = sum(1 for result in results if result.status == "error")
    score = passed / total if total else 0.0
    completed = [
        item for item in results if item.status in {"passed", "failed", "error"}
    ]
    metric_keys = {
        key
        for item in completed
        for key, value in item.metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    metrics = {
        key: round(
            sum(float(item.metrics[key]) for item in completed if key in item.metrics)
            / sum(1 for item in completed if key in item.metrics),
            4,
        )
        for key in sorted(metric_keys)
    }
    flaky = _flaky_case_targets(completed)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "score": score,
        "metrics": metrics,
        "flakes": len(flaky),
        "flaky_targets": flaky,
    }


def compare_eval_run_to_baseline(
    eval_run: HarnessEvalRun, baseline: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    """Return stable pass-rate and normalized metric deltas."""
    if baseline is None:
        return None
    baseline_summary = _mapping(baseline.get("summary"))
    current_metrics = _mapping(eval_run.summary.get("metrics"))
    baseline_metrics = _mapping(baseline_summary.get("metrics"))
    metric_keys = sorted(set(current_metrics) | set(baseline_metrics))
    return {
        "baseline_eval_run_id": baseline.get("eval_run_id"),
        "git_sha": baseline.get("git_sha"),
        "config_hash": baseline.get("config_hash"),
        "score_delta": round(
            float(eval_run.summary.get("score") or 0.0)
            - float(baseline_summary.get("score") or 0.0),
            6,
        ),
        "metric_deltas": {
            key: round(
                float(current_metrics.get(key) or 0.0)
                - float(baseline_metrics.get(key) or 0.0),
                6,
            )
            for key in metric_keys
        },
    }


def eval_compatibility_matrix(
    spec: HarnessEvalSpec, registry: Any
) -> list[dict[str, Any]]:
    """Build only capability-valid case/harness cells for the quality matrix."""
    selected = _selected_harnesses(spec.harnesses or DEFAULT_EVAL_HARNESSES)
    cells: list[dict[str, Any]] = []
    for case in spec.cases:
        for harness_id in _case_harnesses(case, selected, False):
            harness_spec = registry.get(harness_id).spec()
            capabilities = spec_capability_values(harness_spec)
            required = (
                case.required_capability.value
                if case.required_capability is not None
                else None
            )
            if required is not None and required not in capabilities:
                continue
            cells.append(
                {
                    "case_id": case.id,
                    "harness_id": harness_id,
                    "required_capability": required,
                    "capabilities": list(capabilities),
                    "api_mode": spec.api_mode.value,
                    "compatible": True,
                }
            )
    return cells


PROTOCOL_CONFORMANCE_FIXTURES: tuple[tuple[str, HarnessCapability], ...] = (
    ("openai-chat", HarnessCapability.CHAT_COMPLETIONS),
    ("openai-responses", HarnessCapability.RESPONSES),
    ("anthropic-messages", HarnessCapability.ANTHROPIC_MESSAGES),
    ("gemini-generate-content", HarnessCapability.GEMINI_GENERATE_CONTENT),
)


def protocol_conformance_matrix(registry: Any) -> list[dict[str, Any]]:
    """Project protocol fixtures through real harness capabilities and routes."""
    cells: list[dict[str, Any]] = []
    for fixture_id, capability in PROTOCOL_CONFORMANCE_FIXTURES:
        compatible = [
            harness.spec().id
            for harness in registry.list()
            if capability.value in spec_capability_values(harness.spec())
        ]
        for api_mode in (GigaChatApiMode.V1, GigaChatApiMode.V2):
            cells.append(
                {
                    "fixture_id": fixture_id,
                    "required_capability": capability.value,
                    "api_mode": api_mode.value,
                    "compatible_harness_ids": compatible,
                    "runnable": bool(compatible),
                }
            )
    return cells


def _run_metrics(run: HarnessRun) -> dict[str, Any]:
    metadata = _mapping(run.metadata)
    usage = _mapping(metadata.get("usage"))
    execution = _mapping(metadata.get("workspace_execution"))
    metrics: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = value
    started = _timestamp(run.started_at or run.created_at)
    finished = _timestamp(run.finished_at or run.updated_at)
    if started is not None and finished is not None:
        metrics["latency_seconds"] = round(max(finished - started, 0.0), 4)
    changed_files = execution.get("changed_files")
    if isinstance(changed_files, list):
        metrics["changed_files"] = len(changed_files)
    patch = execution.get("patch")
    if isinstance(patch, str):
        metrics["patch_bytes"] = len(patch.encode("utf-8"))
    metrics["test_passed"] = bool(
        metadata.get("test_passed") or execution.get("test_passed")
    )
    runtime = _mapping(metadata.get("runtime"))
    attempt_number = runtime.get("attempt_number")
    if isinstance(attempt_number, int):
        metrics["retries"] = max(attempt_number - 1, 0)
    return metrics


def _flaky_case_targets(results: list[EvalCaseRunResult]) -> list[str]:
    outcomes: dict[tuple[str, str, str], set[bool]] = {}
    for item in results:
        key = (item.case_id, item.target_type, item.target_id or item.harness_id)
        outcomes.setdefault(key, set()).add(item.ok)
    return [
        ":".join(key) for key, values in sorted(outcomes.items()) if len(values) > 1
    ]


def _result_identity(result: EvalCaseRunResult) -> tuple[str, str, str, int]:
    return (
        result.case_id,
        result.target_type,
        result.target_id or result.harness_id,
        result.repetition,
    )


def _timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _bounded_repetitions(value: Any) -> int:
    parsed = _positive_int(value, 1)
    if parsed > MAX_EVAL_REPETITIONS:
        raise ValueError(f"repetitions must be <= {MAX_EVAL_REPETITIONS}")
    return parsed


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _spec_config_hash(
    spec: HarnessEvalSpec, harness_ids: tuple[str, ...], repetitions: int
) -> str:
    payload = {
        "spec": eval_spec_to_dict(spec),
        "harness_ids": harness_ids,
        "repetitions": repetitions,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _eval_config_hash(eval_run: HarnessEvalRun) -> str:
    value = eval_run.metadata.get("config_hash")
    if isinstance(value, str) and value:
        return value
    payload = {
        "spec": eval_run.spec_name,
        "model": eval_run.model,
        "api_mode": eval_run.api_mode.value,
        "mode": eval_run.mode,
        "harness_ids": eval_run.harness_ids,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _git_sha(project_root: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        return None
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        text for text in (_optional_text(item) for item in value) if text is not None
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _redacted_text(value: Any) -> str | None:
    if value is None:
        return None
    redacted = redact_for_storage(str(value))
    return str(redacted) if redacted is not None else None


def _read_json(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("Eval run file must contain a JSON object")
    return data


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
