"""Durable, immutable-state-bound actions for canonical Git environments."""

from __future__ import annotations

from contextlib import suppress
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


ENVIRONMENT_COMMIT_SCHEMA_VERSION = 1
ENVIRONMENT_COMMIT_OWNER = "environment.commit"
MAX_COMMIT_MESSAGE_CHARS = 4096
MAX_AUTHOR_CHARS = 200
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
GIT_MUTATION_TIMEOUT_SECONDS = 10.0
_HEX_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_EMAIL_RE = re.compile(r"[^\s<>@]+@[^\s<>@]+\Z")
_PREVIEW_ID_RE = re.compile(r"commit_[0-9a-f]{64}\Z")


class EnvironmentCommitError(RuntimeError):
    """Content-free failure for one governed local commit action."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EnvironmentCommitPreview:
    """Immutable private preview of one exact local Git commit intent."""

    id: str
    repository_root: str
    worktree_root: str
    branch: str | None
    head: str | None
    diff_sha256: str
    remote: str | None
    staged_count: int
    message: str
    author_name: str
    author_email: str
    commit_date: str
    created_at: str
    schema_version: int = ENVIRONMENT_COMMIT_SCHEMA_VERSION

    @property
    def approval_binding(self) -> str:
        """Return the exact opaque binding consumed by the policy owner."""
        return f"environment-commit-v1:{self.id}"

    @property
    def scope_id(self) -> str:
        """Return a content-free project scope for allow-once approvals."""
        digest = hashlib.sha256(self.worktree_root.encode("utf-8")).hexdigest()
        return f"environment_{digest[:32]}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the explicit approval preview."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "repository_root": self.repository_root,
            "worktree_root": self.worktree_root,
            "branch": self.branch,
            "head": self.head,
            "diff_sha256": self.diff_sha256,
            "remote": self.remote,
            "target_branch": self.branch,
            "staged_count": self.staged_count,
            "message": self.message,
            "author": {"name": self.author_name, "email": self.author_email},
            "commit_date": self.commit_date,
            "created_at": self.created_at,
            "hooks_executed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentCommitPreview:
        """Parse one strict private preview record."""
        author = payload.get("author")
        if not isinstance(author, Mapping):
            raise ValueError("commit preview author is invalid")
        preview = cls(
            schema_version=int(payload.get("schema_version", 0)),
            id=str(payload.get("id", "")),
            repository_root=str(payload.get("repository_root", "")),
            worktree_root=str(payload.get("worktree_root", "")),
            branch=_optional_text(payload.get("branch")),
            head=_optional_text(payload.get("head")),
            diff_sha256=str(payload.get("diff_sha256", "")),
            remote=_optional_text(payload.get("remote")),
            staged_count=int(payload.get("staged_count", -1)),
            message=str(payload.get("message", "")),
            author_name=str(author.get("name", "")),
            author_email=str(author.get("email", "")),
            commit_date=str(payload.get("commit_date", "")),
            created_at=str(payload.get("created_at", "")),
        )
        _validate_preview(preview)
        return preview


@dataclass(frozen=True)
class EnvironmentCommitResult:
    """Durable content-free completion evidence for one commit preview."""

    preview_id: str
    branch: str | None
    parent_head: str | None
    commit_head: str
    completed_at: str
    recovered: bool = False
    schema_version: int = ENVIRONMENT_COMMIT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize bounded completion evidence."""
        return {
            "schema_version": self.schema_version,
            "preview_id": self.preview_id,
            "branch": self.branch,
            "parent_head": self.parent_head,
            "commit_head": self.commit_head,
            "completed_at": self.completed_at,
            "recovered": self.recovered,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentCommitResult:
        """Parse one strict durable completion record."""
        result = cls(
            schema_version=int(payload.get("schema_version", 0)),
            preview_id=str(payload.get("preview_id", "")),
            branch=_optional_text(payload.get("branch")),
            parent_head=_optional_text(payload.get("parent_head")),
            commit_head=str(payload.get("commit_head", "")),
            completed_at=str(payload.get("completed_at", "")),
            recovered=bool(payload.get("recovered", False)),
        )
        if result.schema_version != ENVIRONMENT_COMMIT_SCHEMA_VERSION:
            raise ValueError("unsupported commit result schema")
        if _PREVIEW_ID_RE.fullmatch(result.preview_id) is None:
            raise ValueError("commit result preview id is invalid")
        if _HEX_SHA_RE.fullmatch(result.commit_head) is None:
            raise ValueError("commit result head is invalid")
        if (
            result.parent_head is not None
            and _HEX_SHA_RE.fullmatch(result.parent_head) is None
        ):
            raise ValueError("commit result parent is invalid")
        _parse_timestamp(result.completed_at)
        return result


class EnvironmentCommitService:
    """Preview and apply deterministic local commits through one Git authority."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        git_executable: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        executable = git_executable or shutil.which("git")
        if executable is None:
            raise EnvironmentCommitError("git_unavailable", "Git is unavailable.")
        resolved = Path(executable).expanduser().resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise EnvironmentCommitError("git_unavailable", "Git is unavailable.")
        self._git = str(resolved)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._provider = GitEnvironmentProvider(
            git_executable=self._git,
            clock=self._clock,
        )
        self._root = Path(data_dir).expanduser().resolve() / "environment_commits"
        self._previews = self._root / "previews"
        self._results = self._root / "results"
        self._lock = threading.RLock()

    def preview(
        self,
        workspace: str | Path,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> EnvironmentCommitPreview:
        """Persist or reuse the immutable preview for one exact staged state."""
        message = _validate_message(message)
        author_name = _validate_author(author_name, "author name")
        author_email = _validate_email(author_email)
        snapshot = self._capture(workspace)
        if snapshot.staged_count < 1:
            raise EnvironmentCommitError(
                "no_staged_changes", "A commit requires staged changes."
            )
        if snapshot.detached or snapshot.branch is None:
            raise EnvironmentCommitError(
                "detached_head", "A governed commit requires an attached branch."
            )
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        created_at = now.isoformat().replace("+00:00", "Z")
        semantic = {
            "schema_version": ENVIRONMENT_COMMIT_SCHEMA_VERSION,
            "repository_root": snapshot.repository_root,
            "worktree_root": snapshot.worktree_root,
            "branch": snapshot.branch,
            "head": snapshot.head,
            "diff_sha256": snapshot.diff_sha256,
            "remote": snapshot.remote,
            "staged_count": snapshot.staged_count,
            "message": message,
            "author_name": author_name,
            "author_email": author_email,
        }
        preview_id = f"commit_{_mapping_hash(semantic)}"
        path = self._preview_path(preview_id)
        with self._lock:
            if path.is_file():
                return self.get_preview(preview_id)
            preview = EnvironmentCommitPreview(
                id=preview_id,
                repository_root=snapshot.repository_root,
                worktree_root=snapshot.worktree_root,
                branch=snapshot.branch,
                head=snapshot.head,
                diff_sha256=snapshot.diff_sha256,
                remote=snapshot.remote,
                staged_count=snapshot.staged_count,
                message=message,
                author_name=author_name,
                author_email=author_email,
                commit_date=f"{int(now.timestamp())} +0000",
                created_at=created_at,
            )
            _write_private_json(path, preview.to_dict())
            return preview

    def get_preview(self, preview_id: str) -> EnvironmentCommitPreview:
        """Load one exact private preview."""
        path = self._preview_path(preview_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise EnvironmentCommitError(
                "preview_not_found", "Commit preview was not found."
            ) from exc
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise EnvironmentCommitError(
                "preview_invalid", "Commit preview is unavailable."
            ) from exc
        if not isinstance(payload, Mapping):
            raise EnvironmentCommitError(
                "preview_invalid", "Commit preview is unavailable."
            )
        try:
            return EnvironmentCommitPreview.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise EnvironmentCommitError(
                "preview_invalid", "Commit preview is unavailable."
            ) from exc

    def completed_result(self, preview_id: str) -> EnvironmentCommitResult | None:
        """Return existing completion evidence without mutating Git."""
        path = self._result_path(preview_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("result record is invalid")
            return EnvironmentCommitResult.from_dict(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EnvironmentCommitError(
                "result_invalid", "Commit completion evidence is unavailable."
            ) from exc

    def validate_current(self, preview: EnvironmentCommitPreview) -> None:
        """Fail before approval consumption when the immutable preview is stale."""
        if self.completed_result(preview.id) is not None:
            return
        recovered = self._recover_if_committed(preview)
        if recovered is not None:
            return
        current = self._capture(preview.worktree_root)
        if not _snapshot_matches_preview(current, preview):
            raise EnvironmentCommitError(
                "stale_preview", "Git state changed after the commit preview."
            )

    def apply(self, preview_id: str) -> EnvironmentCommitResult:
        """Create one deterministic commit or return its durable prior result."""
        with self._lock:
            preview = self.get_preview(preview_id)
            completed = self.completed_result(preview.id)
            if completed is not None:
                return completed
            recovered = self._recover_if_committed(preview)
            if recovered is not None:
                return recovered
            current = self._capture(preview.worktree_root)
            if not _snapshot_matches_preview(current, preview):
                raise EnvironmentCommitError(
                    "stale_preview", "Git state changed after the commit preview."
                )
            root = Path(preview.worktree_root)
            tree = self._required_sha(root, "write-tree")
            confirmed = self._capture(preview.worktree_root)
            if not _snapshot_matches_preview(confirmed, preview):
                raise EnvironmentCommitError(
                    "stale_preview", "Git state changed while preparing the commit."
                )
            commit = self._create_commit(preview, tree, write=True)
            old = preview.head or ("0" * 40)
            update = self._run(
                root,
                "update-ref",
                "-m",
                "giga governed environment commit",
                "HEAD",
                commit,
                old,
            )
            if update.returncode != 0:
                recovered = self._recover_if_committed(preview)
                if recovered is not None:
                    return recovered
                raise EnvironmentCommitError(
                    "commit_conflict", "Git state changed while committing."
                )
            result = EnvironmentCommitResult(
                preview_id=preview.id,
                branch=preview.branch,
                parent_head=preview.head,
                commit_head=commit,
                completed_at=_utc_now(self._clock),
            )
            _write_private_json(self._result_path(preview.id), result.to_dict())
            return result

    def _recover_if_committed(
        self, preview: EnvironmentCommitPreview
    ) -> EnvironmentCommitResult | None:
        root = Path(preview.worktree_root)
        head = self._optional_sha(root, "rev-parse", "--verify", "HEAD")
        if head is None or head == preview.head:
            return None
        parent = self._optional_sha(root, "rev-parse", "--verify", f"{head}^")
        if parent != preview.head:
            return None
        tree = self._optional_sha(root, "rev-parse", "--verify", f"{head}^{{tree}}")
        if tree is None:
            return None
        expected = self._create_commit(preview, tree, write=False)
        if expected != head:
            return None
        result = EnvironmentCommitResult(
            preview_id=preview.id,
            branch=preview.branch,
            parent_head=preview.head,
            commit_head=head,
            completed_at=_utc_now(self._clock),
            recovered=True,
        )
        _write_private_json(self._result_path(preview.id), result.to_dict())
        return result

    def _create_commit(
        self,
        preview: EnvironmentCommitPreview,
        tree: str,
        *,
        write: bool,
    ) -> str:
        headers = [f"tree {tree}"]
        if preview.head is not None:
            headers.append(f"parent {preview.head}")
        identity = (
            f"{preview.author_name} <{preview.author_email}> {preview.commit_date}"
        )
        headers.extend((f"author {identity}", f"committer {identity}"))
        content = "\n".join(headers) + "\n\n" + preview.message.rstrip("\n") + "\n"
        args = ["hash-object", "-t", "commit"]
        if write:
            args.append("-w")
        args.append("--stdin")
        result = self._run(
            Path(preview.worktree_root),
            *args,
            input_bytes=content.encode("utf-8"),
        )
        if result.returncode != 0:
            raise EnvironmentCommitError("git_failed", "Git commit creation failed.")
        value = result.stdout.decode("ascii", "replace").strip()
        if _HEX_SHA_RE.fullmatch(value) is None:
            raise EnvironmentCommitError(
                "git_output_invalid", "Git commit output is invalid."
            )
        return value

    def _required_sha(self, root: Path, *args: str) -> str:
        value = self._optional_sha(root, *args)
        if value is None:
            raise EnvironmentCommitError("git_failed", "Git commit preparation failed.")
        return value

    def _optional_sha(self, root: Path, *args: str) -> str | None:
        result = self._run(root, *args)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("ascii", "replace").strip()
        return value if _HEX_SHA_RE.fullmatch(value) else None

    def _run(
        self,
        root: Path,
        *args: str,
        input_bytes: bytes | None = None,
    ) -> _CommandResult:
        environment = dict(os.environ)
        environment.update(
            {
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            }
        )
        return _run_bounded(
            (self._git, "--no-optional-locks", "-C", str(root), *args),
            environment=environment,
            input_bytes=input_bytes,
        )

    def _capture(self, workspace: str | Path) -> EnvironmentSnapshot:
        try:
            return self._provider.snapshot(workspace)
        except EnvironmentCaptureError as exc:
            raise EnvironmentCommitError(exc.code, str(exc)) from exc

    def _preview_path(self, preview_id: str) -> Path:
        _validate_preview_id(preview_id)
        return self._previews / f"{preview_id}.json"

    def _result_path(self, preview_id: str) -> Path:
        _validate_preview_id(preview_id)
        return self._results / f"{preview_id}.json"


@dataclass(frozen=True)
class EnvironmentCommitOutcome:
    """One governed request outcome shared by Web and TUI transports."""

    preview: EnvironmentCommitPreview
    result: EnvironmentCommitResult | None = None
    approval: Any | None = None
    idempotent_replay: bool = False


class GovernedEnvironmentCommitService:
    """Keep policy, approval, stale checks, and Git mutation under one owner."""

    def __init__(
        self,
        commit_service: EnvironmentCommitService,
        runtime_store: RuntimeCoordinationStore,
        policy_engine: PolicyEngine,
    ) -> None:
        self.commit_service = commit_service
        self.runtime_store = runtime_store
        self.policy_engine = policy_engine

    def apply_or_request(
        self,
        preview_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> EnvironmentCommitOutcome:
        """Apply a matching grant or create one exact allow-once approval."""
        preview = self.commit_service.get_preview(preview_id)
        completed = self.commit_service.completed_result(preview.id)
        if completed is not None:
            return EnvironmentCommitOutcome(
                preview=preview,
                result=completed,
                idempotent_replay=True,
            )
        self.commit_service.validate_current(preview)
        context = PolicyContext(
            project_id=project_id or preview.scope_id,
            session_id=session_id,
            reason="Create the exact reviewed local Git commit.",
            preview=preview.to_dict(),
            approval_binding=preview.approval_binding,
            enforcement_owner=ENVIRONMENT_COMMIT_OWNER,
        )
        resolution = self.policy_engine.resolve(
            PermissionAction.GIT_COMMIT,
            profile=INTERACTIVE_PROFILE,
            context=context,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
        )
        if resolution.decision is PolicyDecision.DENY:
            raise EnvironmentCommitError("policy_denied", "Commit denied by policy.")
        if resolution.decision is PolicyDecision.ASK:
            approval = self.runtime_store.create_approval_request(resolution, context)
            return EnvironmentCommitOutcome(preview=preview, approval=approval)
        result = self.commit_service.apply(preview.id)
        return EnvironmentCommitOutcome(preview=preview, result=result)


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run_bounded(
    command: tuple[str, ...],
    *,
    environment: Mapping[str, str],
    input_bytes: bytes | None,
) -> _CommandResult:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
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
    if input_bytes is not None and process.stdin is not None:
        with suppress(BrokenPipeError):
            process.stdin.write(input_bytes)
            process.stdin.close()
    try:
        returncode = process.wait(timeout=GIT_MUTATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise EnvironmentCommitError(
            "git_timeout", "Git commit action timed out."
        ) from exc
    finally:
        for thread in threads:
            thread.join(timeout=1)
    if overflow.is_set():
        raise EnvironmentCommitError(
            "output_limit", "Git commit action exceeded its output limit."
        )
    return _CommandResult(returncode, bytes(stdout), bytes(stderr))


def _snapshot_matches_preview(
    snapshot: EnvironmentSnapshot, preview: EnvironmentCommitPreview
) -> bool:
    return (
        snapshot.repository_root == preview.repository_root
        and snapshot.worktree_root == preview.worktree_root
        and snapshot.branch == preview.branch
        and snapshot.head == preview.head
        and snapshot.diff_sha256 == preview.diff_sha256
        and snapshot.remote == preview.remote
        and snapshot.staged_count == preview.staged_count
        and snapshot.staged_count > 0
        and not snapshot.detached
    )


def _validate_preview(preview: EnvironmentCommitPreview) -> None:
    if preview.schema_version != ENVIRONMENT_COMMIT_SCHEMA_VERSION:
        raise ValueError("unsupported commit preview schema")
    _validate_preview_id(preview.id)
    for value in (preview.repository_root, preview.worktree_root):
        if not value or len(value) > 4096 or "\x00" in value:
            raise ValueError("commit preview path is invalid")
    if preview.branch is None or not preview.branch or len(preview.branch) > 512:
        raise ValueError("commit preview branch is invalid")
    if preview.head is not None and _HEX_SHA_RE.fullmatch(preview.head) is None:
        raise ValueError("commit preview head is invalid")
    if _HEX_SHA_RE.fullmatch(preview.diff_sha256) is None:
        raise ValueError("commit preview diff hash is invalid")
    if preview.staged_count < 1:
        raise ValueError("commit preview staged count is invalid")
    _validate_message(preview.message)
    _validate_author(preview.author_name, "author name")
    _validate_email(preview.author_email)
    if re.fullmatch(r"\d{1,20} [+-]\d{4}", preview.commit_date) is None:
        raise ValueError("commit preview date is invalid")
    _parse_timestamp(preview.created_at)


def _validate_preview_id(value: str) -> None:
    if _PREVIEW_ID_RE.fullmatch(str(value)) is None:
        raise EnvironmentCommitError("preview_invalid", "Commit preview is invalid.")


def _validate_message(value: str) -> str:
    text = str(value)
    if (
        not text.strip()
        or len(text) > MAX_COMMIT_MESSAGE_CHARS
        or "\x00" in text
        or any(ord(character) < 32 and character not in "\n\t" for character in text)
    ):
        raise EnvironmentCommitError("message_invalid", "Commit message is invalid.")
    return text


def _validate_author(value: str, field: str) -> str:
    text = str(value).strip()
    if (
        not text
        or len(text) > MAX_AUTHOR_CHARS
        or any(ord(character) < 32 for character in text)
        or any(character in "<>\n\r" for character in text)
    ):
        raise EnvironmentCommitError("author_invalid", f"Commit {field} is invalid.")
    return text


def _validate_email(value: str) -> str:
    text = str(value).strip()
    if (
        len(text) > MAX_AUTHOR_CHARS
        or any(ord(character) < 32 for character in text)
        or _EMAIL_RE.fullmatch(text) is None
    ):
        raise EnvironmentCommitError(
            "author_invalid", "Commit author email is invalid."
        )
    return text


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
