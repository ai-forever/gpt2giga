"""Safe project-file authoring with validation, previews, and conflict checks."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable, Generic, TypeVar

from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.types import redact_secrets


T = TypeVar("T")


class AuthoringConflictError(RuntimeError):
    """Raised when the source changed after a draft was loaded."""


@dataclass(frozen=True)
class ProjectFileDraft(Generic[T]):
    """Validated project-file draft that is safe to preview and apply."""

    relative_path: str
    source_hash: str
    content: str
    redacted_diff: str
    value: T


class ProjectAuthoringService:
    """Draft and atomically apply validated files below one project root."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).expanduser().resolve()

    def draft(
        self,
        relative_path: str | Path,
        content: str,
        *,
        validate: Callable[[str], T],
        expected_hash: str | None = None,
    ) -> ProjectFileDraft[T]:
        """Validate content and return a redacted diff without writing."""
        path = self._path(relative_path)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        source_hash = content_hash(old)
        if expected_hash is not None and expected_hash != source_hash:
            raise AuthoringConflictError("Project file changed; reload before applying")
        value = validate(content)
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{self._relative(path)}",
                tofile=f"b/{self._relative(path)}",
            )
        )
        return ProjectFileDraft(
            relative_path=self._relative(path),
            source_hash=source_hash,
            content=content,
            redacted_diff=str(redact_secrets(diff)),
            value=value,
        )

    def apply(self, draft: ProjectFileDraft[T]) -> str:
        """Atomically apply a previously validated draft after an ETag check."""
        path = self._path(draft.relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(path):
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            if content_hash(old) != draft.source_hash:
                raise AuthoringConflictError(
                    "Project file changed; reload before applying"
                )
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(draft.content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return content_hash(draft.content)

    def _path(self, relative_path: str | Path) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Project authoring paths must be relative")
        path = (self.root / candidate).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Project authoring path escapes the project root") from exc
        return path

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def content_hash(content: str) -> str:
    """Return the stable ETag used for project-file conflict checks."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
