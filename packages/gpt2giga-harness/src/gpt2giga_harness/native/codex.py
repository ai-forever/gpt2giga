"""Codex native session discovery and command planning."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from gpt2giga_harness.config import DEFAULT_HARNESS_DATA_DIR
from gpt2giga_harness.executables import ExecutableResolver
from gpt2giga_harness.harnesses.agent_cli import build_safe_env
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    cli_args_from_attachments,
    prompt_with_attachments,
)
from gpt2giga_harness.native.base import (
    NativeCommandPlan,
    NativeHistoryConnector,
    native_permission_metadata,
    native_source_workspace,
    native_workspace_policy,
)
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
    create_execution_snapshot,
)
from gpt2giga_harness.native.snapshots import (
    NativeExecutionSnapshotStore,
    validate_resume_snapshot,
)
from gpt2giga_harness.managed_mcp import write_startup_config
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.types import GigaChatApiMode, HarnessContext, HarnessRequest

CODEX_HARNESS_ID = "codex-cli"
CODEX_PROVIDER_NAME = "gpt2giga_harness"
MODE_TO_SANDBOX = {
    "plan": "read-only",
    "read": "read-only",
    "edit": "workspace-write",
}


class CodexNativeHistoryConnector(NativeHistoryConnector):
    """Discover Codex native sessions and plan native commands."""

    harness_id = CODEX_HARNESS_ID
    requires_proxy_preflight = True

    def __init__(
        self,
        *,
        data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
        external_codex_home: str | Path | None = None,
        executable: str | None = None,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.external_codex_home = (
            Path(external_codex_home).expanduser()
            if external_codex_home is not None
            else Path.home() / ".codex"
        )
        self.executable = executable
        self.executable_resolver = executable_resolver or ExecutableResolver.path_only()
        self.snapshot_store = NativeExecutionSnapshotStore(self.data_dir)

    def discover(
        self,
        *,
        workspace: str | None,
        include_external: bool,
    ) -> tuple[NativeSessionRef, ...]:
        """Discover managed Codex refs first, then external refs when requested."""
        project_id = _project_id(workspace)
        managed = self.snapshot_store.reconcile(
            self._discover_source(
                sessions_dir=self.managed_home(project_id) / "sessions",
                workspace=workspace,
                project_id=project_id,
                status=NativeSessionStatus.MANAGED_NATIVE,
                source_kind="managed",
                can_resume=True,
            ),
            harness_id=self.harness_id,
        )
        external: tuple[NativeSessionRef, ...] = ()
        if include_external:
            external = self._discover_source(
                sessions_dir=self.external_codex_home / "sessions",
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
        """Return a defensive transcript preview for a discovered Codex ref."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_messages(path, max_messages=max_messages))

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return all parseable Codex messages for normalized import."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_messages(path, max_messages=None))

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan a native `codex` command without using headless exec mode."""
        source_workspace = native_source_workspace(request)
        project_id = _project_id(source_workspace)
        native_home = self.managed_home(project_id)
        known_sources = tuple(
            str(path) for path in _session_files(native_home / "sessions")
        )
        native_home.mkdir(parents=True, exist_ok=True)
        tool_config_hash = _write_codex_config(native_home, request, context)
        sandbox = MODE_TO_SANDBOX.get(request.mode, MODE_TO_SANDBOX["plan"])
        permission = native_permission_metadata(
            requested_mode=request.mode,
            cli_control="--sandbox",
            cli_value=sandbox,
            read_only=sandbox == "read-only",
        )
        model = request.model or context.default_model
        command = [*self._executable_argv(), "--ask-for-approval", "on-request"]
        if model:
            command.extend(["-m", model])
        command.extend(["--sandbox", sandbox])
        attachment_args = cli_args_from_attachments(request)
        command.extend(attachment_args)
        prompt = prompt_with_attachments(request).strip()
        if prompt:
            if attachment_args:
                command.append("--")
            command.append(prompt)
        env = _codex_env(
            context,
            api_mode=request.api_mode,
            native_home=native_home,
        )
        snapshot = create_execution_snapshot(
            harness_id=self.harness_id,
            api_mode=request.api_mode.value,
            model=model,
            native_home=str(native_home),
            workspace=source_workspace,
            project_id=project_id,
            permission_mode=request.mode,
            tool_config_hash=tool_config_hash,
            source_workspace=source_workspace,
            effective_workspace=request.workspace,
            workspace_policy=native_workspace_policy(request),
        )
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
                "source_workspace": source_workspace,
                "effective_workspace": request.workspace,
                "permission_enforcement": permission,
                **attachment_raw_metadata(request),
            },
            execution_snapshot=snapshot,
            snapshot_known_sources=known_sources,
        )

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan `codex resume <SESSION_ID>` for a managed native session."""
        if ref.status is not NativeSessionStatus.MANAGED_NATIVE:
            raise ValueError("Only managed Codex native sessions can be resumed")
        if not ref.native_session_id:
            raise ValueError("Codex native session id is required for resume")
        snapshot = validate_resume_snapshot(ref, harness_id=self.harness_id)
        native_home = Path(snapshot.native_home or "").expanduser()
        if not snapshot.native_home:
            raise ValueError("Native resume snapshot is missing its managed home")
        api_mode = GigaChatApiMode(snapshot.api_mode)
        native_home.mkdir(parents=True, exist_ok=True)
        _write_codex_config_values(
            native_home,
            model=snapshot.model or context.default_model or "GigaChat",
            base_url=context.api_base_url(api_mode),
        )
        env = _codex_env(context, api_mode=api_mode, native_home=native_home)
        sandbox = MODE_TO_SANDBOX.get(
            snapshot.permission_mode,
            MODE_TO_SANDBOX["plan"],
        )
        permission = native_permission_metadata(
            requested_mode=snapshot.permission_mode,
            cli_control="--sandbox",
            cli_value=sandbox,
            read_only=sandbox == "read-only",
        )
        return NativeCommandPlan(
            command=(
                *self._executable_argv(),
                "--ask-for-approval",
                "on-request",
                "--sandbox",
                sandbox,
                "resume",
                ref.native_session_id,
            ),
            env=env,
            cwd=snapshot.effective_workspace or ref.workspace,
            native_home=str(native_home),
            metadata={
                "harness_id": self.harness_id,
                "native_ref_id": ref.id,
                "api_mode": api_mode.value,
                "managed": True,
                "route_unknown": not snapshot.route_known,
                "resume_warnings": list(snapshot.warnings),
                "source_workspace": ref.metadata.get("source_workspace"),
                "effective_workspace": snapshot.effective_workspace or ref.workspace,
                "permission_enforcement": permission,
            },
            execution_snapshot=snapshot,
        )

    def record_start_snapshot(self, plan: NativeCommandPlan) -> None:
        """Persist a successful Codex native start for later discovery."""
        self.snapshot_store.record_start(plan)

    def managed_home(self, project_id: str) -> Path:
        """Return the managed CODEX_HOME for one project id."""
        return self.data_dir / "native" / "codex" / "homes" / project_id

    def _discover_source(
        self,
        *,
        sessions_dir: Path,
        workspace: str | None,
        project_id: str,
        status: NativeSessionStatus,
        source_kind: str,
        can_resume: bool,
    ) -> tuple[NativeSessionRef, ...]:
        refs = [
            _ref_from_file(
                path,
                workspace=workspace,
                project_id=project_id,
                status=status,
                source_kind=source_kind,
                can_resume=can_resume,
                native_home=str(sessions_dir.parent)
                if status is NativeSessionStatus.MANAGED_NATIVE
                else None,
            )
            for path in _session_files(sessions_dir)
        ]
        refs.sort(key=lambda ref: (ref.updated_at or ref.created_at or "", ref.id))
        refs.reverse()
        return tuple(refs)

    def _executable_argv(self) -> tuple[str, ...]:
        if self.executable is not None:
            return (self.executable,)
        resolution = self.executable_resolver.resolve(self.harness_id, "codex")
        return resolution.command or ("codex",)


