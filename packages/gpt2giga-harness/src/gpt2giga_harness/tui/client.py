"""Typed application clients used by the built-in Textual presentation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import threading
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)

import anyio

from gpt2giga_harness.attachments import (
    AttachmentLimits,
    FilesystemAttachmentStore,
    attachment_to_dict,
    limits_from_project_settings,
)
from gpt2giga_harness.attachments.limits import normalize_workspace_file
from gpt2giga_harness.application import SessionApplicationService
from gpt2giga_harness.claude_handoff import (
    ClaudeHandoffAction,
    ClaudeHandoffLaunchMode,
    claude_handoff_plan_to_dict,
)
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.environments import (
    EnvironmentCaptureError,
    EnvironmentSnapshot,
    GitEnvironmentProvider,
)
from gpt2giga_harness.environment_actions import (
    EnvironmentCommitError,
    EnvironmentCommitService,
    GovernedEnvironmentCommitService,
)
from gpt2giga_harness.github_environments import (
    GitHubEnvironmentService,
    GitHubEnvironmentSnapshot,
)
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.project import (
    HarnessProject,
    load_project_config,
    load_project_state,
    resolve_project,
    update_project_state,
)
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import PolicyEngine, approval_request_to_dict
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.session_exports import write_session_export
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessRun,
    HarnessSession,
    HarnessStoredEvent,
    run_to_dict,
    session_to_dict,
)
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.settings import HarnessSettingsStore
from gpt2giga_harness.structured_sessions import StructuredTurnInput
from gpt2giga_harness.types import availability_to_dict, spec_to_dict
from gpt2giga_harness.workbench_execution import workbench_transport_projection
from gpt2giga_harness.workbench_protocol import (
    WorkbenchBackbone,
    WorkbenchStatePage,
    workbench_state_page_from_dict,
)
from gpt2giga_harness.workbench_resources import (
    PreferenceSnapshot,
    ProcessProjection,
    TaskProjection,
    WorkbenchPreferenceStore,
    WorkbenchResourceService,
    WorkbenchResourceSnapshot,
    preference_snapshot_from_dict,
    process_binding,
    resource_snapshot_from_dict,
    task_binding,
)
from gpt2giga_harness.workspace import workspace_tree
from gpt2giga_harness.worktrees import run_diff_response

MAX_PROJECTS = 50
MAX_SESSIONS = 100
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_DISPLAY_CHARS = 512
MAX_TIMELINE_EVENTS = 100
MAX_TIMELINE_CHARS = 64 * 1024
MAX_FILE_CANDIDATES = 20
MAX_FILE_PREVIEW_CHARS = 8 * 1024
MAX_DIFF_PREVIEW_CHARS = 32 * 1024
MAX_NATIVE_SCROLLBACK_CHARS = 64 * 1024
MAX_NATIVE_INPUT_CHARS = 8 * 1024
HTTP_TIMEOUT_SECONDS = 10.0
RUN_START_TIMEOUT_SECONDS = 5.0
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BIDI_CONTROL_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_TERMINAL_SEQUENCE_RE = re.compile(
    r"\x1b(?:"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)?|"
    r"P.*?(?:\x1b\\|$)|"
    r"\[[0-?]*[ -/]*[@-~]|"
    r"[@-_]"
    r")",
    re.DOTALL,
)
_FULLSCREEN_TERMINAL_RE = re.compile(
    r"\x1b(?:"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)?|"
    r"P.*?(?:\x1b\\|$)|"
    r"\[[0-9;?]*(?:[ABCDEFGHJKSTf]|[hl])"
    r")",
    re.DOTALL,
)
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "canceled"})
_TERMINAL_PROCESS_STATUSES = frozenset(
    {"exited", "stopped", "failed", "timed_out", "interrupted", "unknown"}
)


class WorkbenchClientError(RuntimeError):
    """Bounded client failure safe for presentation."""


@dataclass(frozen=True)
class ProjectSummary:
    """Bounded project navigation item."""

    id: str
    name: str
    root: str
    git_branch: str | None
    session_count: int


@dataclass(frozen=True)
class SessionSummary:
    """Bounded session navigation item."""

    id: str
    title: str
    updated_at: str
    workspace: str | None
    harness_id: str
    model: str | None
    mode: str
    archived: bool = False
    project_id: str | None = None
    preview: str = ""
    native_authority: str | None = None
    native_session_id: str | None = None
    native_operation: str | None = None
    revision: str = ""
    generation: int = 0
    lease: str | None = None


@dataclass(frozen=True)
class SessionActionBinding:
    """Exact session state presented before a navigation mutation."""

    session_id: str
    revision: str
    generation: int
    lease: str | None
    idempotency_key: str


@dataclass(frozen=True)
class SessionPreview:
    """Bounded session preview and transcript-search result."""

    session: SessionSummary
    transcript: tuple[str, ...]
    match_count: int
    truncated: bool


@dataclass(frozen=True)
class SessionExport:
    """Sanitized local export created by session application authority."""

    session_id: str
    path: str
    message_count: int


@dataclass(frozen=True)
class HarnessSummary:
    """Content-free Harness availability projection."""

    id: str
    title: str
    availability: str
    reason: str
    default_transport: str


@dataclass(frozen=True)
class ReadinessSummary:
    """Selected provider/Harness/model/transport readiness."""

    status: str
    provider: str
    provider_status: str
    harness_id: str
    harness_status: str
    model: str | None
    transport: str
    findings: tuple[str, ...]


@dataclass(frozen=True)
class IntegrationSummary:
    """Content-free durable integration inventory status."""

    status: str
    catalog_count: int
    flow_count: int
    verified_count: int


@dataclass(frozen=True)
class EnvironmentSummary:
    """Bounded presentation of one canonical local Git environment."""

    status: str
    branch: str | None = None
    detached: bool = False
    head: str | None = None
    worktree_root: str | None = None
    staged_count: int = 0
    unstaged_count: int = 0
    untracked_count: int = 0
    additions: int = 0
    deletions: int = 0
    commit_ready: bool = False
    push_ready: bool = False
    push_blocker: str | None = None
    captured_at: str | None = None
    issue_pr_status: str = "not_connected"
    github_status: str = "unavailable"
    github_repository: str | None = None
    github_checks: str = "unavailable"
    github_actions: str = "unavailable"
    github_run_count: int = 0
    github_checked_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EnvironmentCommitPreviewSummary:
    """Exact author/message and immutable Git state shown before approval."""

    id: str
    branch: str
    head: str | None
    diff_sha256: str
    staged_count: int
    message: str
    author_name: str
    author_email: str
    worktree_root: str


@dataclass(frozen=True)
class EnvironmentCommitApplySummary:
    """Governed commit outcome for either approval or exact completion."""

    preview: EnvironmentCommitPreviewSummary
    approval: ApprovalSummary | None = None
    commit_head: str | None = None
    idempotent_replay: bool = False


@dataclass(frozen=True)
class NavigationSnapshot:
    """One authoritative, presentation-bounded TUI resnapshot."""

    transport_mode: str
    projects: tuple[ProjectSummary, ...]
    project: ProjectSummary
    sessions: tuple[SessionSummary, ...]
    selected_session_id: str | None
    harnesses: tuple[HarnessSummary, ...]
    readiness: ReadinessSummary
    integrations: IntegrationSummary = IntegrationSummary("unknown", 0, 0, 0)
    environment: EnvironmentSummary = EnvironmentSummary("unavailable")


@dataclass(frozen=True)
class RunActionBinding:
    """Exact mutable run identity presented before one user action."""

    session_id: str
    run_id: str
    revision: str
    generation: int
    idempotency_key: str


@dataclass(frozen=True)
class TimelineEvent:
    """Bounded normalized event suitable for terminal rendering."""

    id: str
    type: str
    message: str
    delta: str | None = None
    tool_name: str | None = None
    approval_id: str | None = None
    input_id: str | None = None
    category: str = "status"
    stream: str | None = None
    artifact_id: str | None = None
    artifact_kind: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ApprovalSummary:
    """Redaction-safe pending approval projected into the selected run."""

    id: str
    action: str
    reason: str
    status: str
    enforcement: str = "unknown"
    enforcement_owner: str = "unknown"
    policy_source: str = "unknown"
    executable: str = "not declared"
    tool: str = "not declared"
    cwd: str = "not declared"
    paths: tuple[str, ...] = ()
    network: str = "not declared"
    mutation_class: str = "unknown"
    decision_scopes: tuple[str, ...] = ("allow_once", "deny")
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunSnapshot:
    """Bounded authoritative run state shared by in-process and attach modes."""

    binding: RunActionBinding
    status: str
    events: tuple[TimelineEvent, ...]
    cursor: str | None
    pending_approvals: tuple[ApprovalSummary, ...] = ()
    resnapshot_reason: str | None = None
    execution_transport: str | None = None
    native_process_id: str | None = None

    @property
    def terminal(self) -> bool:
        """Return whether the durable run reached a terminal state."""
        return self.status in _TERMINAL_RUN_STATUSES


@dataclass(frozen=True)
class FileCandidate:
    """Safe bounded project file candidate and preview."""

    path: str
    name: str
    mime_type: str
    kind: str
    size_bytes: int
    preview: str
    preview_status: str


@dataclass(frozen=True)
class AttachmentSummary:
    """One backend-owned attachment selected for the next turn."""

    id: str
    path: str
    mime_type: str
    kind: str
    size_bytes: int


@dataclass(frozen=True)
class ArtifactSummary:
    """Content-free retained artifact inventory item."""

    type: str
    byte_count: int | None


@dataclass(frozen=True)
class RunInspection:
    """Bounded authoritative diff, evidence, and recovery projection."""

    run_id: str
    status: str
    revision: str
    provider_continuity: str
    harness_status: str
    recovery: str
    artifacts: tuple[ArtifactSummary, ...]
    diff: str
    diff_truncated: bool
    changed_files: tuple[str, ...]
    untracked_files: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class HandoffPreview:
    """Exact external handoff boundary shown before leaving the TUI."""

    kind: str
    status: str
    target: str
    continuity: str
    observability: tuple[str, ...]
    instruction: str
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeTerminalSnapshot:
    """Bounded, terminal-neutral native-process projection."""

    process_id: str
    session_id: str
    run_id: str
    harness_id: str
    transport: str
    status: str
    cursor: int
    output: str = ""
    output_truncated: bool = False
    exit_code: int | None = None
    handoff_required: bool = False

    @property
    def terminal(self) -> bool:
        """Return whether the native process reached a terminal state."""
        return self.status in _TERMINAL_PROCESS_STATUSES


class WorkbenchClient(Protocol):
    """Thin asynchronous client contract shared by both transports."""

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
        """Load one authoritative navigation snapshot."""

    async def workbench_state(
        self,
        *,
        cursor: str | None = None,
        limit: int = 32,
    ) -> WorkbenchStatePage:
        """Load provider-neutral projections and ordered reconnect deltas."""

    async def resources(
        self, session_id: str | None = None
    ) -> WorkbenchResourceSnapshot:
        """Load bounded tasks, processes, usage, preferences, and inventory."""

    async def cancel_task(self, task: TaskProjection) -> TaskProjection:
        """Cancel one exact task owner, lease, generation, and child identity."""

    async def stop_process(self, process: ProcessProjection) -> ProcessProjection:
        """Stop one exact application-owned process."""

    async def save_preferences(
        self, values: Mapping[str, Any], *, expected_revision: str
    ) -> PreferenceSnapshot:
        """Persist one exact private Workbench preference revision."""

    async def preview_environment_commit(
        self,
        workspace: str,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> EnvironmentCommitPreviewSummary:
        """Create one exact local commit preview."""

    async def apply_environment_commit(
        self,
        preview_id: str,
        *,
        workspace: str,
        session_id: str | None = None,
    ) -> EnvironmentCommitApplySummary:
        """Request approval or apply the exact commit once."""

    async def decide_environment_approval(
        self, approval_id: str, decision: str
    ) -> None:
        """Decide one hash-bound environment approval."""

    async def create_session(
        self,
        workspace: str,
        *,
        title: str | None = None,
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
    ) -> SessionSummary:
        """Create a session using explicit intent plus backend-owned defaults."""

    async def remember_session(self, workspace: str, session_id: str) -> None:
        """Persist the selected session through the existing project state."""

    async def search_sessions(
        self,
        query: str = "",
        *,
        provider: str | None = None,
        project: str | None = None,
        include_archived: bool = True,
    ) -> tuple[SessionSummary, ...]:
        """Search bounded session projections across projects and providers."""

    async def preview_session(
        self, session_id: str, *, transcript_query: str = ""
    ) -> SessionPreview:
        """Preview one session without implying filesystem restoration."""

    async def rename_session(
        self, binding: SessionActionBinding, title: str
    ) -> SessionSummary:
        """Rename one exact session revision."""

    async def archive_session(
        self, binding: SessionActionBinding, *, archived: bool = True
    ) -> SessionSummary:
        """Archive or restore one exact session revision."""

    async def delete_session(self, binding: SessionActionBinding) -> None:
        """Delete one exact session revision after confirmation."""

    async def fork_session(self, binding: SessionActionBinding) -> SessionSummary:
        """Fork one exact Harness session without claiming native resume."""

    async def export_session(self, binding: SessionActionBinding) -> SessionExport:
        """Create a sanitized local transcript export."""

    async def submit_turn(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
        attachment_ids: tuple[str, ...] = (),
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
        capability: str | None = None,
        execution_transport: str | None = None,
        native_session_id: str | None = None,
        native_session_operation: str | None = None,
    ) -> RunSnapshot:
        """Submit one typed turn without invoking the Harness CLI."""

    async def snapshot_run(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
    ) -> RunSnapshot:
        """Read a bounded authoritative incremental run snapshot."""

    async def latest_run(self, session_id: str) -> RunSnapshot | None:
        """Return the newest retained run for session reconnect, if any."""

    async def cancel_run(self, binding: RunActionBinding) -> RunSnapshot:
        """Request cancellation for the exact presented run generation."""

    async def fork_run(self, binding: RunActionBinding) -> SessionSummary:
        """Fork the exact presented run into a new Harness session."""

    async def decide_approval(
        self,
        binding: RunActionBinding,
        approval_id: str,
        decision: str,
    ) -> RunSnapshot:
        """Decide one pending approval bound to the presented run."""

    async def steer_run(
        self,
        binding: RunActionBinding,
        content: str,
        *,
        idempotency_key: str,
    ) -> RunSnapshot:
        """Steer the exact active structured turn where supported."""

    async def answer_input(
        self,
        binding: RunActionBinding,
        input_id: str,
        answer: str,
    ) -> RunSnapshot:
        """Answer one exact provider input request where supported."""

    async def search_files(
        self, session_id: str, query: str
    ) -> tuple[FileCandidate, ...]:
        """Return bounded safe project files with neutralized previews."""

    async def attach_file(self, session_id: str, path: str) -> AttachmentSummary:
        """Create one backend-owned workspace attachment reference."""

    async def inspect_run(self, run_id: str) -> RunInspection:
        """Return bounded diff, evidence, provider, and recovery state."""

    async def provider_handoff(self, session_id: str) -> HandoffPreview:
        """Preview the exact provider-owned target without launching it."""

    async def web_handoff(self, session_id: str) -> HandoffPreview:
        """Preview the exact Web target without silently starting a server."""

    async def start_native_terminal(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
        attachment_ids: tuple[str, ...] = (),
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
    ) -> NativeTerminalSnapshot:
        """Start native-terminal execution through an application authority."""

    async def snapshot_native_terminal(
        self, process_id: str, *, cursor: int = 0
    ) -> NativeTerminalSnapshot:
        """Read bounded native output after an exact cursor."""

    async def status_native_terminal(self, process_id: str) -> NativeTerminalSnapshot:
        """Read authoritative native-process lifecycle state."""

    async def send_native_terminal_input(
        self, process_id: str, data: str, *, submit: bool = False
    ) -> NativeTerminalSnapshot:
        """Send reviewed text input to an exact native process."""

    async def resize_native_terminal(
        self, process_id: str, *, rows: int, columns: int
    ) -> NativeTerminalSnapshot:
        """Resize an exact application-owned native process."""

    async def stop_native_terminal(self, process_id: str) -> NativeTerminalSnapshot:
        """Stop an exact application-owned native process."""


class InProcessWorkbenchClient:
    """Use existing application services without FastAPI, uvicorn, or a daemon."""

    transport_mode = "in_process"

    def __init__(
        self,
        config: HarnessConfig,
        *,
        registry: HarnessRegistry | None = None,
        store: FilesystemHarnessSessionStore | None = None,
        github_environment_service: GitHubEnvironmentService | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or create_default_registry()
        self.store = store or FilesystemHarnessSessionStore(config.data_dir)
        runner = HarnessSessionRunner(
            registry=self.registry,
            config=config,
            store=self.store,
        )
        self.settings_store = HarnessSettingsStore(config.data_dir, config)
        self.runtime_store = RuntimeCoordinationStore(config.data_dir)
        try:
            self.environment_commit_service = EnvironmentCommitService(config.data_dir)
        except EnvironmentCommitError:
            self.environment_commit_service = None
        self.governed_environment_commit_service = (
            GovernedEnvironmentCommitService(
                self.environment_commit_service,
                self.runtime_store,
                PolicyEngine(self.runtime_store),
            )
            if self.environment_commit_service is not None
            else None
        )
        self.attachment_store = FilesystemAttachmentStore(config.data_dir)
        self.integration_service = IntegrationFlowService(config.data_dir)
        self.github_environment_service = (
            github_environment_service or GitHubEnvironmentService()
        )
        self.resource_service = WorkbenchResourceService(
            session_store=self.store,
            runtime_store=self.runtime_store,
            preference_store=WorkbenchPreferenceStore(config.data_dir),
            integration_service=self.integration_service,
        )
        self.sessions = SessionApplicationService(
            runner=runner,
            settings_store=self.settings_store,
            runtime_store=self.runtime_store,
        )
        self._active_runs: dict[str, tuple[asyncio.Task[Any], threading.Event]] = {}
        self._submitted_turns: dict[str, str] = {}
        self._session_mutations: dict[str, SessionSummary | SessionExport | None] = {}
        self.workbench_backbone = WorkbenchBackbone()

    async def workbench_state(
        self,
        *,
        cursor: str | None = None,
        limit: int = 32,
    ) -> WorkbenchStatePage:
        """Read the same bounded backbone contract used by attach mode."""
        return self.workbench_backbone.read(cursor, limit=limit)

    async def preview_environment_commit(
        self,
        workspace: str,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> EnvironmentCommitPreviewSummary:
        if self.environment_commit_service is None:
            raise WorkbenchClientError("Git commit action is unavailable")
        preview = await asyncio.to_thread(
            self.environment_commit_service.preview,
            workspace,
            message=message,
            author_name=author_name,
            author_email=author_email,
        )
        return _environment_commit_preview_summary(preview.to_dict())

    async def apply_environment_commit(
        self,
        preview_id: str,
        *,
        workspace: str,
        session_id: str | None = None,
    ) -> EnvironmentCommitApplySummary:
        if (
            self.environment_commit_service is None
            or self.governed_environment_commit_service is None
        ):
            raise WorkbenchClientError("Git commit action is unavailable")
        preview = self.environment_commit_service.get_preview(preview_id)
        resolved = Path(workspace).expanduser().resolve()
        root = Path(preview.worktree_root).resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise WorkbenchClientError("workspace changed after commit preview")
        project_id = preview.scope_id
        if session_id is not None:
            session = self.store.get_session(session_id)
            project_id = str(session.metadata.get("project_id") or "") or project_id
        try:
            outcome = await asyncio.to_thread(
                self.governed_environment_commit_service.apply_or_request,
                preview_id,
                project_id=project_id,
                session_id=session_id,
            )
        except RuntimeError as exc:
            raise WorkbenchClientError(str(exc)) from exc
        return _environment_commit_outcome_summary(outcome)

    async def decide_environment_approval(
        self, approval_id: str, decision: str
    ) -> None:
        self.sessions.decide_approval(approval_id, decision)

    async def resources(
        self, session_id: str | None = None
    ) -> WorkbenchResourceSnapshot:
        """Read resources through the same application authority as attach mode."""
        return self.resource_service.snapshot(session_id)

    async def cancel_task(self, task: TaskProjection) -> TaskProjection:
        """Request exact durable task cancellation."""
        return self.resource_service.cancel_task(task_binding(task))

    async def stop_process(self, process: ProcessProjection) -> ProcessProjection:
        """Fail closed because in-process mode does not own native supervision."""
        self.resource_service.validate_process(process_binding(process))
        raise WorkbenchClientError(
            "native process control requires attach mode; ownership is server-side"
        )

    async def save_preferences(
        self, values: Mapping[str, Any], *, expected_revision: str
    ) -> PreferenceSnapshot:
        """Persist private Workbench-only preferences."""
        return self.resource_service.save_preferences(
            values, expected_revision=expected_revision
        )

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
        if workspace is None and selected_session_id is not None:
            workspace = self.store.get_session(selected_session_id).workspace
        project = resolve_project(workspace, data_dir=self.config.data_dir)
        sessions = self.store.list_sessions(
            workspace=project.root,
            include_archived=False,
            limit=MAX_SESSIONS,
        )
        selected_id = _selected_session_id(
            sessions,
            selected_session_id or load_project_state(project).last_selected_session,
        )
        selected = next(
            (item for item in sessions if item.id == selected_id),
            None,
        )
        harnesses = tuple(
            _harness_summary(
                spec_to_dict(harness.spec()),
                availability_to_dict(harness.availability()),
                workbench_transport_projection(harness),
            )
            for harness in self.registry.list()
        )
        readiness = self._readiness(project, selected, harnesses)
        environment = await asyncio.to_thread(
            _capture_environment_summary,
            project.root,
            self.github_environment_service,
        )
        projects = self._projects(project)
        project_summary = next(item for item in projects if item.id == project.id)
        return NavigationSnapshot(
            transport_mode=self.transport_mode,
            projects=projects,
            project=project_summary,
            sessions=tuple(_session_summary(item) for item in sessions),
            selected_session_id=selected_id,
            harnesses=harnesses,
            readiness=readiness,
            integrations=_in_process_integration_summary(self.integration_service),
            environment=environment,
        )

    async def create_session(
        self,
        workspace: str,
        *,
        title: str | None = None,
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
    ) -> SessionSummary:
        payload = {
            "workspace": workspace,
            **({"title": title} if title else {}),
            **({"harness_id": harness_id} if harness_id else {}),
            **({"model": model} if model else {}),
            **({"api_mode": api_mode} if api_mode else {}),
            **({"mode": mode} if mode else {}),
        }
        session = self.sessions.create_session(
            payload,
            validate_harness=harness_id is not None,
        )
        await self.remember_session(workspace, session.id)
        return _session_summary(session)

    async def remember_session(self, workspace: str, session_id: str) -> None:
        project = resolve_project(
            workspace,
            data_dir=self.config.data_dir,
            load_config_name=False,
        )
        update_project_state(project, {"last_selected_session": session_id})

    async def search_sessions(
        self,
        query: str = "",
        *,
        provider: str | None = None,
        project: str | None = None,
        include_archived: bool = True,
    ) -> tuple[SessionSummary, ...]:
        sessions = self.store.list_sessions(
            project_id=project,
            harness_id=provider,
            q=query.strip() or None,
            include_archived=include_archived,
            limit=MAX_SESSIONS,
        )
        return tuple(_session_summary(item, self.store) for item in sessions)

    async def preview_session(
        self, session_id: str, *, transcript_query: str = ""
    ) -> SessionPreview:
        session = self.store.get_session(session_id)
        messages = self.store.list_messages(session_id)
        needle = transcript_query.strip().casefold()
        matches = [
            item for item in messages if not needle or needle in item.content.casefold()
        ]
        selected = matches[-100:]
        return SessionPreview(
            session=_session_summary(session, self.store),
            transcript=tuple(_message_preview(item) for item in selected),
            match_count=len(matches),
            truncated=len(matches) > len(selected),
        )

    async def rename_session(
        self, binding: SessionActionBinding, title: str
    ) -> SessionSummary:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionSummary):
            return cached
        self._validate_session_binding(binding)
        updated = self.store.update_session_if_revision(
            binding.session_id,
            binding.revision,
            title=_required_content(title, "session title"),
        )
        if updated is None:
            raise WorkbenchClientError(
                "session changed; authoritative resnapshot required"
            )
        result = _session_summary(updated, self.store)
        self._session_mutations[binding.idempotency_key] = result
        return result

    async def archive_session(
        self, binding: SessionActionBinding, *, archived: bool = True
    ) -> SessionSummary:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionSummary):
            return cached
        self._validate_session_binding(binding)
        updated = self.store.update_session_if_revision(
            binding.session_id,
            binding.revision,
            archived=archived,
        )
        if updated is None:
            raise WorkbenchClientError(
                "session changed; authoritative resnapshot required"
            )
        result = _session_summary(updated, self.store)
        self._session_mutations[binding.idempotency_key] = result
        return result

    async def delete_session(self, binding: SessionActionBinding) -> None:
        if binding.idempotency_key in self._session_mutations:
            return
        self._validate_session_binding(binding, require_idle=True)
        if not self.store.delete_session_if_revision(
            binding.session_id, binding.revision
        ):
            raise WorkbenchClientError(
                "session changed; authoritative resnapshot required"
            )
        self._session_mutations[binding.idempotency_key] = None

    async def fork_session(self, binding: SessionActionBinding) -> SessionSummary:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionSummary):
            return cached
        source = self._validate_session_binding(binding)
        source_summary = _session_summary(source, self.store)
        reference = {
            key: value
            for key, value in {
                "authority": source_summary.native_authority,
                "native_id": source_summary.native_session_id,
                "workspace": source.workspace,
                "operation": "fork",
            }.items()
            if value is not None
        }
        metadata = {
            **dict(source.metadata),
            "forked_from_session_id": source.id,
            "fork_semantics": "harness_replay",
            **({"native_session_reference": reference} if reference else {}),
        }
        metadata.pop("structured_session_link", None)
        fork = self.store.create_session(
            title=f"Fork: {source.title}",
            workspace=source.workspace,
            default_harness_id=source.default_harness_id,
            default_model=source.default_model,
            default_api_mode=source.default_api_mode,
            default_mode=source.default_mode,
            metadata=metadata,
        )
        for message in self.store.list_messages(source.id):
            self.store.append_message(
                replace(
                    message,
                    id=new_id("msg"),
                    session_id=fork.id,
                    run_id=None,
                    created_at=utc_now(),
                    metadata={
                        **dict(message.metadata),
                        "forked_from_message_id": message.id,
                    },
                )
            )
        result = _session_summary(fork, self.store)
        self._session_mutations[binding.idempotency_key] = result
        return result

    async def export_session(self, binding: SessionActionBinding) -> SessionExport:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionExport):
            return cached
        session = self._validate_session_binding(binding)
        messages = self.store.list_messages(session.id)
        body = _session_export_text(session, messages)
        path = write_session_export(Path(self.config.data_dir) / "exports", body)
        result = SessionExport(session.id, str(path), len(messages))
        self._session_mutations[binding.idempotency_key] = result
        return result

    def _validate_session_binding(
        self,
        binding: SessionActionBinding,
        *,
        require_idle: bool = False,
    ) -> HarnessSession:
        session = self.store.get_session(binding.session_id)
        summary = _session_summary(session, self.store)
        if (
            summary.revision != binding.revision
            or summary.generation != binding.generation
            or summary.lease != binding.lease
        ):
            raise WorkbenchClientError(
                "session changed; authoritative resnapshot required"
            )
        if require_idle and binding.lease is not None:
            raise WorkbenchClientError("active session lease blocks destructive action")
        return session

    async def submit_turn(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
        attachment_ids: tuple[str, ...] = (),
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
        capability: str | None = None,
        execution_transport: str | None = None,
        native_session_id: str | None = None,
        native_session_operation: str | None = None,
    ) -> RunSnapshot:
        prompt = _required_content(content, "turn content")
        key = _required_identity(idempotency_key, "idempotency key")
        previous_run_id = self._submitted_turns.get(key)
        if previous_run_id is not None:
            previous = self.sessions.get_run(previous_run_id)
            if previous.session_id != session_id:
                raise WorkbenchClientError("idempotency key belongs to another session")
            return await self.snapshot_run(previous.id)
        before = {run.id for run in self.store.list_runs(session_id)}
        cancel_event = threading.Event()
        payload: dict[str, Any] = {
            "prompt": prompt,
            "stream": True,
            "attachment_ids": list(_attachment_ids(attachment_ids)),
        }
        payload.update(
            {
                key: value
                for key, value in {
                    "harness_id": harness_id,
                    "model": model,
                    "api_mode": api_mode,
                    "mode": mode,
                    "capability": capability,
                    "execution_transport": execution_transport,
                    "native_session_id": native_session_id,
                }.items()
                if value is not None
            }
        )
        if native_session_operation is not None:
            payload["extra"] = {"native_session_operation": native_session_operation}
        task = asyncio.create_task(
            anyio.to_thread.run_sync(
                lambda: self.sessions.run_turn(
                    session_id,
                    payload,
                    cancel_event=cancel_event,
                ),
                abandon_on_cancel=True,
            ),
            name=f"tui-turn-{key}",
        )
        run = await self._wait_for_run(session_id, before, task)
        self._submitted_turns[key] = run.id
        self._active_runs[run.id] = (task, cancel_event)
        task.add_done_callback(
            lambda done, run_id=run.id: self._finish_run(run_id, done)
        )
        return await self.snapshot_run(run.id)

    async def snapshot_run(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
    ) -> RunSnapshot:
        run = self.sessions.get_run(run_id)
        generation = _run_generation(run)
        offset, cursor_generation, cursor_invalid = _parse_in_process_cursor(cursor)
        reason = None
        if cursor_invalid:
            offset = 0
            reason = "cursor_gap"
        elif cursor_generation is not None and cursor_generation != generation:
            offset = 0
            reason = "generation_changed"
        try:
            current, page = self.sessions.read_run_event_tail(
                run_id,
                offset,
                limit=MAX_TIMELINE_EVENTS,
                max_bytes=MAX_RESPONSE_BYTES,
            )
        except ValueError:
            current, page = self.sessions.read_run_event_tail(
                run_id,
                0,
                limit=MAX_TIMELINE_EVENTS,
                max_bytes=MAX_RESPONSE_BYTES,
            )
            reason = "cursor_gap"
        if page.has_more:
            reason = reason or "slow_consumer"
        events = _bounded_timeline(tuple(item.event for item in page.items))
        job = self.sessions.find_job_for_run(run_id)
        approvals = tuple(
            _approval_summary(approval_request_to_dict(item))
            for item in self.runtime_store.list_run_approval_requests(
                run_id=run_id,
                job_id=job.id if job is not None else None,
                limit=20,
            )
            if item.status is ApprovalStatus.PENDING
        )
        return _run_snapshot(
            current,
            events=events,
            cursor=f"ip1.{generation}.{page.next_offset}",
            idempotency_key=_run_idempotency_key(current, self._submitted_turns),
            pending_approvals=approvals,
            resnapshot_reason=reason,
        )

    async def latest_run(self, session_id: str) -> RunSnapshot | None:
        runs = self.store.list_runs(session_id)
        if not runs:
            return None
        active = [run for run in runs if run.status.value not in _TERMINAL_RUN_STATUSES]
        return await self.snapshot_run((active or list(runs))[-1].id)

    async def cancel_run(self, binding: RunActionBinding) -> RunSnapshot:
        run = self._validate_binding(binding)
        active = self._active_runs.get(run.id)
        if active is not None:
            active[1].set()
        else:
            job = self.sessions.find_job_for_run(run.id)
            if job is None:
                raise WorkbenchClientError(
                    "run owner is unavailable; authoritative resnapshot required"
                )
            self.runtime_store.request_cancel(job.id)
        return await self.snapshot_run(run.id)

    async def fork_run(self, binding: RunActionBinding) -> SessionSummary:
        run = self._validate_binding(binding)
        source = self.store.get_session(run.session_id)
        metadata = {
            **dict(source.metadata),
            "forked_from_session_id": source.id,
            "forked_from_run_id": run.id,
        }
        metadata.pop("structured_session_link", None)
        fork = self.store.create_session(
            title=f"Fork: {source.title}",
            workspace=run.workspace or source.workspace,
            default_harness_id=run.harness_id,
            default_model=run.model,
            default_api_mode=run.api_mode,
            default_mode=run.mode,
            metadata=metadata,
        )
        for message in _messages_through_run(
            self.store.list_messages(source.id), run.id
        ):
            self.store.append_message(
                replace(
                    message,
                    id=new_id("msg"),
                    session_id=fork.id,
                    run_id=None,
                    created_at=utc_now(),
                    metadata={
                        **dict(message.metadata),
                        "forked_from_message_id": message.id,
                        "forked_from_run_id": run.id,
                    },
                )
            )
        return _session_summary(fork)

    async def decide_approval(
        self,
        binding: RunActionBinding,
        approval_id: str,
        decision: str,
    ) -> RunSnapshot:
        run = self._validate_binding(binding)
        approval = self.runtime_store.get_approval_request(approval_id)
        if approval.run_id != run.id:
            raise WorkbenchClientError("approval does not belong to the selected run")
        self.sessions.decide_approval(approval_id, decision)
        return await self.snapshot_run(run.id)

    async def steer_run(
        self,
        binding: RunActionBinding,
        content: str,
        *,
        idempotency_key: str,
    ) -> RunSnapshot:
        run = self._validate_binding(binding)
        text = _required_content(content, "steer content")
        input_key = _required_identity(idempotency_key, "idempotency key")
        harness = self.registry.get(run.harness_id)
        supervisors = getattr(harness, "_app_server_supervisors", {})
        supervisor = getattr(harness, "app_server_supervisor", None) or supervisors.get(
            self.config.data_dir
        )
        if supervisor is None:
            raise WorkbenchClientError(
                "active structured owner is unavailable; resnapshot before retry"
            )
        try:
            supervisor.steer_turn(run.session_id, StructuredTurnInput(input_key, text))
        except (RuntimeError, ValueError) as exc:
            raise WorkbenchClientError(str(exc)) from exc
        return await self.snapshot_run(run.id)

    async def answer_input(
        self,
        binding: RunActionBinding,
        input_id: str,
        answer: str,
    ) -> RunSnapshot:
        self._validate_binding(binding)
        _required_identity(input_id, "input request")
        _required_content(answer, "input answer")
        raise WorkbenchClientError(
            "the selected provider does not advertise interactive input"
        )

    async def search_files(
        self, session_id: str, query: str
    ) -> tuple[FileCandidate, ...]:
        session = self.store.get_session(session_id)
        workspace = _session_workspace(session)
        limits = _workspace_limits(workspace)
        files = workspace_tree(
            workspace,
            query=query,
            limits=limits,
            result_limit=MAX_FILE_CANDIDATES,
        )
        return tuple(
            _file_candidate(item, workspace=workspace, limits=limits) for item in files
        )

    async def attach_file(self, session_id: str, path: str) -> AttachmentSummary:
        session = self.store.get_session(session_id)
        workspace = _session_workspace(session)
        project_id = _optional_text(session.metadata.get("project_id"))
        if project_id is None:
            project_id = resolve_project(
                workspace,
                data_dir=self.config.data_dir,
                load_config_name=False,
            ).id
        attachment = self.attachment_store.create_workspace_reference(
            session_id=session.id,
            project_id=project_id,
            workspace_root=workspace,
            path=path,
            limits=_workspace_limits(workspace),
        )
        return _attachment_summary(attachment_to_dict(attachment))

    async def inspect_run(self, run_id: str) -> RunInspection:
        run = self.sessions.get_run(run_id)
        return _in_process_run_inspection(
            run,
            registry=self.registry,
            runtime_store=self.runtime_store,
        )

    async def provider_handoff(self, session_id: str) -> HandoffPreview:
        session = self.store.get_session(session_id)
        workspace = _session_workspace(session)
        harness = self.registry.get(session.default_harness_id)
        preview = getattr(harness, "provider_handoff_preview", None)
        if not callable(preview):
            return _blocked_provider_handoff(session.default_harness_id)
        try:
            plan = preview(
                action=ClaudeHandoffAction.OPEN_PROVIDER_UI,
                workspace=workspace,
                launch_mode=ClaudeHandoffLaunchMode.INTERACTIVE,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return HandoffPreview(
                kind="provider",
                status="blocked",
                target=session.default_harness_id,
                continuity="Harness session remains authoritative and unchanged.",
                observability=("provider target was not opened",),
                instruction=_display_text(str(exc)),
            )
        return _provider_handoff_from_mapping(
            claude_handoff_plan_to_dict(plan),
            harness_id=session.default_harness_id,
        )

    async def web_handoff(self, session_id: str) -> HandoffPreview:
        self.store.get_session(session_id)
        return HandoffPreview(
            kind="web",
            status="blocked",
            target="unavailable in in-process mode",
            continuity=f"Session {session_id} remains durable in the local store.",
            observability=(
                "no FastAPI or uvicorn server is started by the terminal client",
            ),
            instruction="Use attach mode with an already running local Web application.",
        )

    async def start_native_terminal(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
        attachment_ids: tuple[str, ...] = (),
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
    ) -> NativeTerminalSnapshot:
        self.store.get_session(session_id)
        _required_content(content, "native terminal prompt")
        _required_identity(idempotency_key, "idempotency key")
        _attachment_ids(attachment_ids)
        raise WorkbenchClientError(
            "native terminal start requires attach mode so the existing policy, "
            "worktree, and process application authority remains the sole owner"
        )

    async def snapshot_native_terminal(
        self, process_id: str, *, cursor: int = 0
    ) -> NativeTerminalSnapshot:
        raise _in_process_native_terminal_error(process_id, cursor=cursor)

    async def status_native_terminal(self, process_id: str) -> NativeTerminalSnapshot:
        raise _in_process_native_terminal_error(process_id)

    async def send_native_terminal_input(
        self, process_id: str, data: str, *, submit: bool = False
    ) -> NativeTerminalSnapshot:
        _native_terminal_input(data)
        raise _in_process_native_terminal_error(process_id)

    async def resize_native_terminal(
        self, process_id: str, *, rows: int, columns: int
    ) -> NativeTerminalSnapshot:
        _native_terminal_dimensions(rows, columns)
        raise _in_process_native_terminal_error(process_id)

    async def stop_native_terminal(self, process_id: str) -> NativeTerminalSnapshot:
        raise _in_process_native_terminal_error(process_id)

    async def _wait_for_run(
        self,
        session_id: str,
        before: set[str],
        task: asyncio.Task[Any],
    ) -> HarnessRun:
        deadline = asyncio.get_running_loop().time() + RUN_START_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            created = [
                run for run in self.store.list_runs(session_id) if run.id not in before
            ]
            if created:
                return created[-1]
            if task.done():
                task.result()
                break
            await asyncio.sleep(0.01)
        task.cancel()
        raise WorkbenchClientError("turn did not create a run before the timeout")

    def _finish_run(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self._active_runs.pop(run_id, None)
        if not task.cancelled():
            task.exception()

    def _validate_binding(self, binding: RunActionBinding) -> HarnessRun:
        run = self.sessions.get_run(binding.run_id)
        if run.session_id != binding.session_id:
            raise WorkbenchClientError("run identity changed; resnapshot required")
        if _run_revision(run) != binding.revision:
            raise WorkbenchClientError("run revision changed; resnapshot required")
        if _run_generation(run) != binding.generation:
            raise WorkbenchClientError("run generation changed; resnapshot required")
        return run

    def _projects(self, current: HarnessProject) -> tuple[ProjectSummary, ...]:
        projects: dict[str, HarnessProject] = {current.id: current}
        for session in self.store.list_sessions(
            include_archived=False,
            limit=MAX_SESSIONS,
        ):
            if not session.workspace:
                continue
            try:
                project = resolve_project(
                    session.workspace,
                    data_dir=self.config.data_dir,
                    load_config_name=False,
                )
            except (OSError, ValueError):
                continue
            projects.setdefault(project.id, project)
            if len(projects) >= MAX_PROJECTS:
                break
        counts = {project_id: 0 for project_id in projects}
        for session in self.store.list_sessions(
            include_archived=False,
            limit=MAX_SESSIONS,
        ):
            project_id = str(session.metadata.get("project_id") or "")
            if project_id in counts:
                counts[project_id] += 1
        ordered = sorted(
            projects.values(),
            key=lambda item: (item.id != current.id, item.name.lower(), item.id),
        )
        return tuple(
            _project_summary(item, session_count=counts.get(item.id, 0))
            for item in ordered
        )

    def _readiness(
        self,
        project: HarnessProject,
        session: HarnessSession | None,
        harnesses: tuple[HarnessSummary, ...],
    ) -> ReadinessSummary:
        defaults = self.settings_store.load().defaults
        harness_id = (
            session.default_harness_id if session else defaults.default_harness_id
        )
        model = session.default_model if session else defaults.default_model
        payload = {
            "prompt": "",
            "workspace": project.root,
            "harness_id": harness_id,
            "model": model,
            "api_mode": (
                session.default_api_mode.value
                if session is not None
                else defaults.default_api_mode
            ),
            "mode": session.default_mode if session is not None else defaults.mode,
            "invocation_mode": defaults.invocation_mode,
            "workspace_policy": defaults.workspace_policy,
            "dry_run": True,
        }
        try:
            prepared = self.sessions.prepare_turn_payload(
                payload,
                session_id=session.id if session else None,
            )
            report = self.sessions.runner.preflight(
                prepared,
                session_id=session.id if session else None,
                durable=False,
            )
            readiness = dict(report.readiness)
        except (KeyError, OSError, ValueError) as exc:
            readiness = {
                "status": "blocked",
                "findings": ({"status": "blocked", "id": type(exc).__name__},),
                "plan": {"execution_transport": defaults.execution_transport},
            }
        return _readiness_summary(
            readiness,
            session=session_to_dict(session) if session else None,
            harnesses=harnesses,
            harness_id=harness_id,
            model=model,
        )


class AttachedWorkbenchClient:
    """Use the existing local REST contract without reading server storage."""

    transport_mode = "attach"

    def __init__(
        self,
        base_url: str,
        *,
        bootstrap_token: str | None = None,
        timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.bootstrap_token = bootstrap_token
        self.timeout_seconds = timeout_seconds
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._bootstrapped = False
        self._session_mutations: dict[str, SessionSummary | SessionExport | None] = {}

    async def workbench_state(
        self,
        *,
        cursor: str | None = None,
        limit: int = 32,
    ) -> WorkbenchStatePage:
        """Read provider-neutral projections through the authenticated API."""
        query: dict[str, str | int] = {"limit": min(max(limit, 1), 32)}
        if cursor is not None:
            query["cursor"] = cursor
        response = await self._request(
            "GET", f"/api/workbench/state?{urlencode(query)}"
        )
        return workbench_state_page_from_dict(response)

    async def resources(
        self, session_id: str | None = None
    ) -> WorkbenchResourceSnapshot:
        """Read bounded resources through the authenticated API."""
        query = f"?{urlencode({'session_id': session_id})}" if session_id else ""
        response = await self._request("GET", f"/api/workbench/resources{query}")
        return resource_snapshot_from_dict(response)

    async def cancel_task(self, task: TaskProjection) -> TaskProjection:
        """Request exact task cancellation through application authority."""
        response = await self._request(
            "POST",
            f"/api/workbench/tasks/{_path_identity(task.id)}/cancel",
            {"binding": task_binding(task)},
        )
        return TaskProjection(**_mapping(response.get("task")))

    async def stop_process(self, process: ProcessProjection) -> ProcessProjection:
        """Stop one exact native process through its server-side owner."""
        response = await self._request(
            "POST",
            f"/api/workbench/processes/{_path_identity(process.id)}/stop",
            {"binding": process_binding(process)},
        )
        return ProcessProjection(**_mapping(response.get("process")))

    async def save_preferences(
        self, values: Mapping[str, Any], *, expected_revision: str
    ) -> PreferenceSnapshot:
        """Persist private Workbench-only preferences through attach mode."""
        response = await self._request(
            "PUT",
            "/api/workbench/preferences",
            {"values": dict(values), "expected_revision": expected_revision},
        )
        return preference_snapshot_from_dict(_mapping(response.get("preferences")))

    async def preview_environment_commit(
        self,
        workspace: str,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> EnvironmentCommitPreviewSummary:
        response = await self._request(
            "POST",
            "/api/environment/commit/preview",
            {
                "workspace": workspace,
                "message": message,
                "author_name": author_name,
                "author_email": author_email,
            },
        )
        return _environment_commit_preview_summary(_mapping(response.get("preview")))

    async def apply_environment_commit(
        self,
        preview_id: str,
        *,
        workspace: str,
        session_id: str | None = None,
    ) -> EnvironmentCommitApplySummary:
        payload: dict[str, Any] = {
            "preview_id": preview_id,
            "workspace": workspace,
        }
        if session_id is not None:
            payload.pop("workspace")
            payload["session_id"] = session_id
        response = await self._request("POST", "/api/environment/commit/apply", payload)
        return _environment_commit_apply_summary(response)

    async def decide_environment_approval(
        self, approval_id: str, decision: str
    ) -> None:
        await self._request(
            "POST",
            f"/api/approvals/{_path_identity(approval_id)}/decision",
            {"decision": decision},
        )

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
        await self._ensure_session()
        if workspace is None and selected_session_id is not None:
            selected_payload = await self._request(
                "GET",
                f"/api/sessions/{_path_identity(selected_session_id)}",
            )
            workspace = _optional_text(
                _mapping(selected_payload.get("session")).get("workspace")
            )
        query = urlencode({"workspace": workspace}) if workspace else ""
        (
            project_payload,
            sessions_payload,
            harness_payload,
            integration_payload,
        ) = await self._parallel_get(
            f"/api/project?{query}" if query else "/api/project",
            f"/api/sessions?{urlencode({'workspace': workspace, 'limit': MAX_SESSIONS})}"
            if workspace
            else f"/api/sessions?limit={MAX_SESSIONS}",
            "/api/harnesses",
            "/api/integrations",
        )
        project_data = _mapping(project_payload.get("project"))
        session_items = tuple(
            _session_summary_from_mapping(item)
            for item in _mapping_items(sessions_payload.get("sessions"), MAX_SESSIONS)
        )
        selected_id = _selected_summary_id(session_items, selected_session_id)
        selected_data = next(
            (
                item
                for item in _mapping_items(
                    sessions_payload.get("sessions"), MAX_SESSIONS
                )
                if str(item.get("id")) == selected_id
            ),
            None,
        )
        harnesses = tuple(
            _harness_summary(
                _mapping(item.get("spec")),
                _mapping(item.get("availability")),
                _mapping(item.get("workbench_transport")),
            )
            for item in _mapping_items(harness_payload.get("harnesses"), 100)
        )
        defaults = _mapping(project_payload.get("defaults"))
        harness_id = str(
            (selected_data or {}).get("default_harness_id")
            or defaults.get("harness")
            or "unknown"
        )
        model = _optional_text(
            (selected_data or {}).get("default_model") or defaults.get("model")
        )
        preflight = await self._request(
            "POST",
            "/api/preflight/run",
            {
                "session_id": selected_id,
                "workspace": str(project_data.get("root") or workspace or ""),
                "harness_id": harness_id,
                "model": model,
                "dry_run": True,
                "durable": False,
            },
        )
        readiness = _mapping(_mapping(preflight.get("preflight")).get("readiness"))
        try:
            environment_payload = await self._request(
                "GET",
                f"/api/environment?{urlencode({'workspace': project_data.get('root') or workspace or ''})}",
            )
            environment = _environment_summary_from_mapping(environment_payload)
        except (TypeError, ValueError, WorkbenchClientError) as exc:
            environment = EnvironmentSummary("unavailable", reason=str(exc)[:240])
        project = _project_summary_from_mapping(
            project_data,
            session_count=len(session_items),
        )
        return NavigationSnapshot(
            transport_mode=self.transport_mode,
            projects=(project,),
            project=project,
            sessions=session_items,
            selected_session_id=selected_id,
            harnesses=harnesses,
            readiness=_readiness_summary(
                readiness,
                session=selected_data,
                harnesses=harnesses,
                harness_id=harness_id,
                model=model,
            ),
            integrations=_integration_summary_from_mapping(integration_payload),
            environment=environment,
        )

    async def create_session(
        self,
        workspace: str,
        *,
        title: str | None = None,
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
    ) -> SessionSummary:
        payload: dict[str, Any] = {"workspace": workspace}
        payload.update(
            {
                key: value
                for key, value in {
                    "title": title,
                    "harness_id": harness_id,
                    "model": model,
                    "api_mode": api_mode,
                    "mode": mode,
                }.items()
                if value is not None
            }
        )
        response = await self._request("POST", "/api/sessions", payload)
        return _session_summary_from_mapping(_mapping(response.get("session")))

    async def remember_session(self, workspace: str, session_id: str) -> None:
        await self._request(
            "PATCH",
            "/api/project/state",
            {"workspace": workspace, "last_selected_session": session_id},
        )

    async def search_sessions(
        self,
        query: str = "",
        *,
        provider: str | None = None,
        project: str | None = None,
        include_archived: bool = True,
    ) -> tuple[SessionSummary, ...]:
        values: dict[str, str | int] = {
            "include_archived": "true" if include_archived else "false",
            "limit": MAX_SESSIONS,
        }
        if query.strip():
            values["q"] = query.strip()
        if provider:
            values["harness_id"] = provider
        if project:
            values["project_id"] = project
        response = await self._request("GET", f"/api/sessions?{urlencode(values)}")
        return tuple(
            _session_summary_from_mapping(item)
            for item in _mapping_items(response.get("sessions"), MAX_SESSIONS)
        )

    async def preview_session(
        self, session_id: str, *, transcript_query: str = ""
    ) -> SessionPreview:
        values = {"q": transcript_query} if transcript_query.strip() else {}
        suffix = f"?{urlencode(values)}" if values else ""
        response = await self._request(
            "GET",
            f"/api/sessions/{_path_identity(session_id)}/navigation-preview{suffix}",
        )
        return _session_preview_from_mapping(response)

    async def rename_session(
        self, binding: SessionActionBinding, title: str
    ) -> SessionSummary:
        return await self._attached_session_patch(binding, {"title": title})

    async def archive_session(
        self, binding: SessionActionBinding, *, archived: bool = True
    ) -> SessionSummary:
        return await self._attached_session_patch(binding, {"archived": archived})

    async def delete_session(self, binding: SessionActionBinding) -> None:
        if binding.idempotency_key in self._session_mutations:
            return
        await self._request(
            "POST",
            f"/api/sessions/{_path_identity(binding.session_id)}/navigation-delete",
            _session_binding_payload(binding),
        )
        self._session_mutations[binding.idempotency_key] = None

    async def fork_session(self, binding: SessionActionBinding) -> SessionSummary:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionSummary):
            return cached
        response = await self._request(
            "POST",
            f"/api/sessions/{_path_identity(binding.session_id)}/navigation-fork",
            _session_binding_payload(binding),
        )
        result = _session_summary_from_mapping(_mapping(response.get("session")))
        self._session_mutations[binding.idempotency_key] = result
        return result

    async def export_session(self, binding: SessionActionBinding) -> SessionExport:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionExport):
            return cached
        response = await self._request(
            "POST",
            f"/api/sessions/{_path_identity(binding.session_id)}/navigation-export",
            _session_binding_payload(binding),
        )
        export = _mapping(response.get("export"))
        result = SessionExport(
            session_id=binding.session_id,
            path=_required_text(export.get("path"), "export path"),
            message_count=_bounded_non_negative_int(export.get("message_count")),
        )
        self._session_mutations[binding.idempotency_key] = result
        return result

    async def _attached_session_patch(
        self,
        binding: SessionActionBinding,
        patch: Mapping[str, Any],
    ) -> SessionSummary:
        cached = self._session_mutations.get(binding.idempotency_key)
        if isinstance(cached, SessionSummary):
            return cached
        response = await self._request(
            "POST",
            f"/api/sessions/{_path_identity(binding.session_id)}/navigation-update",
            {**patch, **_session_binding_payload(binding)},
        )
        result = _session_summary_from_mapping(_mapping(response.get("session")))
        self._session_mutations[binding.idempotency_key] = result
        return result

    async def submit_turn(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
        attachment_ids: tuple[str, ...] = (),
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
        capability: str | None = None,
        execution_transport: str | None = None,
        native_session_id: str | None = None,
        native_session_operation: str | None = None,
    ) -> RunSnapshot:
        payload: dict[str, Any] = {
            "prompt": _required_content(content, "turn content"),
            "stream": True,
            "idempotency_key": _required_identity(idempotency_key, "idempotency key"),
            "attachment_ids": list(_attachment_ids(attachment_ids)),
        }
        payload.update(
            {
                key: value
                for key, value in {
                    "harness_id": harness_id,
                    "model": model,
                    "api_mode": api_mode,
                    "mode": mode,
                    "capability": capability,
                    "execution_transport": execution_transport,
                    "native_session_id": native_session_id,
                }.items()
                if value is not None
            }
        )
        if native_session_operation is not None:
            payload["extra"] = {"native_session_operation": native_session_operation}
        response = await self._request(
            "POST",
            f"/api/sessions/{_path_identity(session_id)}/run/start",
            payload,
        )
        run_id = _required_identity(_mapping(response.get("run")).get("id"), "run id")
        return await self.snapshot_run(run_id)

    async def snapshot_run(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
    ) -> RunSnapshot:
        run_payload = await self._request(
            "GET", f"/api/cockpit/runs/{_path_identity(run_id)}"
        )
        run = _mapping(run_payload.get("run"))
        session_id = _required_identity(run.get("session_id"), "session id")
        generation = _mapping_generation(_mapping(run.get("provider_session")))
        cursor_event_id, cursor_generation, cursor_invalid = _parse_attach_cursor(
            cursor
        )
        reason = None
        if cursor_invalid:
            cursor_event_id = None
            reason = "cursor_gap"
        elif cursor_generation is not None and cursor_generation != generation:
            cursor_event_id = None
            reason = "generation_changed"
        query_values = {"run_id": run_id}
        if cursor_event_id:
            query_values["after_id"] = cursor_event_id
        events_payload, approvals_payload = await self._parallel_get(
            f"/api/sessions/{session_id}/events?{urlencode(query_values)}",
            "/api/approvals?status=pending&limit=100",
        )
        raw_events = _mapping_items(
            events_payload.get("events"), MAX_TIMELINE_EVENTS + 1
        )
        if len(raw_events) > MAX_TIMELINE_EVENTS:
            raw_events = raw_events[-MAX_TIMELINE_EVENTS:]
            reason = reason or "slow_consumer"
        if (
            cursor_event_id
            and not raw_events
            and str(run.get("status")) not in _TERMINAL_RUN_STATUSES
        ):
            full_payload = await self._request(
                "GET",
                f"/api/sessions/{session_id}/events?{urlencode({'run_id': run_id})}",
            )
            full = _mapping_items(full_payload.get("events"), MAX_TIMELINE_EVENTS + 1)
            known_ids = {str(item.get("id")) for item in full}
            if cursor_event_id not in known_ids:
                raw_events = full[-MAX_TIMELINE_EVENTS:]
                reason = "cursor_gap"
        events = _bounded_timeline(
            tuple(_event_from_mapping(item) for item in raw_events)
        )
        last_event_id = events[-1].id if events else cursor_event_id
        approvals = tuple(
            _approval_summary(item)
            for item in _mapping_items(approvals_payload.get("approvals"), 100)
            if str(item.get("run_id") or "") == run_id
        )
        revision = _required_text(
            run_payload.get("snapshot_revision") or _mapping_revision(run),
            "run revision",
        )
        binding = RunActionBinding(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
            generation=generation,
            idempotency_key=_required_identity(
                _mapping(run.get("runtime")).get("idempotency_key") or f"run-{run_id}",
                "idempotency key",
            ),
        )
        return RunSnapshot(
            binding=binding,
            status=_display_text(run.get("status") or "unknown"),
            events=events,
            cursor=(
                f"at1.{generation}.{last_event_id}"
                if last_event_id is not None
                else None
            ),
            pending_approvals=approvals,
            resnapshot_reason=reason,
            execution_transport=_optional_display_text(run.get("execution_transport")),
            native_process_id=_optional_text(run.get("native_process_id")),
        )

    async def latest_run(self, session_id: str) -> RunSnapshot | None:
        response = await self._request(
            "GET", f"/api/sessions/{_path_identity(session_id)}"
        )
        runs = _mapping_items(response.get("runs"), 100)
        if not runs:
            return None
        active = [
            run
            for run in runs
            if str(run.get("status") or "") not in _TERMINAL_RUN_STATUSES
        ]
        selected = (active or list(runs))[-1]
        return await self.snapshot_run(_required_identity(selected.get("id"), "run id"))

    async def cancel_run(self, binding: RunActionBinding) -> RunSnapshot:
        await self._validate_binding(binding)
        await self._request(
            "POST",
            f"/api/runs/{binding.run_id}/cancel",
            _binding_payload(binding),
        )
        return await self.snapshot_run(binding.run_id)

    async def fork_run(self, binding: RunActionBinding) -> SessionSummary:
        await self._validate_binding(binding)
        response = await self._request(
            "POST", f"/api/runs/{binding.run_id}/fork", _binding_payload(binding)
        )
        return _session_summary_from_mapping(_mapping(response.get("session")))

    async def decide_approval(
        self,
        binding: RunActionBinding,
        approval_id: str,
        decision: str,
    ) -> RunSnapshot:
        await self._validate_binding(binding)
        await self._request(
            "POST",
            f"/api/approvals/{_path_identity(approval_id)}/decision",
            {"decision": decision, "run_binding": _binding_payload(binding)},
        )
        return await self.snapshot_run(binding.run_id)

    async def steer_run(
        self,
        binding: RunActionBinding,
        content: str,
        *,
        idempotency_key: str,
    ) -> RunSnapshot:
        await self._validate_binding(binding)
        await self._request(
            "POST",
            f"/api/runs/{binding.run_id}/steer",
            {
                **_binding_payload(binding),
                "content": _required_content(content, "steer content"),
                "idempotency_key": _required_identity(
                    idempotency_key, "idempotency key"
                ),
            },
        )
        return await self.snapshot_run(binding.run_id)

    async def answer_input(
        self,
        binding: RunActionBinding,
        input_id: str,
        answer: str,
    ) -> RunSnapshot:
        await self._validate_binding(binding)
        await self._request(
            "POST",
            f"/api/runs/{binding.run_id}/input",
            {
                **_binding_payload(binding),
                "input_id": _required_identity(input_id, "input request"),
                "answer": _required_content(answer, "input answer"),
            },
        )
        return await self.snapshot_run(binding.run_id)

    async def search_files(
        self, session_id: str, query: str
    ) -> tuple[FileCandidate, ...]:
        response = await self._request(
            "GET",
            f"/api/sessions/{_path_identity(session_id)}/attachments/workspace/search?"
            + urlencode({"q": query, "limit": MAX_FILE_CANDIDATES}),
        )
        candidates: list[FileCandidate] = []
        for item in _mapping_items(response.get("files"), MAX_FILE_CANDIDATES):
            path = _required_text(item.get("path"), "file path")
            preview_response = await self._request(
                "GET",
                f"/api/sessions/{_path_identity(session_id)}/attachments/workspace/preview?"
                + urlencode({"path": path}),
            )
            candidates.append(_file_candidate_from_mapping(item, preview_response))
        return tuple(candidates)

    async def attach_file(self, session_id: str, path: str) -> AttachmentSummary:
        response = await self._request(
            "POST",
            f"/api/sessions/{_path_identity(session_id)}/attachments/workspace",
            {"path": _required_content(path, "file path")},
        )
        return _attachment_summary(_mapping(response.get("attachment")))

    async def inspect_run(self, run_id: str) -> RunInspection:
        identity = _path_identity(run_id)
        run_payload, diff_payload, harness_payload = await self._parallel_get(
            f"/api/cockpit/runs/{identity}",
            f"/api/cockpit/runs/{identity}/diff?max_bytes={MAX_DIFF_PREVIEW_CHARS + 1024}",
            "/api/harnesses",
        )
        summary_payload = await self._request_optional(
            "GET", f"/api/runs/{identity}/summary"
        )
        return _attached_run_inspection(
            run_payload, diff_payload, summary_payload, harness_payload
        )

    async def provider_handoff(self, session_id: str) -> HandoffPreview:
        response = await self._request(
            "GET", f"/api/sessions/{_path_identity(session_id)}"
        )
        session = _mapping(response.get("session")) or response
        harness_id = _required_identity(session.get("default_harness_id"), "Harness id")
        workspace = _required_text(session.get("workspace"), "session workspace")
        handoff = await self._request_optional(
            "GET",
            f"/api/provider-handoffs/{harness_id}/preview?"
            + urlencode(
                {
                    "action": "open_provider_ui",
                    "workspace": workspace,
                    "launch_mode": "interactive",
                }
            ),
        )
        if not handoff:
            return _blocked_provider_handoff(harness_id)
        return _provider_handoff_from_mapping(
            _mapping(handoff.get("handoff")), harness_id=harness_id
        )

    async def web_handoff(self, session_id: str) -> HandoffPreview:
        identity = _path_identity(session_id)
        await self._request("GET", f"/api/sessions/{identity}")
        return HandoffPreview(
            kind="web",
            status="ready",
            target=f"{self.base_url}/cockpit-v2/work/{identity}",
            continuity=f"The Web client resumes Harness session {identity}.",
            observability=(
                "Web and TUI share the server application/runtime/store authority",
                "browser authentication and rendering remain Web-owned",
            ),
            instruction="Open this local URL after reviewing the target and boundary.",
        )

    async def start_native_terminal(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
        attachment_ids: tuple[str, ...] = (),
        harness_id: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        mode: str | None = None,
    ) -> NativeTerminalSnapshot:
        payload: dict[str, Any] = {
            "action": "start",
            "session_id": _path_identity(session_id),
            "prompt": _required_content(content, "native terminal prompt"),
            "idempotency_key": _required_identity(idempotency_key, "idempotency key"),
            "attachment_ids": list(_attachment_ids(attachment_ids)),
            "execution_transport": "native_terminal",
            "invocation_mode": "native",
        }
        payload.update(
            {
                key: value
                for key, value in {
                    "harness_id": harness_id,
                    "model": model,
                    "api_mode": api_mode,
                    "mode": mode,
                }.items()
                if value is not None
            }
        )
        response = await self._request(
            "POST",
            "/api/native/processes/start",
            payload,
        )
        if bool(response.get("approval_required")):
            raise WorkbenchClientError(
                "native process approval is required; review the retained approval "
                "before retrying this exact start"
            )
        return _native_terminal_snapshot_from_mapping(response)

    async def snapshot_native_terminal(
        self, process_id: str, *, cursor: int = 0
    ) -> NativeTerminalSnapshot:
        validated_cursor = _non_negative_cursor(cursor)
        response = await self._request(
            "GET",
            f"/api/native/processes/{_path_identity(process_id)}/output?"
            + urlencode({"cursor": validated_cursor}),
        )
        return _native_terminal_snapshot_from_mapping(response)

    async def status_native_terminal(self, process_id: str) -> NativeTerminalSnapshot:
        response = await self._request(
            "GET", f"/api/native/processes/{_path_identity(process_id)}"
        )
        return _native_terminal_snapshot_from_mapping(response)

    async def send_native_terminal_input(
        self, process_id: str, data: str, *, submit: bool = False
    ) -> NativeTerminalSnapshot:
        response = await self._request(
            "POST",
            f"/api/native/processes/{_path_identity(process_id)}/input",
            {"data": _native_terminal_input(data), "submit": bool(submit)},
        )
        return _native_terminal_snapshot_from_mapping(response)

    async def resize_native_terminal(
        self, process_id: str, *, rows: int, columns: int
    ) -> NativeTerminalSnapshot:
        validated_rows, validated_columns = _native_terminal_dimensions(rows, columns)
        response = await self._request(
            "POST",
            f"/api/native/processes/{_path_identity(process_id)}/resize",
            {"rows": validated_rows, "columns": validated_columns},
        )
        return _native_terminal_snapshot_from_mapping(response)

    async def stop_native_terminal(self, process_id: str) -> NativeTerminalSnapshot:
        response = await self._request(
            "DELETE", f"/api/native/processes/{_path_identity(process_id)}"
        )
        return _native_terminal_snapshot_from_mapping(response)

    async def _validate_binding(self, binding: RunActionBinding) -> None:
        current = await self.snapshot_run(binding.run_id)
        if (
            current.binding.session_id != binding.session_id
            or current.binding.revision != binding.revision
            or current.binding.generation != binding.generation
        ):
            raise WorkbenchClientError("run changed; authoritative resnapshot required")

    async def _parallel_get(
        self,
        *paths: str,
    ) -> tuple[Mapping[str, Any], ...]:
        results: list[Mapping[str, Any] | None] = [None] * len(paths)

        async def fetch(index: int, path: str) -> None:
            results[index] = await self._request("GET", path)

        async with anyio.create_task_group() as group:
            for index, path in enumerate(paths):
                group.start_soon(fetch, index, path)
        return tuple(item or {} for item in results)

    async def _request_optional(self, method: str, path: str) -> Mapping[str, Any]:
        try:
            return await self._request(method, path)
        except WorkbenchClientError:
            return {}

    async def _ensure_session(self) -> None:
        if self._bootstrapped:
            return
        if self.bootstrap_token:
            await self._request(
                "POST",
                "/auth/session",
                authorization=f"Bearer {self.bootstrap_token}",
                ensure_session=False,
            )
        else:
            await self._request("GET", "/", ensure_session=False, expect_json=False)
        self._bootstrapped = True

    async def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        authorization: str | None = None,
        ensure_session: bool = True,
        expect_json: bool = True,
    ) -> Mapping[str, Any]:
        if ensure_session:
            await self._ensure_session()

        def send() -> Mapping[str, Any]:
            body = None
            headers = {"Accept": "application/json"}
            if payload is not None:
                body = json.dumps(dict(payload), separators=(",", ":")).encode()
                headers["Content-Type"] = "application/json"
            if authorization:
                headers["Authorization"] = authorization
            request = Request(
                f"{self.base_url}{path}",
                data=body,
                headers=headers,
                method=method,
            )
            try:
                with self._opener.open(
                    request, timeout=self.timeout_seconds
                ) as response:
                    content = response.read(MAX_RESPONSE_BYTES + 1)
            except HTTPError as exc:
                raise WorkbenchClientError(
                    f"attach request rejected ({exc.code})"
                ) from exc
            except (OSError, URLError) as exc:
                raise WorkbenchClientError("attach endpoint is unavailable") from exc
            if len(content) > MAX_RESPONSE_BYTES:
                raise WorkbenchClientError("attach response exceeded the size limit")
            if not expect_json:
                return {}
            try:
                parsed = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkbenchClientError("attach response is not valid JSON") from exc
            if not isinstance(parsed, Mapping):
                raise WorkbenchClientError("attach response must be an object")
            return parsed

        return await anyio.to_thread.run_sync(send)


def _workspace_limits(workspace: str) -> AttachmentLimits:
    return limits_from_project_settings(load_project_config(workspace).attachments)


def _in_process_integration_summary(
    service: IntegrationFlowService,
) -> IntegrationSummary:
    try:
        catalog_count = len(service.catalog.list())
        flows = service.list()
    except (OSError, RuntimeError, ValueError):
        return IntegrationSummary("blocked", 0, 0, 0)
    verified = sum(
        getattr(item.status, "value", item.status) in {"verified", "active"}
        for item in flows
    )
    return IntegrationSummary("ready", catalog_count, len(flows), verified)


def _integration_summary_from_mapping(data: Mapping[str, Any]) -> IntegrationSummary:
    catalog = _mapping_items(data.get("catalog"), 200)
    flows = _mapping_items(data.get("flows"), 200)
    verified = sum(
        str(item.get("status") or "") in {"verified", "active"} for item in flows
    )
    return IntegrationSummary("ready", len(catalog), len(flows), verified)


def _capture_environment_summary(
    workspace: str,
    github_service: GitHubEnvironmentService | None = None,
) -> EnvironmentSummary:
    try:
        provider = GitEnvironmentProvider()
        snapshot = provider.snapshot(workspace)
        summary = _environment_summary_from_snapshot(snapshot)
        if github_service is None:
            return summary
        github = github_service.inspect(snapshot, provider.hosted_repository(snapshot))
        return _environment_summary_with_github(summary, github)
    except EnvironmentCaptureError as exc:
        return EnvironmentSummary("unavailable", reason=str(exc))


def _environment_summary_from_snapshot(
    snapshot: EnvironmentSnapshot,
) -> EnvironmentSummary:
    return EnvironmentSummary(
        status="fresh",
        branch=snapshot.branch,
        detached=snapshot.detached,
        head=snapshot.head,
        worktree_root=snapshot.worktree_root,
        staged_count=snapshot.staged_count,
        unstaged_count=snapshot.unstaged_count,
        untracked_count=snapshot.untracked_count,
        additions=snapshot.additions,
        deletions=snapshot.deletions,
        commit_ready=snapshot.staged_count > 0,
        push_ready=snapshot.push_ready,
        push_blocker=snapshot.push_blocker,
        captured_at=snapshot.captured_at,
    )


def _environment_summary_from_mapping(data: Mapping[str, Any]) -> EnvironmentSummary:
    snapshot = EnvironmentSnapshot.from_dict(_mapping(data.get("environment")))
    summary = _environment_summary_from_snapshot(snapshot)
    freshness = _mapping(data.get("freshness"))
    issue_pr = _mapping(data.get("issue_pr"))
    commit = _mapping(data.get("commit"))
    github = _mapping(data.get("github"))
    repository = _mapping(github.get("repository"))
    pull_request = _mapping(github.get("pull_request"))
    checks = _mapping(pull_request.get("checks"))
    runs = _mapping_items(github.get("runs"), 5)
    issue_status = str(issue_pr.get("status") or "not_connected")
    number = issue_pr.get("number")
    if issue_pr.get("kind") == "pull_request" and isinstance(number, int):
        issue_status = f"PR #{number} {issue_status} · checks {checks.get('status') or 'unavailable'}"
    return replace(
        summary,
        status=str(freshness.get("status") or "stale"),
        commit_ready=bool(commit.get("ready")),
        issue_pr_status=issue_status,
        github_status=str(github.get("status") or "unavailable"),
        github_repository=_optional_text(repository.get("name_with_owner")),
        github_checks=str(checks.get("status") or "unavailable"),
        github_actions=_github_actions_status(runs),
        github_run_count=len(runs),
        github_checked_at=_optional_text(github.get("checked_at")),
    )


def _environment_summary_with_github(
    summary: EnvironmentSummary,
    github: GitHubEnvironmentSnapshot,
) -> EnvironmentSummary:
    pull_request = github.pull_request
    issue_pr = "none" if github.status == "ready" else "not_connected"
    checks = "unavailable"
    if pull_request is not None:
        checks = pull_request.checks.status
        issue_pr = f"PR #{pull_request.number} {pull_request.state} · checks {checks}"
    runs = tuple(run.to_dict() for run in github.runs)
    return replace(
        summary,
        issue_pr_status=issue_pr,
        github_status=github.status,
        github_repository=(
            github.repository.name_with_owner if github.repository else None
        ),
        github_checks=checks,
        github_actions=_github_actions_status(runs),
        github_run_count=len(runs),
        github_checked_at=github.checked_at,
    )


def _github_actions_status(runs: Sequence[Mapping[str, Any]]) -> str:
    if not runs:
        return "unavailable"
    latest = runs[0]
    return str(latest.get("conclusion") or latest.get("status") or "unknown")


def _session_workspace(session: HarnessSession) -> str:
    workspace = _optional_text(session.workspace)
    if workspace is None:
        raise WorkbenchClientError("session has no project workspace")
    return workspace


def _attachment_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > MAX_FILE_CANDIDATES:
        raise WorkbenchClientError("too many attachments selected")
    return tuple(
        _required_identity(value, "attachment id") for value in dict.fromkeys(values)
    )


def _file_candidate(
    data: Mapping[str, Any],
    *,
    workspace: str,
    limits: AttachmentLimits,
) -> FileCandidate:
    path = _required_text(data.get("path"), "file path")
    kind = _display_text(data.get("kind") or "unknown")
    preview = "Preview is unavailable for this file type."
    preview_status = "unsupported"
    if kind == "text":
        resolved, _relative = normalize_workspace_file(workspace, path, limits)
        raw = resolved.read_bytes()[: MAX_FILE_PREVIEW_CHARS + 1]
        preview = _bounded_content_text(
            raw[:MAX_FILE_PREVIEW_CHARS].decode("utf-8", errors="replace"),
            MAX_FILE_PREVIEW_CHARS,
        )
        preview_status = "truncated" if len(raw) > MAX_FILE_PREVIEW_CHARS else "ready"
    return FileCandidate(
        path=path,
        name=_display_text(data.get("name") or Path(path).name),
        mime_type=_display_text(data.get("mime_type") or "application/octet-stream"),
        kind=kind,
        size_bytes=_bounded_non_negative_int(data.get("size_bytes")),
        preview=preview,
        preview_status=preview_status,
    )


def _file_candidate_from_mapping(
    data: Mapping[str, Any], preview_response: Mapping[str, Any]
) -> FileCandidate:
    preview = _mapping(preview_response.get("preview"))
    return FileCandidate(
        path=_required_text(data.get("path"), "file path"),
        name=_display_text(data.get("name") or "file"),
        mime_type=_display_text(data.get("mime_type") or "application/octet-stream"),
        kind=_display_text(data.get("kind") or "unknown"),
        size_bytes=_bounded_non_negative_int(data.get("size_bytes")),
        preview=_bounded_content_text(
            preview.get("text") or "Preview is unavailable for this file type.",
            MAX_FILE_PREVIEW_CHARS,
        ),
        preview_status=_display_text(preview.get("status") or "unsupported"),
    )


def _attachment_summary(data: Mapping[str, Any]) -> AttachmentSummary:
    return AttachmentSummary(
        id=_required_identity(data.get("id"), "attachment id"),
        path=_required_text(
            data.get("workspace_path") or data.get("filename"), "attachment path"
        ),
        mime_type=_display_text(data.get("mime_type") or "application/octet-stream"),
        kind=_display_text(data.get("kind") or "attachment"),
        size_bytes=_bounded_non_negative_int(data.get("size_bytes")),
    )


def _in_process_run_inspection(
    run: HarnessRun,
    *,
    registry: HarnessRegistry,
    runtime_store: RuntimeCoordinationStore,
) -> RunInspection:
    diff = run_diff_response(run.metadata)
    patch = _bounded_content_text(diff.get("patch") or "", MAX_DIFF_PREVIEW_CHARS)
    raw_patch = str(diff.get("patch") or "")
    metadata = _mapping(run.metadata)
    execution = _mapping(metadata.get("workspace_execution"))
    artifacts: list[ArtifactSummary] = []
    if raw_patch:
        artifacts.append(ArtifactSummary("diff", len(raw_patch.encode("utf-8"))))
    if execution.get("worktree_path"):
        artifacts.append(ArtifactSummary("worktree", None))
    if isinstance(metadata.get("pr_artifact"), Mapping):
        artifacts.append(ArtifactSummary("pr_report", None))
    link = _mapping(metadata.get("structured_session_link"))
    continuity = (
        f"provider link revision {link.get('revision', 'unknown')}"
        if link
        else "no provider session link retained"
    )
    recovery = _display_text(link.get("recovery_state") or "not_required")
    try:
        availability = registry.get(run.harness_id).availability().status.value
    except (AttributeError, KeyError, ValueError):
        availability = "unknown"
    job = runtime_store.find_job_for_run(run.id)
    attempts = runtime_store.list_attempts(job.id) if job is not None else ()
    evidence = (
        f"run={run.id} session={run.session_id}",
        f"status={run.status.value} harness={run.harness_id} availability={availability}",
        (
            f"durable_job={job.status.value} attempts={len(attempts)}"
            if job is not None
            else "durable_job=not_present"
        ),
        f"artifacts={','.join(item.type for item in artifacts) or 'none'}",
        "environment=deferred_to_N6",
    )
    return RunInspection(
        run_id=run.id,
        status=run.status.value,
        revision=_run_revision(run),
        provider_continuity=continuity,
        harness_status=_display_text(availability),
        recovery=recovery,
        artifacts=tuple(artifacts),
        diff=patch,
        diff_truncated=len(raw_patch) > len(patch),
        changed_files=_safe_paths(diff.get("changed_files")),
        untracked_files=_safe_paths(diff.get("untracked_files")),
        evidence=evidence,
    )


def _attached_run_inspection(
    run_payload: Mapping[str, Any],
    diff_payload: Mapping[str, Any],
    summary_payload: Mapping[str, Any],
    harness_payload: Mapping[str, Any],
) -> RunInspection:
    run = _mapping(run_payload.get("run"))
    diff_projection = _mapping(diff_payload.get("patch"))
    provider_session = _mapping(run.get("provider_session"))
    artifacts = tuple(
        ArtifactSummary(
            _display_text(item.get("type") or "artifact"),
            _optional_non_negative_int(item.get("byte_count")),
        )
        for item in _mapping_items(run.get("artifacts"), 50)
    )
    summary = _mapping(summary_payload.get("run"))
    job = _mapping(summary.get("job"))
    explanations = _mapping_items(summary.get("explanations"), 20)
    recovery_item = next(
        (
            item
            for item in explanations
            if str(item.get("id") or item.get("kind") or "") == "recovery"
        ),
        {},
    )
    recovery = _display_text(
        recovery_item.get("summary")
        or provider_session.get("recovery_state")
        or "not_required"
    )
    continuity = (
        f"provider link revision {provider_session.get('revision', 'unknown')}"
        if provider_session
        else "no provider session link retained"
    )
    run_id = _required_identity(run.get("id"), "run id")
    status = _display_text(run.get("status") or "unknown")
    harness_id = _display_text(run.get("harness_id") or "unknown")
    harness_status = "unknown"
    for item in _mapping_items(harness_payload.get("harnesses"), 100):
        if str(_mapping(item.get("spec")).get("id") or "") == harness_id:
            harness_status = _display_text(
                _mapping(item.get("availability")).get("status") or "unknown"
            )
            break
    evidence = (
        f"run={run_id} session={_display_text(run.get('session_id') or 'unknown')}",
        f"status={status} harness={harness_id}",
        (
            f"durable_job={_display_text(job.get('status'))}"
            if job
            else "durable_job=not_present"
        ),
        f"artifacts={','.join(item.type for item in artifacts) or 'none'}",
        "environment=deferred_to_N6",
    )
    patch = _bounded_content_text(
        diff_projection.get("text") or "", MAX_DIFF_PREVIEW_CHARS
    )
    return RunInspection(
        run_id=run_id,
        status=status,
        revision=_required_text(
            run_payload.get("snapshot_revision") or _mapping_revision(run),
            "run revision",
        ),
        provider_continuity=continuity,
        harness_status=f"{harness_id} [{harness_status}]",
        recovery=recovery,
        artifacts=artifacts,
        diff=patch,
        diff_truncated=bool(diff_projection.get("truncated")),
        changed_files=_safe_paths(diff_payload.get("changed_files")),
        untracked_files=_safe_paths(diff_payload.get("untracked_files")),
        evidence=evidence,
    )


def _provider_handoff_from_mapping(
    data: Mapping[str, Any], *, harness_id: str
) -> HandoffPreview:
    command = tuple(
        _display_text(item)
        for item in (
            data.get("command") if isinstance(data.get("command"), list) else ()
        )
    )[:20]
    limits = tuple(
        _display_text(item)
        for item in (
            data.get("observability_limits")
            if isinstance(data.get("observability_limits"), list)
            else ()
        )
    )[:20]
    return HandoffPreview(
        kind="provider",
        status=_display_text(data.get("status") or "blocked"),
        target=_display_text(data.get("surface") or harness_id),
        continuity=(
            "Provider owns the external UI; Harness retains only the current durable session."
        ),
        observability=limits or ("structured provider observability is unavailable",),
        instruction=_display_text(
            data.get("instruction") or data.get("blocker") or "Handoff unavailable"
        ),
        command=command,
    )


def _blocked_provider_handoff(harness_id: str) -> HandoffPreview:
    return HandoffPreview(
        kind="provider",
        status="blocked",
        target=_display_text(harness_id),
        continuity="Harness session remains authoritative and unchanged.",
        observability=("provider UI handoff is not advertised by this Harness",),
        instruction="Continue in the TUI or use an explicit provider-owned terminal flow.",
    )


def _native_terminal_snapshot_from_mapping(
    data: Mapping[str, Any],
) -> NativeTerminalSnapshot:
    process = _mapping(data.get("process"))
    run = _mapping(data.get("run"))
    raw_parts = tuple(
        str(item.get("text") or "") for item in _mapping_items(data.get("outputs"), 512)
    )
    raw_output = "".join(raw_parts)
    handoff_required = bool(_FULLSCREEN_TERMINAL_RE.search(raw_output))
    safe_output = neutralize_native_terminal_output(raw_output)
    output_truncated = bool(data.get("truncated")) or (
        len(safe_output) > MAX_NATIVE_SCROLLBACK_CHARS
    )
    safe_output = safe_output[-MAX_NATIVE_SCROLLBACK_CHARS:]
    return NativeTerminalSnapshot(
        process_id=_required_identity(
            process.get("id") or data.get("process_id"), "native process id"
        ),
        session_id=_required_identity(
            process.get("session_id") or run.get("session_id"), "session id"
        ),
        run_id=_required_identity(process.get("run_id") or run.get("id"), "run id"),
        harness_id=_display_text(
            process.get("harness_id") or run.get("harness_id") or "unknown"
        ),
        transport=_display_text(process.get("transport") or "unknown"),
        status=_display_text(
            data.get("status")
            or process.get("status")
            or run.get("status")
            or "unknown"
        ),
        cursor=_bounded_non_negative_int(
            data.get("cursor")
            if data.get("cursor") is not None
            else process.get("terminal_cursor")
        ),
        output=safe_output,
        output_truncated=output_truncated,
        exit_code=_optional_int(
            data.get("exit_code")
            if data.get("exit_code") is not None
            else process.get("exit_code")
        ),
        handoff_required=handoff_required,
    )


def neutralize_native_terminal_output(value: Any) -> str:
    """Remove terminal-control semantics while preserving bounded visible text."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return _neutralize_presentation_text(text)


