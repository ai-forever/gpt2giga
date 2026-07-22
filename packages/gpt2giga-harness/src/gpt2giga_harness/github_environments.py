"""Bounded read-only GitHub enrichment for canonical local environments."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from gpt2giga_harness.environments import EnvironmentSnapshot, HostedRepositoryHint


GITHUB_ENVIRONMENT_SCHEMA_VERSION = 1
GITHUB_CACHE_TTL_SECONDS = 30.0
GITHUB_TOTAL_TIMEOUT_SECONDS = 8.0
GITHUB_COMMAND_TIMEOUT_SECONDS = 3.0
MAX_GITHUB_CACHE_ENTRIES = 32
MAX_GITHUB_OUTPUT_BYTES = 512 * 1024
MAX_GITHUB_RUNS = 5
MAX_GITHUB_ISSUES = 20
MAX_GITHUB_CHECKS = 200
MAX_GITHUB_JOBS = 200
_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_BRANCH_RE = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
_STATE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class GitHubEnrichmentError(RuntimeError):
    """Content-free failure raised inside the GitHub enrichment boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GitHubCountRollup:
    """Content-free aggregate for checks or Actions jobs."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    pending: int = 0
    skipped: int = 0
    cancelled: int = 0
    unknown: int = 0

    def __post_init__(self) -> None:
        values = (
            self.total,
            self.passed,
            self.failed,
            self.pending,
            self.skipped,
            self.cancelled,
            self.unknown,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise ValueError("GitHub rollup counts must be non-negative integers")
        if self.total != sum(values[1:]):
            raise ValueError("GitHub rollup total is inconsistent")

    @property
    def status(self) -> str:
        if self.failed:
            return "failed"
        if self.pending or self.unknown:
            return "pending"
        if self.cancelled:
            return "cancelled"
        if self.total == 0:
            return "unavailable"
        return "passed"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bounded aggregate."""
        return {
            "status": self.status,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pending": self.pending,
            "skipped": self.skipped,
            "cancelled": self.cancelled,
            "unknown": self.unknown,
        }


@dataclass(frozen=True)
class GitHubRepositoryIdentity:
    """Public repository identity returned by GitHub."""

    host: str
    name_with_owner: str
    url: str
    default_branch: str | None
    is_fork: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize public repository metadata."""
        return {
            "host": self.host,
            "name_with_owner": self.name_with_owner,
            "url": self.url,
            "default_branch": self.default_branch,
            "is_fork": self.is_fork,
        }


@dataclass(frozen=True)
class GitHubIssueState:
    """Bounded linked issue state without title, body, or comments."""

    number: int
    state: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize linked issue identity and state."""
        return {"number": self.number, "state": self.state, "url": self.url}


@dataclass(frozen=True)
class GitHubPullRequestState:
    """Bounded pull-request state for the exact local branch."""

    number: int
    state: str
    url: str
    draft: bool
    head_branch: str
    base_branch: str
    checks: GitHubCountRollup
    issues: tuple[GitHubIssueState, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize PR state without user-authored content."""
        return {
            "number": self.number,
            "state": self.state,
            "url": self.url,
            "draft": self.draft,
            "head_branch": self.head_branch,
            "base_branch": self.base_branch,
            "checks": self.checks.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class GitHubActionsRun:
    """Bounded Actions run identity and aggregate job state."""

    database_id: int
    status: str
    conclusion: str | None
    url: str
    head_sha: str
    created_at: str
    updated_at: str
    jobs: GitHubCountRollup

    def to_dict(self) -> dict[str, Any]:
        """Serialize one run without workflow, job, or step names."""
        return {
            "database_id": self.database_id,
            "status": self.status,
            "conclusion": self.conclusion,
            "url": self.url,
            "head_sha": self.head_sha,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "jobs": self.jobs.to_dict(),
        }


@dataclass(frozen=True)
class GitHubEnvironmentSnapshot:
    """Read-only hosted enrichment bound to one local EnvironmentSnapshot."""

    status: str
    auth_status: str
    checked_at: str
    repository: GitHubRepositoryIdentity | None = None
    pull_request: GitHubPullRequestState | None = None
    runs: tuple[GitHubActionsRun, ...] = ()
    reason_code: str | None = None
    cached: bool = False
    stale: bool = False
    schema_version: int = GITHUB_ENVIRONMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GITHUB_ENVIRONMENT_SCHEMA_VERSION:
            raise ValueError("unsupported GitHub environment schema_version")
        if self.status not in {
            "ready",
            "unavailable",
            "rate_limited",
            "cancelled",
            "stale",
        }:
            raise ValueError("GitHub environment status is invalid")
        if self.auth_status not in {"authenticated", "unauthenticated", "unknown"}:
            raise ValueError("GitHub auth status is invalid")
        _parse_timestamp(self.checked_at)
        if len(self.runs) > MAX_GITHUB_RUNS:
            raise ValueError("too many GitHub Actions runs")
        if self.status == "ready" and self.repository is None:
            raise ValueError("ready GitHub environment requires a repository")
        if self.stale != (self.status == "stale"):
            raise ValueError("GitHub stale state is inconsistent")
        if (
            self.reason_code is not None
            and _STATE_RE.fullmatch(self.reason_code) is None
        ):
            raise ValueError("GitHub reason code is invalid")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the strict public enrichment shape."""
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "auth_status": self.auth_status,
            "checked_at": self.checked_at,
            "repository": self.repository.to_dict() if self.repository else None,
            "pull_request": self.pull_request.to_dict() if self.pull_request else None,
            "runs": [run.to_dict() for run in self.runs],
            "reason_code": self.reason_code,
            "cached": self.cached,
            "stale": self.stale,
        }


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _CacheEntry:
    stored_at: float
    snapshot: GitHubEnvironmentSnapshot


