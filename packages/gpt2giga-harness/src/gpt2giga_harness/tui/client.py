"""Typed application clients used by the built-in Textual presentation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
from http.cookiejar import CookieJar
import json
import re
import threading
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)

import anyio

from gpt2giga_harness.application import SessionApplicationService
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project import (
    HarnessProject,
    load_project_state,
    resolve_project,
    update_project_state,
)
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import approval_request_to_dict
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.session_runner import HarnessSessionRunner
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

MAX_PROJECTS = 50
MAX_SESSIONS = 100
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_DISPLAY_CHARS = 512
MAX_TIMELINE_EVENTS = 100
MAX_TIMELINE_CHARS = 64 * 1024
HTTP_TIMEOUT_SECONDS = 10.0
RUN_START_TIMEOUT_SECONDS = 5.0
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "canceled"})


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
class NavigationSnapshot:
    """One authoritative, presentation-bounded TUI resnapshot."""

    transport_mode: str
    projects: tuple[ProjectSummary, ...]
    project: ProjectSummary
    sessions: tuple[SessionSummary, ...]
    selected_session_id: str | None
    harnesses: tuple[HarnessSummary, ...]
    readiness: ReadinessSummary


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


@dataclass(frozen=True)
class ApprovalSummary:
    """Content-free pending approval projected into the selected run."""

    id: str
    action: str
    reason: str
    status: str


@dataclass(frozen=True)
class RunSnapshot:
    """Bounded authoritative run state shared by in-process and attach modes."""

    binding: RunActionBinding
    status: str
    events: tuple[TimelineEvent, ...]
    cursor: str | None
    pending_approvals: tuple[ApprovalSummary, ...] = ()
    resnapshot_reason: str | None = None

    @property
    def terminal(self) -> bool:
        """Return whether the durable run reached a terminal state."""
        return self.status in _TERMINAL_RUN_STATUSES


class WorkbenchClient(Protocol):
    """Thin asynchronous client contract shared by both transports."""

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
        """Load one authoritative navigation snapshot."""

    async def create_session(
        self,
        workspace: str,
        *,
        title: str | None = None,
    ) -> SessionSummary:
        """Create a session using backend-owned defaults."""

    async def remember_session(self, workspace: str, session_id: str) -> None:
        """Persist the selected session through the existing project state."""

    async def submit_turn(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
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


class InProcessWorkbenchClient:
    """Use existing application services without FastAPI, uvicorn, or a daemon."""

    transport_mode = "in_process"

    def __init__(
        self,
        config: HarnessConfig,
        *,
        registry: HarnessRegistry | None = None,
        store: FilesystemHarnessSessionStore | None = None,
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
        self.sessions = SessionApplicationService(
            runner=runner,
            settings_store=self.settings_store,
            runtime_store=self.runtime_store,
        )
        self._active_runs: dict[str, tuple[asyncio.Task[Any], threading.Event]] = {}
        self._submitted_turns: dict[str, str] = {}

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
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
        )

    async def create_session(
        self,
        workspace: str,
        *,
        title: str | None = None,
    ) -> SessionSummary:
        session = self.sessions.create_session(
            {"workspace": workspace, **({"title": title} if title else {})}
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

    async def submit_turn(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
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
        task = asyncio.create_task(
            anyio.to_thread.run_sync(
                lambda: self.sessions.run_turn(
                    session_id,
                    {"prompt": prompt, "stream": True},
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

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
        await self._ensure_session()
        query = urlencode({"workspace": workspace}) if workspace else ""
        project_payload, sessions_payload, harness_payload = await self._parallel_get(
            f"/api/project?{query}" if query else "/api/project",
            f"/api/sessions?{urlencode({'workspace': workspace, 'limit': MAX_SESSIONS})}"
            if workspace
            else f"/api/sessions?limit={MAX_SESSIONS}",
            "/api/harnesses",
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
        )

    async def create_session(
        self,
        workspace: str,
        *,
        title: str | None = None,
    ) -> SessionSummary:
        payload: dict[str, Any] = {"workspace": workspace}
        if title:
            payload["title"] = title
        response = await self._request("POST", "/api/sessions", payload)
        return _session_summary_from_mapping(_mapping(response.get("session")))

    async def remember_session(self, workspace: str, session_id: str) -> None:
        await self._request(
            "PATCH",
            "/api/project/state",
            {"workspace": workspace, "last_selected_session": session_id},
        )

    async def submit_turn(
        self,
        session_id: str,
        content: str,
        *,
        idempotency_key: str,
    ) -> RunSnapshot:
        response = await self._request(
            "POST",
            f"/api/sessions/{_path_identity(session_id)}/run/start",
            {
                "prompt": _required_content(content, "turn content"),
                "stream": True,
                "idempotency_key": _required_identity(
                    idempotency_key, "idempotency key"
                ),
            },
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


def _session_summary(session: HarnessSession) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        title=_display_text(session.title),
        updated_at=session.updated_at,
        workspace=session.workspace,
        harness_id=session.default_harness_id,
        model=_optional_display_text(session.default_model),
        mode=session.default_mode,
    )


def _session_summary_from_mapping(data: Mapping[str, Any]) -> SessionSummary:
    return SessionSummary(
        id=_required_text(data.get("id"), "session id"),
        title=_display_text(data.get("title") or "Untitled session"),
        updated_at=_display_text(data.get("updated_at") or "unknown"),
        workspace=_optional_text(data.get("workspace")),
        harness_id=_display_text(data.get("default_harness_id") or "unknown"),
        model=_optional_display_text(data.get("default_model")),
        mode=_display_text(data.get("default_mode") or "plan"),
    )


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
    text = str(value or "")
    return (
        _CONTROL_RE.sub("�", text)
        .replace("\r", " ")
        .replace("\n", " ")[:MAX_DISPLAY_CHARS]
    )


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
    return _CONTROL_RE.sub("�", str(value or "")).replace("\r", "")[:8192]


def _optional_identity(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return _required_identity(value, "event identity")
    except WorkbenchClientError:
        return None


def _approval_summary(value: Mapping[str, Any]) -> ApprovalSummary:
    return ApprovalSummary(
        id=_required_identity(value.get("id"), "approval id"),
        action=_display_text(value.get("action") or "approval"),
        reason=_display_text(value.get("reason") or "Approval required"),
        status=_display_text(value.get("status") or "pending"),
    )


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