def _native_terminal_input(value: Any) -> str:
    if not isinstance(value, str):
        raise WorkbenchClientError("native terminal input must be text")
    if not value or len(value) > MAX_NATIVE_INPUT_CHARS:
        raise WorkbenchClientError(
            f"native terminal input must contain 1-{MAX_NATIVE_INPUT_CHARS} characters"
        )
    if (
        _CONTROL_RE.search(value)
        or _BIDI_CONTROL_RE.search(value)
        or "\r" in value
        or "\n" in value
    ):
        raise WorkbenchClientError("native terminal input contains terminal controls")
    return value


def _native_terminal_dimensions(rows: Any, columns: Any) -> tuple[int, int]:
    if (
        not isinstance(rows, int)
        or isinstance(rows, bool)
        or not 2 <= rows <= 200
        or not isinstance(columns, int)
        or isinstance(columns, bool)
        or not 20 <= columns <= 500
    ):
        raise WorkbenchClientError(
            "native terminal dimensions require rows 2-200 and columns 20-500"
        )
    return rows, columns


def _non_negative_cursor(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise WorkbenchClientError("native terminal cursor must be non-negative")
    return value


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _in_process_native_terminal_error(
    process_id: str, *, cursor: int | None = None
) -> WorkbenchClientError:
    _path_identity(process_id)
    if cursor is not None:
        _non_negative_cursor(cursor)
    return WorkbenchClientError(
        "native terminal process control requires attach mode; the in-process "
        "presentation does not read PTYs or runtime stores directly"
    )


def _safe_paths(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_display_text(item) for item in value[:100])


def _bounded_non_negative_int(value: Any) -> int:
    parsed = _optional_non_negative_int(value)
    return parsed if parsed is not None else 0


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _bounded_content_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "")
    return _neutralize_presentation_text(text)[:limit]