def _ref_from_file(
    path: Path,
    *,
    workspace: str | None,
    project_id: str,
    status: NativeSessionStatus,
    source_kind: str,
    can_resume: bool,
    native_home: str | None,
) -> NativeSessionRef:
    summary = _summarize_session_file(path)
    native_session_id = summary.native_session_id or path.stem
    metadata = {
        "path": str(path),
        "project_id": project_id,
        "source_kind": source_kind,
    }
    if native_home is not None:
        metadata["native_home"] = native_home
    if summary.roles:
        metadata["roles"] = tuple(sorted(summary.roles))
    return NativeSessionRef(
        id=_ref_id(path, native_session_id, source_kind),
        harness_id=CODEX_HARNESS_ID,
        native_session_id=native_session_id,
        title=summary.title or native_session_id,
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
        if can_resume
        else (
            "external Codex sessions use the user's Codex home; "
            "managed gpt2giga resume is unavailable"
        ),
        metadata=metadata,
    )


def _session_files(sessions_dir: Path) -> tuple[Path, ...]:
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return ()
    try:
        paths = [
            path
            for pattern in ("*.jsonl", "*.json")
            for path in sessions_dir.rglob(pattern)
            if path.is_file()
        ]
    except OSError:
        return ()
    return tuple(sorted(paths))


