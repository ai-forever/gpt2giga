"""Claude Code native session discovery and command planning."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from gpt2giga_harness.config import DEFAULT_HARNESS_DATA_DIR
from gpt2giga_harness.harnesses.agent_cli import build_safe_env
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    cli_args_from_attachments,
    prompt_with_attachments,
)
from gpt2giga_harness.native.base import NativeCommandPlan, NativeHistoryConnector
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga_harness.managed_mcp import write_startup_config
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.types import GigaChatApiMode, HarnessContext, HarnessRequest

CLAUDE_HARNESS_ID = "claude-code"
MANAGED_SESSION_PREFIX = "gpt2giga"


class ClaudeNativeHistoryConnector(NativeHistoryConnector):
    """Discover Claude Code native sessions and plan native commands."""

    harness_id = CLAUDE_HARNESS_ID

    def __init__(
        self,
        *,
        data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
        external_claude_home: str | Path | None = None,
        executable: str | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.external_claude_home = (
            Path(external_claude_home).expanduser()
            if external_claude_home is not None
            else Path.home() / ".claude"
        )
        self.executable = executable

    def discover(
        self,
        *,
        workspace: str | None,
        include_external: bool,
    ) -> tuple[NativeSessionRef, ...]:
        """Discover managed Claude refs first, then external refs when requested."""
        project_id = _project_id(workspace)
        managed = self._discover_source(
            source_root=self.managed_home(project_id),
            workspace=workspace,
            project_id=project_id,
            status=NativeSessionStatus.MANAGED_NATIVE,
            source_kind="managed",
            can_resume=True,
        )
        external: tuple[NativeSessionRef, ...] = ()
        if include_external:
            external = self._discover_source(
                source_root=self.external_claude_home,
                workspace=workspace,
                project_id=project_id,
                status=NativeSessionStatus.EXTERNAL_NATIVE,
                source_kind="external",
                can_resume=False,
            )
        return (*managed, *external)

    def preview(
        self,
        ref: NativeSessionRef,
        *,
        max_messages: int = 20,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return a defensive transcript preview for a discovered Claude ref."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_messages(path, max_messages=max_messages))

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return all parseable Claude messages for normalized import."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_messages(path, max_messages=None))

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan a native interactive `claude -n <name>` command."""
        project_id = _project_id(request.workspace)
        native_home = self.managed_home(project_id)
        native_home.mkdir(parents=True, exist_ok=True)
        _write_claude_settings(native_home)
        session_name = _managed_session_name(request, project_id)
        command = [self._executable(), "-n", session_name]
        model = request.model or context.default_model
        if model:
            command.extend(["--model", model])
        command.extend(cli_args_from_attachments(request))
        prompt = prompt_with_attachments(request).strip()
        if prompt:
            command.append(prompt)
        env = _claude_env(context, api_mode=request.api_mode, native_home=native_home)
        return NativeCommandPlan(
            command=tuple(command),
            env=env,
            cwd=request.workspace,
            native_home=str(native_home),
            metadata={
                "harness_id": self.harness_id,
                "project_id": project_id,
                "api_mode": request.api_mode.value,
                "managed": True,
                "session_name": session_name,
                **attachment_raw_metadata(request),
            },
        )

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan `claude --resume <name>` for a managed native session."""
        if ref.status is not NativeSessionStatus.MANAGED_NATIVE:
            raise ValueError("Only managed Claude native sessions can be resumed")
        if not ref.native_session_id:
            raise ValueError("Claude native session name is required for resume")
        native_home = _native_home_from_ref(ref)
        if native_home is None:
            native_home = self.managed_home(_project_id(ref.workspace))
        api_mode = _api_mode_from_ref(ref)
        native_home.mkdir(parents=True, exist_ok=True)
        _write_claude_settings(native_home)
        env = _claude_env(context, api_mode=api_mode, native_home=native_home)
        return NativeCommandPlan(
            command=(self._executable(), "--resume", ref.native_session_id),
            env=env,
            cwd=ref.workspace,
            native_home=str(native_home),
            metadata={
                "harness_id": self.harness_id,
                "native_ref_id": ref.id,
                "api_mode": api_mode.value,
                "managed": True,
            },
        )

    def managed_home(self, project_id: str) -> Path:
        """Return the managed HOME used for one project's Claude Code sessions."""
        return self.data_dir / "native" / "claude" / "homes" / project_id

    def _discover_source(
        self,
        *,
        source_root: Path,
        workspace: str | None,
        project_id: str,
        status: NativeSessionStatus,
        source_kind: str,
        can_resume: bool,
    ) -> tuple[NativeSessionRef, ...]:
        refs = [
            ref
            for path in _session_files(source_root)
            if (
                ref := _ref_from_file(
                    path,
                    workspace=workspace,
                    project_id=project_id,
                    status=status,
                    source_kind=source_kind,
                    can_resume=can_resume,
                    native_home=str(source_root)
                    if status is NativeSessionStatus.MANAGED_NATIVE
                    else None,
                )
            )
            is not None
        ]
        refs.sort(key=lambda ref: (ref.updated_at or ref.created_at or "", ref.id))
        refs.reverse()
        return tuple(refs)

    def _executable(self) -> str:
        return self.executable or shutil.which("claude") or "claude"