def _normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("attach URL must be an HTTP(S) origin without credentials")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _selected_session_id(
    sessions: tuple[HarnessSession, ...],
    requested: str | None,
) -> str | None:
    if requested and any(item.id == requested for item in sessions):
        return requested
    return sessions[0].id if sessions else None


def _selected_summary_id(
    sessions: tuple[SessionSummary, ...],
    requested: str | None,
) -> str | None:
    if requested and any(item.id == requested for item in sessions):
        return requested
    return sessions[0].id if sessions else None


def _project_summary(project: HarnessProject, *, session_count: int) -> ProjectSummary:
    return ProjectSummary(
        id=project.id,
        name=_display_text(project.name),
        root=project.root,
        git_branch=_optional_display_text(project.git_branch),
        session_count=session_count,
    )


def _project_summary_from_mapping(
    data: Mapping[str, Any],
    *,
    session_count: int,
) -> ProjectSummary:
    return ProjectSummary(
        id=_required_text(data.get("id"), "project id"),
        name=_display_text(data.get("name") or "Project"),
        root=_required_text(data.get("root"), "project root"),
        git_branch=_optional_display_text(data.get("git_branch")),
        session_count=session_count,
    )


def _session_summary(
    session: HarnessSession,
    store: FilesystemHarnessSessionStore | None = None,
) -> SessionSummary:
    native = _session_native_reference(session.native, session.metadata)
    runs = store.list_runs(session.id) if store is not None else ()
    messages = store.list_messages(session.id) if store is not None else ()
    active = [run.id for run in runs if run.status.value not in _TERMINAL_RUN_STATUSES]
    return SessionSummary(
        id=session.id,
        title=_display_text(session.title),
        updated_at=session.updated_at,
        workspace=session.workspace,
        harness_id=session.default_harness_id,
        model=_optional_display_text(session.default_model),
        mode=session.default_mode,
        archived=session.archived,
        project_id=_optional_text(session.metadata.get("project_id")),
        preview=(
            _bounded_content_text(" ".join(messages[-1].content.split()), 120)
            if messages
            else ""
        ),
        native_authority=_optional_display_text(native.get("authority")),
        native_session_id=_optional_identity(
            native.get("native_id") or native.get("session_id") or native.get("id")
        ),
        native_operation=_optional_display_text(native.get("operation")),
        revision=session.updated_at,
        generation=_session_generation(native),
        lease=active[-1] if active else None,
    )