def _iter_jsonl(path: Path) -> Iterable[Mapping[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, Mapping):
                    yield decoded
    except (OSError, UnicodeDecodeError):
        return


def _iter_messages(
    path: Path,
    *,
    max_messages: int | None,
) -> Iterable[NativeTranscriptMessage]:
    count = 0
    for event in _iter_jsonl(path):
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
        metadata={"source": "codex"},
    )


def _role_from_event(event: Mapping[str, Any]) -> str | None:
    candidates = (
        event.get("role"),
        _nested(event, "message", "role"),
        _nested(event, "author", "role"),
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
        event.get("content"),
        event.get("text"),
        _nested(event, "message", "content"),
        _nested(event, "message", "text"),
        _nested(event, "item", "content"),
        _nested(event, "item", "text"),
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
    for event in _iter_jsonl(path):
        summary.observe_event(event)
    if summary.created_at is None:
        summary.created_at = summary.updated_at
    return summary


def _title_from_content(content: str) -> str:
    title = " ".join(content.split())
    if len(title) > 60:
        title = title[:57].rstrip() + "..."
    return title or "Untitled Codex session"


def _ref_id(path: Path, native_session_id: str, source_kind: str) -> str:
    digest = hashlib.sha256(
        f"{source_kind}:{path}:{native_session_id}".encode("utf-8")
    ).hexdigest()
    return f"native_codex_{digest[:16]}"


def _path_from_ref(ref: NativeSessionRef) -> Path | None:
    path_value = ref.metadata.get("path") or ref.source
    if not path_value:
        return None
    path = Path(str(path_value)).expanduser()
    return path if path.exists() and path.is_file() else None


def _project_id(workspace: str | None) -> str:
    return project_id_for_root(workspace or Path.cwd())


def _codex_env(
    context: HarnessContext,
    *,
    api_mode: GigaChatApiMode,
    native_home: Path,
) -> dict[str, str]:
    return build_safe_env(
        context,
        extra={
            "CODEX_HOME": str(native_home),
            "GPT2GIGA_API_KEY": context.api_key or "0",
            "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
            "GPT2GIGA_HARNESS_API_MODE": api_mode.value,
        },
    )


def _write_codex_config(
    codex_home: Path,
    request: HarnessRequest,
    context: HarnessContext,
) -> str:
    model = request.model or context.default_model or "GigaChat"
    base_url = context.api_base_url(request.api_mode)
    return _write_codex_config_values(codex_home, model=model, base_url=base_url)


def _write_codex_config_values(
    codex_home: Path,
    *,
    model: str,
    base_url: str,
) -> str:
    config = (
        f'model = "{_toml_escape(model)}"\n'
        f'model_provider = "{CODEX_PROVIDER_NAME}"\n'
        'model_reasoning_effort = "none"\n\n'
        f"[model_providers.{CODEX_PROVIDER_NAME}]\n"
        f'name = "{CODEX_PROVIDER_NAME}"\n'
        f'base_url = "{_toml_escape(base_url)}"\n'
        'env_key = "GPT2GIGA_API_KEY"\n'
        'wire_api = "responses"\n'
        "supports_websockets = false\n"
    )
    return write_startup_config("codex-cli", codex_home, config)


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _mtime_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
