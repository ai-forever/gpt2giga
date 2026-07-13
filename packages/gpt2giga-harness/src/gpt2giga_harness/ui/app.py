"""FastAPI app for the minimal Unified Harness browser UI."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass, replace
import json
import threading
from typing import Any, Mapping

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from gpt2giga_harness.arena import (
    ArenaNotFoundError,
    FilesystemHarnessArenaStore,
    HarnessArenaChildRun,
    HarnessArenaRun,
    arena_child_to_dict,
    arena_to_dict,
    queue_arena,
    run_arena,
)
from gpt2giga_harness import proxy
from gpt2giga_harness.attachments import (
    AttachmentLimits,
    AttachmentNotFoundError,
    AttachmentSessionNotFoundError,
    AttachmentValidationError,
    FilesystemAttachmentStore,
    HarnessAttachment,
    attachment_to_dict,
    limits_from_project_settings,
    render_attachments_for_harness,
    render_plan_to_dict,
)
from gpt2giga_harness.config import (
    DEFAULT_MODEL_HINTS,
    HarnessConfig,
    pass_model_env_note,
)
from gpt2giga_harness.evals import (
    EvalRunNotFoundError,
    EvalSpecNotFoundError,
    FilesystemHarnessEvalStore,
    discover_eval_specs,
    eval_run_to_dict,
    eval_spec_load_error_to_dict,
    eval_spec_to_dict,
    load_eval_spec,
    queue_eval,
    run_eval,
)
from gpt2giga_harness.editor import (
    build_open_diff_plan,
    build_open_file_plan,
    build_open_terminal_plan,
    build_open_workspace_plan,
    editor_open_plan_to_dict,
    execute_editor_plan,
    workspace_for_run,
)
from gpt2giga_harness.native.base import (
    NativeCommandPlan,
    discovery_error_to_dict,
)
from gpt2giga_harness.native.models import (
    HarnessInvocationMode,
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga_harness.native.process import (
    NativeProcessManager,
    NativeProcessNotFoundError,
    NativeProcessRef,
    NativeProcessStartError,
    NativeProcessStatus,
    native_output_chunk_to_dict,
    native_process_ref_to_dict,
)
from gpt2giga_harness.native.registry import (
    NativeHistoryConnectorRegistry,
    UnknownNativeHistoryConnectorError,
    create_default_native_registry,
)
from gpt2giga_harness.native.store import (
    FilesystemNativeSessionIndexStore,
    NativeSessionIndexStore,
    native_session_ref_to_dict,
)
from gpt2giga_harness.project import (
    init_project_config,
    load_project_state,
    load_project_config,
    project_config_to_dict,
    project_preset_to_dict,
    project_state_to_dict,
    project_to_dict,
    render_project_preset,
    rendered_project_preset_to_dict,
    resolve_project,
    update_project_state,
)
from gpt2giga_harness.project_memory import (
    FilesystemProjectMemoryStore,
    ProjectMemoryNotFoundError,
    memory_entry_to_dict,
)
from gpt2giga_harness.preflight import (
    PreflightBlockedError,
    build_preflight_report,
    format_preflight_block_message,
    preflight_report_to_dict,
)
from gpt2giga_harness.pr_artifacts import (
    build_pr_artifact,
    create_pr_branch,
    pr_artifact_to_dict,
)
from gpt2giga_harness.plugins import (
    harness_validation_report_to_dict,
    validate_harness_spec,
)
from gpt2giga_harness.provenance import (
    build_replay_request,
    build_run_provenance,
    run_provenance_to_dict,
)
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.routing import (
    recommend_harness_route,
    route_recommendation_to_dict,
)
from gpt2giga_harness.runtime.models import RunStatus, job_to_dict
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    INTERACTIVE_PROFILE,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    approval_request_to_dict,
)
from gpt2giga_harness.runtime.reconcile import RuntimeReconciler
from gpt2giga_harness.runtime.store import JobNotFoundError, RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher
from gpt2giga_harness.schedules import ScheduleService
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    HarnessSessionStore,
    RunNotFoundError,
    SessionNotFoundError,
)
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessNativeLink,
    HarnessRun,
    HarnessSession,
    HarnessStoredEvent,
    bundle_to_dict,
    event_to_dict,
    message_to_dict,
    native_link_to_dict,
    run_to_dict,
    session_to_dict,
)
from gpt2giga_harness.sessions.store import new_id, title_from_prompt, utc_now
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    HarnessEventType,
    HarnessRequest,
    availability_to_dict,
    parse_api_mode,
    parse_builtin_tools,
    parse_capability,
    result_to_dict,
    spec_to_dict,
)
from gpt2giga_harness.tool_profiles import (
    build_tool_profile_statuses,
    tool_profile_status_to_dict,
)
from gpt2giga_harness.ui.routers.runs import router as runs_router
from gpt2giga_harness.ui.routers.schedules import router as schedules_router
from gpt2giga_harness.ui.routers.agents import router as agents_router
from gpt2giga_harness.ui.routers.automation import router as automation_router
from gpt2giga_harness.ui.routers.approvals import router as approvals_router
from gpt2giga_harness.ui.routers.evaluate import router as evaluate_router
from gpt2giga_harness.ui.routers.files import create_file_preview_router
from gpt2giga_harness.ui.routers.tools import router as tools_router
from gpt2giga_harness.ui.routers.workflows import router as workflows_router
from gpt2giga_harness.ui.routers.shell import create_shell_router
from gpt2giga_harness.ui.security import (
    HarnessUISecurity,
    HarnessUISecurityMiddleware,
    is_loopback_host,
)
from gpt2giga_harness.worktrees import (
    WorktreeConflictError,
    WorktreeError,
    apply_run_diff,
    discard_run_worktree,
    open_worktree_response,
    run_diff_response,
)
from gpt2giga_harness.workspace import (
    resolve_workspace,
    workspace_file_metadata,
    workspace_tree,
)


@dataclass
class _ActiveHeadlessRun:
    task: asyncio.Task[Any]
    cancel_event: threading.Event


def create_app(
    config: HarnessConfig | None = None,
    registry: HarnessRegistry | None = None,
    store: HarnessSessionStore | None = None,
    native_registry: NativeHistoryConnectorRegistry | None = None,
    native_index_store: NativeSessionIndexStore | None = None,
    native_process_manager: NativeProcessManager | None = None,
    runtime_store: RuntimeCoordinationStore | None = None,
) -> FastAPI:
    """Create the Unified Harness UI app."""
    config = config or HarnessConfig.from_env()
    registry = registry or create_default_registry()
    store = store or FilesystemHarnessSessionStore(config.data_dir)
    if runtime_store is None and isinstance(store, FilesystemHarnessSessionStore):
        runtime_store = RuntimeCoordinationStore(store.data_dir)
    reconciliation_report = (
        RuntimeReconciler(runtime_store, store).reconcile()
        if runtime_store is not None
        else None
    )
    native_registry = native_registry or create_default_native_registry(
        data_dir=config.data_dir
    )
    native_index_store = native_index_store or FilesystemNativeSessionIndexStore(
        config.data_dir
    )
    native_process_manager = native_process_manager or NativeProcessManager(
        session_store=store
    )
    attachment_store = FilesystemAttachmentStore(config.data_dir)
    arena_store = FilesystemHarnessArenaStore(config.data_dir)
    eval_store = FilesystemHarnessEvalStore(config.data_dir)
    memory_store = FilesystemProjectMemoryStore()
    runner = HarnessSessionRunner(
        registry=registry,
        config=config,
        store=store,
        attachment_store=attachment_store,
        memory_store=memory_store,
    )
    durable_dispatcher = (
        DurableJobDispatcher(
            runtime_store=runtime_store,
            payload_store=DurableJobPayloadStore(config.data_dir),
            runner=runner,
        )
        if runtime_store is not None
        and isinstance(store, FilesystemHarnessSessionStore)
        else None
    )
    policy_engine = PolicyEngine(runtime_store)
    active_headless_runs: dict[str, _ActiveHeadlessRun] = {}
    app = FastAPI(title="gpt2giga Unified Harness", docs_url=None, redoc_url=None)
    ui_security = HarnessUISecurity(config)
    app.add_middleware(HarnessUISecurityMiddleware, security=ui_security)
    app.state.harness_config = config
    app.state.harness_registry = registry
    app.state.harness_session_store = store
    app.state.harness_runtime_store = runtime_store
    app.state.harness_runtime_reconciliation = reconciliation_report
    app.state.harness_session_runner = runner
    app.state.harness_job_dispatcher = durable_dispatcher
    app.state.harness_policy_engine = policy_engine
    app.state.harness_attachment_store = attachment_store
    app.state.harness_arena_store = arena_store
    app.state.harness_eval_store = eval_store
    app.state.harness_schedule_service = (
        ScheduleService(
            runtime_store=runtime_store,
            runner=runner,
            dispatcher=durable_dispatcher,
            eval_store=eval_store,
        )
        if runtime_store is not None and durable_dispatcher is not None
        else None
    )
    app.state.harness_project_memory_store = memory_store
    app.state.harness_native_registry = native_registry
    app.state.harness_native_index_store = native_index_store
    app.state.harness_native_process_manager = native_process_manager

    def _approval_gate(
        action: PermissionAction,
        run: HarnessRun,
        *,
        reason: str,
        preview: Mapping[str, Any],
    ) -> JSONResponse | None:
        if runtime_store is None:
            raise HTTPException(
                status_code=409,
                detail="Durable runtime is required for policy-gated actions",
            )
        session = store.get_session(run.session_id)
        runtime_metadata = run.metadata.get("runtime")
        job_id = (
            str(runtime_metadata.get("job_id") or "") or None
            if isinstance(runtime_metadata, Mapping)
            else None
        )
        if job_id is not None:
            try:
                runtime_store.get_job(job_id)
            except JobNotFoundError:
                job_id = None
        context = PolicyContext(
            project_id=str(session.metadata.get("project_id") or "") or None,
            session_id=run.session_id,
            run_id=run.id,
            job_id=job_id,
            reason=reason,
            preview=preview,
        )
        resolution = policy_engine.resolve(
            action,
            profile=INTERACTIVE_PROFILE,
            context=context,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
        )
        if resolution.decision is PolicyDecision.DENY:
            raise HTTPException(status_code=403, detail="Action denied by policy")
        if resolution.decision is PolicyDecision.ALLOW:
            return None
        approval = runtime_store.create_approval_request(resolution, context)
        existing = any(
            event.type == "approval_requested"
            and event.payload.get("approval_id") == approval.id
            for event in store.list_events(run.session_id, run_id=run.id)
        )
        if not existing:
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type="approval_requested",
                    message=f"Approval required for {action.value}.",
                    payload={
                        "approval_id": approval.id,
                        "action": action.value,
                        "enforcement": resolution.enforcement.value,
                    },
                    created_at=utc_now(),
                    trace_id=context.job_id or run.id,
                    job_id=context.job_id,
                    span_kind="approval",
                    span_status="pending",
                )
            )
        return JSONResponse(
            status_code=202,
            content={
                "approval_required": True,
                "approval": approval_request_to_dict(approval),
            },
        )

    @app.get("/api/harnesses")
    async def harnesses() -> dict[str, Any]:
        harness_items = []
        for harness in registry.list():
            spec = harness.spec()
            validation = registry.validation_report(spec.id) or validate_harness_spec(
                spec
            )
            harness_items.append(
                {
                    "spec": spec_to_dict(spec),
                    "availability": availability_to_dict(harness.availability()),
                    "validation": harness_validation_report_to_dict(validation),
                }
            )
        return {
            "harnesses": harness_items,
            "discovery_errors": list(registry.discovery_errors),
        }

    @app.get("/api/defaults")
    async def defaults() -> dict[str, Any]:
        return {
            "proxy_url": config.proxy_url,
            "default_model": config.default_model or DEFAULT_MODEL_HINTS[0],
            "default_api_mode": config.default_api_mode.value,
            "auto_start_proxy": config.auto_start_proxy,
            "proxy_start_timeout_seconds": config.proxy_start_timeout_seconds,
            "note": pass_model_env_note(),
        }

    @app.get("/api/project")
    async def project(workspace: str | None = Query(default=None)) -> dict[str, Any]:
        try:
            return _project_response(
                workspace=_optional_text(workspace),
                data_dir=config.data_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/project/config")
    async def project_config(
        workspace: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
            )
            loaded = load_project_config(project_context.root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"config": project_config_to_dict(loaded)}

    @app.get("/api/project/presets")
    async def project_presets(
        workspace: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
            )
            loaded = load_project_config(project_context.root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "presets": [
                project_preset_to_dict(name, preset)
                for name, preset in loaded.presets.items()
            ],
        }

    @app.post("/api/project/presets/{preset_name}/render")
    async def render_preset(
        preset_name: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
            )
            loaded = load_project_config(project_context.root)
            rendered = render_project_preset(
                project_context,
                loaded,
                preset_name,
                user_prompt=_optional_text(payload.get("user_prompt")),
                selected_files=_text_tuple(payload.get("selected_files")),
                last_run_diff=_optional_text(payload.get("last_run_diff")),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Preset not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "preset": rendered_project_preset_to_dict(rendered),
        }

    @app.get("/api/project/state")
    async def project_state(
        workspace: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "state": project_state_to_dict(load_project_state(project_context)),
        }

    @app.patch("/api/project/state")
    async def update_state(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            state = update_project_state(project_context, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "state": project_state_to_dict(state),
        }

    @app.post("/api/editor/open-workspace")
    async def editor_open_workspace(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            loaded = load_project_config(project_context.root)
            command = _optional_text(payload.get("command")) or loaded.editor.command
            plan = build_open_workspace_plan(project_context.root, command=command)
            result = execute_editor_plan(
                plan,
                dry_run=bool(payload.get("dry_run", False)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "editor": editor_open_plan_to_dict(result),
        }

    @app.post("/api/editor/open-file")
    async def editor_open_file(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            loaded = load_project_config(project_context.root)
            command = _optional_text(payload.get("command")) or loaded.editor.command
            plan = build_open_file_plan(
                project_context.root,
                _required_text(payload.get("path"), "path is required"),
                command=command,
                line=_optional_int(payload.get("line")),
                column=_optional_int(payload.get("column")),
            )
            result = execute_editor_plan(
                plan,
                dry_run=bool(payload.get("dry_run", False)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "editor": editor_open_plan_to_dict(result),
        }

    @app.post("/api/editor/open-diff")
    async def editor_open_diff(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            run_id = _required_text(payload.get("run_id"), "run_id is required")
            run = store.get_run(run_id)
            project_context = resolve_project(
                workspace_for_run(run),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            loaded = load_project_config(project_context.root)
            command = _optional_text(payload.get("command")) or loaded.editor.command
            plan = build_open_diff_plan(
                run,
                data_dir=config.data_dir,
                command=command,
            )
            result = execute_editor_plan(
                plan,
                dry_run=bool(payload.get("dry_run", False)),
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "run": run_to_dict(run),
            "project": project_to_dict(project_context),
            "editor": editor_open_plan_to_dict(result),
        }

    @app.post("/api/editor/open-terminal")
    async def editor_open_terminal(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            run_id = _required_text(payload.get("run_id"), "run_id is required")
            run = store.get_run(run_id)
            workspace = workspace_for_run(run)
            if workspace is None:
                raise ValueError("Run does not have a workspace to open in a terminal.")
            project_context = resolve_project(
                workspace,
                data_dir=config.data_dir,
                load_config_name=False,
            )
            loaded = load_project_config(project_context.root)
            command = (
                _optional_text(payload.get("command")) or loaded.editor.terminal_command
            )
            plan = build_open_terminal_plan(workspace, command=command)
            result = execute_editor_plan(
                plan,
                dry_run=bool(payload.get("dry_run", False)),
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "run": run_to_dict(run),
            "project": project_to_dict(project_context),
            "editor": editor_open_plan_to_dict(result),
        }

    @app.get("/api/project/memory")
    async def project_memory(
        workspace: str | None = Query(default=None),
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
                load_config_name=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        memories = memory_store.list(
            project_context,
            include_disabled=include_disabled,
        )
        return {
            "project": project_to_dict(project_context),
            "memories": [memory_entry_to_dict(entry) for entry in memories],
        }

    @app.post("/api/project/memory")
    async def add_project_memory(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            memory = memory_store.add(
                project_context,
                text=_required_text(payload.get("text"), "memory text is required"),
                tags=_text_tuple(payload.get("tags")),
                source_session_id=_optional_text(payload.get("source_session_id")),
                source_run_id=_optional_text(payload.get("source_run_id")),
                enabled=bool(payload.get("enabled", True)),
                manual=bool(payload.get("manual", True)),
                confidence=_optional_float(payload.get("confidence")),
                metadata=_metadata_mapping(payload.get("metadata")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "memory": memory_entry_to_dict(memory),
        }

    @app.patch("/api/project/memory/{memory_id}")
    async def update_project_memory(
        memory_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            update_kwargs: dict[str, Any] = {
                "text": _optional_text(payload.get("text")),
                "tags": _text_tuple(payload.get("tags")) if "tags" in payload else None,
                "enabled": bool(payload["enabled"]) if "enabled" in payload else None,
                "manual": bool(payload["manual"]) if "manual" in payload else None,
            }
            if "confidence" in payload:
                update_kwargs["confidence"] = _optional_float(payload.get("confidence"))
            if "metadata" in payload:
                update_kwargs["metadata"] = _metadata_mapping(payload.get("metadata"))
            memory = memory_store.update(
                project_context,
                memory_id,
                **update_kwargs,
            )
        except ProjectMemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Memory not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "memory": memory_entry_to_dict(memory),
        }

    @app.delete("/api/project/memory/{memory_id}")
    async def delete_project_memory(
        memory_id: str,
        workspace: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            memory_store.delete(project_context, memory_id)
        except ProjectMemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Memory not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "deleted": True,
            "project": project_to_dict(project_context),
        }

    @app.get("/api/tools")
    async def tools(workspace: str | None = Query(default=None)) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
            )
            loaded = load_project_config(project_context.root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        statuses = build_tool_profile_statuses(
            loaded.tool_profiles,
            registry,
            include_previews=False,
        )
        return {
            "project": project_to_dict(project_context),
            "profiles": [tool_profile_status_to_dict(status) for status in statuses],
        }

    @app.post("/api/tools/sync")
    async def tools_sync(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
            )
            loaded = load_project_config(project_context.root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        statuses = build_tool_profile_statuses(
            loaded.tool_profiles,
            registry,
            include_previews=True,
        )
        return {
            "dry_run": True,
            "project": project_to_dict(project_context),
            "profiles": [tool_profile_status_to_dict(status) for status in statuses],
        }

    @app.get("/api/evals")
    async def evals(workspace: str | None = Query(default=None)) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(workspace),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            specs, errors = discover_eval_specs(project_context.root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "project": project_to_dict(project_context),
            "specs": [eval_spec_to_dict(spec) for spec in specs],
            "errors": [eval_spec_load_error_to_dict(error) for error in errors],
            "runs": [
                eval_run_to_dict(eval_run)
                for eval_run in eval_store.list_runs(project_context)
            ],
        }

    @app.get("/api/evals/runs/{eval_run_id}")
    async def get_eval_run(eval_run_id: str) -> dict[str, Any]:
        try:
            eval_run = eval_store.get_any(eval_run_id)
        except EvalRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Eval run not found") from exc
        return _eval_run_response(eval_run, store)

    @app.post("/api/evals/{eval_name}/runs")
    async def create_eval_run(
        eval_name: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            spec = load_eval_spec(project_context.root, eval_name)
            eval_runner = queue_eval if durable_dispatcher is not None else run_eval
            eval_run = await run_in_threadpool(
                eval_runner,
                runner=runner,
                eval_store=eval_store,
                project=project_context,
                spec=spec,
                harness_ids=_text_tuple(payload.get("harness_ids")),
                model=_optional_text(payload.get("model")),
                api_mode=payload.get("api_mode"),
                mode=_optional_text(payload.get("mode")),
                workspace_policy=_optional_text(payload.get("workspace_policy")),
                dry_run=bool(payload.get("dry_run")),
                repetitions=int(payload.get("repetitions") or 1),
                **(
                    {"dispatcher": durable_dispatcher}
                    if durable_dispatcher is not None
                    else {}
                ),
            )
        except EvalSpecNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Eval spec not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _eval_run_response(eval_run, store)

    @app.post("/api/project/init")
    async def project_init(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            project_context = resolve_project(
                _optional_text(payload.get("workspace")),
                data_dir=config.data_dir,
                load_config_name=False,
            )
            init_project_config(
                project_context.root,
                project_name=_optional_text(payload.get("name")),
                overwrite=bool(payload.get("overwrite")),
            )
            return _project_response(
                workspace=project_context.root,
                data_dir=config.data_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/models")
    async def models(api_mode: str = Query(default="v2")) -> dict[str, Any]:
        try:
            mode = parse_api_mode(api_mode)
        except ValueError:
            return {
                "ok": False,
                "models": _fallback_models(config),
                "source": "fallback",
                "error": "invalid api_mode; expected v1 or v2",
                "note": pass_model_env_note(),
            }
        try:
            discovery = proxy.discover_models(
                config,
                mode,
                include_compat_paths=False,
                include_fallback=False,
            )
        except Exception:
            return {
                "ok": False,
                "models": [],
                "source": f"/{mode.value}/models",
                "error": "model discovery failed",
                "note": pass_model_env_note(),
            }
        return {
            "ok": discovery.ok,
            "models": list(discovery.models),
            "source": discovery.source,
            "error": discovery.error,
            "note": pass_model_env_note(),
        }

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        status = proxy.health_check(config)
        return {
            "ok": status.ok,
            "proxy_url": status.url,
            "path": status.path,
            "status_code": status.status_code,
            "error": status.error,
        }

    @app.post("/api/preflight/run")
    async def preflight_run(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            report = runner.preflight(
                payload,
                session_id=_optional_text(payload.get("session_id")),
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"preflight": preflight_report_to_dict(report)}

    @app.post("/api/route/recommendation")
    async def route_recommendation(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            attachments = _route_recommendation_attachments(
                payload,
                attachment_store=attachment_store,
            )
            recommendation = recommend_harness_route(
                registry,
                prompt=str(payload.get("prompt") or ""),
                mode=_optional_text(payload.get("mode")),
                workspace=_optional_text(payload.get("workspace")),
                attachments=attachments,
                selected_files=_text_tuple(payload.get("selected_files")),
            )
        except AttachmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"recommendation": route_recommendation_to_dict(recommendation)}

    @app.get("/api/sessions")
    async def sessions(
        project_id: str | None = Query(default=None),
        workspace: str | None = Query(default=None),
        harness_id: str | None = Query(default=None),
        q: str | None = Query(default=None),
        include_archived: bool = Query(default=False),
        include_arena: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(workspace))
        items = store.list_sessions(
            project_id=_optional_text(project_id),
            workspace=resolved_workspace,
            harness_id=_optional_text(harness_id),
            q=_optional_text(q),
            include_archived=include_archived,
            limit=limit if include_arena else None,
        )
        if not include_arena:
            arena_session_ids = {
                arena.session_id
                for arena in arena_store.list(workspace=resolved_workspace)
            }
            items = tuple(
                session for session in items if session.id not in arena_session_ids
            )[:limit]
        return {"sessions": [_session_summary(store, session.id) for session in items]}

    @app.post("/api/sessions")
    async def create_session(payload: dict[str, Any] = Body(default_factory=dict)):
        try:
            session = runner.create_session(
                title=_optional_text(payload.get("title")),
                workspace=_optional_text(payload.get("workspace")),
                default_harness_id=str(payload.get("harness_id") or "echo"),
                default_model=_optional_text(payload.get("model")),
                default_api_mode=payload.get("api_mode") or config.default_api_mode,
                default_mode=str(payload.get("mode") or "plan"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session": _session_summary(store, session.id)}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        try:
            return bundle_to_dict(store.get_session_bundle(session_id))
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.get("/api/native/sessions")
    async def native_sessions(
        harness_id: str | None = Query(default=None),
        workspace: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
        include_external: bool = Query(default=False),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(workspace))
        resolved_project_id = _native_project_id(
            project_id=_optional_text(project_id),
            workspace=resolved_workspace,
            data_dir=config.data_dir,
        )
        refs = native_index_store.list_refs(
            harness_id=_optional_text(harness_id),
            workspace=resolved_workspace,
            project_id=resolved_project_id,
            limit=limit,
        )
        refs = _filter_external_native_refs(refs, include_external=include_external)
        return {"sessions": [native_session_ref_to_dict(ref) for ref in refs]}

    @app.post("/api/native/sessions/sync")
    async def native_sessions_sync(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(payload.get("workspace")))
        resolved_project_id = _native_project_id(
            project_id=_optional_text(payload.get("project_id")),
            workspace=resolved_workspace,
            data_dir=config.data_dir,
        )
        result = native_registry.discover(
            harness_id=_optional_text(payload.get("harness_id")),
            workspace=resolved_workspace,
            include_external=bool(payload.get("include_external")),
        )
        stored = [
            native_index_store.upsert_ref(ref, project_id=resolved_project_id)
            for ref in result.sessions
        ]
        return {
            "sessions": [native_session_ref_to_dict(ref) for ref in stored],
            "errors": [discovery_error_to_dict(error) for error in result.errors],
        }

    @app.get("/api/native/sessions/{native_ref_id}/preview")
    async def native_session_preview(
        native_ref_id: str,
        max_messages: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        ref = _native_ref_or_404(native_index_store, native_ref_id)
        connector = _native_connector_or_404(native_registry, ref.harness_id)
        messages = connector.preview(ref, max_messages=max_messages)
        return {
            "ref": native_session_ref_to_dict(ref),
            "messages": [
                _native_transcript_message_to_dict(message) for message in messages
            ],
        }

    @app.post("/api/native/sessions/{native_ref_id}/import")
    async def native_session_import(native_ref_id: str) -> dict[str, Any]:
        ref = _native_ref_or_404(native_index_store, native_ref_id)
        if not ref.can_import:
            raise HTTPException(
                status_code=400,
                detail="Native session cannot be imported",
            )
        connector = _native_connector_or_404(native_registry, ref.harness_id)
        imported = connector.import_ref(ref)
        if not imported:
            raise HTTPException(
                status_code=400,
                detail="Native session has no importable messages",
            )
        session = store.create_session(
            title=str(redact_for_storage(ref.title)),
            workspace=ref.workspace,
            default_harness_id=ref.harness_id,
            default_model=_optional_text(ref.metadata.get("model")),
            default_api_mode=config.default_api_mode,
            default_mode="plan",
            native={
                "source": "native_import",
                "native_ref_id": ref.id,
                "native_session_id": ref.native_session_id,
                "status": ref.status.value,
            },
            metadata=_native_import_session_metadata(ref),
        )
        messages = []
        skipped_count = 0
        for message in imported:
            role = _native_import_message_role(message.role)
            if role is None:
                skipped_count += 1
                store.append_event(
                    HarnessStoredEvent(
                        id=new_id("evt"),
                        session_id=session.id,
                        run_id="native_import",
                        type="native_import_warning",
                        message="Skipped native transcript item with unknown role.",
                        payload={
                            "native_ref_id": ref.id,
                            "native_session_id": ref.native_session_id,
                            "role": message.role,
                            "metadata": _redacted_mapping(message.metadata),
                        },
                        created_at=message.created_at or utc_now(),
                    )
                )
                continue
            messages.append(
                store.append_message(
                    HarnessMessage(
                        id=new_id("msg"),
                        session_id=session.id,
                        run_id=None,
                        role=role,
                        content=str(redact_for_storage(message.content)),
                        created_at=message.created_at or utc_now(),
                        harness_id=ref.harness_id,
                        metadata={
                            "source": "native_import",
                            "native_ref_id": ref.id,
                            "native_session_id": ref.native_session_id,
                            **dict(redact_for_storage(dict(message.metadata))),
                        },
                    )
                )
            )
        link = store.append_native_link(
            session.id,
            HarnessNativeLink(
                id=new_id("nlink"),
                session_id=session.id,
                harness_id=ref.harness_id,
                status=NativeSessionStatus.IMPORTED,
                created_at=utc_now(),
                updated_at=utc_now(),
                native_session_id=ref.native_session_id,
                native_ref_id=ref.id,
                source=ref.source,
                workspace=ref.workspace,
                metadata={
                    "source_status": ref.status.value,
                    "imported_message_count": len(messages),
                    "skipped_item_count": skipped_count,
                    "project_id": ref.metadata.get("project_id"),
                },
            ),
        )
        return {
            "session": _session_summary(store, session.id),
            "messages": [message_to_dict(message) for message in messages],
            "native_link": native_link_to_dict(link),
        }

    @app.post("/api/sessions/{session_id}/native/link")
    async def native_session_link(
        session_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            session = store.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        ref = _native_ref_or_404(
            native_index_store,
            _required_text(payload.get("native_ref_id"), "native_ref_id is required"),
        )
        link = store.append_native_link(
            session.id,
            HarnessNativeLink(
                id=new_id("nlink"),
                session_id=session.id,
                harness_id=ref.harness_id,
                status=NativeSessionStatus.LINKED,
                created_at=utc_now(),
                updated_at=utc_now(),
                native_session_id=ref.native_session_id,
                native_ref_id=ref.id,
                source=ref.source,
                workspace=ref.workspace,
                metadata={
                    "source_status": ref.status.value,
                    "project_id": ref.metadata.get("project_id"),
                    "can_resume": ref.can_resume,
                    "resume_reason": ref.resume_reason,
                },
            ),
        )
        return {
            "session": _session_summary(store, session.id),
            "native_link": native_link_to_dict(link),
        }

    @app.post("/api/native/processes/start")
    async def native_process_start(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        run = None
        try:
            session = store.get_session(
                _required_text(payload.get("session_id"), "session_id is required")
            )
            options = _native_process_start_options(
                payload=payload,
                session=session,
                config=config,
                native_registry=native_registry,
                native_index_store=native_index_store,
                store=store,
                attachment_store=attachment_store,
            )
            run = store.create_run(
                session_id=session.id,
                harness_id=options["harness_id"],
                status="running",
                prompt=options["prompt"],
                model=options["model"],
                api_mode=options["api_mode"],
                capability=options["capability"],
                mode=options["mode"],
                workspace=options["workspace"],
                invocation_mode=HarnessInvocationMode.NATIVE,
                started_at=utc_now(),
                metadata=_native_process_run_metadata(options),
            )
            if options["action"] == "start" and options["prompt"]:
                store.append_message(
                    HarnessMessage(
                        id=new_id("msg"),
                        session_id=session.id,
                        run_id=run.id,
                        role="user",
                        content=options["prompt"],
                        created_at=utc_now(),
                        harness_id=options["harness_id"],
                        model=options["model"],
                        api_mode=options["api_mode"],
                    )
                )
            session_patch: dict[str, Any] = {
                "default_harness_id": options["harness_id"],
                "default_model": options["model"],
                "default_api_mode": options["api_mode"],
                "default_mode": options["mode"],
                "workspace": options["workspace"],
            }
            if (
                session.title == "Untitled session"
                and options["action"] == "start"
                and options["prompt"]
            ):
                session_patch["title"] = title_from_prompt(options["prompt"])
            store.update_session(session.id, **session_patch)
            process_ref = native_process_manager.start(
                options["plan"],
                session_id=session.id,
                workspace=options["workspace"],
                run_id=run.id,
            )
            run = store.update_run(
                run.id,
                command=process_ref.display_command,
                native_session_id=options["native_session_id"],
                metadata=_native_process_run_metadata(options, process_ref),
            )
            native_link = _append_native_process_link(
                store=store,
                session=session,
                options=options,
                process_ref=process_ref,
            )
            provenance = _build_current_run_provenance(
                store=store,
                registry=registry,
                config=config,
                run=run,
            )
            run = store.update_run(
                run.id,
                metadata={
                    **dict(run.metadata),
                    "provenance": run_provenance_to_dict(provenance),
                },
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except HTTPException:
            raise
        except (NativeProcessStartError, ValueError) as exc:
            if run is not None:
                store.update_run(
                    run.id,
                    status="failed",
                    error=str(exc),
                    finished_at=utc_now(),
                )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "process": native_process_ref_to_dict(process_ref),
            "run": run_to_dict(run),
            "native_link": native_link_to_dict(native_link),
        }

    @app.post("/api/native/processes/{process_id}/input")
    async def native_process_input(
        process_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        message = None
        try:
            data = payload.get("data", payload.get("text", ""))
            process_ref = native_process_manager.write(process_id, str(data))
            run = _sync_native_process_run(store, process_ref)
            message_content = _optional_text(payload.get("message"))
            if message_content is not None and run is not None:
                message = store.append_message(
                    HarnessMessage(
                        id=new_id("msg"),
                        session_id=run.session_id,
                        run_id=run.id,
                        role="user",
                        content=str(redact_for_storage(message_content)),
                        created_at=utc_now(),
                        harness_id=run.harness_id,
                        model=run.model,
                        api_mode=run.api_mode,
                        metadata={"source": "native_stdin"},
                    )
                )
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "process": native_process_ref_to_dict(process_ref),
            "run": run_to_dict(run) if run is not None else None,
            "message": message_to_dict(message) if message is not None else None,
        }

    @app.get("/api/native/processes/{process_id}/output")
    async def native_process_output(
        process_id: str,
        cursor: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            chunk = native_process_manager.read_since(process_id, cursor)
            process_ref = native_process_manager.status(process_id)
            run = _sync_native_process_run(store, process_ref)
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        payload = native_output_chunk_to_dict(chunk)
        payload["run"] = run_to_dict(run) if run is not None else None
        return payload

    @app.get("/api/native/processes/{process_id}")
    async def native_process_status(process_id: str) -> dict[str, Any]:
        try:
            process_ref = native_process_manager.status(process_id)
            run = _sync_native_process_run(store, process_ref)
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        return {
            "process": native_process_ref_to_dict(process_ref),
            "run": run_to_dict(run) if run is not None else None,
        }

    @app.delete("/api/native/processes/{process_id}")
    async def native_process_stop(process_id: str) -> dict[str, Any]:
        try:
            process_ref = native_process_manager.stop(process_id)
            run = _sync_native_process_run(store, process_ref)
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        return {
            "stopped": True,
            "process": native_process_ref_to_dict(process_ref),
            "run": run_to_dict(run) if run is not None else None,
        }

    @app.patch("/api/sessions/{session_id}")
    async def update_session(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            patch = _session_patch(payload)
            session = store.update_session(session_id, **patch)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session": _session_summary(store, session.id)}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        try:
            store.delete_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return {"deleted": True}

    @app.post("/api/sessions/{session_id}/attachments")
    async def create_attachment(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            session = store.get_session(session_id)
            attachment = attachment_store.create_upload(
                session_id=session.id,
                project_id=_session_project_id(session),
                filename=str(payload.get("filename") or ""),
                data=_decode_attachment_payload(payload.get("data_base64")),
                mime_type=_optional_text(payload.get("mime_type")),
                source=_optional_text(payload.get("source")) or "upload",
                metadata=_metadata_mapping(payload.get("metadata")),
                limits=_attachment_limits(session),
            )
        except (SessionNotFoundError, AttachmentSessionNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except (AttachmentValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"attachment": _attachment_response(registry, attachment)}

    @app.post("/api/sessions/{session_id}/attachments/workspace")
    async def create_workspace_attachment(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            session = store.get_session(session_id)
            workspace_root = _attachment_workspace(session, payload)
            attachment = attachment_store.create_workspace_reference(
                session_id=session.id,
                project_id=_session_project_id(session)
                or resolve_project(workspace_root, data_dir=config.data_dir).id,
                workspace_root=workspace_root,
                path=_required_text(payload.get("path"), "path is required"),
                mime_type=_optional_text(payload.get("mime_type")),
                metadata=_metadata_mapping(payload.get("metadata")),
                limits=_attachment_limits(session, workspace_root=workspace_root),
            )
        except (SessionNotFoundError, AttachmentSessionNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except (AttachmentValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"attachment": _attachment_response(registry, attachment)}

    @app.get("/api/sessions/{session_id}/attachments")
    async def session_attachments(session_id: str) -> dict[str, Any]:
        try:
            store.get_session(session_id)
            attachments = attachment_store.list_session_attachments(session_id)
        except (SessionNotFoundError, AttachmentSessionNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return {
            "attachments": [
                _attachment_response(registry, attachment) for attachment in attachments
            ]
        }

    @app.get("/api/attachments/{attachment_id}/metadata")
    async def attachment_metadata(attachment_id: str) -> dict[str, Any]:
        try:
            attachment = attachment_store.get_attachment(attachment_id)
        except AttachmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        return {"attachment": _attachment_response(registry, attachment)}

    @app.get("/api/attachments/{attachment_id}")
    async def attachment_blob(attachment_id: str) -> Response:
        try:
            attachment = attachment_store.get_attachment(attachment_id)
            data = attachment_store.read_blob(attachment_id)
        except AttachmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        except AttachmentValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type=attachment.mime_type,
            headers={
                "Content-Disposition": _content_disposition(attachment.filename),
                "X-GPT2GIGA-Attachment-Id": attachment.id,
            },
        )

    @app.delete("/api/attachments/{attachment_id}")
    async def delete_attachment(attachment_id: str) -> dict[str, Any]:
        try:
            attachment_store.delete_attachment(attachment_id)
        except AttachmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        return {"deleted": True}

    @app.get("/api/workspace/tree")
    async def workspace_tree_endpoint(
        workspace: str | None = Query(default=None),
        q: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            workspace_root = _workspace_api_root(workspace, config.data_dir)
            files = workspace_tree(
                workspace_root,
                query=q,
                limits=_workspace_limits(workspace_root),
                result_limit=limit,
            )
        except (AttachmentValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "workspace": workspace_root,
            "q": _optional_text(q) or "",
            "files": files,
        }

    @app.get("/api/workspace/file/metadata")
    async def workspace_file_metadata_endpoint(
        workspace: str | None = Query(default=None),
        path: str = Query(...),
    ) -> dict[str, Any]:
        try:
            workspace_root = _workspace_api_root(workspace, config.data_dir)
            metadata = workspace_file_metadata(
                workspace_root,
                path,
                limits=_workspace_limits(workspace_root),
            )
        except (AttachmentValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "workspace": workspace_root,
            "file": metadata,
        }

    async def _start_headless_run(
        session_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRun:
        if durable_dispatcher is not None:
            idempotency_key = str(
                payload.get("idempotency_key") or f"ui_{new_id('submit')}"
            )
            submission = await run_in_threadpool(
                durable_dispatcher.submit,
                session_id,
                payload,
                idempotency_key=idempotency_key,
                origin="manual",
            )
            return submission.queued.run
        before_run_ids = {run.id for run in store.list_runs(session_id)}
        cancel_event = threading.Event()
        task = asyncio.create_task(
            run_in_threadpool(
                runner.run_in_session,
                session_id,
                payload,
                cancel_event=cancel_event,
            )
        )
        run = await _wait_for_started_run(
            store=store,
            session_id=session_id,
            before_run_ids=before_run_ids,
            task=task,
        )
        active_headless_runs[run.id] = _ActiveHeadlessRun(
            task=task,
            cancel_event=cancel_event,
        )
        task.add_done_callback(
            lambda _task, run_id=run.id: active_headless_runs.pop(run_id, None)
        )
        return run

    def _run_start_response(run: HarnessRun) -> dict[str, Any]:
        events = store.list_events(run.session_id, run_id=run.id)
        payload = {
            "session": _session_summary(store, run.session_id),
            "run": run_to_dict(run),
            "events": [_event_response(event) for event in events],
            "stream_url": f"/api/runs/{run.id}/events/stream",
            "cancel_url": f"/api/runs/{run.id}/cancel",
        }
        job = runtime_store.find_job_for_run(run.id) if runtime_store else None
        if job is not None:
            payload["job"] = job_to_dict(job)
        return payload

    def _run_provenance_response(run: HarnessRun) -> dict[str, Any]:
        provenance = _build_current_run_provenance(
            store=store,
            registry=registry,
            config=config,
            run=run,
        )
        return {
            "run": run_to_dict(run),
            "provenance": run_provenance_to_dict(provenance),
        }

    @app.post("/api/sessions/run/start")
    async def create_session_and_start_run(
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            harness_id = str(payload.get("harness_id") or "echo")
            registry.get(harness_id)
            session = runner.create_session(
                title=_optional_text(payload.get("title"))
                or title_from_prompt(str(payload.get("prompt") or "")),
                workspace=_optional_text(payload.get("workspace")),
                default_harness_id=harness_id,
                default_model=_optional_text(payload.get("model")),
                default_api_mode=payload.get("api_mode") or config.default_api_mode,
                default_mode=str(payload.get("mode") or "plan"),
            )
            run = await _start_headless_run(session.id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return _run_start_response(run)

    @app.post("/api/sessions/{session_id}/run/start")
    async def start_run_in_session(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            store.get_session(session_id)
            run = await _start_headless_run(session_id, payload)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return _run_start_response(run)

    @app.get("/api/runs/{run_id}/events/stream")
    async def run_events_stream(
        run_id: str,
        after_id: str | None = Query(default=None),
    ) -> StreamingResponse:
        try:
            store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

        async def stream_events():
            last_id = _optional_text(after_id)
            terminal_event_seen = False
            while True:
                try:
                    current_run = store.get_run(run_id)
                    events = store.list_events(
                        current_run.session_id,
                        run_id=run_id,
                        after_id=last_id,
                    )
                except (RunNotFoundError, SessionNotFoundError):
                    break
                for event in events:
                    last_id = event.id
                    if event.type == HarnessEventType.RUN_FINISHED.value:
                        terminal_event_seen = True
                    yield _sse_event(event)
                if _run_status_is_terminal(current_run.status) and not events:
                    if not terminal_event_seen:
                        terminal_event_seen = any(
                            event.type == HarnessEventType.RUN_FINISHED.value
                            for event in store.list_events(
                                current_run.session_id,
                                run_id=run_id,
                            )
                        )
                    if not terminal_event_seen:
                        yield _sse_event(
                            HarnessStoredEvent(
                                id=f"evt_terminal_{current_run.id}",
                                session_id=current_run.session_id,
                                run_id=current_run.id,
                                type=HarnessEventType.RUN_FINISHED.value,
                                message="Harness run reached a terminal state.",
                                payload={
                                    "status": current_run.status,
                                    "synthetic": True,
                                },
                                created_at=(
                                    current_run.finished_at
                                    or current_run.updated_at
                                    or current_run.created_at
                                ),
                            )
                        )
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        if _run_status_is_terminal(run.status):
            return {
                "cancel_requested": False,
                "active": False,
                "run": run_to_dict(run),
            }
        durable_job = (
            runtime_store.find_job_for_run(run.id)
            if runtime_store is not None
            else None
        )
        if durable_job is not None:
            job = runtime_store.request_cancel(durable_job.id)
            attempts = runtime_store.list_attempts(job.id)
            active_attempt = next(
                (attempt for attempt in reversed(attempts) if attempt.run_id == run.id),
                None,
            )
            if active_attempt is None and job.status.value == "queued":
                job = runtime_store.transition_job(
                    job.id, "canceled", expected_status="queued"
                )
                run = store.update_run(
                    run.id,
                    status="canceled",
                    finished_at=utc_now(),
                    error="Harness run canceled before worker claim.",
                    metadata={**dict(run.metadata), "cancel_requested": True},
                )
            else:
                run = store.update_run(
                    run.id,
                    metadata={**dict(run.metadata), "cancel_requested": True},
                )
            if not bool(run.metadata.get("cancel_event_recorded")):
                store.append_event(
                    HarnessStoredEvent(
                        id=new_id("evt"),
                        session_id=run.session_id,
                        run_id=run.id,
                        type=HarnessEventType.CANCEL_REQUESTED.value,
                        message="Harness run cancellation requested.",
                        payload={
                            "job_id": job.id,
                            "active": active_attempt is not None,
                        },
                        created_at=utc_now(),
                        trace_id=job.id,
                        job_id=job.id,
                        attempt_id=active_attempt.id if active_attempt else None,
                    )
                )
            return {
                "cancel_requested": True,
                "active": active_attempt is not None,
                "job": job_to_dict(job),
                "run": run_to_dict(run),
            }
        active = active_headless_runs.get(run.id)
        if active is not None and active.task.done():
            active = None
        # A headless task can finish and remove itself from the active map after
        # the first read. Re-read before applying a synthetic cancellation so a
        # completed run can never be overwritten with a stale canceled status.
        run = store.get_run(run.id)
        if _run_status_is_terminal(run.status):
            return {
                "cancel_requested": False,
                "active": False,
                "run": run_to_dict(run),
            }
        already_requested = bool(run.metadata.get("cancel_requested"))
        if active is not None:
            active.cancel_event.set()
            metadata = {**dict(run.metadata), "cancel_requested": True}
            run = store.update_run(run.id, metadata=metadata)
        else:
            metadata = {**dict(run.metadata), "cancel_requested": True}
            run = store.update_run(
                run.id,
                status="canceled",
                finished_at=utc_now(),
                error="Harness run canceled.",
                metadata=metadata,
            )
        if not already_requested:
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type=HarnessEventType.CANCEL_REQUESTED.value,
                    message="Harness run cancellation requested.",
                    payload={"active": active is not None},
                    created_at=utc_now(),
                )
            )
            if active is None:
                store.append_event(
                    HarnessStoredEvent(
                        id=new_id("evt"),
                        session_id=run.session_id,
                        run_id=run.id,
                        type=HarnessEventType.RUN_CANCELED.value,
                        message="Harness run canceled.",
                        payload={},
                        created_at=utc_now(),
                    )
                )
                store.append_event(
                    HarnessStoredEvent(
                        id=new_id("evt"),
                        session_id=run.session_id,
                        run_id=run.id,
                        type=HarnessEventType.RUN_FINISHED.value,
                        message="Harness run finished.",
                        payload={"status": "canceled"},
                        created_at=utc_now(),
                    )
                )
        return {
            "cancel_requested": True,
            "active": active is not None,
            "run": run_to_dict(run),
        }

    @app.get("/api/runs/{run_id}/diff")
    async def run_diff(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return {"run": run_to_dict(run), "diff": run_diff_response(run.metadata)}

    @app.get("/api/runs/{run_id}/pr")
    async def run_pr_artifact(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        artifact = build_pr_artifact(run)
        return {
            "run": run_to_dict(run),
            "pr_artifact": pr_artifact_to_dict(artifact),
        }

    @app.get("/api/runs/{run_id}/provenance")
    async def run_provenance(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return _run_provenance_response(run)

    @app.post("/api/runs/{run_id}/replay")
    async def replay_run(
        run_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
            raw_request = _latest_raw_request_for_run(store, run)
            replay_payload = build_replay_request(run, raw_request=raw_request)
            if "stream" in payload:
                replay_payload["stream"] = bool(payload.get("stream"))
            result = runner.run_in_session(run.session_id, replay_payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = result.to_dict()
        response["source_run"] = run_to_dict(run)
        response["replay_request"] = replay_payload
        return response

    @app.post("/api/runs/{run_id}/fork")
    async def fork_run(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
            session = _fork_session_from_run(store, run)
            bundle = store.get_session_bundle(session.id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return {
            "source_run": run_to_dict(run),
            "session": _session_summary(store, session.id),
            "bundle": bundle_to_dict(bundle),
        }

    @app.get("/api/runs/{run_id}/patch")
    async def run_patch(run_id: str) -> Response:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        artifact = build_pr_artifact(run)
        return Response(content=artifact.patch, media_type="text/plain")

    @app.post("/api/runs/{run_id}/apply", response_model=None)
    async def apply_run_patch(
        run_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any] | JSONResponse:
        try:
            run = store.get_run(run_id)
            approval_response = _approval_gate(
                PermissionAction.GIT_APPLY,
                run,
                reason="Apply an isolated worktree diff to the source checkout.",
                preview={
                    "branch_name": _optional_text(payload.get("branch_name")),
                    "changed_files": run_diff_response(run.metadata).get(
                        "changed_files", []
                    ),
                },
            )
            if approval_response is not None:
                return approval_response
            workspace_execution = apply_run_diff(
                run.metadata,
                branch_name=_optional_text(payload.get("branch_name")),
            )
            metadata = {
                **dict(run.metadata),
                "workspace_execution": workspace_execution,
            }
            run = store.update_run(run.id, metadata=metadata)
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type="worktree_applied",
                    message="Applied isolated worktree diff to the source checkout.",
                    payload={
                        "changed_files": workspace_execution.get("changed_files", []),
                        "applied_branch": workspace_execution.get("applied_branch"),
                    },
                    created_at=utc_now(),
                )
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except WorktreeConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorktreeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "applied": True,
            "run": run_to_dict(run),
            "diff": run_diff_response(run.metadata),
        }

    @app.post("/api/runs/{run_id}/branch", response_model=None)
    async def create_run_branch(
        run_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any] | JSONResponse:
        try:
            run = store.get_run(run_id)
            approval_response = _approval_gate(
                PermissionAction.GIT_BRANCH_CREATE,
                run,
                reason="Create a local branch from the isolated run patch.",
                preview={
                    "branch_name": _optional_text(payload.get("branch_name")),
                    "changed_files": run_diff_response(run.metadata).get(
                        "changed_files", []
                    ),
                },
            )
            if approval_response is not None:
                return approval_response
            branch = create_pr_branch(
                run,
                branch_name=_optional_text(payload.get("branch_name")),
            )
            metadata = {
                **dict(run.metadata),
                "workspace_execution": branch["workspace_execution"],
            }
            run = store.update_run(run.id, metadata=metadata)
            artifact = build_pr_artifact(run)
            metadata = {
                **dict(run.metadata),
                "pr_artifact": pr_artifact_to_dict(artifact),
            }
            run = store.update_run(run.id, metadata=metadata)
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type="pr_branch_created",
                    message="Created local branch from run patch.",
                    payload={"branch_name": branch["branch_name"]},
                    created_at=utc_now(),
                )
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except WorktreeConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorktreeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "branch_created": True,
            "branch_name": branch["branch_name"],
            "run": run_to_dict(run),
            "diff": run_diff_response(run.metadata),
            "pr_artifact": pr_artifact_to_dict(build_pr_artifact(run)),
        }

    @app.post("/api/runs/{run_id}/discard")
    async def discard_run_worktree_endpoint(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
            workspace_execution = discard_run_worktree(run.metadata)
            metadata = {
                **dict(run.metadata),
                "workspace_execution": workspace_execution,
            }
            run = store.update_run(run.id, metadata=metadata)
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type="worktree_discarded",
                    message="Discarded isolated worktree for this run.",
                    payload={"worktree_path": workspace_execution.get("worktree_path")},
                    created_at=utc_now(),
                )
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except WorktreeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "discarded": True,
            "run": run_to_dict(run),
            "diff": run_diff_response(run.metadata),
        }

    @app.post("/api/runs/{run_id}/open-worktree")
    async def open_run_worktree(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
            response = open_worktree_response(run.metadata)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return {"run": run_to_dict(run), "worktree": response}

    @app.post("/api/sessions/run")
    async def create_session_and_run(
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            result = runner.create_and_run(payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @app.post("/api/sessions/{session_id}/run")
    async def run_in_session(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            result = runner.run_in_session(session_id, payload)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        run_id: str | None = Query(default=None),
        after_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            events = store.list_events(session_id, run_id=run_id, after_id=after_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return {
            "events": [
                {
                    "id": event.id,
                    "session_id": event.session_id,
                    "run_id": event.run_id,
                    "type": event.type,
                    "message": event.message,
                    "payload": dict(event.payload),
                    "created_at": event.created_at,
                }
                for event in events
            ]
        }

    @app.get("/api/arena/runs")
    async def list_arena_runs(
        workspace: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(workspace))
        arenas = arena_store.list(workspace=resolved_workspace, limit=limit)
        return {"arenas": [_arena_response(arena, store)["arena"] for arena in arenas]}

    @app.post("/api/arena/runs")
    async def create_arena_run(
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            arena_runner = queue_arena if durable_dispatcher is not None else run_arena
            arena = await run_in_threadpool(
                arena_runner,
                runner=runner,
                arena_store=arena_store,
                payload=payload,
                session_id=_optional_text(payload.get("session_id")),
                **(
                    {"dispatcher": durable_dispatcher}
                    if durable_dispatcher is not None
                    else {}
                ),
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _arena_response(arena, store)

    @app.get("/api/arena/runs/{arena_id}")
    async def get_arena_run(arena_id: str) -> dict[str, Any]:
        try:
            arena = arena_store.get(arena_id)
        except ArenaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Arena run not found") from exc
        return _arena_response(arena, store)

    @app.get("/api/arena/runs/{arena_id}/events/stream")
    async def arena_events_stream(
        arena_id: str,
        after_id: str | None = Query(default=None),
    ) -> StreamingResponse:
        try:
            arena_store.get(arena_id)
        except ArenaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Arena run not found") from exc

        async def stream_events():
            last_id = _optional_text(after_id)
            while True:
                try:
                    current_arena = arena_store.get(arena_id)
                except ArenaNotFoundError:
                    break
                events = _arena_events(current_arena, store, after_id=last_id)
                for child, event in events:
                    last_id = event.id
                    yield _arena_sse_event(current_arena, child, event)
                if _arena_status_is_terminal(current_arena.status) and not events:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/run")
    async def run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        harness_id = str(payload.get("harness_id") or "echo")
        try:
            harness = registry.get(harness_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        extra = dict(extra)
        if bool(payload.get("dry_run")):
            extra["dry_run"] = True
        try:
            api_mode = parse_api_mode(payload.get("api_mode"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid api_mode; expected v1 or v2",
            ) from exc
        try:
            capability = parse_capability(
                payload.get("capability") or HarnessCapability.CHAT_COMPLETIONS.value
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid capability",
            ) from exc
        try:
            builtin_tools = parse_builtin_tools(payload.get("builtin_tools"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if builtin_tools and api_mode is not GigaChatApiMode.V2:
            raise HTTPException(
                status_code=400,
                detail="built-in tools require /v2/chat/completions",
            )
        unsupported_builtin_tools = [
            tool.value
            for tool in builtin_tools
            if tool not in set(getattr(harness.spec(), "supported_builtin_tools", ()))
        ]
        if unsupported_builtin_tools:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{harness_id} does not support built-in tools: "
                    + ", ".join(unsupported_builtin_tools)
                ),
            )
        request = HarnessRequest(
            prompt=str(payload.get("prompt") or ""),
            model=_optional_text(payload.get("model")),
            api_mode=api_mode,
            capability=capability,
            mode=str(payload.get("mode") or "plan"),
            stream=bool(payload.get("stream")),
            workspace=resolve_workspace(_optional_text(payload.get("workspace"))),
            builtin_tools=builtin_tools,
            extra=extra,
        )
        preflight = build_preflight_report(
            prompt=request.prompt,
            workspace=request.workspace,
            data_dir=config.data_dir,
        )
        if preflight.hard_block:
            raise HTTPException(
                status_code=400,
                detail=format_preflight_block_message(preflight),
            )
        try:
            result = harness.run(request, config.to_context())
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Harness run failed",
            ) from exc
        return result_to_dict(result)

    app.include_router(agents_router)
    app.include_router(automation_router)
    app.include_router(approvals_router)
    app.include_router(evaluate_router)
    app.include_router(tools_router)
    app.include_router(workflows_router)
    app.include_router(runs_router)
    app.include_router(schedules_router)
    app.include_router(create_file_preview_router(config.data_dir))
    # The shell catch-all must remain last so unknown API and asset paths never
    # become HTML responses.
    app.include_router(create_shell_router(ui_security))
    return app


def validate_ui_bind(host: str, *, allow_remote: bool) -> None:
    """Reject unsafe remote UI binding unless explicitly allowed."""
    if not is_loopback_host(host) and not allow_remote:
        raise ValueError(
            f"Refusing to bind UI to {host} without --allow-remote. "
            "The UI may expose local harness execution."
        )


def _build_current_run_provenance(
    *,
    store: HarnessSessionStore,
    registry: HarnessRegistry,
    config: HarnessConfig,
    run: HarnessRun,
):
    session = store.get_session(run.session_id)
    try:
        spec = registry.get(run.harness_id).spec()
    except KeyError:
        spec = None
    return build_run_provenance(
        run,
        session=session,
        spec=spec,
        raw_requests=store.list_raw_requests(run.session_id),
        raw_responses=store.list_raw_responses(run.session_id),
        events=store.list_events(run.session_id, run_id=run.id),
        data_dir=config.data_dir,
    )


def _latest_raw_request_for_run(
    store: HarnessSessionStore,
    run: HarnessRun,
):
    records = [
        record
        for record in store.list_raw_requests(run.session_id)
        if record.run_id == run.id
    ]
    return records[-1] if records else None


def _fork_session_from_run(
    store: HarnessSessionStore,
    run: HarnessRun,
) -> HarnessSession:
    source = store.get_session(run.session_id)
    metadata = {
        **dict(source.metadata),
        "forked_from_session_id": source.id,
        "forked_from_run_id": run.id,
    }
    fork = store.create_session(
        title=f"Fork: {source.title}",
        workspace=run.workspace or source.workspace,
        default_harness_id=run.harness_id,
        default_model=run.model,
        default_api_mode=run.api_mode,
        default_mode=run.mode,
        metadata=metadata,
    )
    for message in _messages_through_run(store.list_messages(source.id), run.id):
        store.append_message(
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
    return fork


def _messages_through_run(
    messages: tuple[HarnessMessage, ...],
    run_id: str,
) -> tuple[HarnessMessage, ...]:
    selected: list[HarnessMessage] = []
    seen_target_run = False
    for message in messages:
        selected.append(message)
        if message.run_id == run_id:
            seen_target_run = True
            if message.role in {"assistant", "error"}:
                break
        elif seen_target_run:
            selected.pop()
            break
    return tuple(selected)


async def _wait_for_started_run(
    *,
    store: HarnessSessionStore,
    session_id: str,
    before_run_ids: set[str],
    task: asyncio.Task[Any],
) -> HarnessRun:
    for _ in range(200):
        runs = [
            run for run in store.list_runs(session_id) if run.id not in before_run_ids
        ]
        if runs:
            return runs[-1]
        if task.done():
            task.result()
            break
        await asyncio.sleep(0.01)
    raise RuntimeError("Harness run did not start")


def _event_response(event: HarnessStoredEvent) -> dict[str, Any]:
    return event_to_dict(event)


def _route_recommendation_attachments(
    payload: Mapping[str, Any],
    *,
    attachment_store: FilesystemAttachmentStore,
) -> tuple[Mapping[str, Any], ...]:
    attachments: list[Mapping[str, Any]] = []
    raw_attachments = payload.get("attachments")
    if raw_attachments is not None:
        if not isinstance(raw_attachments, list):
            raise ValueError("attachments must be a list")
        attachments.extend(
            dict(item) for item in raw_attachments if isinstance(item, Mapping)
        )
    raw_ids = payload.get("attachment_ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, list):
            raise ValueError("attachment_ids must be a list")
        for attachment_id in _text_tuple(raw_ids):
            attachment = attachment_store.get_attachment(attachment_id)
            attachment_payload = attachment_to_dict(attachment)
            attachment_payload.pop("storage_path", None)
            attachments.append(attachment_payload)
    return tuple(attachments)


def _text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    items: list[str] = []
    for item in value:
        text = _optional_text(item)
        if text is not None:
            items.append(text)
    return tuple(items)


def _sse_event(event: HarnessStoredEvent) -> str:
    payload = _event_response(event)
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event.id}\ndata: {data}\n\n"


def _arena_response(
    arena: HarnessArenaRun,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    payload = arena_to_dict(arena)
    payload["child_runs"] = [
        _arena_child_response(child, store) for child in arena.child_runs
    ]
    try:
        payload["session"] = _session_summary(store, arena.session_id)
    except SessionNotFoundError:
        payload["session"] = None
    return {"arena": payload}


def _eval_run_response(
    eval_run,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    payload = eval_run_to_dict(eval_run)
    try:
        payload["session"] = _session_summary(store, eval_run.session_id)
    except SessionNotFoundError:
        payload["session"] = None
    return {"eval_run": payload}


def _arena_child_response(
    child: HarnessArenaChildRun,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    payload = arena_child_to_dict(child)
    if child.run_id is None:
        return payload
    try:
        run = store.get_run(child.run_id)
        payload["run"] = run_to_dict(run)
        payload["message"] = _last_run_message(store, run)
        payload["event_count"] = len(store.list_events(run.session_id, run_id=run.id))
    except (RunNotFoundError, SessionNotFoundError):
        payload["missing"] = True
    return payload


def _last_run_message(
    store: HarnessSessionStore,
    run: HarnessRun,
) -> dict[str, Any] | None:
    messages = [
        message
        for message in store.list_messages(run.session_id)
        if message.run_id == run.id and message.role in {"assistant", "error"}
    ]
    if not messages:
        return None
    return message_to_dict(messages[-1])


def _arena_events(
    arena: HarnessArenaRun,
    store: HarnessSessionStore,
    *,
    after_id: str | None = None,
) -> list[tuple[HarnessArenaChildRun, HarnessStoredEvent]]:
    events: list[tuple[HarnessArenaChildRun, HarnessStoredEvent]] = []
    for child in arena.child_runs:
        if child.run_id is None or child.session_id is None:
            continue
        try:
            child_events = store.list_events(child.session_id, run_id=child.run_id)
        except SessionNotFoundError:
            continue
        events.extend((child, event) for event in child_events)
    events.sort(key=lambda item: (item[1].created_at, item[0].index, item[1].id))
    if after_id is None:
        return events
    seen = False
    filtered: list[tuple[HarnessArenaChildRun, HarnessStoredEvent]] = []
    for item in events:
        if seen:
            filtered.append(item)
        elif item[1].id == after_id:
            seen = True
    return filtered


def _arena_sse_event(
    arena: HarnessArenaRun,
    child: HarnessArenaChildRun,
    event: HarnessStoredEvent,
) -> str:
    payload = {
        "id": event.id,
        "arena_id": arena.id,
        "child_index": child.index,
        "harness_id": child.harness_id,
        "type": event.type,
        "message": event.message,
        "payload": dict(event.payload),
        "created_at": event.created_at,
        "event": event_to_dict(event),
    }
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event.id}\ndata: {data}\n\n"


def _run_status_is_terminal(status: str) -> bool:
    return status in {"succeeded", "failed", "canceled"}


def _arena_status_is_terminal(status: str) -> bool:
    return status in {"succeeded", "failed", "partial", "canceled"}


def _native_project_id(
    *,
    project_id: str | None,
    workspace: str | None,
    data_dir: str,
) -> str | None:
    if project_id is not None:
        return project_id
    if workspace is None:
        return None
    return resolve_project(workspace, data_dir=data_dir).id


def _filter_external_native_refs(
    refs: tuple[NativeSessionRef, ...],
    *,
    include_external: bool,
) -> tuple[NativeSessionRef, ...]:
    if include_external:
        return refs
    external_statuses = {
        NativeSessionStatus.EXTERNAL_NATIVE,
        NativeSessionStatus.READONLY,
    }
    return tuple(ref for ref in refs if ref.status not in external_statuses)


def _native_ref_or_404(
    native_index_store: NativeSessionIndexStore,
    native_ref_id: str,
) -> NativeSessionRef:
    ref = native_index_store.get_ref(native_ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="Native session not found")
    return ref


def _native_connector_or_404(
    native_registry: NativeHistoryConnectorRegistry,
    harness_id: str,
):
    try:
        return native_registry.get(harness_id)
    except UnknownNativeHistoryConnectorError as exc:
        raise HTTPException(
            status_code=404,
            detail="Native connector not found",
        ) from exc


def _native_process_start_options(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    config: HarnessConfig,
    native_registry: NativeHistoryConnectorRegistry,
    native_index_store: NativeSessionIndexStore,
    store: HarnessSessionStore,
    attachment_store: FilesystemAttachmentStore,
) -> dict[str, Any]:
    action = str(payload.get("action") or "start").strip().lower()
    if action not in {"start", "resume"}:
        raise ValueError("action must be start or resume")
    if action == "resume":
        return _native_process_resume_options(
            payload=payload,
            session=session,
            config=config,
            native_registry=native_registry,
            native_index_store=native_index_store,
            store=store,
        )
    return _native_process_new_options(
        payload=payload,
        session=session,
        config=config,
        native_registry=native_registry,
        attachment_store=attachment_store,
    )


def _native_process_new_options(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    config: HarnessConfig,
    native_registry: NativeHistoryConnectorRegistry,
    attachment_store: FilesystemAttachmentStore,
) -> dict[str, Any]:
    harness_id = _required_text(
        payload.get("harness_id") or session.default_harness_id,
        "harness_id is required",
    )
    connector = _native_connector_or_404(native_registry, harness_id)
    api_mode = parse_api_mode(payload.get("api_mode") or session.default_api_mode)
    capability = parse_capability(
        payload.get("capability") or HarnessCapability.AGENT_CLI.value
    )
    workspace = resolve_workspace(
        _optional_text(payload.get("workspace")) or session.workspace
    )
    prompt = str(payload.get("prompt") or "")
    model = _optional_text(payload.get("model")) or session.default_model
    mode = str(payload.get("mode") or session.default_mode)
    attachment_ids = _attachment_ids(payload.get("attachment_ids"))
    attachments = _load_native_attachments(
        attachment_store,
        session.id,
        attachment_ids,
    )
    preflight = build_preflight_report(
        prompt=prompt,
        workspace=workspace,
        attachments=attachments,
        data_dir=config.data_dir,
    )
    if preflight.hard_block:
        raise PreflightBlockedError(preflight)
    preflight_payload = preflight_report_to_dict(preflight)
    attachment_payloads = tuple(
        _native_attachment_metadata(attachment) for attachment in attachments
    )
    attachment_render_plan = (
        render_attachments_for_harness(
            harness_id,
            attachments,
            attachment_store,
            prompt=prompt,
        )
        if attachments
        else None
    )
    attachment_render_plan_payload = (
        render_plan_to_dict(attachment_render_plan)
        if attachment_render_plan is not None
        else None
    )
    extra = _native_request_extra(
        _metadata_mapping(payload.get("extra")),
        attachment_payloads,
        attachment_render_plan_payload,
    )
    extra["preflight"] = preflight_payload
    request = HarnessRequest(
        prompt=prompt,
        model=model,
        api_mode=api_mode,
        capability=capability,
        mode=mode,
        invocation_mode=HarnessInvocationMode.NATIVE,
        workspace=workspace,
        session_id=session.id,
        attachments=attachment_payloads,
        attachment_render_plan=attachment_render_plan_payload,
        extra=extra,
    )
    plan = connector.build_start_command(request, config.to_context())
    native_session_id = _native_session_id_from_plan(plan)
    return {
        "action": "start",
        "plan": plan,
        "harness_id": harness_id,
        "prompt": prompt,
        "model": model,
        "api_mode": api_mode,
        "capability": capability,
        "mode": mode,
        "workspace": workspace,
        "native_ref": None,
        "native_session_id": native_session_id,
        "attachment_ids": attachment_ids,
        "attachments": attachment_payloads,
        "attachment_render_plan": attachment_render_plan_payload,
        "preflight": preflight_payload,
    }


def _native_process_resume_options(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    config: HarnessConfig,
    native_registry: NativeHistoryConnectorRegistry,
    native_index_store: NativeSessionIndexStore,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    native_ref_id = _optional_text(payload.get("native_ref_id"))
    if native_ref_id is not None:
        ref = _native_ref_or_404(native_index_store, native_ref_id)
    else:
        harness_id = _required_text(
            payload.get("harness_id") or session.default_harness_id,
            "harness_id is required",
        )
        ref = _native_ref_from_session_link(store, session, harness_id)
    if not ref.can_resume:
        raise HTTPException(
            status_code=400,
            detail=ref.resume_reason or "Native session cannot be resumed",
        )
    connector = _native_connector_or_404(native_registry, ref.harness_id)
    plan = connector.build_resume_command(ref, config.to_context())
    api_mode = parse_api_mode(payload.get("api_mode") or session.default_api_mode)
    capability = parse_capability(
        payload.get("capability") or HarnessCapability.AGENT_CLI.value
    )
    workspace = resolve_workspace(
        _optional_text(payload.get("workspace")) or ref.workspace or session.workspace
    )
    prompt = (
        _optional_text(payload.get("prompt")) or f"Resume native session: {ref.title}"
    )
    return {
        "action": "resume",
        "plan": plan,
        "harness_id": ref.harness_id,
        "prompt": prompt,
        "model": _optional_text(payload.get("model"))
        or _optional_text(ref.metadata.get("model"))
        or session.default_model,
        "api_mode": api_mode,
        "capability": capability,
        "mode": str(payload.get("mode") or session.default_mode),
        "workspace": workspace,
        "native_ref": ref,
        "native_session_id": ref.native_session_id,
        "attachment_ids": (),
        "attachments": (),
        "attachment_render_plan": None,
    }


def _native_process_run_metadata(
    options: Mapping[str, Any],
    process_ref: NativeProcessRef | None = None,
) -> dict[str, Any]:
    ref = options.get("native_ref")
    plan = options.get("plan")
    native_session_id = _optional_text(options.get("native_session_id"))
    metadata = {
        "invocation_mode": HarnessInvocationMode.NATIVE.value,
        "native_action": options["action"],
    }
    if native_session_id is not None:
        metadata["native_session_id"] = native_session_id
    if isinstance(ref, NativeSessionRef):
        metadata.update(
            {
                "native_ref_id": ref.id,
                "native_session_id": ref.native_session_id,
                "native_status": ref.status.value,
            }
        )
    elif isinstance(plan, NativeCommandPlan) and plan.native_home is not None:
        metadata["native_home"] = plan.native_home
    if process_ref is not None:
        metadata["native_process"] = {
            "id": process_ref.id,
            "pid": process_ref.pid,
            "transport": process_ref.transport,
            "status": process_ref.status.value,
        }
    attachments = options.get("attachments")
    if isinstance(attachments, tuple | list) and attachments:
        metadata["attachment_ids"] = list(options.get("attachment_ids") or ())
        metadata["attachments"] = [dict(attachment) for attachment in attachments]
    attachment_render_plan = options.get("attachment_render_plan")
    if isinstance(attachment_render_plan, Mapping):
        metadata["attachment_render_plan"] = dict(attachment_render_plan)
    preflight = options.get("preflight")
    if isinstance(preflight, Mapping):
        metadata["preflight"] = dict(preflight)
    return metadata


def _append_native_process_link(
    *,
    store: HarnessSessionStore,
    session: HarnessSession,
    options: Mapping[str, Any],
    process_ref: NativeProcessRef,
) -> HarnessNativeLink:
    ref = options.get("native_ref")
    native_session_id = _optional_text(options.get("native_session_id"))
    can_resume = native_session_id is not None
    resume_reason = None if can_resume else _native_missing_session_id_reason()
    status = (
        ref.status
        if isinstance(ref, NativeSessionRef)
        else NativeSessionStatus.MANAGED_NATIVE
    )
    now = utc_now()
    metadata: dict[str, Any] = {
        "native_action": options["action"],
        "native_process_id": process_ref.id,
        "run_id": process_ref.run_id,
        "can_resume": can_resume,
        "resume_reason": resume_reason,
        "command": list(process_ref.display_command),
        "process_status": process_ref.status.value,
    }
    if process_ref.native_home is not None:
        metadata["native_home"] = process_ref.native_home
    if isinstance(ref, NativeSessionRef):
        metadata.update(
            {
                "source_ref_status": ref.status.value,
                "source_ref_can_resume": ref.can_resume,
                "source_ref_resume_reason": ref.resume_reason,
            }
        )
    if isinstance(options.get("plan"), NativeCommandPlan):
        metadata["plan_metadata"] = dict(options["plan"].metadata)
    return store.append_native_link(
        session.id,
        HarnessNativeLink(
            id=new_id("nlink"),
            session_id=session.id,
            harness_id=str(options["harness_id"]),
            status=status,
            created_at=now,
            updated_at=now,
            native_session_id=native_session_id,
            native_ref_id=ref.id if isinstance(ref, NativeSessionRef) else None,
            source=f"native_process_{options['action']}",
            workspace=_optional_text(options.get("workspace")) or session.workspace,
            metadata=metadata,
        ),
    )


def _native_ref_from_session_link(
    store: HarnessSessionStore,
    session: HarnessSession,
    harness_id: str,
) -> NativeSessionRef:
    link = store.get_native_link(session.id, harness_id)
    if link is None:
        raise HTTPException(
            status_code=400,
            detail="native_ref_id is required or session native link is unavailable",
        )
    can_resume = bool(link.metadata.get("can_resume")) and bool(link.native_session_id)
    resume_reason = _optional_text(link.metadata.get("resume_reason"))
    if not can_resume and resume_reason is None:
        resume_reason = _native_missing_session_id_reason()
    return NativeSessionRef(
        id=link.native_ref_id or link.id,
        harness_id=link.harness_id,
        native_session_id=link.native_session_id,
        title=str(link.metadata.get("title") or "Managed native session"),
        workspace=link.workspace or session.workspace,
        source=link.source or "native_process",
        status=link.status,
        created_at=link.created_at,
        updated_at=link.updated_at,
        message_count=None,
        can_preview=False,
        can_import=False,
        can_resume=can_resume,
        resume_reason=resume_reason,
        metadata=link.metadata,
    )


def _native_session_id_from_plan(plan: NativeCommandPlan) -> str | None:
    metadata = dict(plan.metadata)
    for key in (
        "native_session_id",
        "managed_session_id",
        "session_name",
        "session_id",
        "codex_session_id",
        "claude_session_id",
        "gemini_session_id",
    ):
        value = _optional_text(metadata.get(key))
        if value is not None:
            return value
    return None


def _native_missing_session_id_reason() -> str:
    return (
        "Native session id was not detected yet; sync native sessions after the "
        "CLI writes history."
    )


def _attachment_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("attachment_ids must be a list")
    ids: list[str] = []
    for item in value:
        attachment_id = _optional_text(item)
        if attachment_id is None:
            raise ValueError("attachment_ids must contain non-empty strings")
        ids.append(attachment_id)
    return tuple(ids)


def _load_native_attachments(
    attachment_store: FilesystemAttachmentStore,
    session_id: str,
    attachment_ids: tuple[str, ...],
) -> tuple[HarnessAttachment, ...]:
    attachments: list[HarnessAttachment] = []
    for attachment_id in attachment_ids:
        try:
            attachment = attachment_store.get_attachment(attachment_id)
        except AttachmentNotFoundError as exc:
            raise ValueError(f"Unknown attachment id: {attachment_id}") from exc
        if attachment.session_id != session_id:
            raise ValueError(f"Attachment does not belong to session: {attachment_id}")
        attachments.append(attachment)
    return tuple(attachments)


def _native_attachment_metadata(
    attachment: HarnessAttachment,
) -> dict[str, Any]:
    payload = attachment_to_dict(attachment)
    payload.pop("storage_path", None)
    return payload


def _native_request_extra(
    extra: Mapping[str, Any],
    attachments: tuple[Mapping[str, Any], ...],
    attachment_render_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(extra)
    if attachments:
        payload["attachment_ids"] = [
            str(attachment["id"]) for attachment in attachments
        ]
        payload["attachments"] = [dict(attachment) for attachment in attachments]
    if attachment_render_plan:
        payload["attachment_render_plan"] = dict(attachment_render_plan)
    return payload


def _sync_native_process_run(
    store: HarnessSessionStore,
    process_ref: NativeProcessRef,
):
    status = _run_status_from_process(process_ref)
    metadata = _existing_run_metadata(store, process_ref)
    metadata.update(
        {
            "invocation_mode": HarnessInvocationMode.NATIVE.value,
            "native_process": {
                "id": process_ref.id,
                "pid": process_ref.pid,
                "transport": process_ref.transport,
                "status": process_ref.status.value,
                "exit_code": process_ref.exit_code,
            },
        }
    )
    patch: dict[str, Any] = {
        "status": status,
        "command": process_ref.display_command,
        "metadata": metadata,
    }
    if process_ref.status is not NativeProcessStatus.RUNNING:
        patch["finished_at"] = process_ref.updated_at
    if process_ref.status is NativeProcessStatus.EXITED and process_ref.exit_code:
        patch["error"] = f"Native process exited with code {process_ref.exit_code}"
    try:
        return store.update_run(process_ref.run_id, **patch)
    except RunNotFoundError:
        return None


def _existing_run_metadata(
    store: HarnessSessionStore,
    process_ref: NativeProcessRef,
) -> dict[str, Any]:
    try:
        for run in store.list_runs(process_ref.session_id):
            if run.id == process_ref.run_id:
                return dict(run.metadata)
    except SessionNotFoundError:
        return {}
    return {}


def _run_status_from_process(process_ref: NativeProcessRef) -> RunStatus:
    if process_ref.status is NativeProcessStatus.RUNNING:
        return RunStatus.RUNNING
    if process_ref.status is NativeProcessStatus.STOPPED:
        return RunStatus.CANCELED
    if process_ref.status is NativeProcessStatus.FAILED:
        return RunStatus.FAILED
    if process_ref.exit_code == 0:
        return RunStatus.SUCCEEDED
    return RunStatus.FAILED


def _native_transcript_message_to_dict(
    message: NativeTranscriptMessage,
) -> dict[str, Any]:
    return {
        "role": _native_message_role(message.role),
        "content": str(redact_for_storage(message.content)),
        "created_at": message.created_at,
        "metadata": _redacted_mapping(message.metadata),
    }


def _native_import_session_metadata(ref: NativeSessionRef) -> dict[str, Any]:
    project_id = _optional_text(ref.metadata.get("project_id"))
    metadata: dict[str, Any] = {
        "source": "native_import",
        "source_harness_id": ref.harness_id,
        "native_ref_id": ref.id,
        "native_session_id": ref.native_session_id,
        "native_status": ref.status.value,
    }
    if project_id is not None:
        metadata["project_id"] = project_id
    if ref.workspace is not None:
        metadata["project_root"] = ref.workspace
    return metadata


def _native_message_role(role: str) -> str:
    normalized = str(role).strip().lower()
    if normalized in {"user", "assistant", "system", "tool"}:
        return normalized
    if normalized == "model":
        return "assistant"
    return "assistant"


def _native_import_message_role(role: str) -> str | None:
    normalized = str(role).strip().lower()
    if normalized in {"user", "assistant", "system", "tool"}:
        return normalized
    if normalized == "model":
        return "assistant"
    return None


def _redacted_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = dict(value) if isinstance(value, Mapping) else {}
    redacted = redact_for_storage(value)
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, message: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(message)
    return text


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _decode_attachment_payload(value: Any) -> bytes:
    text = _required_text(value, "data_base64 is required")
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("data_base64 is invalid") from exc


def _metadata_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _session_project_id(session: HarnessSession) -> str | None:
    return _optional_text(session.metadata.get("project_id"))


def _session_project_root(session: HarnessSession) -> str | None:
    return _optional_text(session.metadata.get("project_root")) or _optional_text(
        session.workspace
    )


def _attachment_limits(
    session: HarnessSession,
    *,
    workspace_root: str | None = None,
) -> AttachmentLimits:
    project_root = workspace_root or _session_project_root(session)
    if project_root is None:
        return AttachmentLimits()
    loaded = load_project_config(project_root)
    return limits_from_project_settings(loaded.attachments)


def _attachment_workspace(
    session: HarnessSession,
    payload: dict[str, Any],
) -> str:
    workspace = _optional_text(payload.get("workspace")) or _session_project_root(
        session
    )
    if workspace is None:
        raise ValueError("workspace is required")
    return resolve_workspace(workspace)


def _workspace_api_root(workspace: str | None, data_dir: str) -> str:
    resolved = resolve_workspace(_optional_text(workspace))
    if resolved is not None:
        return resolved
    return resolve_project(None, data_dir=data_dir).root


def _workspace_limits(workspace_root: str) -> AttachmentLimits:
    return limits_from_project_settings(load_project_config(workspace_root).attachments)


def _attachment_response(
    registry: HarnessRegistry,
    attachment: HarnessAttachment,
) -> dict[str, Any]:
    payload = attachment_to_dict(attachment)
    payload.pop("storage_path", None)
    payload["url"] = f"/api/attachments/{attachment.id}"
    payload["supported_by"] = _attachment_supported_by(registry, attachment)
    payload["warnings"] = _attachment_warnings(registry, attachment)
    return payload


def _attachment_supported_by(
    registry: HarnessRegistry,
    attachment: HarnessAttachment,
) -> dict[str, bool]:
    support: dict[str, bool] = {}
    for harness in registry.list():
        spec = harness.spec()
        support[spec.id] = bool(
            spec.supports_attachments
            and attachment.kind in spec.accepted_attachment_kinds
        )
    return support


def _attachment_warnings(
    registry: HarnessRegistry,
    attachment: HarnessAttachment,
) -> list[str]:
    warnings: list[str] = []
    for harness in registry.list():
        spec = harness.spec()
        if not spec.supports_attachments:
            warnings.append(f"{spec.id} does not support attachments.")
        elif attachment.kind not in spec.accepted_attachment_kinds:
            warnings.append(f"{spec.id} does not accept {attachment.kind} attachments.")
    return warnings


def _content_disposition(filename: str) -> str:
    safe = "".join(
        char for char in filename if char.isalnum() or char in {" ", ".", "_", "-"}
    ).strip()
    if not safe:
        safe = "attachment"
    return f'inline; filename="{safe}"'


def _session_summary(
    store: HarnessSessionStore,
    session_id: str,
) -> dict[str, Any]:
    session = store.get_session(session_id)
    messages = store.list_messages(session_id)
    runs = store.list_runs(session_id)
    preview = ""
    if messages:
        preview = " ".join(messages[-1].content.split())[:120]
    last_status = runs[-1].status if runs else None
    payload = session_to_dict(session)
    project_id = _optional_text(session.metadata.get("project_id"))
    payload.update(
        {
            "last_message_preview": preview,
            "last_run_status": last_status,
            "project_id": project_id,
            "project": (
                {
                    "id": project_id,
                    "root": session.metadata.get("project_root"),
                    "name": session.metadata.get("project_name"),
                }
                if project_id
                else None
            ),
        }
    )
    return payload


def _session_patch(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "workspace",
        "default_harness_id",
        "default_model",
        "default_api_mode",
        "default_mode",
        "pinned",
        "archived",
        "tags",
        "metadata",
    }
    patch = {key: payload[key] for key in allowed if key in payload}
    if "workspace" in patch:
        patch["workspace"] = resolve_workspace(_optional_text(patch["workspace"]))
    if "default_api_mode" in patch:
        patch["default_api_mode"] = parse_api_mode(patch["default_api_mode"])
    return patch


def _project_response(workspace: str | None, data_dir: str) -> dict[str, Any]:
    project_context = resolve_project(workspace, data_dir=data_dir)
    loaded = load_project_config(project_context.root)
    config_payload = project_config_to_dict(loaded)
    return {
        "project": project_to_dict(project_context),
        "config": config_payload,
        "state": project_state_to_dict(load_project_state(project_context)),
        "defaults": config_payload["defaults"],
        "presets": list(config_payload["presets"].values()),
        "tools": list(config_payload["tools"].values()),
    }


def _fallback_models(config: HarnessConfig) -> list[str]:
    return list(
        dict.fromkeys(
            model for model in (config.default_model, *DEFAULT_MODEL_HINTS) if model
        )
    )