def _session_summary_from_mapping(data: Mapping[str, Any]) -> SessionSummary:
    native = _mapping(data.get("native_session_reference"))
    if not native:
        native = _session_native_reference(
            _mapping(data.get("native")), _mapping(data.get("metadata"))
        )
    return SessionSummary(
        id=_required_text(data.get("id"), "session id"),
        title=_display_text(data.get("title") or "Untitled session"),
        updated_at=_display_text(data.get("updated_at") or "unknown"),
        workspace=_optional_text(data.get("workspace")),
        harness_id=_display_text(data.get("default_harness_id") or "unknown"),
        model=_optional_display_text(data.get("default_model")),
        mode=_display_text(data.get("default_mode") or "plan"),
        archived=bool(data.get("archived")),
        project_id=_optional_text(data.get("project_id")),
        preview=_bounded_content_text(data.get("last_message_preview"), 120),
        native_authority=_optional_display_text(native.get("authority")),
        native_session_id=_optional_identity(
            native.get("native_id") or native.get("session_id") or native.get("id")
        ),
        native_operation=_optional_display_text(native.get("operation")),
        revision=_required_text(
            data.get("session_revision") or data.get("updated_at"),
            "session revision",
        ),
        generation=_bounded_non_negative_int(
            data.get("session_generation")
            if data.get("session_generation") is not None
            else _session_generation(native)
        ),
        lease=_optional_identity(data.get("session_lease")),
    )


