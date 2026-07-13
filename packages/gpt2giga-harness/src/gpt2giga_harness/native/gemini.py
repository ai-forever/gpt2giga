"""Gemini CLI native session discovery and command planning."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from gpt2giga_harness.config import DEFAULT_HARNESS_DATA_DIR
from gpt2giga_harness.executables import ExecutableResolver
from gpt2giga_harness.harnesses.agent_cli import build_safe_env
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    prompt_with_attachments,
)
from gpt2giga_harness.harnesses.gemini_cli import gemini_cli_custom_headers
from gpt2giga_harness.native.base import (
    NativeCommandPlan,
    NativeHistoryConnector,
    NativePromptDelivery,
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

GEMINI_HARNESS_ID = "gemini-cli"
LIST_SESSIONS_TIMEOUT_SECONDS = 5.0
CAPABILITY_PROBE_TIMEOUT_SECONDS = 5.0
_SESSION_ID_RE = re.compile(r"(?P<id>[A-Za-z0-9][A-Za-z0-9_.:-]{3,})")
MODE_TO_APPROVAL = {
    "plan": "plan",
    "read": "plan",
    "edit": "default",
}


class GeminiNativeHistoryConnector(NativeHistoryConnector):
    """Discover Gemini CLI native sessions and plan native commands."""

    harness_id = GEMINI_HARNESS_ID
    requires_proxy_preflight = True

    def __init__(
        self,
        *,
        data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
        external_gemini_home: str | Path | None = None,
        executable: str | None = None,
        executable_resolver: ExecutableResolver | None = None,
        list_sessions_runner: Callable[
            [tuple[str, ...], Mapping[str, str], str | None],
            subprocess.CompletedProcess[str],
        ]
        | None = None,
        capability_probe_runner: Callable[
            [tuple[str, ...], Mapping[str, str], str | None],
            subprocess.CompletedProcess[str],
        ]
        | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.external_gemini_home = (
            Path(external_gemini_home).expanduser()
            if external_gemini_home is not None
            else Path.home()
        )
        self.executable = executable
        self.executable_resolver = executable_resolver or ExecutableResolver.path_only()
        self.list_sessions_runner = list_sessions_runner or _run_list_sessions
        self.capability_probe_runner = capability_probe_runner or _run_capability_probe
        self.snapshot_store = NativeExecutionSnapshotStore(self.data_dir)
        self._prompt_interactive_supported: bool | None = None

    def discover(
        self,
        *,
        workspace: str | None,
        include_external: bool,
    ) -> tuple[NativeSessionRef, ...]:
        """Discover Gemini refs from CLI listing, managed files, then external files."""
        project_id = _project_id(workspace)
        listed: tuple[NativeSessionRef, ...] = ()
        if include_external:
            listed = self._discover_from_cli_list(
                workspace=workspace,
                project_id=project_id,
            )
        managed = self.snapshot_store.reconcile(
            self._discover_source(
                gemini_home=self.managed_home(project_id),
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
                gemini_home=self.external_gemini_home,
                workspace=workspace,
                project_id=project_id,
                status=NativeSessionStatus.EXTERNAL_NATIVE,
                source_kind="external",
                can_resume=False,
            )
        return (*listed, *managed, *external)

    def preview(
        self,
        ref: NativeSessionRef,
        *,
        max_messages: int = 20,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return a defensive transcript preview for a discovered Gemini ref."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_messages(path, max_messages=max_messages))

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return all parseable Gemini messages for normalized import."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_messages(path, max_messages=None))

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan a native interactive `gemini` command."""
        source_workspace = native_source_workspace(request)
        project_id = _project_id(source_workspace)
        native_home = self.managed_home(project_id)
        known_sources = tuple(
            str(path) for path in _checkpoint_files(native_home, request.workspace)
        )
        native_home.mkdir(parents=True, exist_ok=True)
        tool_config_hash = _write_gemini_settings(native_home)
        model = request.model or context.default_model
        executable = self._executable()
        approval_mode = MODE_TO_APPROVAL.get(
            request.mode,
            MODE_TO_APPROVAL["plan"],
        )
        permission = native_permission_metadata(
            requested_mode=request.mode,
            cli_control="--approval-mode",
            cli_value=approval_mode,
            read_only=approval_mode == "plan",
        )
        command = [executable, "--approval-mode", approval_mode]
        if model:
            command.extend(["-m", model])
        prompt = prompt_with_attachments(request)
        metadata: dict[str, Any] = {
            "harness_id": self.harness_id,
            "project_id": project_id,
            "api_mode": request.api_mode.value,
            "managed": True,
            "chat_commands": ("/chat save <tag>", "/chat resume <tag>"),
            "source_workspace": source_workspace,
            "effective_workspace": request.workspace,
            "permission_enforcement": permission,
            **attachment_raw_metadata(request),
        }
        env = _gemini_env(
            context,
            api_mode=request.api_mode,
            native_home=native_home,
            model=model,
        )
        prompt_delivery = None
        display_command: list[str] = []
        if prompt:
            if not self._supports_prompt_interactive(
                executable=executable,
                env=env,
                cwd=request.workspace,
            ):
                raise ValueError(
                    "Installed Gemini CLI does not support safe native initial "
                    "prompt delivery via --prompt-interactive"
                )
            command.extend(["--prompt-interactive", prompt])
            display_command = [*command[:-1], "<initial-prompt>"]
            prompt_delivery = NativePromptDelivery(
                idempotency_key=_prompt_delivery_key(request),
                mechanism="gemini_prompt_interactive",
                prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                byte_count=len(prompt.encode("utf-8")),
            )
            metadata["prompt_delivery_capability"] = {
                "supported": True,
                "mechanism": "--prompt-interactive",
                "evidence": "gemini --help",
            }
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
            display_command=tuple(display_command),
            env=env,
            cwd=request.workspace,
            native_home=str(native_home),
            metadata=metadata,
            execution_snapshot=snapshot,
            snapshot_known_sources=known_sources,
            prompt_delivery=prompt_delivery,
        )

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan `gemini --resume <id>` for a managed native session."""
        if ref.status is not NativeSessionStatus.MANAGED_NATIVE:
            raise ValueError("Only managed Gemini native sessions can be resumed")
        if not ref.native_session_id:
            raise ValueError("Gemini native session id is required for resume")
        snapshot = validate_resume_snapshot(ref, harness_id=self.harness_id)
        if not snapshot.native_home:
            raise ValueError("Native resume snapshot is missing its managed home")
        native_home = Path(snapshot.native_home).expanduser()
        api_mode = GigaChatApiMode(snapshot.api_mode)
        native_home.mkdir(parents=True, exist_ok=True)
        _write_gemini_settings(native_home)
        env = _gemini_env(
            context,
            api_mode=api_mode,
            native_home=native_home,
            model=snapshot.model or context.default_model,
        )
        approval_mode = MODE_TO_APPROVAL.get(
            snapshot.permission_mode,
            MODE_TO_APPROVAL["plan"],
        )
        permission = native_permission_metadata(
            requested_mode=snapshot.permission_mode,
            cli_control="--approval-mode",
            cli_value=approval_mode,
            read_only=approval_mode == "plan",
        )
        return NativeCommandPlan(
            command=(
                self._executable(),
                "--approval-mode",
                approval_mode,
                "--resume",
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
        """Persist a successful Gemini native start for later discovery."""
        self.snapshot_store.record_start(plan)

    def managed_home(self, project_id: str) -> Path:
        """Return the managed HOME used for one project's Gemini CLI sessions."""
        return self.data_dir / "native" / "gemini" / "homes" / project_id

    def _supports_prompt_interactive(
        self,
        *,
        executable: str,
        env: Mapping[str, str],
        cwd: str | None,
    ) -> bool:
        """Probe whether this Gemini CLI accepts an interactive initial prompt."""
        if self._prompt_interactive_supported is not None:
            return self._prompt_interactive_supported
        try:
            completed = self.capability_probe_runner(
                (executable, "--help"),
                env,
                cwd,
            )
        except (OSError, subprocess.SubprocessError):
            supported = False
        else:
            output = f"{completed.stdout}\n{completed.stderr}"
            supported = completed.returncode == 0 and "--prompt-interactive" in output
        self._prompt_interactive_supported = supported
        return supported

    def _discover_from_cli_list(
        self,
        *,
        workspace: str | None,
        project_id: str,
    ) -> tuple[NativeSessionRef, ...]:
        executable = self._available_executable()
        if executable is None:
            return ()
        env = build_safe_env(HarnessContext(proxy_url=""))
        try:
            completed = self.list_sessions_runner(
                (executable, "--list-sessions"),
                env,
                workspace,
            )
        except (OSError, subprocess.SubprocessError):
            return ()
        if completed.returncode != 0:
            return ()
        return _refs_from_list_output(
            completed.stdout,
            workspace=workspace,
            project_id=project_id,
        )

    def _discover_source(
        self,
        *,
        gemini_home: Path,
        workspace: str | None,
        project_id: str,
        status: NativeSessionStatus,
        source_kind: str,
        can_resume: bool,
    ) -> tuple[NativeSessionRef, ...]:
        refs = [
            ref
            for path in _checkpoint_files(gemini_home, workspace)
            if (
                ref := _ref_from_file(
                    path,
                    workspace=workspace,
                    project_id=project_id,
                    status=status,
                    source_kind=source_kind,
                    can_resume=can_resume,
                    native_home=str(gemini_home)
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
        if self.executable is not None:
            return self.executable
        resolution = self.executable_resolver.resolve(self.harness_id, "gemini")
        return resolution.executable or resolution.configured or "gemini"

    def _available_executable(self) -> str | None:
        if self.executable is not None:
            return self.executable
        return self.executable_resolver.resolve(self.harness_id, "gemini").executable


def _refs_from_list_output(
    output: str,
    *,
    workspace: str | None,
    project_id: str,
) -> tuple[NativeSessionRef, ...]:
    refs = _refs_from_json_list_output(
        output, workspace=workspace, project_id=project_id
    )
    if refs:
        return refs
    return _refs_from_text_list_output(
        output, workspace=workspace, project_id=project_id
    )


def _refs_from_json_list_output(
    output: str,
    *,
    workspace: str | None,
    project_id: str,
) -> tuple[NativeSessionRef, ...]:
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return ()
    if isinstance(decoded, Mapping):
        raw_items = decoded.get("sessions") or decoded.get("items") or ()
    else:
        raw_items = decoded
    if not isinstance(raw_items, list):
        return ()
    refs = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        session_id = _text_from_keys(item, "id", "session_id", "sessionId", "uuid")
        if session_id is None:
            continue
        title = _text_from_keys(item, "title", "name", "tag") or session_id
        refs.append(
            _listed_ref(
                session_id=session_id,
                title=title,
                workspace=workspace,
                project_id=project_id,
                created_at=_text_from_keys(item, "created_at", "createdAt"),
                updated_at=_text_from_keys(item, "updated_at", "updatedAt", "time"),
                message_count=_optional_int(item.get("message_count")),
            )
        )
    return tuple(refs)


def _refs_from_text_list_output(
    output: str,
    *,
    workspace: str | None,
    project_id: str,
) -> tuple[NativeSessionRef, ...]:
    refs = []
    for line in output.splitlines():
        text = line.strip()
        if not text or set(text) <= {"-", " "}:
            continue
        lower = text.lower()
        if "session" in lower and "id" in lower and "title" in lower:
            continue
        match = _SESSION_ID_RE.search(text)
        if match is None:
            continue
        session_id = match.group("id")
        title = text[match.end() :].strip(" -:\t") or session_id
        refs.append(
            _listed_ref(
                session_id=session_id,
                title=title,
                workspace=workspace,
                project_id=project_id,
            )
        )
    return tuple(refs)


def _listed_ref(
    *,
    session_id: str,
    title: str,
    workspace: str | None,
    project_id: str,
    created_at: str | None = None,
    updated_at: str | None = None,
    message_count: int | None = None,
) -> NativeSessionRef:
    metadata = {
        "project_id": project_id,
        "source_kind": "cli_list",
    }
    return NativeSessionRef(
        id=_ref_id(Path("gemini-list-sessions"), session_id, "cli_list"),
        harness_id=GEMINI_HARNESS_ID,
        native_session_id=session_id,
        title=title,
        workspace=workspace,
        source="gemini --list-sessions",
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        created_at=created_at,
        updated_at=updated_at,
        message_count=message_count,
        can_preview=False,
        can_import=False,
        can_resume=False,
        resume_reason=(
            "Gemini CLI listing uses the user's Gemini home; "
            "managed gpt2giga resume is unavailable"
        ),
        metadata=metadata,
    )


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
    native_session_id = summary.native_session_id or path.stem
    if summary.message_count == 0 and not summary.native_session_id:
        return None
    metadata = {
        "path": str(path),
        "project_id": project_id,
        "source_kind": source_kind,
    }
    if native_home is not None:
        metadata["native_home"] = native_home
    if summary.model is not None:
        metadata["model"] = summary.model
    if summary.roles:
        metadata["roles"] = tuple(sorted(summary.roles))
    return NativeSessionRef(
        id=_ref_id(path, native_session_id, source_kind),
        harness_id=GEMINI_HARNESS_ID,
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
        if can_resume and native_session_id
        else (
            "external Gemini sessions use the user's Gemini home; "
            "managed gpt2giga resume is unavailable"
        ),
        metadata=metadata,
    )


def _checkpoint_files(gemini_home: Path, workspace: str | None) -> tuple[Path, ...]:
    roots = _checkpoint_roots(gemini_home, workspace)
    paths: set[Path] = set()
    try:
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            paths.update(path for path in root.rglob("*.jsonl") if path.is_file())
            paths.update(path for path in root.rglob("*.json") if path.is_file())
    except OSError:
        return ()
    return tuple(sorted(paths))


def _checkpoint_roots(gemini_home: Path, workspace: str | None) -> tuple[Path, ...]:
    tmp_root = gemini_home / ".gemini" / "tmp"
    if workspace is not None:
        roots: list[Path] = []
        storage_key = _project_storage_key(gemini_home, workspace)
        if storage_key is not None:
            roots.append(tmp_root / storage_key)
        roots.append(tmp_root / project_hash_for_workspace(workspace))
        return tuple(dict.fromkeys(roots))
    return (tmp_root,)


def _project_storage_key(gemini_home: Path, workspace: str) -> str | None:
    projects_path = gemini_home / ".gemini" / "projects.json"
    try:
        decoded = json.loads(projects_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    projects = decoded.get("projects") if isinstance(decoded, Mapping) else None
    if not isinstance(projects, Mapping):
        return None
    normalized_workspace = str(Path(workspace).expanduser().resolve())
    value = projects.get(normalized_workspace)
    if value is None:
        for candidate_workspace, candidate_value in projects.items():
            try:
                candidate = str(Path(str(candidate_workspace)).expanduser().resolve())
            except (OSError, ValueError):
                continue
            if candidate == normalized_workspace:
                value = candidate_value
                break
    if value is None or not str(value).strip():
        return None
    storage_key = str(value).strip()
    tmp_root = (gemini_home / ".gemini" / "tmp").resolve()
    try:
        (tmp_root / storage_key).resolve().relative_to(tmp_root)
    except (OSError, ValueError):
        return None
    return storage_key


def _iter_events(path: Path) -> Iterable[Mapping[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if path.suffix.lower() == ".json":
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return
        yield from _events_from_decoded(decoded)
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


def _events_from_decoded(decoded: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(decoded, list):
        for item in decoded:
            if isinstance(item, Mapping):
                yield item
        return
    if not isinstance(decoded, Mapping):
        return
    yield decoded
    raw_messages = decoded.get("messages")
    if not isinstance(raw_messages, list):
        return
    inherited = {
        key: value
        for key in ("id", "session_id", "sessionId", "model")
        if (value := decoded.get(key)) is not None
    }
    for item in raw_messages:
        if not isinstance(item, Mapping):
            continue
        event = dict(inherited)
        event.update(item)
        yield event


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
    metadata: dict[str, Any] = {"source": "gemini"}
    if event.get("id") is not None:
        metadata["native_message_id"] = str(event["id"])
    if event.get("model") is not None:
        metadata["model"] = str(event["model"])
    return NativeTranscriptMessage(
        role=role,
        content=content,
        created_at=_timestamp_from_event(event),
        metadata=metadata,
    )


def _role_from_event(event: Mapping[str, Any]) -> str | None:
    candidates = (
        event.get("role"),
        _nested(event, "message", "role"),
        event.get("author"),
        event.get("type"),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        role = str(candidate).strip().lower()
        if role in {"model", "gemini"}:
            return "assistant"
        if role == "function":
            return "tool"
        if role in {"user", "assistant", "system", "tool"}:
            return role
    return None


def _content_from_event(event: Mapping[str, Any]) -> str | None:
    candidates = (
        event.get("content"),
        event.get("text"),
        event.get("parts"),
        _nested(event, "message", "content"),
        _nested(event, "message", "text"),
        _nested(event, "message", "parts"),
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
        for key in ("text", "content", "value", "parts"):
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
    for key in ("session_id", "sessionId", "checkpoint_id", "uuid", "id"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _title_from_event(event: Mapping[str, Any]) -> str | None:
    for key in ("title", "name", "tag", "summary"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return _title_from_content(str(value))
    return None


def _model_from_event(event: Mapping[str, Any]) -> str | None:
    value = event.get("model")
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


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
        self.model: str | None = None
        self.message_count = 0
        self.roles: set[str] = set()
        try:
            self.updated_at = _mtime_timestamp(path)
        except OSError:
            self.updated_at = None

    def observe_event(self, event: Mapping[str, Any]) -> None:
        if self.native_session_id is None:
            self.native_session_id = _session_id_from_event(event)
        if self.title is None:
            self.title = _title_from_event(event)
        if self.model is None:
            self.model = _model_from_event(event)
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


def _title_from_content(content: str) -> str:
    title = " ".join(content.split())
    if len(title) > 60:
        title = title[:57].rstrip() + "..."
    return title or "Untitled Gemini session"


def _ref_id(path: Path, native_session_id: str, source_kind: str) -> str:
    digest = hashlib.sha256(
        f"{source_kind}:{path}:{native_session_id}".encode("utf-8")
    ).hexdigest()
    return f"native_gemini_{digest[:16]}"


def _path_from_ref(ref: NativeSessionRef) -> Path | None:
    path_value = ref.metadata.get("path") or ref.source
    if not path_value:
        return None
    path = Path(str(path_value)).expanduser()
    return path if path.exists() and path.is_file() else None


def _text_from_keys(data: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _project_id(workspace: str | None) -> str:
    return project_id_for_root(workspace or Path.cwd())


def _prompt_delivery_key(request: HarnessRequest) -> str:
    value = request.extra.get("native_prompt_idempotency_key")
    if value is not None and str(value).strip():
        return str(value).strip()
    return f"nprompt_{uuid.uuid4().hex}"


def project_hash_for_workspace(workspace: str | Path) -> str:
    """Return the best-effort Gemini project hash for a workspace path."""
    normalized = str(Path(workspace).expanduser().resolve())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _gemini_env(
    context: HarnessContext,
    *,
    api_mode: GigaChatApiMode,
    native_home: Path,
    model: str | None,
) -> dict[str, str]:
    extra = {
        "GOOGLE_GEMINI_BASE_URL": context.api_base_url(api_mode),
        "GEMINI_API_KEY": context.api_key or "0",
        "GEMINI_CLI_TRUST_WORKSPACE": "true",
        "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
        "GPT2GIGA_HARNESS_API_MODE": api_mode.value,
    }
    if model is not None:
        extra["GEMINI_MODEL"] = model
        extra["GEMINI_CLI_CUSTOM_HEADERS"] = gemini_cli_custom_headers(
            context,
            model,
        )
    return build_safe_env(context, home=str(native_home), extra=extra)


def _write_gemini_settings(home: Path) -> str:
    return write_startup_config(
        "gemini-cli",
        home,
        {"security": {"auth": {"selectedType": "gemini-api-key"}}},
    )


def _run_list_sessions(
    command: tuple[str, ...],
    env: Mapping[str, str],
    cwd: str | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=LIST_SESSIONS_TIMEOUT_SECONDS,
        check=False,
    )


def _run_capability_probe(
    command: tuple[str, ...],
    env: Mapping[str, str],
    cwd: str | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=CAPABILITY_PROBE_TIMEOUT_SECONDS,
        check=False,
    )


def _mtime_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
