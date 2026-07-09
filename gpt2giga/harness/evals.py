"""Local eval and benchmark runs for project harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from gpt2giga.harness.project import HarnessProject
from gpt2giga.harness.sessions.redaction import redact_for_storage
from gpt2giga.harness.sessions.store import new_id, utc_now
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.types import GigaChatApiMode, parse_api_mode

EVALS_RELATIVE_DIR = Path(".giga") / "evals"
EVAL_RUNS_DIR = "eval-runs"
DEFAULT_EVAL_HARNESSES = ("echo",)
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
        _write_json_atomic(
            directory / f"{eval_run.id}.json", eval_run_to_dict(eval_run)
        )
        return eval_run

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

    def _project_runs_dir(self, project: HarnessProject) -> Path:
        return Path(project.state_dir).expanduser() / EVAL_RUNS_DIR


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
) -> HarnessEvalRun:
    """Run a project eval spec against selected harnesses."""
    selected_harnesses = _selected_harnesses(
        harness_ids or spec.harnesses or DEFAULT_EVAL_HARNESSES
    )
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
        metadata={"dry_run": dry_run},
    )
    eval_store.save(project, eval_run)
    results: list[EvalCaseRunResult] = []
    override_harnesses = bool(harness_ids)
    for case in spec.cases:
        for harness_id in _case_harnesses(case, selected_harnesses, override_harnesses):
            results.append(
                _run_eval_case(
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
            )
            eval_run = replace(
                eval_run,
                status=_eval_run_status(
                    results,
                    expected_count=_expected_count(
                        spec, selected_harnesses, override_harnesses
                    ),
                ),
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
    }
    if include_cases:
        payload["cases"] = [
            {
                "id": case.id,
                "prompt": _redacted_text(case.prompt),
                "harnesses": list(case.harnesses),
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


def _expected_count(
    spec: HarnessEvalSpec,
    selected_harnesses: tuple[str, ...],
    override_harnesses: bool,
) -> int:
    return sum(
        len(_case_harnesses(case, selected_harnesses, override_harnesses))
        for case in spec.cases
    )


def _eval_run_status(
    results: list[EvalCaseRunResult],
    *,
    expected_count: int,
) -> str:
    if len(results) < expected_count:
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
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "score": score,
    }


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