def _session_native_reference(
    native: Mapping[str, Any], metadata: Mapping[str, Any]
) -> Mapping[str, Any]:
    explicit = _mapping(metadata.get("native_session_reference"))
    if explicit:
        return explicit
    structured = _mapping(metadata.get("structured_session_link"))
    if structured:
        return {
            "authority": structured.get("provider")
            or structured.get("authority")
            or native.get("harness_id"),
            "native_id": structured.get("thread_id")
            or structured.get("session_id")
            or structured.get("native_session_id"),
            "operation": structured.get("operation") or "resume",
            "revision": structured.get("revision"),
            "link_hash": structured.get("link_hash"),
        }
    return native


def _session_generation(native: Mapping[str, Any]) -> int:
    revision = native.get("revision")
    if isinstance(revision, int) and revision >= 0:
        return revision
    return _hash_generation(_optional_text(native.get("link_hash")))


def session_action_binding(
    session: SessionSummary, *, idempotency_key: str
) -> SessionActionBinding:
    """Bind one navigation action to the exact presented session state."""
    return SessionActionBinding(
        session_id=session.id,
        revision=session.revision,
        generation=session.generation,
        lease=session.lease,
        idempotency_key=_required_identity(idempotency_key, "idempotency key"),
    )


def _session_binding_payload(binding: SessionActionBinding) -> dict[str, Any]:
    return {
        "session_revision": binding.revision,
        "session_generation": binding.generation,
        "session_lease": binding.lease,
        "idempotency_key": binding.idempotency_key,
    }


