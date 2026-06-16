#!/usr/bin/env python3
"""Run example files as an E2E smoke matrix against gpt2giga."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = REPO_ROOT / "examples"
DEFAULT_BASE_URL = "http://localhost:8090"
DEFAULT_API_VERSIONS = ("v1", "v2")
PASS = "passed"
FAIL = "failed"
SKIP = "skipped"


@dataclass(frozen=True)
class SkipRule:
    pattern: str
    reason: str


@dataclass(frozen=True)
class ExampleCase:
    path: Path
    rel_path: str
    skip_reason: str | None = None


@dataclass(frozen=True)
class ExampleResult:
    path: str
    api_version: str
    status: str
    duration_seconds: float
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


DEFAULT_SKIP_RULES = (
    SkipRule(
        "examples/openai/files/*",
        "OpenAI Files API router is prepared but not mounted.",
    ),
    SkipRule(
        "examples/openai/batches/*",
        "OpenAI Batches API router is prepared but not mounted.",
    ),
    SkipRule(
        "examples/anthropic/message_batches/*",
        "Anthropic Message Batches API router is prepared but not mounted.",
    ),
    SkipRule(
        "examples/gemini/files/*",
        "Gemini Files API router is prepared but not mounted.",
    ),
    SkipRule(
        "examples/gemini/batches/*",
        "Gemini Batch API router is prepared but not mounted.",
    ),
    SkipRule(
        "examples/openai/agents/*",
        "OpenAI Agents example needs the integrations group and external APIs.",
    ),
)


class ExampleSourceTransformer(ast.NodeTransformer):
    """Patch an example module for the requested smoke-test target."""

    def __init__(self, api_version: str, base_url: str) -> None:
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        node = self.generic_visit(node)
        if any(_is_api_version_target(target) for target in node.targets):
            node.value = ast.copy_location(ast.Constant(self.api_version), node.value)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        node = self.generic_visit(node)
        if _is_api_version_target(node.target):
            node.value = ast.copy_location(
                ast.Constant(self.api_version),
                node.value or node,
            )
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if not isinstance(node.value, str):
            return node

        updated = _rewrite_local_base_url(
            node.value,
            api_version=self.api_version,
            base_url=self.base_url,
        )
        if updated == node.value:
            return node
        return ast.copy_location(ast.Constant(updated), node)


def _is_api_version_target(target: ast.AST) -> bool:
    return isinstance(target, ast.Name) and target.id == "api_version"


def _rewrite_local_base_url(value: str, *, api_version: str, base_url: str) -> str:
    if DEFAULT_BASE_URL not in value:
        return value

    updated = value.replace(DEFAULT_BASE_URL, base_url.rstrip("/"))
    for version in DEFAULT_API_VERSIONS:
        updated = updated.replace(
            f"{base_url.rstrip('/')}/{version}",
            f"{base_url.rstrip('/')}/{api_version}",
        )
    return updated


def parse_api_versions(raw: str) -> tuple[str, ...]:
    versions: list[str] = []
    for item in raw.split(","):
        version = item.strip().lower().removeprefix("/")
        if not version:
            continue
        if version not in DEFAULT_API_VERSIONS:
            raise ValueError(
                f"unsupported api_version {version!r}; expected v1 and/or v2"
            )
        if version not in versions:
            versions.append(version)
    if not versions:
        raise ValueError("at least one api_version is required")
    return tuple(versions)


def positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be greater than or equal to 1")
    return value


def relative_to_repo(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def known_skip_reason(rel_path: str) -> str | None:
    for rule in DEFAULT_SKIP_RULES:
        if fnmatch.fnmatch(rel_path, rule.pattern):
            return rule.reason
    return None


def discover_example_cases(
    roots: list[Path],
    *,
    include_known_unsupported: bool,
    exclude_patterns: list[str],
) -> list[ExampleCase]:
    paths: list[Path] = []
    for root in roots:
        path = root if root.is_absolute() else REPO_ROOT / root
        if not path.exists():
            raise ValueError(f"path does not exist: {root}")
        if path.is_file():
            if path.suffix == ".py" and path.name != "__init__.py":
                paths.append(path)
            continue
        paths.extend(
            candidate
            for candidate in path.rglob("*.py")
            if candidate.name != "__init__.py"
        )

    cases: list[ExampleCase] = []
    seen: set[Path] = set()
    for path in sorted({item.resolve() for item in paths}):
        if path in seen:
            continue
        seen.add(path)

        rel_path = relative_to_repo(path)
        if any(fnmatch.fnmatch(rel_path, pattern) for pattern in exclude_patterns):
            continue

        skip_reason = None
        if not include_known_unsupported:
            skip_reason = known_skip_reason(rel_path)
        cases.append(ExampleCase(path=path, rel_path=rel_path, skip_reason=skip_reason))
    return cases


def build_child_env(base_url: str, api_version: str) -> dict[str, str]:
    env = os.environ.copy()
    clean_base_url = base_url.rstrip("/")
    versioned_base_url = f"{clean_base_url}/{api_version}/"
    env["GPT2GIGA_EXAMPLE_API_VERSION"] = api_version
    env["GPT2GIGA_EXAMPLE_BASE_URL"] = clean_base_url
    env["OPENAI_BASE_URL"] = versioned_base_url
    env["ANTHROPIC_BASE_URL"] = versioned_base_url
    env.setdefault("OPENAI_API_KEY", "0")
    env.setdefault("ANTHROPIC_API_KEY", "any-key")
    return env


def execute_example_file(path: Path, *, api_version: str, base_url: str) -> None:
    path = path.resolve()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    tree = ExampleSourceTransformer(api_version, base_url).visit(tree)
    ast.fix_missing_locations(tree)

    globals_dict = {
        "__builtins__": __builtins__,
        "__cached__": None,
        "__doc__": None,
        "__file__": str(path),
        "__name__": "__main__",
        "__package__": None,
    }
    previous_argv = sys.argv[:]
    previous_path = sys.path[:]
    try:
        sys.argv = [str(path)]
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        exec(compile(tree, str(path), "exec"), globals_dict)
    finally:
        sys.argv = previous_argv
        sys.path[:] = previous_path


def run_example_subprocess(
    case: ExampleCase,
    *,
    api_version: str,
    base_url: str,
    python: str,
    timeout: float,
) -> ExampleResult:
    start = time.monotonic()
    command = [
        python,
        str(Path(__file__).resolve()),
        "--_run-example",
        str(case.path),
        "--_api-version",
        api_version,
        "--base-url",
        base_url,
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=build_child_env(base_url, api_version),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        return ExampleResult(
            path=case.rel_path,
            api_version=api_version,
            status=FAIL,
            duration_seconds=duration,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            error=f"timed out after {timeout:.1f}s",
        )

    duration = time.monotonic() - start
    status = PASS if completed.returncode == 0 else FAIL
    return ExampleResult(
        path=case.rel_path,
        api_version=api_version,
        status=status,
        duration_seconds=duration,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_matrix(
    cases: list[ExampleCase],
    *,
    api_versions: tuple[str, ...],
    base_url: str,
    python: str,
    timeout: float,
    concurrency: int,
    fail_fast: bool,
    verbose: bool,
) -> list[ExampleResult]:
    if concurrency < 1:
        raise ValueError("concurrency must be greater than or equal to 1")

    results: list[ExampleResult] = []
    for api_version in api_versions:
        stop_scheduling = False
        pending_cases = iter(cases)
        active: dict[Future[ExampleResult], ExampleCase] = {}

        with ThreadPoolExecutor(max_workers=concurrency) as executor:

            def schedule_until_full() -> None:
                nonlocal stop_scheduling
                while not stop_scheduling and len(active) < concurrency:
                    try:
                        case = next(pending_cases)
                    except StopIteration:
                        return

                    if case.skip_reason is not None:
                        result = ExampleResult(
                            path=case.rel_path,
                            api_version=api_version,
                            status=SKIP,
                            duration_seconds=0.0,
                            error=case.skip_reason,
                        )
                        print(
                            f"[{api_version}] SKIP {case.rel_path} - {case.skip_reason}"
                        )
                        results.append(result)
                        continue

                    print(f"[{api_version}] RUN  {case.rel_path}")
                    future = executor.submit(
                        run_example_subprocess,
                        case,
                        api_version=api_version,
                        base_url=base_url,
                        python=python,
                        timeout=timeout,
                    )
                    active[future] = case

            schedule_until_full()
            while active:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    case = active.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = ExampleResult(
                            path=case.rel_path,
                            api_version=api_version,
                            status=FAIL,
                            duration_seconds=0.0,
                            error=f"runner failed: {exc}",
                        )

                    results.append(result)
                    print_result(result, verbose=verbose)
                    if fail_fast and result.status == FAIL:
                        stop_scheduling = True

                schedule_until_full()

        if stop_scheduling:
            return results

    return results


def print_result(result: ExampleResult, *, verbose: bool) -> None:
    if result.status == PASS:
        print(
            f"[{result.api_version}] OK   {result.path} "
            f"({result.duration_seconds:.1f}s)"
        )
        if verbose and result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if verbose and result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        return

    if result.status == FAIL:
        print(
            f"[{result.api_version}] FAIL {result.path} "
            f"({result.duration_seconds:.1f}s)"
        )
        return

    if result.status == SKIP:
        suffix = f" - {result.error}" if result.error else ""
        print(f"[{result.api_version}] SKIP {result.path}{suffix}")


def check_server_health(base_url: str, timeout: float) -> None:
    url = f"{base_url.rstrip('/')}/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read(500).decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"cannot reach {url}: {exc}") from exc

    if status != 200:
        raise RuntimeError(f"{url} returned HTTP {status}: {body}")


def summarize_results(
    results: list[ExampleResult], *, failure_output_lines: int
) -> None:
    passed = sum(result.status == PASS for result in results)
    failed = sum(result.status == FAIL for result in results)
    skipped = sum(result.status == SKIP for result in results)
    print(f"\nSmoke summary: {passed} passed, {failed} failed, {skipped} skipped.")

    failures = [result for result in results if result.status == FAIL]
    if not failures:
        return

    print("\nFailures by file:")
    for result in failures:
        print(f"- [{result.api_version}] {result.path}")
        if result.returncode is not None:
            print(f"  return code: {result.returncode}")
        if result.error:
            print(f"  error: {result.error}")
        stdout = tail_text(result.stdout, failure_output_lines)
        stderr = tail_text(result.stderr, failure_output_lines)
        if stdout:
            print("  stdout:")
            print(_indent(stdout, "    "))
        if stderr:
            print("  stderr:")
            print(_indent(stderr, "    "))


def write_json_report(
    path: Path,
    *,
    results: list[ExampleResult],
    base_url: str,
    api_versions: tuple[str, ...],
    failure_output_lines: int,
) -> None:
    payload = {
        "base_url": base_url.rstrip("/"),
        "api_versions": list(api_versions),
        "summary": {
            PASS: sum(result.status == PASS for result in results),
            FAIL: sum(result.status == FAIL for result in results),
            SKIP: sum(result.status == SKIP for result in results),
        },
        "results": [
            result_to_json(result, failure_output_lines=failure_output_lines)
            for result in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def result_to_json(
    result: ExampleResult,
    *,
    failure_output_lines: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": result.path,
        "api_version": result.api_version,
        "status": result.status,
        "duration_seconds": round(result.duration_seconds, 3),
    }
    if result.returncode is not None:
        payload["returncode"] = result.returncode
    if result.error:
        payload["error"] = result.error
    if result.status == FAIL:
        payload["stdout_tail"] = tail_text(result.stdout, failure_output_lines)
        payload["stderr_tail"] = tail_text(result.stderr, failure_output_lines)
    return payload


def tail_text(text: str, max_lines: int) -> str:
    if max_lines <= 0 or not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.rstrip()
    clipped = "\n".join(lines[-max_lines:])
    return f"... clipped {len(lines) - max_lines} lines ...\n{clipped}"


def _indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run examples/**/*.py against a local gpt2giga server for v1/v2 "
            "smoke coverage."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["examples"],
        help="Example files or directories to run. Defaults to examples/.",
    )
    parser.add_argument(
        "--api-versions",
        default=",".join(DEFAULT_API_VERSIONS),
        help="Comma-separated API versions to test. Default: v1,v2.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Root gpt2giga URL. Default: http://localhost:8090.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Per-example timeout in seconds. Default: 180.",
    )
    parser.add_argument(
        "-n",
        "--concurrency",
        type=positive_int,
        default=1,
        help="Maximum number of examples to run at the same time. Default: 1.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for child example runs.",
    )
    parser.add_argument(
        "--include-known-unsupported",
        action="store_true",
        help="Also run file/batch and agents examples that are skipped by default.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="fnmatch pattern for repo-relative example paths to exclude.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional path for a structured JSON report.",
    )
    parser.add_argument(
        "--failure-output-lines",
        type=int,
        default=80,
        help="How many stdout/stderr lines to keep for each failure. Default: 80.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed example.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print stdout/stderr for successful examples too.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the discovered matrix without executing examples.",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Do not check BASE_URL/health before running examples.",
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=3.0,
        help="Health-check timeout in seconds. Default: 3.",
    )
    parser.add_argument("--_run-example", help=argparse.SUPPRESS)
    parser.add_argument("--_api-version", help=argparse.SUPPRESS)
    return parser


def run_cli(args: argparse.Namespace) -> int:
    try:
        api_versions = parse_api_versions(args.api_versions)
        roots = [Path(path) for path in args.paths]
        cases = discover_example_cases(
            roots,
            include_known_unsupported=args.include_known_unsupported,
            exclude_patterns=args.exclude,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not cases:
        print("error: no example files discovered", file=sys.stderr)
        return 2

    runnable = sum(case.skip_reason is None for case in cases)
    skipped = len(cases) - runnable
    print(
        f"Discovered {len(cases)} example files: "
        f"{runnable} runnable, {skipped} skipped by default."
    )

    if args.dry_run:
        for api_version in api_versions:
            for case in cases:
                marker = "SKIP" if case.skip_reason else "RUN "
                suffix = f" - {case.skip_reason}" if case.skip_reason else ""
                print(f"[{api_version}] {marker} {case.rel_path}{suffix}")
        return 0

    if not args.skip_health_check:
        try:
            check_server_health(args.base_url, args.health_timeout)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    results = run_matrix(
        cases,
        api_versions=api_versions,
        base_url=args.base_url,
        python=args.python,
        timeout=args.timeout,
        concurrency=args.concurrency,
        fail_fast=args.fail_fast,
        verbose=args.verbose,
    )
    summarize_results(results, failure_output_lines=args.failure_output_lines)

    if args.report_json:
        write_json_report(
            args.report_json,
            results=results,
            base_url=args.base_url,
            api_versions=api_versions,
            failure_output_lines=args.failure_output_lines,
        )
        print(f"\nWrote JSON report: {args.report_json}")

    return 1 if any(result.status == FAIL for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args._run_example:
        if not args._api_version:
            print(
                "error: --_api-version is required with --_run-example", file=sys.stderr
            )
            return 2
        execute_example_file(
            Path(args._run_example),
            api_version=args._api_version,
            base_url=args.base_url,
        )
        return 0

    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