def _write_claude_settings(home: Path) -> None:
    write_startup_config("claude-code", home, {})


def _ref_from_file(
    path: Path,
    *,
    workspace: str | None,
    project_id: str,
    status: NativeSessionStatus,
    source_kind: str,
    can_resume: bool,
    native_home: str | None,
) -> NativeSessionRef | None:
    summary = _summarize_session_file(path)
    native_session_id = (
        summary.session_name
        or summary.native_session_id
        or _session_name_from_path(path)
    )
    if summary.message_count == 0 and not native_session_id:
        return None
    metadata = {
        "path": str(path),
        "project_id": project_id,
        "source_kind": source_kind,
    }
    if native_home is not None:
        metadata["native_home"] = native_home
    if summary.session_name is not None:
        metadata["session_name"] = summary.session_name
    if summary.native_session_id is not None:
        metadata["claude_session_id"] = summary.native_session_id
    if summary.roles:
        metadata["roles"] = tuple(sorted(summary.roles))
    return NativeSessionRef(
        id=_ref_id(path, native_session_id or path.stem, source_kind),
        harness_id=CLAUDE_HARNESS_ID,
        native_session_id=native_session_id,
        title=summary.title or native_session_id or "Untitled Claude session",
        workspace=workspace,
        source=str(path),
        status=status,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        message_count=summary.message_count,
        can_preview=summary.message_count > 0,
        can_import=summary.message_count > 0,
        can_resume=can_resume and bool(native_session_id),
        resume_reason=None
        if can_resume and native_session_id
        else (
            "external Claude sessions use the user's Claude home; "
            "managed gpt2giga resume is unavailable"
        ),
        metadata=metadata,
    )


def _session_files(source_root: Path) -> tuple[Path, ...]:
    if not source_root.exists() or not source_root.is_dir():
        return ()
    search_roots = (
        source_root / ".claude" / "projects",
        source_root / "projects",
        source_root / "sessions",
        source_root,
    )
    paths: set[Path] = set()
    try:
        for root in search_roots:
            if not root.exists() or not root.is_dir():
                continue
            if root == source_root:
                paths.update(path for path in root.glob("*.jsonl") if path.is_file())
                continue
            paths.update(path for path in root.rglob("*.jsonl") if path.is_file())
    except OSError:
        return ()
    return tuple(sorted(paths))