def _session_preview_from_mapping(data: Mapping[str, Any]) -> SessionPreview:
    return SessionPreview(
        session=_session_summary_from_mapping(_mapping(data.get("session"))),
        transcript=tuple(
            _bounded_content_text(item, MAX_DISPLAY_CHARS)
            for item in data.get("transcript", ())
            if isinstance(item, str)
        )[:100],
        match_count=_bounded_non_negative_int(data.get("match_count")),
        truncated=bool(data.get("truncated")),
    )


def _message_preview(message: HarnessMessage) -> str:
    content = _bounded_content_text(message.content, MAX_DISPLAY_CHARS)
    return f"{_display_text(message.role).upper()} · {message.created_at}\n{content}"


def _session_export_text(
    session: HarnessSession, messages: tuple[HarnessMessage, ...]
) -> str:
    header = (
        f"# {_display_text(session.title)}\n\n"
        f"Session: `{session.id}`  \n"
        f"Workspace: conversation context only; filesystem restore is not included.\n\n"
    )
    transcript = "\n\n".join(
        f"## {_display_text(item.role).title()} · {item.created_at}\n\n"
        f"{_neutralize_presentation_text(item.content)}"
        for item in messages
    )
    return f"{header}{transcript}\n"


def _harness_summary(
    spec: Mapping[str, Any],
    availability: Mapping[str, Any],
    transport: Mapping[str, Any],
) -> HarnessSummary:
    return HarnessSummary(
        id=_required_text(spec.get("id"), "Harness id"),
        title=_display_text(spec.get("title") or spec.get("id") or "Harness"),
        availability=_display_text(availability.get("status") or "unknown"),
        reason=_display_text(availability.get("reason") or "not checked"),
        default_transport=_display_text(transport.get("default") or "one_shot"),
    )