CommandRunner = Callable[
    [tuple[str, ...], Path, float, threading.Event], _CommandResult
]


class GitHubEnvironmentService:
    """Inspect GitHub through explicit read-only gh commands and a bounded TTL."""

    def __init__(
        self,
        *,
        gh_executable: str | None = None,
        command_runner: CommandRunner | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        cache_ttl_seconds: float = GITHUB_CACHE_TTL_SECONDS,
    ) -> None:
        self._runner = command_runner or _run_gh_command
        executable = gh_executable or shutil.which("gh")
        if executable is not None and command_runner is None:
            candidate = Path(executable).expanduser().resolve()
            executable = (
                str(candidate)
                if candidate.is_file() and os.access(candidate, os.X_OK)
                else None
            )
        self._gh = executable
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._cache_ttl = max(0.0, min(float(cache_ttl_seconds), 300.0))
        self._cache: OrderedDict[tuple[str, ...], _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def inspect(
        self,
        environment: EnvironmentSnapshot,
        repository_hint: HostedRepositoryHint | None,
        *,
        cancel_event: threading.Event | None = None,
        force: bool = False,
    ) -> GitHubEnvironmentSnapshot:
        """Return cached or freshly inspected GitHub state for one exact local HEAD."""
        cancel = cancel_event or threading.Event()
        checked_at = _format_timestamp(self._clock())
        if repository_hint is None:
            return _failure_snapshot("repository_unavailable", checked_at=checked_at)
        key = (
            repository_hint.host,
            repository_hint.name_with_owner,
            environment.worktree_root,
            environment.branch or "",
            environment.head or "",
        )
        cached = self._cached(key)
        if cached is not None and not force:
            return replace(cached, cached=True)
        if self._gh is None:
            return self._stale_or_failure(key, "gh_unavailable", checked_at)
        if (
            environment.branch is None
            or _BRANCH_RE.fullmatch(environment.branch) is None
        ):
            return self._stale_or_failure(key, "branch_unavailable", checked_at)
        if cancel.is_set():
            return self._stale_or_failure(key, "cancelled", checked_at)

        started = self._monotonic()
        repo_arg = f"{repository_hint.host}/{repository_hint.name_with_owner}"
        try:
            auth = self._command(
                environment,
                cancel,
                started,
                "auth",
                "status",
                "--active",
                "--hostname",
                repository_hint.host,
                allow_failure=True,
            )
            if auth.returncode != 0:
                code = _classify_failure(auth.stderr, default="unauthenticated")
                return self._stale_or_failure(
                    key, code, checked_at, auth_status="unauthenticated"
                )

            repo_payload = self._json_command(
                environment,
                cancel,
                started,
                "repo",
                "view",
                repo_arg,
                "--json",
                "nameWithOwner,url,isFork,defaultBranchRef",
            )
            repository = _parse_repository(repo_payload, repository_hint)
            pr_payload = self._json_command(
                environment,
                cancel,
                started,
                "pr",
                "list",
                "--repo",
                repo_arg,
                "--head",
                environment.branch,
                "--state",
                "all",
                "--limit",
                "1",
                "--json",
                "number,state,url,isDraft,headRefName,baseRefName,closingIssuesReferences,statusCheckRollup",
            )
            pull_request = _parse_pull_request(
                pr_payload,
                repository_hint.host,
                expected_branch=environment.branch,
            )
            runs_payload = self._json_command(
                environment,
                cancel,
                started,
                "run",
                "list",
                "--repo",
                repo_arg,
                "--branch",
                environment.branch,
                "--limit",
                str(MAX_GITHUB_RUNS),
                "--json",
                "databaseId,status,conclusion,headSha,url,createdAt,updatedAt",
            )
            run_items = _bounded_list(runs_payload, MAX_GITHUB_RUNS, "Actions runs")
            jobs = GitHubCountRollup()
            if run_items:
                run_id = _required_positive_int(run_items[0], "databaseId")
                jobs_payload = self._json_command(
                    environment,
                    cancel,
                    started,
                    "run",
                    "view",
                    str(run_id),
                    "--repo",
                    repo_arg,
                    "--json",
                    "jobs",
                )
                jobs = _parse_rollup(
                    _bounded_list(
                        _mapping(jobs_payload).get("jobs"),
                        MAX_GITHUB_JOBS,
                        "Actions jobs",
                    )
                )
            runs = _parse_runs(run_items, repository_hint.host, jobs)
        except GitHubEnrichmentError as exc:
            return self._stale_or_failure(key, exc.code, checked_at)

        snapshot = GitHubEnvironmentSnapshot(
            status="ready",
            auth_status="authenticated",
            checked_at=checked_at,
            repository=repository,
            pull_request=pull_request,
            runs=runs,
        )
        self._store(key, snapshot)
        return snapshot

    def _command(
        self,
        environment: EnvironmentSnapshot,
        cancel: threading.Event,
        started: float,
        *args: str,
        allow_failure: bool = False,
    ) -> _CommandResult:
        remaining = GITHUB_TOTAL_TIMEOUT_SECONDS - (self._monotonic() - started)
        if remaining <= 0:
            raise GitHubEnrichmentError(
                "github_timeout", "GitHub enrichment timed out."
            )
        result = self._runner(
            (str(self._gh), *args),
            Path(environment.worktree_root),
            min(GITHUB_COMMAND_TIMEOUT_SECONDS, remaining),
            cancel,
        )
        if result.returncode != 0 and not allow_failure:
            raise GitHubEnrichmentError(
                _classify_failure(result.stderr), "GitHub inspection failed."
            )
        return result

    def _json_command(
        self,
        environment: EnvironmentSnapshot,
        cancel: threading.Event,
        started: float,
        *args: str,
    ) -> Any:
        result = self._command(environment, cancel, started, *args)
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubEnrichmentError(
                "github_output_invalid", "GitHub returned invalid JSON."
            ) from exc

    def _cached(self, key: tuple[str, ...]) -> GitHubEnvironmentSnapshot | None:
        now = self._monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or now - entry.stored_at > self._cache_ttl:
                return None
            self._cache.move_to_end(key)
            return entry.snapshot

    def _store(self, key: tuple[str, ...], snapshot: GitHubEnvironmentSnapshot) -> None:
        with self._lock:
            self._cache[key] = _CacheEntry(self._monotonic(), snapshot)
            self._cache.move_to_end(key)
            while len(self._cache) > MAX_GITHUB_CACHE_ENTRIES:
                self._cache.popitem(last=False)

    def _stale_or_failure(
        self,
        key: tuple[str, ...],
        code: str,
        checked_at: str,
        *,
        auth_status: str = "unknown",
    ) -> GitHubEnvironmentSnapshot:
        with self._lock:
            entry = self._cache.get(key)
        if entry is not None:
            return replace(
                entry.snapshot,
                status="stale",
                reason_code=code,
                cached=True,
                stale=True,
            )
        return _failure_snapshot(code, checked_at=checked_at, auth_status=auth_status)


def _failure_snapshot(
    code: str,
    *,
    checked_at: str,
    auth_status: str = "unknown",
) -> GitHubEnvironmentSnapshot:
    status = (
        "rate_limited"
        if code == "rate_limited"
        else "cancelled"
        if code == "cancelled"
        else "unavailable"
    )
    return GitHubEnvironmentSnapshot(
        status=status,
        auth_status=auth_status,
        checked_at=checked_at,
        reason_code=code,
        stale=False,
    )


def _run_gh_command(
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: float,
    cancel_event: threading.Event,
) -> _CommandResult:
    environment = dict(os.environ)
    environment.update(
        {
            "GH_PROMPT_DISABLED": "1",
            "GH_PAGER": "cat",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "CLICOLOR": "0",
            "NO_COLOR": "1",
        }
    )
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()

    def drain(stream: Any, target: bytearray) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = MAX_GITHUB_OUTPUT_BYTES + 1 - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(target) > MAX_GITHUB_OUTPUT_BYTES or len(chunk) > remaining:
                overflow.set()

    threads = (
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    )
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while process.poll() is None:
            if cancel_event.wait(
                timeout=min(0.05, max(deadline - time.monotonic(), 0.0))
            ):
                process.kill()
                process.wait()
                raise GitHubEnrichmentError(
                    "cancelled", "GitHub enrichment was cancelled."
                )
            if time.monotonic() >= deadline:
                process.kill()
                process.wait()
                raise GitHubEnrichmentError(
                    "github_timeout", "GitHub enrichment timed out."
                )
            if overflow.is_set():
                process.kill()
                process.wait()
                raise GitHubEnrichmentError(
                    "github_output_limit", "GitHub output exceeded its limit."
                )
        returncode = int(process.returncode or 0)
    finally:
        for thread in threads:
            thread.join(timeout=1)
    if overflow.is_set():
        raise GitHubEnrichmentError(
            "github_output_limit", "GitHub output exceeded its limit."
        )
    return _CommandResult(returncode, bytes(stdout), bytes(stderr))


def _parse_repository(
    payload: Any, hint: HostedRepositoryHint
) -> GitHubRepositoryIdentity:
    data = _mapping(payload)
    name = _required_text(data, "nameWithOwner", 201)
    if name.casefold() != hint.name_with_owner.casefold():
        raise GitHubEnrichmentError(
            "repository_mismatch", "GitHub repository identity changed."
        )
    url = _safe_url(_required_text(data, "url", 2048), hint.host)
    default_ref = data.get("defaultBranchRef")
    default_branch = None
    if default_ref is not None:
        default_branch = _required_text(_mapping(default_ref), "name", 512)
        _validate_branch(default_branch)
    is_fork = data.get("isFork")
    if not isinstance(is_fork, bool):
        raise GitHubEnrichmentError(
            "github_output_invalid", "GitHub fork state is invalid."
        )
    return GitHubRepositoryIdentity(hint.host, name, url, default_branch, is_fork)


def _parse_pull_request(
    payload: Any, host: str, *, expected_branch: str
) -> GitHubPullRequestState | None:
    items = _bounded_list(payload, 1, "pull requests")
    if not items:
        return None
    data = _mapping(items[0])
    head = _required_text(data, "headRefName", 512)
    base = _required_text(data, "baseRefName", 512)
    _validate_branch(head)
    _validate_branch(base)
    if head != expected_branch:
        raise GitHubEnrichmentError(
            "pull_request_mismatch", "GitHub pull-request identity changed."
        )
    draft = data.get("isDraft")
    if not isinstance(draft, bool):
        raise GitHubEnrichmentError(
            "github_output_invalid", "GitHub draft state is invalid."
        )
    issue_items = _bounded_list(
        data.get("closingIssuesReferences"), MAX_GITHUB_ISSUES, "linked issues"
    )
    issues = tuple(
        GitHubIssueState(
            number=_required_positive_int(item, "number"),
            state=_state(_required_text(item, "state", 64)),
            url=_safe_url(_required_text(item, "url", 2048), host),
        )
        for item in issue_items
    )
    checks = _parse_rollup(
        _bounded_list(data.get("statusCheckRollup"), MAX_GITHUB_CHECKS, "checks")
    )
    return GitHubPullRequestState(
        number=_required_positive_int(data, "number"),
        state=_state(_required_text(data, "state", 64)),
        url=_safe_url(_required_text(data, "url", 2048), host),
        draft=draft,
        head_branch=head,
        base_branch=base,
        checks=checks,
        issues=issues,
    )


def _parse_runs(
    items: Sequence[Mapping[str, Any]],
    host: str,
    latest_jobs: GitHubCountRollup,
) -> tuple[GitHubActionsRun, ...]:
    runs = []
    for index, data in enumerate(items):
        conclusion_value = data.get("conclusion")
        conclusion = (
            _state(conclusion_value)
            if isinstance(conclusion_value, str) and conclusion_value
            else None
        )
        runs.append(
            GitHubActionsRun(
                database_id=_required_positive_int(data, "databaseId"),
                status=_state(_required_text(data, "status", 64)),
                conclusion=conclusion,
                url=_safe_url(_required_text(data, "url", 2048), host),
                head_sha=_required_sha(data, "headSha"),
                created_at=_required_timestamp(data, "createdAt"),
                updated_at=_required_timestamp(data, "updatedAt"),
                jobs=latest_jobs if index == 0 else GitHubCountRollup(),
            )
        )
    return tuple(runs)


def _parse_rollup(items: Sequence[Mapping[str, Any]]) -> GitHubCountRollup:
    counts = {
        "passed": 0,
        "failed": 0,
        "pending": 0,
        "skipped": 0,
        "cancelled": 0,
        "unknown": 0,
    }
    for item in items:
        raw = item.get("conclusion") or item.get("state") or item.get("status") or ""
        value = str(raw).casefold()
        if value in {"success", "passed", "pass"}:
            counts["passed"] += 1
        elif value in {
            "failure",
            "failed",
            "error",
            "timed_out",
            "startup_failure",
            "action_required",
        }:
            counts["failed"] += 1
        elif value in {
            "queued",
            "pending",
            "in_progress",
            "waiting",
            "requested",
            "expected",
        }:
            counts["pending"] += 1
        elif value in {"skipped", "neutral"}:
            counts["skipped"] += 1
        elif value in {"cancelled", "canceled", "stale"}:
            counts["cancelled"] += 1
        else:
            counts["unknown"] += 1
    return GitHubCountRollup(total=len(items), **counts)


def _classify_failure(payload: bytes, *, default: str = "github_failed") -> str:
    text = payload[:8192].decode("utf-8", "replace").casefold()
    if "rate limit" in text or "secondary rate" in text:
        return "rate_limited"
    if "not logged" in text or "authentication" in text or "bad credentials" in text:
        return "unauthenticated"
    if "could not resolve" in text or "network" in text or "connection" in text:
        return "network_unavailable"
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GitHubEnrichmentError(
            "github_output_invalid", "GitHub object is invalid."
        )
    return value


def _bounded_list(value: Any, limit: int, name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) > limit:
        raise GitHubEnrichmentError(
            "github_output_invalid", f"GitHub {name} output is invalid."
        )
    return [_mapping(item) for item in value]


def _required_text(data: Mapping[str, Any], field: str, limit: int) -> str:
    value = data.get(field)
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(char) < 32 for char in value)
    ):
        raise GitHubEnrichmentError("github_output_invalid", "GitHub text is invalid.")
    return value