def _iter_events(path: Path) -> Iterable[Mapping[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        try:
            decoded = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, Mapping):
            yield decoded


def _iter_messages(
    path: Path,
    *,
    max_messages: int | None,
) -> Iterable[NativeTranscriptMessage]:
    count = 0
    for event in _iter_events(path):
        message = _message_from_event(event)
        if message is None:
            continue
        yield message
        count += 1
        if max_messages is not None and count >= max_messages:
            return


def _message_from_event(event: Mapping[str, Any]) -> NativeTranscriptMessage | None:
    role = _role_from_event(event)
    content = _content_from_event(event)
    if role is None or content is None:
        return None
    return NativeTranscriptMessage(
        role=role,
        content=content,
        created_at=_timestamp_from_event(event),
        metadata={"source": "claude"},
    )


def _role_from_event(event: Mapping[str, Any]) -> str | None:
    candidates = (
        _nested(event, "message", "role"),
        event.get("role"),
        event.get("type"),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        role = str(candidate).strip().lower()
        if role in {"user", "assistant", "system", "tool"}:
            return role
    return None


def _content_from_event(event: Mapping[str, Any]) -> str | None:
    candidates = (
        _nested(event, "message", "content"),
        _nested(event, "message", "text"),
        event.get("content"),
        event.get("text"),
    )
    for candidate in candidates:
        text = _content_text(candidate)
        if text:
            return text
    return None


def _content_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, Mapping):
        for key in ("text", "content", "value"):
            text = _content_text(value.get(key))
            if text:
                return text
        return None
    if isinstance(value, list):
        parts = [_content_text(item) for item in value]
        text = "\n".join(part for part in parts if part)
        return text or None
    return None


def _timestamp_from_event(event: Mapping[str, Any]) -> str | None:
    for key in ("timestamp", "created_at", "createdAt", "time", "updated_at"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _session_id_from_event(event: Mapping[str, Any]) -> str | None:
    for key in ("session_id", "sessionId", "conversation_id", "thread_id"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _session_name_from_event(event: Mapping[str, Any]) -> str | None:
    candidates = (
        event.get("session_name"),
        event.get("sessionName"),
        _nested(event, "session", "name"),
        _nested(event, "conversation", "name"),
    )
    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return None


def _title_from_event(event: Mapping[str, Any]) -> str | None:
    for key in ("title", "summary"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return _title_from_content(str(value))
    return None


def _nested(event: Mapping[str, Any], *path: str) -> Any:
    value: Any = event
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


class _SessionSummary:
    def __init__(self, path: Path) -> None:
        self.native_session_id: str | None = None
        self.session_name: str | None = _session_name_from_path(path)
        self.title: str | None = None
        self.created_at: str | None = None
        self.updated_at: str | None = None
        self.message_count = 0
        self.roles: set[str] = set()
        try:
            self.updated_at = _mtime_timestamp(path)
        except OSError:
            self.updated_at = None

    def observe_event(self, event: Mapping[str, Any]) -> None:
        if self.native_session_id is None:
            self.native_session_id = _session_id_from_event(event)
        if self.session_name is None:
            self.session_name = _session_name_from_event(event)
        if self.title is None:
            self.title = _title_from_event(event)
        timestamp = _timestamp_from_event(event)
        if timestamp is not None:
            self.created_at = self.created_at or timestamp
            self.updated_at = timestamp
        message = _message_from_event(event)
        if message is None:
            return
        self.message_count += 1
        self.roles.add(message.role)
        if self.title is None and message.role == "user":
            self.title = _title_from_content(message.content)


def _summarize_session_file(path: Path) -> _SessionSummary:
    summary = _SessionSummary(path)
    for event in _iter_events(path):
        summary.observe_event(event)
    if summary.created_at is None:
        summary.created_at = summary.updated_at
    return summary


def _managed_session_name(request: HarnessRequest, project_id: str) -> str:
    source_id = request.session_id or request.run_id or project_id
    short_id = _slugify(source_id, fallback="session")[:12].strip("-")
    prompt_slug = _slugify(request.prompt, fallback="chat")[:32].strip("-")
    return f"{MANAGED_SESSION_PREFIX}-{short_id}-{prompt_slug}"[:80].rstrip("-")


def _session_name_from_path(path: Path) -> str | None:
    stem = path.stem.strip()
    if stem.startswith(f"{MANAGED_SESSION_PREFIX}-"):
        return stem
    return None


def _title_from_content(content: str) -> str:
    title = " ".join(content.split())
    if len(title) > 60:
        title = title[:57].rstrip() + "..."
    return title or "Untitled Claude session"


def _slugify(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def _ref_id(path: Path, native_session_id: str, source_kind: str) -> str:
    digest = hashlib.sha256(
        f"{source_kind}:{path}:{native_session_id}".encode("utf-8")
    ).hexdigest()
    return f"native_claude_{digest[:16]}"


def _path_from_ref(ref: NativeSessionRef) -> Path | None:
    path_value = ref.metadata.get("path") or ref.source
    if not path_value:
        return None
    path = Path(str(path_value)).expanduser()
    return path if path.exists() and path.is_file() else None


def _native_home_from_ref(ref: NativeSessionRef) -> Path | None:
    value = ref.metadata.get("native_home")
    if value is None:
        return None
    return Path(str(value)).expanduser()


def _api_mode_from_ref(ref: NativeSessionRef) -> GigaChatApiMode:
    value = ref.metadata.get("api_mode")
    if isinstance(value, GigaChatApiMode):
        return value
    try:
        return GigaChatApiMode(str(value))
    except ValueError:
        return GigaChatApiMode.V2


def _project_id(workspace: str | None) -> str:
    return project_id_for_root(workspace or Path.cwd())


def _claude_env(
    context: HarnessContext,
    *,
    api_mode: GigaChatApiMode,
    native_home: Path,
) -> dict[str, str]:
    return build_safe_env(
        context,
        home=str(native_home),
        extra={
            "ANTHROPIC_BASE_URL": context.api_base_url(api_mode),
            "ANTHROPIC_API_KEY": context.api_key or "0",
            "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
            "GPT2GIGA_HARNESS_API_MODE": api_mode.value,
        },
    )


def _mtime_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
