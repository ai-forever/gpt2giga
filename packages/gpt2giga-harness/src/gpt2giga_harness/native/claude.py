"""Claude Code native session discovery and command planning."""

from __future__ import annotations

import hashlib
import json
import re
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
from gpt2giga_harness.harnesses.claude_code import claude_code_custom_headers
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

CLAUDE_HARNESS_ID = "claude-code"
MANAGED_SESSION_PREFIX = "gpt2giga"
MODE_TO_PERMISSION = {
    "plan": "plan",
    "read": "plan",
    "edit": "default",
}


class ClaudeNativeHistoryConnector(NativeHistoryConnector):
    """Discover Claude Code native sessions and plan native commands."""

    harness_id = CLAUDE_HARNESS_ID
    requires_proxy_preflight = True

    def __init__(
        self,
        *,
        data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
        external_claude_home: str | Path | None = None,
        executable: str | None = None,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.external_claude_home = (
            Path(external_claude_home).expanduser()
            if external_claude_home is not None
            else Path.home() / ".claude"
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
        """Discover managed Claude refs first, then external refs when requested."""
        project_id = _project_id(workspace)
        managed = self.snapshot_store.reconcile(
            self._discover_source(
                source_root=self.managed_home(project_id),
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
        return tuple(_iter_session_messages(path, max_messages=max_messages))

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return all parseable Claude messages for normalized import."""
        path = _path_from_ref(ref)
        if path is None:
            return ()
        return tuple(_iter_session_messages(path, max_messages=None))

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Plan a native interactive `claude -n <name>` command."""
        source_workspace = native_source_workspace(request)
        project_id = _project_id(source_workspace)
        native_home = self.managed_home(project_id)
        known_sources = tuple(str(path) for path in _session_files(native_home))
        native_home.mkdir(parents=True, exist_ok=True)
        tool_config_hash = _write_claude_settings(
            native_home,
            workspace=request.workspace,
        )
        session_name = _managed_session_name(request, project_id)
        permission_mode = MODE_TO_PERMISSION.get(
            request.mode,
            MODE_TO_PERMISSION["plan"],
        )
        permission = native_permission_metadata(
            requested_mode=request.mode,
            cli_control="--permission-mode",
            cli_value=permission_mode,
            read_only=permission_mode == "plan",
        )
        command = [
            *self._executable_argv(),
            "--permission-mode",
            permission_mode,
            "-n",
            session_name,
        ]
        model = request.model or context.default_model
        if model:
            command.extend(["--model", model])
        command.extend(cli_args_from_attachments(request))
        prompt = prompt_with_attachments(request).strip()
        if prompt:
            command.append(prompt)
        env = _claude_env(
            context,
            api_mode=request.api_mode,
            native_home=native_home,
            model=model,
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
                "session_name": session_name,
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
        """Plan `claude --resume <name>` for a managed native session."""
        if ref.status is not NativeSessionStatus.MANAGED_NATIVE:
            raise ValueError("Only managed Claude native sessions can be resumed")
        if not ref.native_session_id:
            raise ValueError("Claude native session name is required for resume")
        snapshot = validate_resume_snapshot(ref, harness_id=self.harness_id)
        if not snapshot.native_home:
            raise ValueError("Native resume snapshot is missing its managed home")
        native_home = Path(snapshot.native_home).expanduser()
        api_mode = GigaChatApiMode(snapshot.api_mode)
        native_home.mkdir(parents=True, exist_ok=True)
        _write_claude_settings(
            native_home,
            workspace=snapshot.effective_workspace or ref.workspace,
        )
        env = _claude_env(
            context,
            api_mode=api_mode,
            native_home=native_home,
            model=snapshot.model,
        )
        permission_mode = MODE_TO_PERMISSION.get(
            snapshot.permission_mode,
            MODE_TO_PERMISSION["plan"],
        )
        permission = native_permission_metadata(
            requested_mode=snapshot.permission_mode,
            cli_control="--permission-mode",
            cli_value=permission_mode,
            read_only=permission_mode == "plan",
        )
        return NativeCommandPlan(
            command=(
                *self._executable_argv(),
                "--permission-mode",
                permission_mode,
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
        """Persist a successful Claude native start for later discovery."""
        native_session_id = str(plan.metadata.get("session_name") or "").strip() or None
        self.snapshot_store.record_start(
            plan,
            native_session_id=native_session_id,
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

    def _executable_argv(self) -> tuple[str, ...]:
        if self.executable is not None:
            return (self.executable,)
        resolution = self.executable_resolver.resolve(self.harness_id, "claude")
        return resolution.command or ("claude",)


def _write_claude_settings(home: Path, *, workspace: str | None) -> str:
    startup: dict[str, Any] = {"hasCompletedOnboarding": True}
    if workspace:
        trusted_workspace = str(Path(workspace).expanduser().resolve())
        startup["projects"] = {trusted_workspace: {"hasTrustDialogAccepted": True}}
    return write_startup_config("claude-code", home, startup)


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
            paths.update(
                path
                for path in root.rglob("*.jsonl")
                if path.is_file() and "subagents" not in path.parts
            )
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


def _iter_session_messages(
    path: Path,
    *,
    max_messages: int | None,
) -> Iterable[NativeTranscriptMessage]:
    indexed_messages: list[tuple[NativeTranscriptMessage, int]] = []
    for message in _iter_messages(path, max_messages=None):
        indexed_messages.append((message, len(indexed_messages)))
    for subagent_path in _subagent_session_files(path):
        context = _subagent_context(subagent_path)
        if context is None:
            continue
        for message in _iter_messages(subagent_path, max_messages=None):
            nested_message = _subagent_tool_message(message, context=context)
            if nested_message is not None:
                indexed_messages.append((nested_message, len(indexed_messages)))
    indexed_messages.sort(
        key=lambda item: (
            item[0].created_at is None,
            item[0].created_at or "",
            item[1],
        )
    )
    for index, (message, _) in enumerate(indexed_messages):
        if max_messages is not None and index >= max_messages:
            return
        yield message


def _subagent_session_files(path: Path) -> tuple[Path, ...]:
    subagents_dir = path.parent / path.stem / "subagents"
    try:
        if not subagents_dir.is_dir():
            return ()
        return tuple(sorted(subagents_dir.glob("*.jsonl")))
    except OSError:
        return ()


def _subagent_context(path: Path) -> Mapping[str, Any] | None:
    metadata_path = path.with_suffix(".meta.json")
    try:
        decoded = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, Mapping):
        return None
    parent_tool_call_id = decoded.get("toolUseId")
    if parent_tool_call_id is None or not str(parent_tool_call_id).strip():
        return None
    return {
        "parent_tool_call_id": str(parent_tool_call_id).strip(),
        "subagent_id": path.stem,
        "subagent_type": str(decoded.get("agentType") or "subagent").strip(),
        "subagent_description": str(decoded.get("description") or "").strip(),
        "subagent_depth": decoded.get("spawnDepth"),
    }


def _subagent_tool_message(
    message: NativeTranscriptMessage,
    *,
    context: Mapping[str, Any],
) -> NativeTranscriptMessage | None:
    tool_calls = message.metadata.get("tool_calls")
    tool_results = message.metadata.get("tool_results")
    if not tool_calls and not tool_results:
        return None
    metadata = dict(message.metadata)
    native_message_id = metadata.get("native_message_id")
    if native_message_id is not None:
        metadata["native_message_id"] = f"{context['subagent_id']}:{native_message_id}"
    for key in (
        "parent_tool_call_id",
        "subagent_id",
        "subagent_type",
        "subagent_description",
        "subagent_depth",
    ):
        metadata[key] = context.get(key)
    if tool_calls:
        metadata["tool_calls"] = [{**tool_call, **context} for tool_call in tool_calls]
    if tool_results:
        metadata["tool_results"] = [
            {**tool_result, **context} for tool_result in tool_results
        ]
    return NativeTranscriptMessage(
        role=message.role,
        content="",
        created_at=message.created_at,
        metadata=metadata,
    )


def _message_from_event(event: Mapping[str, Any]) -> NativeTranscriptMessage | None:
    role = _role_from_event(event)
    content = _content_from_event(event) or ""
    tool_calls, tool_results = _tool_records_from_event(event)
    if role is None or (not content and not tool_calls and not tool_results):
        return None
    metadata = {"source": "claude"}
    native_message_id = event.get("uuid")
    if native_message_id is not None and str(native_message_id).strip():
        metadata["native_message_id"] = str(native_message_id).strip()
    if tool_calls:
        metadata["tool_calls"] = tool_calls
    if tool_results:
        metadata["tool_results"] = tool_results
        if role == "user" and not content:
            role = "tool"
    return NativeTranscriptMessage(
        role=role,
        content=content,
        created_at=_timestamp_from_event(event),
        metadata=metadata,
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
    candidates = _content_candidates(event)
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
        if _tool_call_from_block(value, fallback_id=None) is not None:
            return None
        if _tool_result_from_block(value, fallback_id=None) is not None:
            return None
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


def _content_candidates(event: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _nested(event, "message", "content"),
        _nested(event, "message", "text"),
        event.get("content"),
        event.get("text"),
    )


def _tool_records_from_event(
    event: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    content = next(
        (
            candidate
            for candidate in _content_candidates(event)
            if candidate is not None
        ),
        None,
    )
    blocks = content if isinstance(content, list) else [content]
    fallback_id = _optional_tool_id(event.get("tools_state_id"))
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        block_fallback_id = fallback_id
        if fallback_id is not None and len(blocks) > 1:
            block_fallback_id = f"{fallback_id}:{index}"
        call = _tool_call_from_block(block, fallback_id=block_fallback_id)
        if call is not None:
            calls.append(call)
        result = _tool_result_from_block(block, fallback_id=block_fallback_id)
        if result is not None:
            results.append(result)
    return calls, results


def _tool_call_from_block(
    block: Mapping[str, Any],
    *,
    fallback_id: str | None,
) -> dict[str, Any] | None:
    if block.get("type") == "tool_use":
        tool_call_id = _optional_tool_id(block.get("id")) or fallback_id or "tool-call"
        return {
            "tool_call_id": tool_call_id,
            "name": str(block.get("name") or "tool"),
            "arguments": block.get("input"),
            "status": "running",
        }
    function_call = block.get("function_call")
    if not isinstance(function_call, Mapping):
        return None
    tool_call_id = _optional_tool_id(block.get("id")) or fallback_id or "tool-call"
    return {
        "tool_call_id": tool_call_id,
        "name": str(function_call.get("name") or "tool"),
        "arguments": function_call.get("arguments"),
        "status": "running",
    }


def _tool_result_from_block(
    block: Mapping[str, Any],
    *,
    fallback_id: str | None,
) -> dict[str, Any] | None:
    if block.get("type") == "tool_result":
        tool_call_id = (
            _optional_tool_id(block.get("tool_use_id")) or fallback_id or "tool-call"
        )
        return {
            "tool_call_id": tool_call_id,
            "result": block.get("content"),
            "status": "failed" if block.get("is_error") else "completed",
        }
    function_result = block.get("function_result")
    if not isinstance(function_result, Mapping):
        return None
    tool_call_id = _optional_tool_id(block.get("id")) or fallback_id or "tool-call"
    return {
        "tool_call_id": tool_call_id,
        "name": str(function_result.get("name") or "tool"),
        "result": function_result.get("result"),
        "status": "completed",
    }


def _optional_tool_id(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


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
        event.get("customTitle") if event.get("type") == "custom-title" else None,
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


def _project_id(workspace: str | None) -> str:
    return project_id_for_root(workspace or Path.cwd())


def _claude_env(
    context: HarnessContext,
    *,
    api_mode: GigaChatApiMode,
    native_home: Path,
    model: str | None,
) -> dict[str, str]:
    extra = {
        "ANTHROPIC_BASE_URL": context.api_base_url(api_mode),
        "ANTHROPIC_AUTH_TOKEN": context.api_key or "0",
        "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
        "GPT2GIGA_HARNESS_API_MODE": api_mode.value,
    }
    if model is not None:
        extra["ANTHROPIC_CUSTOM_HEADERS"] = claude_code_custom_headers(
            context,
            model,
        )
    return build_safe_env(
        context,
        home=str(native_home),
        extra=extra,
    )


def _mtime_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
