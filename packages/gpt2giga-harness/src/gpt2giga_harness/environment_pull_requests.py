"""Governed, immutable-state-bound pull-request creation for Environments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit

from gpt2giga_harness.environments import (
    EnvironmentCaptureError,
    EnvironmentSnapshot,
    GitEnvironmentProvider,
    HostedRepositoryHint,
)
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    INTERACTIVE_PROFILE,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore


ENVIRONMENT_PULL_REQUEST_SCHEMA_VERSION = 1
ENVIRONMENT_PULL_REQUEST_OWNER = "environment.pull_request"
MAX_PULL_REQUEST_TITLE_CHARS = 256
MAX_PULL_REQUEST_BODY_CHARS = 16 * 1024
MAX_HOSTED_OUTPUT_BYTES = 1024 * 1024
HOSTED_COMMAND_TIMEOUT_SECONDS = 15.0
_HEX_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_PREVIEW_ID_RE = re.compile(r"pull_request_[0-9a-f]{64}\Z")
_REF_COMPONENT_RE = re.compile(r"(?!-)(?!.*\.\.)(?!.*@\{)[^\x00-\x20~^:?*\\]+\Z")


class EnvironmentPullRequestError(RuntimeError):
    """Content-free failure for one governed hosted pull-request action."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EnvironmentPullRequestPreview:
    """Private preview of one exact hosted pull-request creation intent."""

    id: str
    repository_root: str
    worktree_root: str
    repository_host: str
    repository_name: str
    repository_url: str
    remote: str
    source_branch: str
    source_head: str
    source_remote_head: str
    base_branch: str
    base_head: str
    diff_sha256: str
    title: str
    body: str
    created_at: str
    schema_version: int = ENVIRONMENT_PULL_REQUEST_SCHEMA_VERSION

    @property
    def approval_binding(self) -> str:
        """Return the opaque immutable binding consumed by the policy owner."""
        return f"environment-pull-request-v1:{self.id}"

    @property
    def scope_id(self) -> str:
        """Return a content-free project scope for allow-once approvals."""
        digest = hashlib.sha256(self.worktree_root.encode("utf-8")).hexdigest()
        return f"environment_{digest[:32]}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the exact hosted-write preview."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "repository_root": self.repository_root,
            "worktree_root": self.worktree_root,
            "repository": {
                "host": self.repository_host,
                "name_with_owner": self.repository_name,
                "url": self.repository_url,
            },
            "remote": self.remote,
            "source_branch": self.source_branch,
            "source_head": self.source_head,
            "source_remote_head": self.source_remote_head,
            "base_branch": self.base_branch,
            "base_head": self.base_head,
            "diff_sha256": self.diff_sha256,
            "title": self.title,
            "body": self.body,
            "permissions": {
                "network_connect": True,
                "hosted_write": True,
                "create_pull_request": True,
                "update_pull_request": False,
                "merge_pull_request": False,
                "write_issue": False,
                "write_checks": False,
                "write_actions": False,
                "push_commits": False,
            },
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentPullRequestPreview:
        """Parse one strict private preview record."""
        repository = payload.get("repository")
        if not isinstance(repository, Mapping):
            raise ValueError("pull-request preview repository is invalid")
        preview = cls(
            schema_version=int(payload.get("schema_version", 0)),
            id=str(payload.get("id", "")),
            repository_root=str(payload.get("repository_root", "")),
            worktree_root=str(payload.get("worktree_root", "")),
            repository_host=str(repository.get("host", "")),
            repository_name=str(repository.get("name_with_owner", "")),
            repository_url=str(repository.get("url", "")),
            remote=str(payload.get("remote", "")),
            source_branch=str(payload.get("source_branch", "")),
            source_head=str(payload.get("source_head", "")),
            source_remote_head=str(payload.get("source_remote_head", "")),
            base_branch=str(payload.get("base_branch", "")),
            base_head=str(payload.get("base_head", "")),
            diff_sha256=str(payload.get("diff_sha256", "")),
            title=str(payload.get("title", "")),
            body=str(payload.get("body", "")),
            created_at=str(payload.get("created_at", "")),
        )
        _validate_preview(preview)
        return preview


