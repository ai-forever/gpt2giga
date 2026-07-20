"""Typed application clients used by the optional Textual presentation."""

from __future__ import annotations

from dataclasses import dataclass
from http.cookiejar import CookieJar
import json
import re
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
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.models import HarnessSession, session_to_dict
from gpt2giga_harness.settings import HarnessSettingsStore
from gpt2giga_harness.types import availability_to_dict, spec_to_dict
from gpt2giga_harness.workbench_execution import workbench_transport_projection

MAX_PROJECTS = 50
MAX_SESSIONS = 100
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_DISPLAY_CHARS = 512
HTTP_TIMEOUT_SECONDS = 10.0
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


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
        self.sessions = SessionApplicationService(
            runner=runner,
            settings_store=self.settings_store,
        )

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