def _readiness_summary(
    readiness: Mapping[str, Any],
    *,
    session: Mapping[str, Any] | None,
    harnesses: tuple[HarnessSummary, ...],
    harness_id: str,
    model: str | None,
) -> ReadinessSummary:
    selected_harness = next(
        (item for item in harnesses if item.id == harness_id),
        None,
    )
    provider, provider_status = _provider_binding(session)
    plan = _mapping(readiness.get("plan"))
    findings = tuple(
        _display_text(item.get("id") or item.get("status") or "finding")
        for item in _mapping_items(readiness.get("findings"), 20)
        if str(item.get("status") or "") in {"blocked", "degraded", "unknown"}
    )
    return ReadinessSummary(
        status=_display_text(readiness.get("status") or "unknown"),
        provider=provider,
        provider_status=provider_status,
        harness_id=harness_id,
        harness_status=(
            selected_harness.availability if selected_harness else "unknown"
        ),
        model=model,
        transport=_display_text(
            plan.get("execution_transport")
            or (selected_harness.default_transport if selected_harness else "unknown")
        ),
        findings=findings,
    )


def _provider_binding(session: Mapping[str, Any] | None) -> tuple[str, str]:
    if not session:
        return "pending execution snapshot", "not_checked"
    metadata = _mapping(session.get("metadata"))
    snapshot = _mapping(metadata.get("execution_snapshot"))
    provider = _mapping(snapshot.get("provider"))
    provider_id = _optional_display_text(provider.get("id"))
    revision = _optional_display_text(provider.get("revision"))
    if provider_id:
        return (
            f"{provider_id}@{revision}" if revision else provider_id,
            "bound",
        )
    return "pending execution snapshot", "not_checked"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_items(value: Any, limit: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value[:limit] if isinstance(item, Mapping))


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise WorkbenchClientError(f"{field_name} is missing")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:MAX_DISPLAY_CHARS]