@dataclass(frozen=True)
class EnvironmentPullRequestResult:
    """Durable, bounded evidence for one exact pull request."""

    preview_id: str
    number: int
    state: str
    source_branch: str
    base_branch: str
    commit_head: str
    pull_request_url: str
    commit_url: str
    checks_url: str
    run_evidence_url: str
    completed_at: str
    recovered: bool = False
    schema_version: int = ENVIRONMENT_PULL_REQUEST_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize bounded hosted completion evidence."""
        return {
            "schema_version": self.schema_version,
            "preview_id": self.preview_id,
            "number": self.number,
            "state": self.state,
            "source_branch": self.source_branch,
            "base_branch": self.base_branch,
            "commit_head": self.commit_head,
            "pull_request_url": self.pull_request_url,
            "commit_url": self.commit_url,
            "checks_url": self.checks_url,
            "run_evidence_url": self.run_evidence_url,
            "completed_at": self.completed_at,
            "recovered": self.recovered,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentPullRequestResult:
        """Parse one strict durable completion record."""
        result = cls(
            schema_version=int(payload.get("schema_version", 0)),
            preview_id=str(payload.get("preview_id", "")),
            number=int(payload.get("number", 0)),
            state=str(payload.get("state", "")),
            source_branch=str(payload.get("source_branch", "")),
            base_branch=str(payload.get("base_branch", "")),
            commit_head=str(payload.get("commit_head", "")),
            pull_request_url=str(payload.get("pull_request_url", "")),
            commit_url=str(payload.get("commit_url", "")),
            checks_url=str(payload.get("checks_url", "")),
            run_evidence_url=str(payload.get("run_evidence_url", "")),
            completed_at=str(payload.get("completed_at", "")),
            recovered=bool(payload.get("recovered", False)),
        )
        _validate_result(result)
        return result


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


HostedCommandRunner = Callable[
    [tuple[str, ...], Path, bytes | None, float], _CommandResult
]


class EnvironmentPullRequestService:
    """Preview and create exact same-repository pull requests through gh."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        git_executable: str | None = None,
        gh_executable: str | None = None,
        command_runner: HostedCommandRunner | None = None,
        clock: Callable[[], datetime] | None = None,
        repository_resolver: Callable[
            [EnvironmentSnapshot], HostedRepositoryHint | None
        ]
        | None = None,
    ) -> None:
        git = _resolve_executable(git_executable or shutil.which("git"))
        if git is None:
            raise EnvironmentPullRequestError("git_unavailable", "Git is unavailable.")
        gh = gh_executable or shutil.which("gh")
        if command_runner is None:
            gh = _resolve_executable(gh)
        if gh is None:
            raise EnvironmentPullRequestError(
                "gh_unavailable", "GitHub CLI is unavailable."
            )
        self._git = git
        self._gh = str(gh)
        self._runner = command_runner or _run_hosted_command
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._provider = GitEnvironmentProvider(git_executable=git, clock=self._clock)
        self._repository_resolver = (
            repository_resolver or self._provider.hosted_repository
        )
        self._root = Path(data_dir).expanduser().resolve() / "environment_pull_requests"
        self._previews = self._root / "previews"
        self._results = self._root / "results"
        self._lock = threading.RLock()

    def preview(
        self,
        workspace: str | Path,
        *,
        title: str,
        body: str,
        base_branch: str | None = None,
    ) -> EnvironmentPullRequestPreview:
        """Persist or reuse one local/remote/hosted-state-bound PR preview."""
        title = _validate_title(title)
        body = _validate_body(body)
        snapshot = self._capture(workspace)
        remote, source_branch, source_head = self._source(snapshot)
        hint = self._repository_resolver(snapshot)
        if hint is None:
            raise EnvironmentPullRequestError(
                "hosted_remote_required",
                "A governed pull request requires one supported hosted remote.",
            )
        source_remote_head = self._remote_head(
            Path(snapshot.worktree_root), remote, source_branch
        )
        if source_remote_head != source_head:
            raise EnvironmentPullRequestError(
                "source_not_pushed",
                "The exact source HEAD must be pushed before pull-request creation.",
            )
        repository_url, default_branch = self._repository(snapshot, hint)
        base = _validate_ref_component(base_branch or default_branch, "base branch")
        if base == source_branch:
            raise EnvironmentPullRequestError(
                "base_matches_source",
                "Pull-request base and source branches must differ.",
            )
        base_head = self._remote_head(Path(snapshot.worktree_root), remote, base)
        if base_head is None:
            raise EnvironmentPullRequestError(
                "base_unavailable", "The pull-request base branch is unavailable."
            )
        semantic = {
            "schema_version": ENVIRONMENT_PULL_REQUEST_SCHEMA_VERSION,
            "repository_root": snapshot.repository_root,
            "worktree_root": snapshot.worktree_root,
            "repository_host": hint.host,
            "repository_name": hint.name_with_owner,
            "repository_url": repository_url,
            "remote": remote,
            "source_branch": source_branch,
            "source_head": source_head,
            "source_remote_head": source_remote_head,
            "base_branch": base,
            "base_head": base_head,
            "diff_sha256": snapshot.diff_sha256,
            "title": title,
            "body": body,
        }
        preview_id = f"pull_request_{_mapping_hash(semantic)}"
        path = self._preview_path(preview_id)
        with self._lock:
            if path.is_file():
                return self.get_preview(preview_id)
            preview = EnvironmentPullRequestPreview(
                id=preview_id,
                repository_root=snapshot.repository_root,
                worktree_root=snapshot.worktree_root,
                repository_host=hint.host,
                repository_name=hint.name_with_owner,
                repository_url=repository_url,
                remote=remote,
                source_branch=source_branch,
                source_head=source_head,
                source_remote_head=source_remote_head,
                base_branch=base,
                base_head=base_head,
                diff_sha256=snapshot.diff_sha256,
                title=title,
                body=body,
                created_at=_utc_now(self._clock),
            )
            _write_private_json(path, preview.to_dict())
            return preview

    def get_preview(self, preview_id: str) -> EnvironmentPullRequestPreview:
        """Load one exact private pull-request preview."""
        path = self._preview_path(preview_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("pull-request preview record is invalid")
            return EnvironmentPullRequestPreview.from_dict(payload)
        except FileNotFoundError as exc:
            raise EnvironmentPullRequestError(
                "preview_not_found", "Pull-request preview was not found."
            ) from exc
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EnvironmentPullRequestError(
                "preview_invalid", "Pull-request preview is unavailable."
            ) from exc

    def completed_result(self, preview_id: str) -> EnvironmentPullRequestResult | None:
        """Return durable completion evidence without contacting GitHub."""
        path = self._result_path(preview_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("pull-request result record is invalid")
            return EnvironmentPullRequestResult.from_dict(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EnvironmentPullRequestError(
                "result_invalid", "Pull-request completion evidence is unavailable."
            ) from exc

    def validate_current(self, preview: EnvironmentPullRequestPreview) -> None:
        """Fail before approval consumption when any bound state is stale."""
        if self.completed_result(preview.id) is not None:
            return
        snapshot = self._capture(preview.worktree_root)
        if not _snapshot_matches_preview(snapshot, preview):
            raise EnvironmentPullRequestError(
                "stale_preview", "Git state changed after the pull-request preview."
            )
        hint = self._repository_resolver(snapshot)
        if (
            hint is None
            or hint.host != preview.repository_host
            or hint.name_with_owner.casefold() != preview.repository_name.casefold()
        ):
            raise EnvironmentPullRequestError(
                "remote_changed", "Hosted repository changed after the preview."
            )
        repository_url, _ = self._repository(snapshot, hint)
        if repository_url != preview.repository_url:
            raise EnvironmentPullRequestError(
                "remote_changed", "Hosted repository changed after the preview."
            )
        root = Path(preview.worktree_root)
        if (
            self._remote_head(root, preview.remote, preview.source_branch)
            != preview.source_remote_head
        ):
            raise EnvironmentPullRequestError(
                "remote_changed", "Source branch changed after the preview."
            )
        if (
            self._remote_head(root, preview.remote, preview.base_branch)
            != preview.base_head
        ):
            raise EnvironmentPullRequestError(
                "remote_changed", "Base branch changed after the preview."
            )

    def apply(self, preview_id: str) -> EnvironmentPullRequestResult:
        """Create one exact PR once, or recover the matching hosted result."""
        with self._lock:
            preview = self.get_preview(preview_id)
            completed = self.completed_result(preview.id)
            if completed is not None:
                return completed
            self.validate_current(preview)
            existing = self._find_existing(preview)
            if existing is not None:
                result = self._result(preview, existing, recovered=True)
                _write_private_json(self._result_path(preview.id), result.to_dict())
                return result
            payload = json.dumps(
                {
                    "title": preview.title,
                    "body": preview.body,
                    "head": preview.source_branch,
                    "base": preview.base_branch,
                    "draft": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            response = self._command(
                Path(preview.worktree_root),
                "api",
                "--hostname",
                preview.repository_host,
                "--method",
                "POST",
                f"repos/{preview.repository_name}/pulls",
                "--input",
                "-",
                input_bytes=payload,
                allow_failure=True,
            )
            if response.returncode != 0:
                existing = self._find_existing(preview)
                if existing is None:
                    raise EnvironmentPullRequestError(
                        _classify_hosted_failure(response.stderr),
                        "Pull-request creation failed.",
                    )
                result = self._result(preview, existing, recovered=True)
            else:
                result = self._result(
                    preview,
                    _parse_pull_request(response.stdout, preview),
                    recovered=False,
                )
            _write_private_json(self._result_path(preview.id), result.to_dict())
            return result

    def _capture(self, workspace: str | Path) -> EnvironmentSnapshot:
        try:
            return self._provider.snapshot(workspace)
        except EnvironmentCaptureError as exc:
            raise EnvironmentPullRequestError(exc.code, str(exc)) from exc

    def _source(self, snapshot: EnvironmentSnapshot) -> tuple[str, str, str]:
        if snapshot.detached or snapshot.branch is None:
            raise EnvironmentPullRequestError(
                "detached_head", "A governed pull request requires an attached branch."
            )
        if snapshot.head is None:
            raise EnvironmentPullRequestError(
                "unborn_head", "A governed pull request requires a commit."
            )
        if snapshot.remote is None:
            raise EnvironmentPullRequestError(
                "remote_unavailable", "A governed pull request requires a remote."
            )
        remote = _validate_ref_component(snapshot.remote, "remote")
        source_branch = snapshot.branch
        if snapshot.upstream is not None:
            prefix = f"{remote}/"
            if not snapshot.upstream.startswith(prefix):
                raise EnvironmentPullRequestError(
                    "upstream_mismatch",
                    "The selected remote does not own the upstream.",
                )
            source_branch = snapshot.upstream.removeprefix(prefix)
        return (
            remote,
            _validate_ref_component(source_branch, "source branch"),
            snapshot.head,
        )

    def _repository(
        self, snapshot: EnvironmentSnapshot, hint: HostedRepositoryHint
    ) -> tuple[str, str]:
        self._auth(snapshot, hint.host)
        payload = self._json_command(
            Path(snapshot.worktree_root),
            "repo",
            "view",
            f"{hint.host}/{hint.name_with_owner}",
            "--json",
            "nameWithOwner,url,defaultBranchRef,isFork",
        )
        if not isinstance(payload, Mapping):
            raise EnvironmentPullRequestError(
                "hosted_output_invalid", "Hosted repository output is invalid."
            )
        name = str(payload.get("nameWithOwner", ""))
        if name.casefold() != hint.name_with_owner.casefold():
            raise EnvironmentPullRequestError(
                "repository_mismatch", "Hosted repository identity changed."
            )
        if payload.get("isFork") is True:
            raise EnvironmentPullRequestError(
                "fork_unsupported", "Cross-repository pull requests require review."
            )
        if payload.get("isFork") is not False:
            raise EnvironmentPullRequestError(
                "hosted_output_invalid", "Hosted repository fork state is invalid."
            )
        url = _safe_repository_url(str(payload.get("url", "")), hint)
        default = payload.get("defaultBranchRef")
        if not isinstance(default, Mapping):
            raise EnvironmentPullRequestError(
                "base_unavailable", "The default base branch is unavailable."
            )
        return url, _validate_ref_component(str(default.get("name", "")), "base branch")

    def _auth(self, snapshot: EnvironmentSnapshot, host: str) -> None:
        result = self._command(
            Path(snapshot.worktree_root),
            "auth",
            "status",
            "--active",
            "--hostname",
            host,
            allow_failure=True,
        )
        if result.returncode != 0:
            raise EnvironmentPullRequestError(
                _classify_hosted_failure(result.stderr, default="unauthenticated"),
                "Hosted authentication is unavailable.",
            )

    def _find_existing(
        self, preview: EnvironmentPullRequestPreview
    ) -> Mapping[str, Any] | None:
        payload = self._json_command(
            Path(preview.worktree_root),
            "pr",
            "list",
            "--repo",
            f"{preview.repository_host}/{preview.repository_name}",
            "--head",
            preview.source_branch,
            "--base",
            preview.base_branch,
            "--state",
            "open",
            "--limit",
            "10",
            "--json",
            "number,url,state,headRefName,headRefOid,baseRefName",
        )
        if not isinstance(payload, list) or len(payload) > 10:
            raise EnvironmentPullRequestError(
                "hosted_output_invalid", "Pull-request lookup output is invalid."
            )
        matches = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise EnvironmentPullRequestError(
                    "hosted_output_invalid", "Pull-request lookup output is invalid."
                )
            if (
                item.get("headRefName") == preview.source_branch
                and item.get("headRefOid") == preview.source_head
                and item.get("baseRefName") == preview.base_branch
            ):
                matches.append(item)
        if len(matches) > 1:
            raise EnvironmentPullRequestError(
                "pull_request_ambiguous", "Matching pull-request state is ambiguous."
            )
        return matches[0] if matches else None

    def _remote_head(self, root: Path, remote: str, branch: str) -> str | None:
        environment = _noninteractive_environment()
        result = _run_hosted_command(
            (
                self._git,
                "-c",
                "credential.helper=",
                "ls-remote",
                "--refs",
                "--heads",
                "--exit-code",
                "--",
                remote,
                f"refs/heads/{branch}",
            ),
            root,
            None,
            HOSTED_COMMAND_TIMEOUT_SECONDS,
            environment=environment,
        )
        if result.returncode == 2 and not result.stdout.strip():
            return None
        if result.returncode != 0:
            raise EnvironmentPullRequestError(
                "remote_unavailable", "Remote Git state is unavailable."
            )
        records = [
            line.split()
            for line in result.stdout.decode("ascii", "strict").splitlines()
            if line
        ]
        if (
            len(records) != 1
            or len(records[0]) != 2
            or _HEX_SHA_RE.fullmatch(records[0][0]) is None
        ):
            raise EnvironmentPullRequestError(
                "remote_output_invalid", "Remote Git state is invalid."
            )
        return records[0][0]

    def _json_command(self, root: Path, *args: str) -> Any:
        result = self._command(root, *args)
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnvironmentPullRequestError(
                "hosted_output_invalid", "Hosted command returned invalid JSON."
            ) from exc

    def _command(
        self,
        root: Path,
        *args: str,
        input_bytes: bytes | None = None,
        allow_failure: bool = False,
    ) -> _CommandResult:
        result = self._runner(
            (self._gh, *args), root, input_bytes, HOSTED_COMMAND_TIMEOUT_SECONDS
        )
        if result.returncode != 0 and not allow_failure:
            raise EnvironmentPullRequestError(
                _classify_hosted_failure(result.stderr), "Hosted command failed."
            )
        return result

    def _result(
        self,
        preview: EnvironmentPullRequestPreview,
        payload: Mapping[str, Any],
        *,
        recovered: bool,
    ) -> EnvironmentPullRequestResult:
        parsed = _parse_pull_request_mapping(payload, preview)
        number = parsed["number"]
        url = parsed["url"]
        return EnvironmentPullRequestResult(
            preview_id=preview.id,
            number=number,
            state=parsed["state"],
            source_branch=preview.source_branch,
            base_branch=preview.base_branch,
            commit_head=preview.source_head,
            pull_request_url=url,
            commit_url=f"{preview.repository_url}/commit/{preview.source_head}",
            checks_url=f"{url}/checks",
            run_evidence_url=(
                f"{preview.repository_url}/actions?query="
                f"branch%3A{quote(preview.source_branch, safe='')}"
            ),
            completed_at=_utc_now(self._clock),
            recovered=recovered,
        )

    def _preview_path(self, preview_id: str) -> Path:
        _validate_preview_id(preview_id)
        return self._previews / f"{preview_id}.json"

    def _result_path(self, preview_id: str) -> Path:
        _validate_preview_id(preview_id)
        return self._results / f"{preview_id}.json"


@dataclass(frozen=True)
class EnvironmentPullRequestOutcome:
    """Policy-aware PR outcome returned to presentation clients."""

    preview: EnvironmentPullRequestPreview
    approval: Any | None = None
    result: EnvironmentPullRequestResult | None = None
    idempotent_replay: bool = False


class GovernedEnvironmentPullRequestService:
    """Keep policy, approval, stale checks, and hosted mutation under one owner."""

    def __init__(
        self,
        pull_request_service: EnvironmentPullRequestService,
        runtime_store: RuntimeCoordinationStore,
        policy_engine: PolicyEngine,
    ) -> None:
        self.pull_request_service = pull_request_service
        self.runtime_store = runtime_store
        self.policy_engine = policy_engine

    def apply_or_request(
        self,
        preview_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> EnvironmentPullRequestOutcome:
        """Apply a matching grant or create one exact allow-once approval."""
        preview = self.pull_request_service.get_preview(preview_id)
        completed = self.pull_request_service.completed_result(preview.id)
        if completed is not None:
            return EnvironmentPullRequestOutcome(
                preview=preview, result=completed, idempotent_replay=True
            )
        self.pull_request_service.validate_current(preview)
        context = PolicyContext(
            project_id=project_id or preview.scope_id,
            session_id=session_id,
            reason="Create the exact reviewed pull request in the exact repository.",
            preview=preview.to_dict(),
            approval_binding=preview.approval_binding,
            enforcement_owner=ENVIRONMENT_PULL_REQUEST_OWNER,
        )
        resolution = self.policy_engine.resolve(
            PermissionAction.GITHUB_PULL_REQUEST_CREATE,
            profile=INTERACTIVE_PROFILE,
            context=context,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
        )
        if resolution.decision is PolicyDecision.DENY:
            raise EnvironmentPullRequestError(
                "policy_denied", "Pull-request creation denied by policy."
            )
        if resolution.decision is PolicyDecision.ASK:
            approval = self.runtime_store.create_approval_request(resolution, context)
            return EnvironmentPullRequestOutcome(preview=preview, approval=approval)
        result = self.pull_request_service.apply(preview.id)
        return EnvironmentPullRequestOutcome(preview=preview, result=result)


def _parse_pull_request(
    payload: bytes, preview: EnvironmentPullRequestPreview
) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Pull-request result is invalid."
        ) from exc
    if not isinstance(value, Mapping):
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Pull-request result is invalid."
        )
    _parse_pull_request_mapping(value, preview)
    return value


def _parse_pull_request_mapping(
    value: Mapping[str, Any], preview: EnvironmentPullRequestPreview
) -> dict[str, Any]:
    number = value.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Pull-request number is invalid."
        )
    url = value.get("html_url", value.get("url"))
    if not isinstance(url, str):
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Pull-request URL is invalid."
        )
    expected = f"{preview.repository_url}/pull/{number}"
    if url != expected:
        raise EnvironmentPullRequestError(
            "repository_mismatch", "Pull-request repository identity changed."
        )
    state = str(value.get("state", "")).casefold()
    if state != "open":
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Pull-request state is invalid."
        )
    head_ref = value.get("headRefName")
    head_oid = value.get("headRefOid")
    base_ref = value.get("baseRefName")
    if isinstance(value.get("head"), Mapping):
        head_ref = value["head"].get("ref")
        head_oid = value["head"].get("sha")
    if isinstance(value.get("base"), Mapping):
        base_ref = value["base"].get("ref")
    if (
        head_ref != preview.source_branch
        or head_oid != preview.source_head
        or base_ref != preview.base_branch
    ):
        raise EnvironmentPullRequestError(
            "pull_request_mismatch", "Pull-request identity changed."
        )
    return {"number": number, "url": url, "state": state}


def _snapshot_matches_preview(
    snapshot: EnvironmentSnapshot, preview: EnvironmentPullRequestPreview
) -> bool:
    return (
        snapshot.repository_root == preview.repository_root
        and snapshot.worktree_root == preview.worktree_root
        and snapshot.branch is not None
        and snapshot.head == preview.source_head
        and snapshot.diff_sha256 == preview.diff_sha256
        and snapshot.remote == preview.remote
        and not snapshot.detached
        and (
            snapshot.branch == preview.source_branch
            or snapshot.upstream == f"{preview.remote}/{preview.source_branch}"
        )
    )


def _validate_preview(preview: EnvironmentPullRequestPreview) -> None:
    if preview.schema_version != ENVIRONMENT_PULL_REQUEST_SCHEMA_VERSION:
        raise ValueError("unsupported pull-request preview schema")
    _validate_preview_id(preview.id)
    for value in (preview.repository_root, preview.worktree_root):
        if not value or len(value) > 4096 or "\x00" in value:
            raise ValueError("pull-request preview path is invalid")
    hint = HostedRepositoryHint(preview.repository_host, preview.repository_name)
    if _safe_repository_url(preview.repository_url, hint) != preview.repository_url:
        raise ValueError("pull-request repository URL is invalid")
    _validate_ref_component(preview.remote, "remote")
    _validate_ref_component(preview.source_branch, "source branch")
    _validate_ref_component(preview.base_branch, "base branch")
    for value in (
        preview.source_head,
        preview.source_remote_head,
        preview.base_head,
        preview.diff_sha256,
    ):
        if _HEX_SHA_RE.fullmatch(value) is None:
            raise ValueError("pull-request preview hash is invalid")
    _validate_title(preview.title)
    _validate_body(preview.body)
    _parse_timestamp(preview.created_at)


def _validate_result(result: EnvironmentPullRequestResult) -> None:
    if result.schema_version != ENVIRONMENT_PULL_REQUEST_SCHEMA_VERSION:
        raise ValueError("unsupported pull-request result schema")
    if _PREVIEW_ID_RE.fullmatch(result.preview_id) is None:
        raise ValueError("pull-request result preview id is invalid")
    if result.number <= 0 or result.state != "open":
        raise ValueError("pull-request result identity is invalid")
    _validate_ref_component(result.source_branch, "source branch")
    _validate_ref_component(result.base_branch, "base branch")
    if _HEX_SHA_RE.fullmatch(result.commit_head) is None:
        raise ValueError("pull-request result commit is invalid")
    parsed = urlsplit(result.pull_request_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(f"/pull/{result.number}")
    ):
        raise ValueError("pull-request result URL is invalid")
    repository_url = result.pull_request_url.removesuffix(f"/pull/{result.number}")
    if result.commit_url != f"{repository_url}/commit/{result.commit_head}":
        raise ValueError("pull-request commit URL is invalid")
    if result.checks_url != f"{result.pull_request_url}/checks":
        raise ValueError("pull-request checks URL is invalid")
    if not result.run_evidence_url.startswith(
        f"{repository_url}/actions?query=branch%3A"
    ):
        raise ValueError("pull-request run evidence URL is invalid")
    _parse_timestamp(result.completed_at)


def _validate_title(value: str) -> str:
    text = str(value).strip()
    if (
        not text
        or len(text) > MAX_PULL_REQUEST_TITLE_CHARS
        or any(ord(char) < 32 for char in text)
    ):
        raise EnvironmentPullRequestError(
            "title_invalid", "Pull-request title is invalid."
        )
    return text


def _validate_body(value: str) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_PULL_REQUEST_BODY_CHARS or "\x00" in text:
        raise EnvironmentPullRequestError(
            "body_invalid", "Pull-request body is invalid."
        )
    return text


def _validate_preview_id(value: str) -> None:
    if _PREVIEW_ID_RE.fullmatch(str(value)) is None:
        raise EnvironmentPullRequestError(
            "preview_invalid", "Pull-request preview is invalid."
        )


def _validate_ref_component(value: str, field: str) -> str:
    text = str(value)
    if (
        not text
        or len(text) > 512
        or text.startswith("/")
        or text.endswith(("/", ".", ".lock"))
        or "//" in text
        or _REF_COMPONENT_RE.fullmatch(text) is None
    ):
        raise EnvironmentPullRequestError("ref_invalid", f"Git {field} is invalid.")
    return text


def _safe_repository_url(value: str, hint: HostedRepositoryHint) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Hosted repository URL is invalid."
        ) from exc
    expected_path = f"/{hint.name_with_owner}"
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != hint.host.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/").casefold() != expected_path.casefold()
    ):
        raise EnvironmentPullRequestError(
            "hosted_output_invalid", "Hosted repository URL is invalid."
        )
    return value.rstrip("/")


