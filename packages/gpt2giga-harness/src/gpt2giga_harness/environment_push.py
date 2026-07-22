"""Durable, immutable-state-bound push actions for canonical Git environments."""

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


ENVIRONMENT_PUSH_SCHEMA_VERSION = 1
ENVIRONMENT_PUSH_OWNER = "environment.push"
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
GIT_PUSH_TIMEOUT_SECONDS = 30.0
_HEX_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_PREVIEW_ID_RE = re.compile(r"push_[0-9a-f]{64}\Z")
_REF_COMPONENT_RE = re.compile(r"(?!-)(?!.*\.\.)(?!.*@\{)[^\x00-\x20~^:?*\\]+\Z")


class EnvironmentPushError(RuntimeError):
    """Content-free failure for one governed remote push action."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EnvironmentPushPreview:
    """Immutable private preview of one exact non-force Git push intent."""

    id: str
    repository_root: str
    worktree_root: str
    repository_host: str
    repository_name: str
    branch: str
    head: str
    diff_sha256: str
    remote: str
    upstream: str | None
    target_branch: str
    remote_ref: str
    remote_head: str | None
    ahead: int
    behind: int
    set_upstream: bool
    created_at: str
    schema_version: int = ENVIRONMENT_PUSH_SCHEMA_VERSION

    @property
    def approval_binding(self) -> str:
        """Return the exact opaque binding consumed by the policy owner."""
        return f"environment-push-v1:{self.id}"

    @property
    def scope_id(self) -> str:
        """Return a content-free project scope for allow-once approvals."""
        digest = hashlib.sha256(self.worktree_root.encode("utf-8")).hexdigest()
        return f"environment_{digest[:32]}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the explicit remote-write approval preview."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "repository_root": self.repository_root,
            "worktree_root": self.worktree_root,
            "repository": {
                "host": self.repository_host,
                "name_with_owner": self.repository_name,
            },
            "branch": self.branch,
            "head": self.head,
            "diff_sha256": self.diff_sha256,
            "remote": self.remote,
            "upstream": self.upstream,
            "target_branch": self.target_branch,
            "remote_ref": self.remote_ref,
            "remote_head": self.remote_head,
            "ahead": self.ahead,
            "behind": self.behind,
            "permissions": {
                "network_connect": True,
                "remote_write": True,
                "create_remote_branch": self.remote_head is None,
                "set_upstream": self.set_upstream,
                "force_update": False,
                "delete_remote_branch": False,
                "follow_tags": False,
                "execute_hooks": False,
            },
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentPushPreview:
        """Parse one strict private preview record."""
        repository = payload.get("repository")
        if not isinstance(repository, Mapping):
            raise ValueError("push preview repository is invalid")
        preview = cls(
            schema_version=int(payload.get("schema_version", 0)),
            id=str(payload.get("id", "")),
            repository_root=str(payload.get("repository_root", "")),
            worktree_root=str(payload.get("worktree_root", "")),
            repository_host=str(repository.get("host", "")),
            repository_name=str(repository.get("name_with_owner", "")),
            branch=str(payload.get("branch", "")),
            head=str(payload.get("head", "")),
            diff_sha256=str(payload.get("diff_sha256", "")),
            remote=str(payload.get("remote", "")),
            upstream=_optional_text(payload.get("upstream")),
            target_branch=str(payload.get("target_branch", "")),
            remote_ref=str(payload.get("remote_ref", "")),
            remote_head=_optional_text(payload.get("remote_head")),
            ahead=int(payload.get("ahead", -1)),
            behind=int(payload.get("behind", -1)),
            set_upstream=bool(payload.get("permissions", {}).get("set_upstream"))
            if isinstance(payload.get("permissions"), Mapping)
            else False,
            created_at=str(payload.get("created_at", "")),
        )
        _validate_preview(preview)
        return preview


@dataclass(frozen=True)
class EnvironmentPushResult:
    """Durable completion evidence for one exact remote commit update."""

    preview_id: str
    remote: str
    branch: str
    target_branch: str
    remote_ref: str
    commit_head: str
    remote_commit_url: str
    run_evidence_url: str
    upstream_configured: bool
    completed_at: str
    recovered: bool = False
    schema_version: int = ENVIRONMENT_PUSH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize bounded remote completion evidence."""
        return {
            "schema_version": self.schema_version,
            "preview_id": self.preview_id,
            "remote": self.remote,
            "branch": self.branch,
            "target_branch": self.target_branch,
            "remote_ref": self.remote_ref,
            "commit_head": self.commit_head,
            "remote_commit_url": self.remote_commit_url,
            "run_evidence_url": self.run_evidence_url,
            "upstream_configured": self.upstream_configured,
            "completed_at": self.completed_at,
            "recovered": self.recovered,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentPushResult:
        """Parse one strict durable completion record."""
        result = cls(
            schema_version=int(payload.get("schema_version", 0)),
            preview_id=str(payload.get("preview_id", "")),
            remote=str(payload.get("remote", "")),
            branch=str(payload.get("branch", "")),
            target_branch=str(payload.get("target_branch", "")),
            remote_ref=str(payload.get("remote_ref", "")),
            commit_head=str(payload.get("commit_head", "")),
            remote_commit_url=str(payload.get("remote_commit_url", "")),
            run_evidence_url=str(payload.get("run_evidence_url", "")),
            upstream_configured=bool(payload.get("upstream_configured", False)),
            completed_at=str(payload.get("completed_at", "")),
            recovered=bool(payload.get("recovered", False)),
        )
        _validate_result(result)
        return result


class EnvironmentPushService:
    """Preview and apply exact non-force pushes through one Git authority."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        git_executable: str | None = None,
        clock: Callable[[], datetime] | None = None,
        repository_resolver: Callable[
            [EnvironmentSnapshot], HostedRepositoryHint | None
        ]
        | None = None,
    ) -> None:
        executable = git_executable or shutil.which("git")
        if executable is None:
            raise EnvironmentPushError("git_unavailable", "Git is unavailable.")
        resolved = Path(executable).expanduser().resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise EnvironmentPushError("git_unavailable", "Git is unavailable.")
        self._git = str(resolved)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._provider = GitEnvironmentProvider(
            git_executable=self._git,
            clock=self._clock,
        )
        self._repository_resolver = (
            repository_resolver or self._provider.hosted_repository
        )
        self._root = Path(data_dir).expanduser().resolve() / "environment_pushes"
        self._previews = self._root / "previews"
        self._results = self._root / "results"
        self._lock = threading.RLock()

    def preview(self, workspace: str | Path) -> EnvironmentPushPreview:
        """Persist or reuse one remote-state-bound push preview."""
        snapshot = self._capture(workspace)
        branch, head, remote, target_branch = self._push_target(snapshot)
        hint = self._repository_resolver(snapshot)
        if hint is None:
            raise EnvironmentPushError(
                "hosted_remote_required",
                "A governed push requires one supported hosted remote.",
            )
        self._reject_push_url_override(Path(snapshot.worktree_root), remote)
        remote_ref = f"refs/heads/{target_branch}"
        remote_head = self._remote_head(
            Path(snapshot.worktree_root), remote, remote_ref
        )
        semantic = {
            "schema_version": ENVIRONMENT_PUSH_SCHEMA_VERSION,
            "repository_root": snapshot.repository_root,
            "worktree_root": snapshot.worktree_root,
            "repository_host": hint.host,
            "repository_name": hint.name_with_owner,
            "branch": branch,
            "head": head,
            "diff_sha256": snapshot.diff_sha256,
            "remote": remote,
            "upstream": snapshot.upstream,
            "target_branch": target_branch,
            "remote_ref": remote_ref,
            "remote_head": remote_head,
            "ahead": snapshot.ahead,
            "behind": snapshot.behind,
            "set_upstream": snapshot.upstream is None,
        }
        preview_id = f"push_{_mapping_hash(semantic)}"
        path = self._preview_path(preview_id)
        with self._lock:
            if path.is_file():
                return self.get_preview(preview_id)
            preview = EnvironmentPushPreview(
                id=preview_id,
                repository_root=snapshot.repository_root,
                worktree_root=snapshot.worktree_root,
                repository_host=hint.host,
                repository_name=hint.name_with_owner,
                branch=branch,
                head=head,
                diff_sha256=snapshot.diff_sha256,
                remote=remote,
                upstream=snapshot.upstream,
                target_branch=target_branch,
                remote_ref=remote_ref,
                remote_head=remote_head,
                ahead=snapshot.ahead,
                behind=snapshot.behind,
                set_upstream=snapshot.upstream is None,
                created_at=_utc_now(self._clock),
            )
            _write_private_json(path, preview.to_dict())
            return preview

    def get_preview(self, preview_id: str) -> EnvironmentPushPreview:
        """Load one exact private push preview."""
        path = self._preview_path(preview_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("push preview record is invalid")
            return EnvironmentPushPreview.from_dict(payload)
        except FileNotFoundError as exc:
            raise EnvironmentPushError(
                "preview_not_found", "Push preview was not found."
            ) from exc
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EnvironmentPushError(
                "preview_invalid", "Push preview is unavailable."
            ) from exc

    def completed_result(self, preview_id: str) -> EnvironmentPushResult | None:
        """Return existing completion evidence without contacting the remote."""
        path = self._result_path(preview_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("push result record is invalid")
            return EnvironmentPushResult.from_dict(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EnvironmentPushError(
                "result_invalid", "Push completion evidence is unavailable."
            ) from exc

    def validate_current(self, preview: EnvironmentPushPreview) -> None:
        """Fail before approval consumption when local or remote state is stale."""
        if self.completed_result(preview.id) is not None:
            return
        if self._recover_if_pushed(preview) is not None:
            return
        current = self._capture(preview.worktree_root)
        if not _snapshot_matches_preview(current, preview):
            raise EnvironmentPushError(
                "stale_preview", "Git state changed after the push preview."
            )
        self._validate_remote_identity(current, preview)
        remote_head = self._remote_head(
            Path(preview.worktree_root), preview.remote, preview.remote_ref
        )
        if remote_head != preview.remote_head:
            raise EnvironmentPushError(
                "remote_changed", "Remote Git state changed after the push preview."
            )

    def apply(self, preview_id: str) -> EnvironmentPushResult:
        """Push one exact commit once or recover its durable prior result."""
        with self._lock:
            preview = self.get_preview(preview_id)
            completed = self.completed_result(preview.id)
            if completed is not None:
                return completed
            recovered = self._recover_if_pushed(preview)
            if recovered is not None:
                return recovered
            self.validate_current(preview)
            completed = self.completed_result(preview.id)
            if completed is not None:
                return completed
            root = Path(preview.worktree_root)
            args = [
                "push",
                "--porcelain",
                "--no-verify",
                "--no-follow-tags",
            ]
            if preview.set_upstream:
                args.append("--set-upstream")
            args.extend(("--", preview.remote, f"HEAD:{preview.remote_ref}"))
            result = self._run(root, *args)
            if result.returncode != 0:
                recovered = self._recover_if_pushed(preview)
                if recovered is not None:
                    return recovered
                raise EnvironmentPushError(
                    _classify_push_failure(result.stderr), "Git push failed."
                )
            remote_head = self._remote_head(root, preview.remote, preview.remote_ref)
            if remote_head != preview.head:
                raise EnvironmentPushError(
                    "remote_unconfirmed", "Remote Git push could not be confirmed."
                )
            result_record = self._result(preview, recovered=False)
            _write_private_json(self._result_path(preview.id), result_record.to_dict())
            return result_record

    def _recover_if_pushed(
        self, preview: EnvironmentPushPreview
    ) -> EnvironmentPushResult | None:
        remote_head = self._remote_head(
            Path(preview.worktree_root), preview.remote, preview.remote_ref
        )
        if remote_head != preview.head:
            return None
        result = self._result(preview, recovered=True)
        _write_private_json(self._result_path(preview.id), result.to_dict())
        return result

    def _result(
        self, preview: EnvironmentPushPreview, *, recovered: bool
    ) -> EnvironmentPushResult:
        base = (
            f"https://{preview.repository_host}/{preview.repository_name}"
            f"/commit/{preview.head}"
        )
        current = self._capture(preview.worktree_root)
        return EnvironmentPushResult(
            preview_id=preview.id,
            remote=preview.remote,
            branch=preview.branch,
            target_branch=preview.target_branch,
            remote_ref=preview.remote_ref,
            commit_head=preview.head,
            remote_commit_url=base,
            run_evidence_url=f"{base}/checks",
            upstream_configured=current.upstream
            == f"{preview.remote}/{preview.target_branch}",
            completed_at=_utc_now(self._clock),
            recovered=recovered,
        )

    def _push_target(self, snapshot: EnvironmentSnapshot) -> tuple[str, str, str, str]:
        if snapshot.detached or snapshot.branch is None:
            raise EnvironmentPushError(
                "detached_head", "A governed push requires an attached branch."
            )
        if snapshot.head is None:
            raise EnvironmentPushError("unborn_head", "A push requires a commit.")
        if snapshot.remote is None:
            raise EnvironmentPushError(
                "remote_unavailable", "A push requires one selected remote."
            )
        _validate_ref_component(snapshot.branch, "branch")
        _validate_ref_component(snapshot.remote, "remote")
        target_branch = snapshot.branch
        if snapshot.upstream is not None:
            prefix = f"{snapshot.remote}/"
            if not snapshot.upstream.startswith(prefix):
                raise EnvironmentPushError(
                    "upstream_mismatch",
                    "The selected remote does not own the branch upstream.",
                )
            target_branch = snapshot.upstream.removeprefix(prefix)
        _validate_ref_component(target_branch, "target branch")
        return snapshot.branch, snapshot.head, snapshot.remote, target_branch

    def _reject_push_url_override(self, root: Path, remote: str) -> None:
        result = self._run(root, "config", "--get-all", f"remote.{remote}.pushurl")
        if result.returncode == 0 and result.stdout.strip():
            raise EnvironmentPushError(
                "push_url_override",
                "A separate Git push URL is not supported by governed push.",
            )
        if result.returncode not in {0, 1}:
            raise EnvironmentPushError(
                "git_failed", "Git remote configuration is unavailable."
            )

    def _validate_remote_identity(
        self,
        snapshot: EnvironmentSnapshot,
        preview: EnvironmentPushPreview,
    ) -> None:
        root = Path(snapshot.worktree_root)
        self._reject_push_url_override(root, preview.remote)
        hint = self._repository_resolver(snapshot)
        if (
            hint is None
            or hint.host != preview.repository_host
            or hint.name_with_owner != preview.repository_name
        ):
            raise EnvironmentPushError(
                "remote_changed",
                "Remote Git identity changed after the push preview.",
            )

    def _remote_head(self, root: Path, remote: str, remote_ref: str) -> str | None:
        result = self._run(
            root,
            "ls-remote",
            "--refs",
            "--heads",
            "--exit-code",
            "--",
            remote,
            remote_ref,
        )
        if result.returncode == 2 and not result.stdout.strip():
            return None
        if result.returncode != 0:
            raise EnvironmentPushError(
                "remote_unavailable", "Remote Git state is unavailable."
            )
        records = [record for record in result.stdout.splitlines() if record]
        if len(records) != 1:
            raise EnvironmentPushError(
                "remote_output_invalid", "Remote Git state is invalid."
            )
        fields = records[0].decode("ascii", "replace").split("\t")
        if (
            len(fields) != 2
            or _HEX_SHA_RE.fullmatch(fields[0]) is None
            or fields[1] != remote_ref
        ):
            raise EnvironmentPushError(
                "remote_output_invalid", "Remote Git state is invalid."
            )
        return fields[0]

    def _run(self, root: Path, *args: str) -> _CommandResult:
        environment = dict(os.environ)
        environment.update(
            {
                "GCM_INTERACTIVE": "Never",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            }
        )
        return _run_bounded(
            (self._git, "--no-optional-locks", "-C", str(root), *args),
            environment=environment,
        )

    def _capture(self, workspace: str | Path) -> EnvironmentSnapshot:
        try:
            return self._provider.snapshot(workspace)
        except EnvironmentCaptureError as exc:
            raise EnvironmentPushError(exc.code, str(exc)) from exc

    def _preview_path(self, preview_id: str) -> Path:
        _validate_preview_id(preview_id)
        return self._previews / f"{preview_id}.json"

    def _result_path(self, preview_id: str) -> Path:
        _validate_preview_id(preview_id)
        return self._results / f"{preview_id}.json"


@dataclass(frozen=True)
class EnvironmentPushOutcome:
    """One governed push outcome shared by Web and TUI transports."""

    preview: EnvironmentPushPreview
    result: EnvironmentPushResult | None = None
    approval: Any | None = None
    idempotent_replay: bool = False


class GovernedEnvironmentPushService:
    """Keep policy, approval, stale checks, and remote mutation under one owner."""

    def __init__(
        self,
        push_service: EnvironmentPushService,
        runtime_store: RuntimeCoordinationStore,
        policy_engine: PolicyEngine,
    ) -> None:
        self.push_service = push_service
        self.runtime_store = runtime_store
        self.policy_engine = policy_engine

    def apply_or_request(
        self,
        preview_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> EnvironmentPushOutcome:
        """Apply a matching grant or create one exact allow-once approval."""
        preview = self.push_service.get_preview(preview_id)
        completed = self.push_service.completed_result(preview.id)
        if completed is not None:
            return EnvironmentPushOutcome(
                preview=preview,
                result=completed,
                idempotent_replay=True,
            )
        self.push_service.validate_current(preview)
        recovered = self.push_service.completed_result(preview.id)
        if recovered is not None:
            return EnvironmentPushOutcome(
                preview=preview,
                result=recovered,
                idempotent_replay=True,
            )
        context = PolicyContext(
            project_id=project_id or preview.scope_id,
            session_id=session_id,
            reason="Push the exact reviewed commit to the exact remote branch.",
            preview=preview.to_dict(),
            approval_binding=preview.approval_binding,
            enforcement_owner=ENVIRONMENT_PUSH_OWNER,
        )
        resolution = self.policy_engine.resolve(
            PermissionAction.GIT_PUSH,
            profile=INTERACTIVE_PROFILE,
            context=context,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
        )
        if resolution.decision is PolicyDecision.DENY:
            raise EnvironmentPushError("policy_denied", "Push denied by policy.")
        if resolution.decision is PolicyDecision.ASK:
            approval = self.runtime_store.create_approval_request(resolution, context)
            return EnvironmentPushOutcome(preview=preview, approval=approval)
        result = self.push_service.apply(preview.id)
        return EnvironmentPushOutcome(preview=preview, result=result)


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run_bounded(
    command: tuple[str, ...], *, environment: Mapping[str, str]
) -> _CommandResult:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(environment),
    )
    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()

    def drain(stream, target: bytearray) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = MAX_GIT_OUTPUT_BYTES + 1 - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(target) > MAX_GIT_OUTPUT_BYTES or len(chunk) > remaining:
                overflow.set()

    threads = (
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    )
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=GIT_PUSH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise EnvironmentPushError("git_timeout", "Git push action timed out.") from exc
    finally:
        for thread in threads:
            thread.join(timeout=1)
    if overflow.is_set():
        raise EnvironmentPushError(
            "output_limit", "Git push action exceeded its output limit."
        )
    return _CommandResult(returncode, bytes(stdout), bytes(stderr))


def _snapshot_matches_preview(
    snapshot: EnvironmentSnapshot, preview: EnvironmentPushPreview
) -> bool:
    return (
        snapshot.repository_root == preview.repository_root
        and snapshot.worktree_root == preview.worktree_root
        and snapshot.branch == preview.branch
        and snapshot.head == preview.head
        and snapshot.diff_sha256 == preview.diff_sha256
        and snapshot.remote == preview.remote
        and snapshot.upstream == preview.upstream
        and snapshot.ahead == preview.ahead
        and snapshot.behind == preview.behind
        and not snapshot.detached
    )


def _validate_preview(preview: EnvironmentPushPreview) -> None:
    if preview.schema_version != ENVIRONMENT_PUSH_SCHEMA_VERSION:
        raise ValueError("unsupported push preview schema")
    _validate_preview_id(preview.id)
    for value in (preview.repository_root, preview.worktree_root):
        if not value or len(value) > 4096 or "\x00" in value:
            raise ValueError("push preview path is invalid")
    HostedRepositoryHint(preview.repository_host, preview.repository_name)
    _validate_ref_component(preview.branch, "branch")
    _validate_ref_component(preview.remote, "remote")
    _validate_ref_component(preview.target_branch, "target branch")
    if preview.remote_ref != f"refs/heads/{preview.target_branch}":
        raise ValueError("push preview remote ref is invalid")
    if _HEX_SHA_RE.fullmatch(preview.head) is None:
        raise ValueError("push preview head is invalid")
    if _HEX_SHA_RE.fullmatch(preview.diff_sha256) is None:
        raise ValueError("push preview diff hash is invalid")
    if (
        preview.remote_head is not None
        and _HEX_SHA_RE.fullmatch(preview.remote_head) is None
    ):
        raise ValueError("push preview remote head is invalid")
    if preview.ahead < 0 or preview.behind < 0:
        raise ValueError("push preview divergence is invalid")
    if preview.set_upstream != (preview.upstream is None):
        raise ValueError("push preview upstream permission is invalid")
    _parse_timestamp(preview.created_at)


def _validate_result(result: EnvironmentPushResult) -> None:
    if result.schema_version != ENVIRONMENT_PUSH_SCHEMA_VERSION:
        raise ValueError("unsupported push result schema")
    if _PREVIEW_ID_RE.fullmatch(result.preview_id) is None:
        raise ValueError("push result preview id is invalid")
    _validate_ref_component(result.remote, "remote")
    _validate_ref_component(result.branch, "branch")
    _validate_ref_component(result.target_branch, "target branch")
    if result.remote_ref != f"refs/heads/{result.target_branch}":
        raise ValueError("push result remote ref is invalid")
    if _HEX_SHA_RE.fullmatch(result.commit_head) is None:
        raise ValueError("push result commit is invalid")
    expected_suffix = f"/commit/{result.commit_head}"
    if (
        not result.remote_commit_url.startswith("https://")
        or not result.remote_commit_url.endswith(expected_suffix)
        or result.run_evidence_url != f"{result.remote_commit_url}/checks"
    ):
        raise ValueError("push result evidence links are invalid")
    _parse_timestamp(result.completed_at)


def _validate_preview_id(value: str) -> None:
    if _PREVIEW_ID_RE.fullmatch(str(value)) is None:
        raise EnvironmentPushError("preview_invalid", "Push preview is invalid.")


def _validate_ref_component(value: str, field: str) -> None:
    text = str(value)
    if (
        not text
        or len(text) > 512
        or text.startswith("/")
        or text.endswith(("/", ".", ".lock"))
        or "//" in text
        or _REF_COMPONENT_RE.fullmatch(text) is None
    ):
        raise EnvironmentPushError("ref_invalid", f"Git {field} is invalid.")


def _classify_push_failure(payload: bytes) -> str:
    """Classify bounded Git diagnostics without retaining their content."""
    text = payload[:8192].decode("utf-8", "replace").casefold()
    if "protected branch" in text or "gh006" in text:
        return "protected_branch"
    if any(
        marker in text
        for marker in (
            "permission",
            "denied",
            "forbidden",
            "not authorized",
            "authentication failed",
        )
    ):
        return "permission_denied"
    if any(
        marker in text
        for marker in ("could not resolve", "network", "connection", "timed out")
    ):
        return "network_unavailable"
    return "push_failed"


def _mapping_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


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