def _display_text(value: Any) -> str:
    text = _neutralize_presentation_text(str(value or ""))
    return text.replace("\r", " ").replace("\n", " ")[:MAX_DISPLAY_CHARS]


def _optional_display_text(value: Any) -> str | None:
    text = _optional_text(value)
    return _display_text(text) if text is not None else None


def _required_identity(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}", text):
        raise WorkbenchClientError(f"{field_name} is invalid")
    return text


def _path_identity(value: Any) -> str:
    return _required_identity(value, "path identity")


def _required_content(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkbenchClientError(f"{field_name} is required")
    if len(value) > 32_768:
        raise WorkbenchClientError(f"{field_name} exceeds the size limit")
    return value


def _run_revision(run: HarnessRun) -> str:
    payload = json.dumps(
        run_to_dict(run),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mapping_revision(run: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(run),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_generation(run: HarnessRun) -> int:
    metadata = _mapping(run.metadata)
    link = _mapping(metadata.get("structured_session_link"))
    revision = link.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision > 0:
        return revision
    runtime = _mapping(metadata.get("runtime"))
    attempt = runtime.get("attempt_number")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0:
        return attempt
    link_hash = _optional_text(link.get("link_hash"))
    return _hash_generation(link_hash) if link_hash else 1


def _mapping_generation(provider_session: Mapping[str, Any]) -> int:
    revision = provider_session.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision > 0:
        return revision
    link_hash = _optional_text(provider_session.get("link_hash"))
    return _hash_generation(link_hash) if link_hash else 1


def _hash_generation(value: str | None) -> int:
    if not value:
        return 1
    return max(int(hashlib.sha256(value.encode()).hexdigest()[:8], 16), 1)


def _run_idempotency_key(run: HarnessRun, submitted: Mapping[str, str]) -> str:
    return next(
        (key for key, run_id in submitted.items() if run_id == run.id),
        f"run-{run.id}",
    )


def _run_snapshot(
    run: HarnessRun,
    *,
    events: tuple[TimelineEvent, ...],
    cursor: str | None,
    idempotency_key: str,
    pending_approvals: tuple[ApprovalSummary, ...] = (),
    resnapshot_reason: str | None = None,
) -> RunSnapshot:
    metadata = _mapping(run.metadata)
    native_process = _mapping(metadata.get("native_process"))
    return RunSnapshot(
        binding=RunActionBinding(
            session_id=run.session_id,
            run_id=run.id,
            revision=_run_revision(run),
            generation=_run_generation(run),
            idempotency_key=_required_identity(idempotency_key, "run idempotency key"),
        ),
        status=run.status.value,
        events=events,
        cursor=cursor,
        pending_approvals=pending_approvals,
        resnapshot_reason=resnapshot_reason,
        execution_transport=_optional_display_text(metadata.get("execution_transport")),
        native_process_id=_optional_text(native_process.get("id")),
    )


def _parse_in_process_cursor(
    value: str | None,
) -> tuple[int, int | None, bool]:
    if value is None:
        return 0, None, False
    parts = value.split(".", 2)
    if len(parts) != 3 or parts[0] != "ip1":
        return 0, None, True
    try:
        generation = int(parts[1])
        offset = int(parts[2])
    except ValueError:
        return 0, None, True
    if generation < 1 or offset < 0:
        return 0, None, True
    return offset, generation, False


def _parse_attach_cursor(
    value: str | None,
) -> tuple[str | None, int | None, bool]:
    if value is None:
        return None, None, False
    parts = value.split(".", 2)
    if len(parts) != 3 or parts[0] != "at1":
        return None, None, True
    try:
        generation = int(parts[1])
    except ValueError:
        return None, None, True
    try:
        event_id = _required_identity(parts[2], "event cursor")
    except WorkbenchClientError:
        return None, None, True
    return event_id, generation, False


def _bounded_timeline(
    events: tuple[HarnessStoredEvent, ...],
) -> tuple[TimelineEvent, ...]:
    retained: list[TimelineEvent] = []
    character_count = 0
    for event in reversed(events[-MAX_TIMELINE_EVENTS:]):
        item = _timeline_event(event)
        item_size = (
            len(item.message) + len(item.delta or "") + len(item.tool_name or "")
        )
        if retained and character_count + item_size > MAX_TIMELINE_CHARS:
            break
        retained.append(item)
        character_count += item_size
    retained.reverse()
    return tuple(retained)


def _timeline_event(event: HarnessStoredEvent) -> TimelineEvent:
    payload = _mapping(event.payload)
    delta = None
    for key in ("delta", "text", "content", "reasoning"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            delta = _bounded_event_text(value)
            break
    return TimelineEvent(
        id=_required_identity(event.id, "event id"),
        type=_display_text(event.type),
        message=_bounded_event_text(event.message),
        delta=delta,
        tool_name=_optional_display_text(
            payload.get("name") or payload.get("tool_name")
        ),
        approval_id=_optional_identity(payload.get("approval_id")),
        input_id=_optional_identity(
            payload.get("input_id") or payload.get("request_id")
        ),
        category=_timeline_category(event.type),
        stream=_optional_display_text(payload.get("stream")),
        artifact_id=_optional_identity(
            payload.get("artifact_id") or payload.get("file_id")
        ),
        artifact_kind=_optional_display_text(
            payload.get("artifact_type") or payload.get("kind")
        ),
        truncated=bool(payload.get("truncated")),
    )


def _event_from_mapping(value: Mapping[str, Any]) -> HarnessStoredEvent:
    return HarnessStoredEvent(
        id=_required_identity(value.get("id"), "event id"),
        session_id=_required_identity(value.get("session_id"), "session id"),
        run_id=_required_identity(value.get("run_id"), "run id"),
        type=_display_text(value.get("type") or "event"),
        message=_bounded_event_text(value.get("message") or ""),
        payload=_mapping(value.get("payload")),
        created_at=_display_text(value.get("created_at") or "unknown"),
    )


def _bounded_event_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "")
    return _neutralize_presentation_text(text)[:8192]


def _neutralize_presentation_text(value: str) -> str:
    """Neutralize control sequences and bidi overrides for all TUI surfaces."""
    text = _TERMINAL_SEQUENCE_RE.sub("⟦terminal-control⟧", value)
    text = _BIDI_CONTROL_RE.sub("�", text)
    return _CONTROL_RE.sub("�", text)


def _optional_identity(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return _required_identity(value, "event identity")
    except WorkbenchClientError:
        return None


def _approval_summary(value: Mapping[str, Any]) -> ApprovalSummary:
    preview = _mapping(value.get("preview"))
    executable = preview.get("executable") or preview.get("command")
    if isinstance(executable, (list, tuple)):
        executable = executable[0] if executable else None
    paths = _safe_paths(preview.get("paths") or preview.get("changed_files"))
    hash_bound = bool(preview.get("approval_binding_sha256"))
    scopes = (
        ("allow_once", "deny")
        if hash_bound or not value.get("run_id")
        else ("allow_once", "allow_run", "deny")
    )
    details: list[str] = []
    author = preview.get("author")
    if isinstance(author, Mapping):
        details.append(
            "Author: "
            + _display_text(author.get("name") or "unknown")
            + " <"
            + _display_text(author.get("email") or "unknown")
            + ">"
        )
    if preview.get("message") is not None:
        details.append("Message: " + _display_text(preview.get("message")))
    if preview.get("head") is not None:
        details.append("HEAD: " + _display_text(preview.get("head")))
    if preview.get("diff_sha256") is not None:
        details.append("Diff: " + _display_text(preview.get("diff_sha256")))
    return ApprovalSummary(
        id=_required_identity(value.get("id"), "approval id"),
        action=_display_text(value.get("action") or "approval"),
        reason=_display_text(value.get("reason") or "Approval required"),
        status=_display_text(value.get("status") or "pending"),
        enforcement=_display_text(value.get("enforcement") or "unknown"),
        enforcement_owner=_display_text(value.get("enforcement_owner") or "unknown"),
        policy_source=_display_text(value.get("policy_source") or "unknown"),
        executable=_display_text(executable or "not declared"),
        tool=_display_text(
            preview.get("tool") or preview.get("tool_name") or "not declared"
        ),
        cwd=_display_text(preview.get("cwd") or "not declared"),
        paths=paths,
        network=_approval_network_label(preview),
        mutation_class=_display_text(
            preview.get("mutation_class") or value.get("action") or "unknown"
        ),
        decision_scopes=scopes,
        details=tuple(details),
    )


def _environment_commit_preview_summary(
    value: Mapping[str, Any],
) -> EnvironmentCommitPreviewSummary:
    author = _mapping(value.get("author"))
    return EnvironmentCommitPreviewSummary(
        id=_required_identity(value.get("id"), "commit preview id"),
        branch=_display_text(value.get("branch") or "detached"),
        head=_optional_text(value.get("head")),
        diff_sha256=_required_identity(value.get("diff_sha256"), "diff hash"),
        staged_count=max(0, int(value.get("staged_count", 0))),
        message=_display_text(value.get("message") or ""),
        author_name=_display_text(author.get("name") or ""),
        author_email=_display_text(author.get("email") or ""),
        worktree_root=_display_text(value.get("worktree_root") or ""),
    )


def _environment_commit_apply_summary(
    value: Mapping[str, Any],
) -> EnvironmentCommitApplySummary:
    preview = _environment_commit_preview_summary(_mapping(value.get("preview")))
    approval_payload = value.get("approval")
    result = _mapping(value.get("result"))
    return EnvironmentCommitApplySummary(
        preview=preview,
        approval=(
            _approval_summary(approval_payload)
            if isinstance(approval_payload, Mapping)
            else None
        ),
        commit_head=_optional_text(result.get("commit_head")),
        idempotent_replay=bool(value.get("idempotent_replay", False)),
    )


def _environment_commit_outcome_summary(outcome: Any) -> EnvironmentCommitApplySummary:
    return EnvironmentCommitApplySummary(
        preview=_environment_commit_preview_summary(outcome.preview.to_dict()),
        approval=(
            _approval_summary(approval_request_to_dict(outcome.approval))
            if outcome.approval is not None
            else None
        ),
        commit_head=(
            outcome.result.commit_head if outcome.result is not None else None
        ),
        idempotent_replay=outcome.idempotent_replay,
    )


def _timeline_category(event_type: str) -> str:
    normalized = event_type.lower().replace("-", "_")
    if "approval" in normalized:
        return "approval"
    if "question" in normalized or "input_request" in normalized:
        return "question"
    if "reason" in normalized:
        return "reasoning"
    if "stderr" in normalized:
        return "stderr"
    if "stdout" in normalized or "output_delta" in normalized:
        return "stdout"
    if "diff" in normalized:
        return "diff"
    if "file" in normalized or "attachment" in normalized:
        return "file"
    if "mcp" in normalized:
        return "mcp"
    if "web" in normalized:
        return "web"
    if "tool" in normalized or "command" in normalized:
        return "tool"
    if "plan" in normalized or "todo" in normalized:
        return "plan"
    if "warning" in normalized:
        return "warning"
    if "error" in normalized or "failed" in normalized:
        return "error"
    if "message" in normalized or normalized in {"user", "assistant", "agent"}:
        return "message"
    return "status"


def _approval_network_label(preview: Mapping[str, Any]) -> str:
    value = preview.get("network")
    if isinstance(value, bool):
        return "required" if value else "not required"
    if value is None:
        value = preview.get("network_required")
    if isinstance(value, bool):
        return "required" if value else "not required"
    return _display_text(value or "not declared")


def _binding_payload(binding: RunActionBinding) -> dict[str, Any]:
    return {
        "session_id": binding.session_id,
        "run_id": binding.run_id,
        "revision": binding.revision,
        "generation": binding.generation,
        "idempotency_key": binding.idempotency_key,
    }


def _messages_through_run(
    messages: tuple[HarnessMessage, ...], run_id: str
) -> tuple[HarnessMessage, ...]:
    selected: list[HarnessMessage] = []
    seen_target = False
    for message in messages:
        selected.append(message)
        if message.run_id == run_id:
            seen_target = True
            if message.role in {"assistant", "error"}:
                break
        elif seen_target:
            selected.pop()
            break
    return tuple(selected)