def _classify_hosted_failure(payload: bytes, *, default: str = "hosted_failed") -> str:
    text = payload[:8192].decode("utf-8", "replace").casefold()
    if "rate limit" in text or "secondary rate" in text:
        return "rate_limited"
    if "not logged" in text or "authentication" in text or "bad credentials" in text:
        return "unauthenticated"
    if "permission" in text or "forbidden" in text or "resource not accessible" in text:
        return "permission_denied"
    if "could not resolve" in text or "network" in text or "connection" in text:
        return "network_unavailable"
    return default


def _run_hosted_command(
    command: tuple[str, ...],
    cwd: Path,
    input_bytes: bytes | None,
    timeout_seconds: float,
    *,
    environment: Mapping[str, str] | None = None,
) -> _CommandResult:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(environment or _noninteractive_environment()),
    )
    try:
        stdout, stderr = process.communicate(input_bytes, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise EnvironmentPullRequestError(
            "hosted_timeout", "Hosted command timed out."
        ) from exc
    if len(stdout) > MAX_HOSTED_OUTPUT_BYTES or len(stderr) > MAX_HOSTED_OUTPUT_BYTES:
        raise EnvironmentPullRequestError(
            "hosted_output_limit", "Hosted command exceeded its output limit."
        )
    return _CommandResult(process.returncode, stdout, stderr)


def _noninteractive_environment() -> dict[str, str]:
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
    return environment


def _resolve_executable(value: str | None) -> str | None:
    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    return str(path)


def _mapping_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo is None:
        raise ValueError("timestamp is invalid")
    return parsed


def _utc_now(clock: Callable[[], datetime]) -> str:
    return (
        clock()
        .astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