def _required_positive_int(data: Mapping[str, Any], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GitHubEnrichmentError("github_output_invalid", "GitHub id is invalid.")
    return value


def _required_sha(data: Mapping[str, Any], field: str) -> str:
    value = _required_text(data, field, 64)
    if _SHA_RE.fullmatch(value) is None:
        raise GitHubEnrichmentError("github_output_invalid", "GitHub SHA is invalid.")
    return value


def _validate_branch(value: str) -> None:
    if _BRANCH_RE.fullmatch(value) is None:
        raise GitHubEnrichmentError(
            "github_output_invalid", "GitHub branch is invalid."
        )


def _state(value: str) -> str:
    normalized = value.casefold()
    if _STATE_RE.fullmatch(normalized) is None:
        raise GitHubEnrichmentError("github_output_invalid", "GitHub state is invalid.")
    return normalized


def _safe_url(value: str, expected_host: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise GitHubEnrichmentError(
            "github_output_invalid", "GitHub URL is invalid."
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != expected_host.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GitHubEnrichmentError("github_output_invalid", "GitHub URL is invalid.")
    return value


def _required_timestamp(data: Mapping[str, Any], field: str) -> str:
    value = _required_text(data, field, 64)
    try:
        _parse_timestamp(value)
    except ValueError as exc:
        raise GitHubEnrichmentError(
            "github_output_invalid", "GitHub timestamp is invalid."
        ) from exc
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
