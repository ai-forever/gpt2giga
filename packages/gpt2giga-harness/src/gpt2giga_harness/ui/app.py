"""FastAPI app for the minimal Unified Harness browser UI."""

from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from time import monotonic
from typing import Any, Mapping

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from gpt2giga_harness.arena import (
    ArenaNotFoundError,
    FilesystemHarnessArenaStore,
    HarnessArenaChildRun,
    HarnessArenaRun,
    arena_child_to_dict,
    arena_to_dict,
    continue_arena,
    queue_arena,
    queue_arena_follow_up,
    run_arena,
)
from gpt2giga_harness.application import SessionApplicationService
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
from gpt2giga_harness.ui.async_execution import (
    AsyncDiagnosticsMiddleware,
    AsyncExecutionDiagnostics,
    ConformantAPIRoute,
    async_handler_contract_errors,
    run_in_threadpool,
    run_stream_offload,
    stop_monitor,
)
from gpt2giga_harness.ui.execution_contracts import install_execution_contracts
from gpt2giga_harness.harnesses.attachment_plan import attachment_capability_error
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
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.native.base import (
    NativeCommandPlan,
    NativePromptDelivery,
    NativePromptDeliveryStatus,
    discovery_error_to_dict,
    native_prompt_delivery_to_dict,
)
from gpt2giga_harness.native.discovery import normalize_native_workspace
from gpt2giga_harness.native.models import (
    HarnessInvocationMode,
    NativeExecutionSnapshot,
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
    create_execution_snapshot,
    execution_snapshot_from_dict,
    execution_snapshot_to_dict,
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
from gpt2giga_harness.reviewed_evidence import reviewed_evidence_manifest
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
    NATIVE_PROCESS_SPAWN_OWNER,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    REVIEWED_PROMOTION_APPLY_OWNER,
    REVIEWED_PROMOTION_BRANCH_OWNER,
    approval_request_to_dict,
    permission_profile,
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
from gpt2giga_harness.sessions.event_stream import (
    EventCursorPosition,
    RunEventBroker,
    StreamCapacityError,
    StreamSignal,
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
from gpt2giga_harness.cli_capabilities import (
    CliCapabilitySnapshot,
    cli_capability_snapshot_to_dict,
)
from gpt2giga_harness.claude_handoff import (
    ClaudeHandoffError,
    claude_execution_surfaces_to_dict,
    claude_handoff_capability_to_dict,
)
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
from gpt2giga_harness.settings import HarnessSettingsStore
from gpt2giga_harness.ui.performance import ui_performance_budgets
from gpt2giga_harness.ui.mutation_contracts import install_mutation_contracts
from gpt2giga_harness.ui.routers.runs import router as runs_router
from gpt2giga_harness.ui.routers.schedules import router as schedules_router
from gpt2giga_harness.ui.routers.settings import router as settings_router
from gpt2giga_harness.ui.routers.agents import router as agents_router
from gpt2giga_harness.ui.routers.automation import router as automation_router
from gpt2giga_harness.ui.routers.approvals import router as approvals_router
from gpt2giga_harness.ui.routers.cockpit import router as cockpit_router
from gpt2giga_harness.ui.routers.evaluate import router as evaluate_router
from gpt2giga_harness.ui.routers.files import create_file_preview_router
from gpt2giga_harness.ui.routers.provider_handoffs import (
    create_provider_handoff_router,
)
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
    prepare_workspace_execution,
    review_run_diff,
    run_diff_response,
)
from gpt2giga_harness.workspace import (
    resolve_workspace,
    workspace_file_metadata,
    workspace_tree,
)
from gpt2giga_harness.workbench_execution import workbench_transport_projection


NATIVE_SUBMIT_KEY_DELAY_SECONDS = 0.05
RUN_EVENT_STREAM_HEARTBEAT_SECONDS = 10.0
RUN_EVENT_STREAM_POLL_SECONDS = 0.1


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
        session_store=store,
        runtime_store=runtime_store,
    )
    attachment_store = FilesystemAttachmentStore(config.data_dir)
    arena_store = FilesystemHarnessArenaStore(config.data_dir)
    eval_store = FilesystemHarnessEvalStore(config.data_dir)
    memory_store = FilesystemProjectMemoryStore()
    settings_store = HarnessSettingsStore(config.data_dir, config)
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
    session_service = SessionApplicationService(
        runner=runner,
        settings_store=settings_store,
        runtime_store=runtime_store,
        dispatcher=durable_dispatcher,
    )
    policy_engine = PolicyEngine(runtime_store)
    active_headless_runs: dict[str, _ActiveHeadlessRun] = {}
    async_diagnostics = AsyncExecutionDiagnostics()
    run_event_broker = getattr(store, "event_broker", RunEventBroker())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        monitor = asyncio.create_task(
            async_diagnostics.monitor_event_loop(),
            name="harness-event-loop-lag",
        )
        try:
            yield
        finally:
            await stop_monitor(monitor)

    app = FastAPI(
        title="gpt2giga Unified Harness",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.router.route_class = ConformantAPIRoute
    ui_security = HarnessUISecurity(config)
    app.add_middleware(HarnessUISecurityMiddleware, security=ui_security)
    app.add_middleware(
        AsyncDiagnosticsMiddleware,
        diagnostics=async_diagnostics,
    )
    app.state.harness_config = config
    app.state.harness_registry = registry
    app.state.harness_session_store = store
    app.state.harness_runtime_store = runtime_store
    app.state.harness_runtime_reconciliation = reconciliation_report
    app.state.harness_session_runner = runner
    app.state.harness_session_service = session_service
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
    app.state.harness_async_diagnostics = async_diagnostics
    app.state.harness_run_event_broker = run_event_broker
    app.state.harness_settings_store = settings_store

    def _approval_gate(
        action: PermissionAction,
        run: HarnessRun,
        *,
        reason: str,
        preview: Mapping[str, Any],
        approval_binding: str | None = None,
        enforcement_owner: str | None = None,
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
            approval_binding=approval_binding,
            enforcement_owner=enforcement_owner,
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
    def harnesses() -> dict[str, Any]:
        harness_items = []
        for harness in registry.list():
            spec = harness.spec()
            validation = registry.validation_report(spec.id) or validate_harness_spec(
                spec
            )
            capability_probe = getattr(harness, "capability_probe", None)
            provider_handoff_probe = getattr(
                harness, "provider_handoff_capability", None
            )
            provider_handoff = None
            execution_surfaces: list[dict[str, Any]] = []
            if callable(provider_handoff_probe):
                try:
                    handoff_capability = provider_handoff_probe()
                except ClaudeHandoffError:
                    handoff_capability = None
                if handoff_capability is not None:
                    provider_handoff = claude_handoff_capability_to_dict(
                        handoff_capability
                    )
                    execution_surfaces = claude_execution_surfaces_to_dict(
                        handoff_capability
                    )
            harness_items.append(
                {
                    "spec": spec_to_dict(spec),
                    "availability": availability_to_dict(harness.availability()),
                    "compatibility": (
                        cli_capability_snapshot_to_dict(capability_probe())
                        if callable(capability_probe)
                        else None
                    ),
                    "provider_handoff": provider_handoff,
                    "execution_surfaces": execution_surfaces,
                    "workbench_transport": workbench_transport_projection(harness),
                    "validation": harness_validation_report_to_dict(validation),
                }
            )
        return {
            "harnesses": harness_items,
            "discovery_errors": list(registry.discovery_errors),
        }

    @app.get("/api/defaults")
    def defaults() -> dict[str, Any]:
        harness_defaults = settings_store.load().defaults
        return {
            "proxy_url": config.proxy_url,
            "default_harness_id": harness_defaults.default_harness_id,
            "default_model": harness_defaults.default_model,
            "default_api_mode": harness_defaults.default_api_mode,
            "default_mode": harness_defaults.mode,
            "execution_transport": harness_defaults.execution_transport,
            "invocation_mode": harness_defaults.invocation_mode,
            "workspace_policy": harness_defaults.workspace_policy,
            "permission_profile": harness_defaults.permission_profile,
            "stream": harness_defaults.stream,
            "auto_start_proxy": config.auto_start_proxy,
            "proxy_start_timeout_seconds": config.proxy_start_timeout_seconds,
            "note": pass_model_env_note(),
            "performance_budgets": ui_performance_budgets(),
        }

    @app.get("/api/project")
    def project(workspace: str | None = Query(default=None)) -> dict[str, Any]:
        try:
            return _project_response(
                workspace=_optional_text(workspace),
                data_dir=config.data_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/project/config")
    def project_config(
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
    def project_presets(
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
    def render_preset(
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
    def project_state(
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
    def update_state(
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
    def editor_open_workspace(
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
    def editor_open_file(
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
    def editor_open_diff(
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
    def editor_open_terminal(
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
    def project_memory(
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
    def add_project_memory(
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
    def update_project_memory(
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
    def delete_project_memory(
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
    def tools(workspace: str | None = Query(default=None)) -> dict[str, Any]:
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
    def tools_sync(
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
    def evals(workspace: str | None = Query(default=None)) -> dict[str, Any]:
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
    def get_eval_run(eval_run_id: str) -> dict[str, Any]:
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

            def prepare_eval():
                project_context = resolve_project(
                    _optional_text(payload.get("workspace")),
                    data_dir=config.data_dir,
                    load_config_name=False,
                )
                return project_context, load_eval_spec(project_context.root, eval_name)

            project_context, spec = await run_in_threadpool(prepare_eval)
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
                execution_transport=_optional_text(payload.get("execution_transport")),
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
        return await run_in_threadpool(_eval_run_response, eval_run, store)

    @app.post("/api/project/init")
    def project_init(
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
    def models(api_mode: str = Query(default="v2")) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            mode = parse_api_mode(api_mode)
        except ValueError:
            return {
                "schema_version": 1,
                "ok": False,
                "api_mode": None,
                "route_path": None,
                "health": "unknown",
                "last_checked_at": checked_at,
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
                "schema_version": 1,
                "ok": False,
                "api_mode": mode.value,
                "route_path": f"/{mode.value}/models",
                "health": "unknown",
                "last_checked_at": checked_at,
                "models": [],
                "source": f"/{mode.value}/models",
                "error": "model discovery failed",
                "note": pass_model_env_note(),
            }
        return {
            "schema_version": 1,
            "ok": discovery.ok,
            "api_mode": mode.value,
            "route_path": f"/{mode.value}/models",
            "health": "ready" if discovery.ok else "blocked",
            "last_checked_at": checked_at,
            "models": list(discovery.models[:100]),
            "source": discovery.source,
            "error": None if discovery.ok else "model discovery failed",
            "note": pass_model_env_note(),
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        status = proxy.health_check(config)
        return {
            "ok": status.ok,
            "proxy_url": status.url,
            "path": status.path,
            "status_code": status.status_code,
            "error": status.error,
            "async_data_plane": async_diagnostics.snapshot(),
            "event_streams": run_event_broker.snapshot(),
        }

    @app.post("/api/preflight/run")
    def preflight_run(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        durable = bool(
            durable_dispatcher is not None
            and str(payload.get("invocation_mode") or "headless") != "native"
        )
        if payload.get("durable") is False:
            durable = False
        try:
            prepared = session_service.prepare_turn_payload(
                payload,
                session_id=_optional_text(payload.get("session_id")),
            )
            report = runner.preflight(
                prepared,
                session_id=_optional_text(payload.get("session_id")),
                durable=durable,
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"preflight": preflight_report_to_dict(report)}

    @app.post("/api/route/recommendation")
    def route_recommendation(
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
    def sessions(
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
        arenas = arena_store.list(workspace=resolved_workspace)
        arena_child_session_ids = {
            child.session_id
            for arena in arenas
            for child in arena.child_runs
            if child.session_id is not None
        }
        items = tuple(
            session for session in items if session.id not in arena_child_session_ids
        )
        if not include_arena:
            arena_session_ids = {arena.session_id for arena in arenas}
            items = tuple(
                session for session in items if session.id not in arena_session_ids
            )[:limit]
        else:
            items = items[:limit]
        return {"sessions": [_session_summary(store, session.id) for session in items]}

    @app.post("/api/sessions")
    def create_session(payload: dict[str, Any] = Body(default_factory=dict)):
        try:
            session = session_service.create_session(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session": _session_summary(store, session.id)}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            return bundle_to_dict(store.get_session_bundle(session_id))
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.get("/api/native/sessions")
    def native_sessions(
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
    def native_sessions_sync(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(payload.get("workspace")))
        resolved_project_id = _native_project_id(
            project_id=_optional_text(payload.get("project_id")),
            workspace=resolved_workspace,
            data_dir=config.data_dir,
        )
        try:
            result = native_registry.discover(
                harness_id=_optional_text(payload.get("harness_id")),
                workspace=resolved_workspace,
                include_external=bool(payload.get("include_external")),
                cursor=_optional_text(payload.get("cursor")),
                limit=_native_discovery_limit(payload.get("limit")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stored = [
            native_index_store.upsert_ref(
                ref,
                project_id=_native_discovered_project_id(
                    ref,
                    workspace=resolved_workspace,
                    project_id=resolved_project_id,
                ),
            )
            for ref in result.sessions
        ]
        return {
            "sessions": [native_session_ref_to_dict(ref) for ref in stored],
            "errors": [discovery_error_to_dict(error) for error in result.errors],
            "next_cursor": result.next_cursor,
            "scanned_count": result.scanned_count,
        }

    @app.get("/api/native/sessions/{native_ref_id}/preview")
    def native_session_preview(
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
    def native_session_import(native_ref_id: str) -> dict[str, Any]:
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
            default_model=(
                ref.execution_snapshot.model
                if ref.execution_snapshot is not None
                else _optional_text(ref.metadata.get("model"))
            ),
            default_api_mode=parse_api_mode(
                ref.execution_snapshot.api_mode
                if ref.execution_snapshot is not None
                else config.default_api_mode
            ),
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
                    **_native_snapshot_link_metadata(ref),
                },
            ),
        )
        return {
            "session": _session_summary(store, session.id),
            "messages": [message_to_dict(message) for message in messages],
            "native_link": native_link_to_dict(link),
        }

    @app.post("/api/sessions/{session_id}/native/link")
    def native_session_link(
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
                    **_native_snapshot_link_metadata(ref),
                },
            ),
        )
        return {
            "session": _session_summary(store, session.id),
            "native_link": native_link_to_dict(link),
        }

    @app.post("/api/native/processes/start", response_model=None)
    def native_process_start(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any] | JSONResponse:
        run = None
        process_ref = None
        options = None
        workspace_execution = None
        try:
            session = store.get_session(
                _required_text(payload.get("session_id"), "session_id is required")
            )
            action = str(payload.get("action") or "start").strip().lower()
            if action not in {"start", "resume"}:
                raise ValueError("action must be start or resume")
            if action == "start":
                _native_permission_mode(payload.get("mode") or session.default_mode)
            policy_result = _native_process_policy_gate(
                payload=payload,
                session=session,
                policy_engine=policy_engine,
                runtime_store=runtime_store,
            )
            if isinstance(policy_result, JSONResponse):
                return policy_result
            run_id, policy_metadata = policy_result
            effective_payload = dict(payload)
            if action == "start":
                mode = _native_permission_mode(
                    payload.get("mode") or session.default_mode
                )
                source_workspace = resolve_workspace(
                    _optional_text(payload.get("workspace")) or session.workspace
                )
                if mode == "edit" and source_workspace is None:
                    raise WorktreeError(
                        "Native edit isolation requires an explicit workspace; "
                        "refusing to inherit the UI server checkout."
                    )
                workspace_execution = prepare_workspace_execution(
                    requested_policy=payload.get("workspace_policy"),
                    harness_kind="agent-cli",
                    mode=mode,
                    workspace=source_workspace,
                    data_dir=config.data_dir,
                    session_id=session.id,
                    run_id=run_id,
                )
                effective_payload["mode"] = mode
                effective_payload["workspace"] = workspace_execution.request_workspace
                extra = _metadata_mapping(payload.get("extra"))
                extra["native_source_workspace"] = source_workspace
                extra["workspace_execution"] = workspace_execution.to_metadata()
                effective_payload["extra"] = extra
            options = _native_process_start_options(
                payload=effective_payload,
                session=session,
                config=config,
                registry=registry,
                native_registry=native_registry,
                native_index_store=native_index_store,
                store=store,
                attachment_store=attachment_store,
            )
            if workspace_execution is None:
                workspace_metadata = _native_resume_workspace_execution(options)
            else:
                workspace_metadata = workspace_execution.to_metadata()
            requested_workspace_policy = (
                str(payload.get("workspace_policy") or "auto").strip().lower()
            )
            if (
                action == "resume"
                and options["mode"] == "edit"
                and requested_workspace_policy in {"auto", "worktree"}
                and workspace_metadata.get("policy") != "worktree"
            ):
                raise NativeProcessStartError(
                    "Native edit resume has no isolated worktree evidence; "
                    "refusing to resume in the source checkout."
                )
            options["source_workspace"] = (
                workspace_metadata.get("source_workspace") or options["workspace"]
            )
            options["workspace_execution"] = workspace_metadata
            options["policy"] = policy_metadata
            options["plan"] = replace(
                options["plan"],
                metadata={
                    **dict(options["plan"].metadata),
                    "workspace_execution": workspace_metadata,
                    "policy": policy_metadata,
                },
            )
            run = store.create_run(
                run_id=run_id,
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
                "workspace": options["source_workspace"],
            }
            if (
                session.title == "Untitled session"
                and options["action"] == "start"
                and options["prompt"]
            ):
                session_patch["title"] = title_from_prompt(options["prompt"])
            store.update_session(session.id, **session_patch)
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=session.id,
                    run_id=run.id,
                    type="policy_allowed",
                    message="Harness policy allowed native process spawn.",
                    payload=policy_metadata,
                    created_at=utc_now(),
                    trace_id=run.id,
                    span_kind="policy",
                    span_status="allowed",
                )
            )
            process_ref = native_process_manager.start(
                options["plan"],
                session_id=session.id,
                workspace=options["workspace"],
                run_id=run.id,
                timeout_seconds=_native_timeout_seconds(payload.get("timeout_seconds")),
            )
            if options["action"] == "start":
                recorder = getattr(options["connector"], "record_start_snapshot", None)
                if recorder is not None:
                    try:
                        recorder(options["plan"])
                    except (OSError, ValueError) as exc:
                        native_process_manager.stop(process_ref.id)
                        raise NativeProcessStartError(
                            "Could not persist native execution snapshot"
                        ) from exc
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
                runtime_store=runtime_store,
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
            if isinstance(options, Mapping):
                route_preflight = options.get("proxy_route_preflight")
                if isinstance(route_preflight, proxy.ProxyRoutePreflight):
                    proxy.stop_owned_sidecar(route_preflight.startup)
            if run is not None:
                store.update_run(
                    run.id,
                    status="failed",
                    error=str(exc),
                    finished_at=utc_now(),
                    metadata=_native_process_run_metadata(
                        options,
                        process_ref,
                        prompt_delivery_status=(
                            NativePromptDeliveryStatus.FAILED
                            if process_ref is None
                            else None
                        ),
                        prompt_delivery_error=(
                            str(exc) if process_ref is None else None
                        ),
                    ),
                )
            elif workspace_execution is not None and workspace_execution.worktree_path:
                with suppress(WorktreeError):
                    discard_run_worktree(
                        {"workspace_execution": workspace_execution.to_metadata()}
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
            process_ref = await run_in_threadpool(
                native_process_manager.write, process_id, str(data)
            )
            if payload.get("submit") is True:
                await asyncio.sleep(NATIVE_SUBMIT_KEY_DELAY_SECONDS)
                process_ref = await run_in_threadpool(
                    native_process_manager.write, process_id, "\r"
                )
            run = await run_in_threadpool(
                _sync_native_process_run,
                store,
                process_ref,
                native_registry=native_registry,
                native_index_store=native_index_store,
            )
            message_content = _optional_text(payload.get("message"))
            if message_content is not None and run is not None:
                message = await run_in_threadpool(
                    store.append_message,
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
                    ),
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
    def native_process_output(
        process_id: str,
        cursor: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            chunk = native_process_manager.read_since(process_id, cursor)
            process_ref = native_process_manager.status(process_id)
            run = _sync_native_process_run(
                store,
                process_ref,
                native_registry=native_registry,
                native_index_store=native_index_store,
            )
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        payload = native_output_chunk_to_dict(chunk)
        payload["run"] = run_to_dict(run) if run is not None else None
        payload["messages"] = (
            [message_to_dict(message) for message in _native_run_messages(store, run)]
            if run is not None
            else []
        )
        payload["events"] = (
            [event_to_dict(event) for event in _native_run_events(store, run)]
            if run is not None
            else []
        )
        return payload

    @app.get("/api/native/processes/{process_id}/output/stream")
    async def native_process_output_stream(
        process_id: str,
        cursor: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        stream_cursor = max(cursor, _native_sse_cursor(last_event_id))
        try:
            await run_stream_offload(native_process_manager.status, process_id)
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc

        async def stream_output():
            current_cursor = stream_cursor
            last_keepalive = asyncio.get_running_loop().time()

            def poll_stream(cursor_value: int):
                chunk = native_process_manager.read_since(process_id, cursor_value)
                process_ref = native_process_manager.status(process_id)
                run = _sync_native_process_run(
                    store,
                    process_ref,
                    native_registry=native_registry,
                    native_index_store=native_index_store,
                )
                event_payload = native_output_chunk_to_dict(chunk)
                event_payload["run"] = run_to_dict(run) if run is not None else None
                event_payload["messages"] = (
                    [
                        message_to_dict(message)
                        for message in _native_run_messages(store, run)
                    ]
                    if run is not None
                    else []
                )
                event_payload["events"] = (
                    [event_to_dict(event) for event in _native_run_events(store, run)]
                    if run is not None
                    else []
                )
                return chunk, process_ref, event_payload

            while True:
                try:
                    chunk, process_ref, event_payload = await run_stream_offload(
                        poll_stream, current_cursor
                    )
                except NativeProcessNotFoundError:
                    break
                should_emit = (
                    bool(chunk.outputs)
                    or chunk.truncated
                    or (process_ref.status is not NativeProcessStatus.RUNNING)
                )
                if should_emit:
                    current_cursor = chunk.cursor
                    yield _native_output_sse(event_payload)
                    last_keepalive = asyncio.get_running_loop().time()
                if process_ref.status is not NativeProcessStatus.RUNNING:
                    break
                now = asyncio.get_running_loop().time()
                if now - last_keepalive >= 10:
                    yield ": keepalive\n\n"
                    last_keepalive = now
                await asyncio.sleep(0.1)

        return StreamingResponse(
            stream_output(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/native/processes/{process_id}/resize")
    def native_process_resize(
        process_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            process_ref = native_process_manager.resize(
                process_id,
                rows=payload.get("rows"),
                columns=payload.get("columns"),
            )
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "process": native_process_ref_to_dict(process_ref),
            "rows": payload["rows"],
            "columns": payload["columns"],
        }

    @app.get("/api/native/processes/{process_id}")
    def native_process_status(process_id: str) -> dict[str, Any]:
        try:
            process_ref = native_process_manager.status(process_id)
            run = _sync_native_process_run(
                store,
                process_ref,
                native_registry=native_registry,
                native_index_store=native_index_store,
            )
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        return {
            "process": native_process_ref_to_dict(process_ref),
            "run": run_to_dict(run) if run is not None else None,
        }

    @app.delete("/api/native/processes/{process_id}")
    def native_process_stop(process_id: str) -> dict[str, Any]:
        try:
            process_ref = native_process_manager.stop(process_id)
            run = _sync_native_process_run(
                store,
                process_ref,
                native_registry=native_registry,
                native_index_store=native_index_store,
            )
        except NativeProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Native process not found"
            ) from exc
        return {
            "stopped": process_ref.status is not NativeProcessStatus.RUNNING,
            "cancel_requested": process_ref.cancel_requested_at is not None,
            "process": native_process_ref_to_dict(process_ref),
            "run": run_to_dict(run) if run is not None else None,
        }

    @app.patch("/api/sessions/{session_id}")
    def update_session(
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
    def delete_session(session_id: str) -> dict[str, Any]:
        try:
            store.delete_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return {"deleted": True}

    @app.post("/api/sessions/{session_id}/attachments")
    def create_attachment(
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
    def create_workspace_attachment(
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

    @app.get("/api/sessions/{session_id}/attachments/workspace/search")
    def search_session_workspace_attachments(
        session_id: str,
        q: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        """Return bounded safe attachment candidates for one session workspace."""
        try:
            session = store.get_session(session_id)
            workspace_root = _attachment_workspace(session, {})
            files = workspace_tree(
                workspace_root,
                query=q,
                limits=_attachment_limits(session, workspace_root=workspace_root),
                result_limit=limit,
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except (AttachmentValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "q": _optional_text(q) or "",
            "files": files,
            "bounded": True,
        }

    @app.get("/api/sessions/{session_id}/attachments")
    def session_attachments(session_id: str) -> dict[str, Any]:
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
    def attachment_metadata(attachment_id: str) -> dict[str, Any]:
        try:
            attachment = attachment_store.get_attachment(attachment_id)
        except AttachmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        return {"attachment": _attachment_response(registry, attachment)}

    @app.get("/api/attachments/{attachment_id}")
    def attachment_blob(attachment_id: str) -> Response:
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
    def delete_attachment(attachment_id: str) -> dict[str, Any]:
        try:
            attachment_store.delete_attachment(attachment_id)
        except AttachmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        return {"deleted": True}

    @app.get("/api/workspace/tree")
    def workspace_tree_endpoint(
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
    def workspace_file_metadata_endpoint(
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
                session_service.submit_turn,
                session_id,
                payload,
                idempotency_key=idempotency_key,
                origin="interactive",
            )
            return submission.queued.run
        existing_runs = await run_in_threadpool(store.list_runs, session_id)
        before_run_ids = {run.id for run in existing_runs}
        cancel_event = threading.Event()
        task = asyncio.create_task(
            run_in_threadpool(
                session_service.run_turn,
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
        events = session_service.list_run_events(run.id)
        payload = {
            "session": _session_summary(store, run.session_id),
            "run": run_to_dict(run),
            "events": [_event_response(event) for event in events],
            "stream_url": f"/api/runs/{run.id}/events/stream",
            "cancel_url": f"/api/runs/{run.id}/cancel",
        }
        job = session_service.find_job_for_run(run.id)
        if job is not None:
            payload["job"] = job_to_dict(job)
        return payload

    def _run_provenance_response(run: HarnessRun) -> dict[str, Any]:
        provenance = _build_current_run_provenance(
            store=store,
            registry=registry,
            config=config,
            run=run,
            runtime_store=runtime_store,
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
            session = await run_in_threadpool(
                session_service.create_session,
                payload,
                title_from_turn=True,
                validate_harness=True,
            )
            run = await _start_headless_run(session.id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return await run_in_threadpool(_run_start_response, run)

    @app.post("/api/sessions/{session_id}/run/start")
    async def start_run_in_session(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            await run_in_threadpool(store.get_session, session_id)
            run = await _start_headless_run(session_id, payload)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return await run_in_threadpool(_run_start_response, run)

    @app.get("/api/runs/{run_id}/events/stream")
    async def run_events_stream(
        run_id: str,
        after_id: str | None = Query(default=None),
        tail_only: bool = Query(default=False),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            initial_run = await run_stream_offload(session_service.get_run, run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        try:
            subscription = run_event_broker.subscribe(run_id)
        except StreamCapacityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            cursor_position = await run_stream_offload(
                _resolve_run_stream_cursor,
                store,
                initial_run,
                _optional_text(last_event_id) or _optional_text(after_id),
                tail_only=tail_only,
            )
        except ValueError as exc:
            subscription.close()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        async def stream_events():
            current_offset = cursor_position.offset
            terminal_event_seen = cursor_position.terminal_seen
            next_heartbeat_at = monotonic() + RUN_EVENT_STREAM_HEARTBEAT_SECONDS
            try:
                while True:
                    try:
                        current_run, page = await run_stream_offload(
                            session_service.read_run_event_tail,
                            run_id,
                            current_offset,
                        )
                    except (RunNotFoundError, SessionNotFoundError, ValueError):
                        break
                    for item in page.items:
                        current_offset = item.next_offset
                        event = item.event
                        if event.type == HarnessEventType.RUN_FINISHED.value:
                            terminal_event_seen = True
                        cursor = _encode_run_stream_cursor(
                            current_run,
                            current_offset,
                            terminal_event_seen=terminal_event_seen,
                        )
                        yield _run_sse_event(event, cursor)
                    if page.next_offset > current_offset:
                        current_offset = page.next_offset
                    if page.has_more:
                        continue
                    if _run_status_is_terminal(current_run.status):
                        if terminal_event_seen:
                            break
                        terminal_event_seen = True
                        cursor = _encode_run_stream_cursor(
                            current_run,
                            current_offset,
                            terminal_event_seen=True,
                        )
                        yield _run_sse_event(
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
                            ),
                            cursor,
                        )
                        break
                    signal = await subscription.wait(RUN_EVENT_STREAM_POLL_SECONDS)
                    cursor = _encode_run_stream_cursor(
                        current_run,
                        current_offset,
                        terminal_event_seen=terminal_event_seen,
                    )
                    if signal is StreamSignal.RESNAPSHOT_REQUIRED:
                        yield _run_resnapshot_sse(current_run, cursor)
                    elif signal is None and monotonic() >= next_heartbeat_at:
                        yield ": heartbeat\n\n"
                        next_heartbeat_at = (
                            monotonic() + RUN_EVENT_STREAM_HEARTBEAT_SECONDS
                        )
            finally:
                subscription.close()

        return StreamingResponse(
            stream_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
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
    def run_diff(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return {"run": run_to_dict(run), "diff": run_diff_response(run.metadata)}

    @app.get("/api/runs/{run_id}/pr")
    def run_pr_artifact(run_id: str) -> dict[str, Any]:
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
    def run_provenance(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return _run_provenance_response(run)

    @app.post("/api/runs/{run_id}/replay")
    def replay_run(
        run_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
            raw_request = _latest_raw_request_for_run(store, run)
            replay_payload = build_replay_request(
                run,
                raw_request=raw_request,
                reviewed_evidence=_reviewed_evidence_for_run(runtime_store, run.id),
            )
            if "stream" in payload:
                replay_payload["stream"] = bool(payload.get("stream"))
            if (
                replay_payload.get("execution_transport")
                == ExecutionTransport.NATIVE_STRUCTURED.value
            ):
                if durable_dispatcher is None:
                    raise ValueError(
                        "native_structured replay requires the durable runtime"
                    )
                if run.mode == "edit":
                    replay_payload["workspace_policy"] = "worktree"
                replay_session = runner.create_session(
                    title=f"Replay: {title_from_prompt(run.prompt)}",
                    workspace=run.workspace,
                    default_harness_id=run.harness_id,
                    default_model=run.model,
                    default_api_mode=run.api_mode,
                    default_mode=run.mode,
                )
                replay_extra = replay_payload.get("extra")
                replay_source_value = (
                    replay_extra.get("replay_source")
                    if isinstance(replay_extra, Mapping)
                    else None
                )
                replay_source = (
                    dict(replay_source_value)
                    if isinstance(replay_source_value, Mapping)
                    else {}
                )
                replay_session = store.update_session(
                    replay_session.id,
                    metadata={
                        **dict(replay_session.metadata),
                        "replay_source": replay_source,
                    },
                )
                submission = durable_dispatcher.submit(
                    replay_session.id,
                    replay_payload,
                    idempotency_key=f"replay:{run.id}:{replay_session.id}",
                    origin="manual",
                )
                return {
                    "session": session_to_dict(replay_session),
                    "run": run_to_dict(submission.queued.run),
                    "source_run": run_to_dict(run),
                    "replay_request": replay_payload,
                    "replay": {
                        "source": replay_source,
                        "destination_harness_session_id": replay_session.id,
                        "provider_session_pending": True,
                    },
                }
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
    def fork_run(run_id: str) -> dict[str, Any]:
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
    def run_patch(run_id: str) -> Response:
        try:
            run = store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        artifact = build_pr_artifact(run)
        return Response(content=artifact.patch, media_type="text/plain")

    @app.post("/api/runs/{run_id}/apply", response_model=None)
    def apply_run_patch(
        run_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any] | JSONResponse:
        try:
            run = store.get_run(run_id)
            branch_name = _optional_text(payload.get("branch_name"))
            review = review_run_diff(run.metadata, branch_name=branch_name)
            approval_response = _approval_gate(
                PermissionAction.GIT_APPLY,
                run,
                reason="Apply an isolated worktree diff to the source checkout.",
                preview=review.to_preview(),
                approval_binding=review.approval_binding,
                enforcement_owner=REVIEWED_PROMOTION_APPLY_OWNER,
            )
            if approval_response is not None:
                return approval_response
            workspace_execution = apply_run_diff(
                run.metadata,
                review=review,
                branch_name=branch_name,
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
                        "source_sha": review.source_sha,
                        "patch_sha256": review.patch_sha256,
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
    def create_run_branch(
        run_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any] | JSONResponse:
        try:
            run = store.get_run(run_id)
            branch_name = (
                _optional_text(payload.get("branch_name"))
                or build_pr_artifact(run).branch_name_suggestion
            )
            review = review_run_diff(run.metadata, branch_name=branch_name)
            approval_response = _approval_gate(
                PermissionAction.GIT_BRANCH_CREATE,
                run,
                reason="Create a local branch from the isolated run patch.",
                preview=review.to_preview(),
                approval_binding=review.approval_binding,
                enforcement_owner=REVIEWED_PROMOTION_BRANCH_OWNER,
            )
            if approval_response is not None:
                return approval_response
            branch = create_pr_branch(
                run,
                review=review,
                branch_name=branch_name,
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
                    payload={
                        "branch_name": branch["branch_name"],
                        "source_sha": review.source_sha,
                        "patch_sha256": review.patch_sha256,
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
            "branch_created": True,
            "branch_name": branch["branch_name"],
            "run": run_to_dict(run),
            "diff": run_diff_response(run.metadata),
            "pr_artifact": pr_artifact_to_dict(build_pr_artifact(run)),
        }

    @app.post("/api/runs/{run_id}/discard")
    def discard_run_worktree_endpoint(run_id: str) -> dict[str, Any]:
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
    def open_run_worktree(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
            response = open_worktree_response(run.metadata)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return {"run": run_to_dict(run), "worktree": response}

    @app.post("/api/sessions/run")
    def create_session_and_run(
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            result = session_service.create_and_run(payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @app.post("/api/sessions/{session_id}/run")
    def run_in_session(
        session_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            result = session_service.run_turn(session_id, payload)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown harness") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @app.get("/api/sessions/{session_id}/events")
    def session_events(
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
    def list_arena_runs(
        workspace: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(workspace))
        arenas = arena_store.list(workspace=resolved_workspace, limit=limit)
        return {"arenas": [_arena_summary_response(arena) for arena in arenas]}

    @app.post("/api/arena/runs")
    async def create_arena_run(
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            payload = dict(payload)
            if not str(payload.get("prompt") or "").strip():
                raise ValueError("prompt is required")
            if _first_text(payload.get("harness_ids")) is None:
                raise ValueError("harness_ids must contain at least one harness")
            workspace_paths = _bounded_arena_workspace_paths(
                payload.pop("workspace_paths", None)
            )
            session_id = _optional_text(payload.get("session_id"))
            if workspace_paths and session_id is None:
                session = runner.create_session(
                    title=title_from_prompt(str(payload.get("prompt") or "")),
                    workspace=_optional_text(payload.get("workspace")),
                    default_harness_id=_first_text(payload.get("harness_ids"))
                    or "echo",
                    default_model=_optional_text(payload.get("model")),
                    default_api_mode=payload.get("api_mode"),
                    default_mode=str(payload.get("mode") or "plan"),
                )
                session_id = session.id
                payload["session_id"] = session_id
            if workspace_paths:
                session = store.get_session(session_id or "")
                workspace_root = _attachment_workspace(session, payload)
                attachment_ids = [
                    attachment_store.create_workspace_reference(
                        session_id=session.id,
                        project_id=_session_project_id(session)
                        or resolve_project(workspace_root, data_dir=config.data_dir).id,
                        workspace_root=workspace_root,
                        path=path,
                        metadata={"arena_shared": True},
                        limits=_attachment_limits(
                            session, workspace_root=workspace_root
                        ),
                    ).id
                    for path in workspace_paths
                ]
                payload["attachment_ids"] = attachment_ids
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
        except (AttachmentValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await run_in_threadpool(_arena_response, arena, store)

    @app.get("/api/arena/runs/{arena_id}")
    def get_arena_run(arena_id: str) -> dict[str, Any]:
        try:
            arena = arena_store.get(arena_id)
        except ArenaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Arena run not found") from exc
        return _arena_response(arena, store)

    @app.post("/api/arena/runs/{arena_id}/turns")
    async def create_arena_follow_up(
        arena_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            arena = await run_in_threadpool(arena_store.get, arena_id)
            payload = dict(payload)
            if not str(payload.get("prompt") or "").strip():
                raise ValueError("prompt is required")
            workspace_paths = _bounded_arena_workspace_paths(
                payload.pop("workspace_paths", None)
            )
            if workspace_paths:
                session = await run_in_threadpool(store.get_session, arena.session_id)
                workspace_root = _attachment_workspace(session, payload)

                def create_shared_attachments() -> list[str]:
                    return [
                        attachment_store.create_workspace_reference(
                            session_id=session.id,
                            project_id=_session_project_id(session)
                            or resolve_project(
                                workspace_root, data_dir=config.data_dir
                            ).id,
                            workspace_root=workspace_root,
                            path=path,
                            metadata={"arena_shared": True, "arena_id": arena.id},
                            limits=_attachment_limits(
                                session, workspace_root=workspace_root
                            ),
                        ).id
                        for path in workspace_paths
                    ]

                payload["attachment_ids"] = await run_in_threadpool(
                    create_shared_attachments
                )
            follow_up_runner = (
                queue_arena_follow_up
                if durable_dispatcher is not None
                else continue_arena
            )
            arena = await run_in_threadpool(
                follow_up_runner,
                runner=runner,
                arena_store=arena_store,
                arena=arena,
                payload=payload,
                **(
                    {"dispatcher": durable_dispatcher}
                    if durable_dispatcher is not None
                    else {}
                ),
            )
        except ArenaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Arena run not found") from exc
        except (AttachmentValidationError, SessionNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await run_in_threadpool(_arena_response, arena, store)

    @app.post("/api/arena/runs/{arena_id}/children/{child_index}/retry")
    async def retry_arena_child(
        arena_id: str,
        child_index: int,
    ) -> dict[str, Any]:
        try:
            arena = await run_in_threadpool(arena_store.get, arena_id)
            child = next(item for item in arena.child_runs if item.index == child_index)
            if child.run_id is None or child.session_id is None:
                raise ValueError("arena child has not started")
            source_run = await run_in_threadpool(store.get_run, child.run_id)
            raw_request = await run_in_threadpool(
                _latest_raw_request_for_run, store, source_run
            )
            replay_payload = build_replay_request(
                source_run,
                raw_request=raw_request,
                reviewed_evidence=_reviewed_evidence_for_run(
                    runtime_store, source_run.id
                ),
            )
            if source_run.status.value in {"queued", "running", "retry_wait"}:
                raise ValueError("arena child is still active")
            replay_payload["extra"] = {
                **dict(replay_payload.get("extra") or {}),
                "arena": {
                    "arena_id": arena.id,
                    "child_index": child.index,
                    "child_count": len(arena.harness_ids),
                    "parent_session_id": arena.session_id,
                    "turn_index": max(int(arena.metadata.get("turn_count") or 0), 0),
                },
            }
            target_session_id = child.session_id
            if (
                replay_payload.get("execution_transport")
                == ExecutionTransport.NATIVE_STRUCTURED.value
            ):
                if durable_dispatcher is None:
                    raise ValueError(
                        "native_structured Arena retry requires the durable runtime"
                    )
                if source_run.mode == "edit":
                    replay_payload["workspace_policy"] = "worktree"
                retry_session = runner.create_session(
                    title=f"Arena retry: {title_from_prompt(source_run.prompt)}",
                    workspace=source_run.workspace,
                    default_harness_id=source_run.harness_id,
                    default_model=source_run.model,
                    default_api_mode=source_run.api_mode,
                    default_mode=source_run.mode,
                )
                retry_session = store.update_session(
                    retry_session.id,
                    metadata={
                        **dict(retry_session.metadata),
                        "arena_retry_source_run_id": source_run.id,
                        "arena_id": arena.id,
                        "arena_child_index": child.index,
                    },
                )
                target_session_id = retry_session.id
            if durable_dispatcher is not None:
                submission = await run_in_threadpool(
                    durable_dispatcher.submit,
                    target_session_id,
                    replay_payload,
                    idempotency_key=(
                        f"arena:{arena.id}:{child.index}:retry:{source_run.id}"
                    ),
                    origin="manual",
                )
                replacement = HarnessArenaChildRun(
                    harness_id=child.harness_id,
                    index=child.index,
                    session_id=target_session_id,
                    run_id=submission.queued.run.id,
                    status="queued",
                )
            else:
                result = await run_in_threadpool(
                    runner.run_in_session, target_session_id, replay_payload
                )
                replacement = HarnessArenaChildRun(
                    harness_id=child.harness_id,
                    index=child.index,
                    session_id=target_session_id,
                    run_id=result.run.id,
                    status=result.run.status.value,
                    error=result.run.error,
                    result_text=(
                        result.result.text
                        if result.run.status.value == "succeeded"
                        else None
                    ),
                )
            arena = arena_store.upsert_child(arena.id, replacement)
        except ArenaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Arena run not found") from exc
        except (RunNotFoundError, StopIteration) as exc:
            raise HTTPException(
                status_code=404, detail="Arena child not found"
            ) from exc
        except (SessionNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await run_in_threadpool(_arena_response, arena, store)

    @app.get("/api/arena/runs/{arena_id}/events/stream")
    async def arena_events_stream(
        arena_id: str,
        after_id: str | None = Query(default=None),
    ) -> StreamingResponse:
        try:
            await run_stream_offload(arena_store.get, arena_id)
        except ArenaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Arena run not found") from exc

        async def stream_events():
            last_id = _optional_text(after_id)

            def poll_stream(cursor_value: str | None):
                current_arena = arena_store.get(arena_id)
                events = _arena_events(
                    current_arena,
                    store,
                    after_id=cursor_value,
                )
                return current_arena, events

            while True:
                try:
                    current_arena, events = await run_stream_offload(
                        poll_stream, last_id
                    )
                except ArenaNotFoundError:
                    break
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
    def run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
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
    app.include_router(cockpit_router)
    app.include_router(evaluate_router)
    app.include_router(tools_router)
    app.include_router(workflows_router)
    app.include_router(runs_router)
    app.include_router(schedules_router)
    app.include_router(settings_router)
    app.include_router(create_file_preview_router(config.data_dir))
    app.include_router(create_provider_handoff_router(registry))
    # The shell catch-all must remain last so unknown API and asset paths never
    # become HTML responses.
    app.include_router(create_shell_router(ui_security))
    install_mutation_contracts(app)
    install_execution_contracts(app)
    if handler_errors := async_handler_contract_errors(app.routes):
        raise RuntimeError(
            "Harness async handler contract invalid: " + "; ".join(handler_errors)
        )
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
    runtime_store: RuntimeCoordinationStore | None = None,
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
        policy_audit_events=(
            runtime_store.list_policy_audit_events(run_id=run.id)
            if runtime_store is not None
            else ()
        ),
        data_dir=config.data_dir,
    )


def _reviewed_evidence_for_run(
    runtime_store: RuntimeCoordinationStore | None,
    run_id: str,
) -> dict[str, Any] | None:
    if runtime_store is None:
        return None
    return reviewed_evidence_manifest(
        run_id,
        runtime_store.list_policy_audit_events(run_id=run_id),
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
    run_thread = run.metadata.get("app_server_thread")
    session_thread = source.metadata.get("app_server_thread")
    source_thread = (
        dict(run_thread)
        if isinstance(run_thread, Mapping)
        else dict(session_thread)
        if isinstance(session_thread, Mapping)
        else {}
    )
    metadata = {
        **dict(source.metadata),
        "forked_from_session_id": source.id,
        "forked_from_run_id": run.id,
    }
    metadata.pop("app_server_thread", None)
    metadata.pop("structured_session_link", None)
    metadata.pop("app_server_fork", None)
    if source_thread.get("thread_id"):
        metadata["app_server_fork"] = {
            "thread_id": source_thread["thread_id"],
            "turn_id": source_thread.get("latest_turn_id"),
            "source_session_id": source.id,
            "source_run_id": run.id,
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
        stored_runs = await run_in_threadpool(store.list_runs, session_id)
        runs = [run for run in stored_runs if run.id not in before_run_ids]
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


def _run_sse_event(event: HarnessStoredEvent, cursor: str) -> str:
    payload = _event_response(event)
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {cursor}\ndata: {data}\n\n"


def _run_resnapshot_sse(run: HarnessRun, cursor: str) -> str:
    payload = {
        "type": "resnapshot_required",
        "reason": "slow_consumer",
        "cursor": cursor,
        "snapshot_url": f"/api/cockpit/sessions/{run.session_id}/events",
        "stream_url": f"/api/runs/{run.id}/events/stream",
    }
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: resnapshot\nid: {cursor}\ndata: {data}\n\n"


def _resolve_run_stream_cursor(
    store: HarnessSessionStore,
    run: HarnessRun,
    value: str | None,
    *,
    tail_only: bool = False,
) -> EventCursorPosition:
    if value is None:
        if tail_only:
            resolver = getattr(store, "event_tail_offset", None)
            if not callable(resolver):
                raise ValueError("session store does not support durable event tails")
            return EventCursorPosition(
                offset=resolver(run.session_id),
                terminal_seen=False,
            )
        return EventCursorPosition(offset=0, terminal_seen=False)
    if value.startswith("hc1."):
        return _decode_run_stream_cursor(value, run)
    resolver = getattr(store, "resolve_event_cursor", None)
    if not callable(resolver):
        raise ValueError("session store does not support durable event cursors")
    position = resolver(run.session_id, run_id=run.id, event_id=value)
    if position is None:
        raise ValueError("event cursor is stale; fetch a bounded snapshot")
    return position


def _encode_run_stream_cursor(
    run: HarnessRun,
    offset: int,
    *,
    terminal_event_seen: bool,
) -> str:
    scope = hashlib.sha256(f"{run.session_id}\0{run.id}".encode()).hexdigest()[:16]
    payload = json.dumps(
        {
            "v": 1,
            "scope": scope,
            "offset": max(offset, 0),
            "terminal": terminal_event_seen,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "hc1." + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_run_stream_cursor(value: str, run: HarnessRun) -> EventCursorPosition:
    try:
        encoded = value.removeprefix("hc1.")
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
        scope = hashlib.sha256(f"{run.session_id}\0{run.id}".encode()).hexdigest()[:16]
        if (
            not isinstance(payload, Mapping)
            or payload.get("v") != 1
            or payload.get("scope") != scope
        ):
            raise ValueError
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("invalid or cross-run event cursor") from exc
    return EventCursorPosition(
        offset=offset,
        terminal_seen=bool(payload.get("terminal")),
    )


def _native_sse_cursor(last_event_id: str | None) -> int:
    value = _optional_text(last_event_id)
    if value is None:
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def _native_output_sse(payload: Mapping[str, Any]) -> str:
    cursor = max(int(payload.get("cursor") or 0), 0)
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {cursor}\ndata: {data}\n\n"


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


def _arena_summary_response(arena: HarnessArenaRun) -> dict[str, Any]:
    payload = arena_to_dict(arena)
    payload["prompt"] = ""
    payload["child_runs"] = [arena_child_to_dict(child) for child in arena.child_runs]
    return payload


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
        messages = store.list_messages(run.session_id)[-100:]
        runs = store.list_runs(run.session_id)[-50:]
        events = store.list_events(run.session_id)[-200:]
        payload["messages"] = [message_to_dict(item) for item in messages]
        payload["runs"] = [run_to_dict(item) for item in runs]
        payload["activity"] = [
            event_to_dict(item)
            for item in events
            if item.type.startswith(("tool_", "approval_"))
            or item.type
            in {
                "cancel_requested",
                "error",
                "run_canceled",
                "run_finished",
                "warning",
            }
        ][-100:]
        payload["event_count"] = len(events)
        payload["bounded"] = True
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


def _bounded_arena_workspace_paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("workspace_paths must be a list")
    if len(value) > 8:
        raise ValueError("workspace_paths must contain at most 8 files")
    paths = tuple(str(item).strip() for item in value)
    if any(not path for path in paths):
        raise ValueError("workspace_paths must contain non-empty strings")
    return paths


def _first_text(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    return _optional_text(value[0])


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


def _native_discovery_limit(value: Any) -> int:
    if value is None:
        return 100
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="limit must be an integer") from exc
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    return limit


def _native_discovered_project_id(
    ref: NativeSessionRef,
    *,
    workspace: str | None,
    project_id: str | None,
) -> str | None:
    """Apply request scope only when the discovered ref proves the same workspace."""
    if (
        project_id is not None
        and normalize_native_workspace(ref.workspace)
        == normalize_native_workspace(workspace)
        and ref.workspace is not None
    ):
        return project_id
    return _optional_text(ref.metadata.get("project_id"))


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


def _require_native_cli_compatibility(
    registry: HarnessRegistry,
    harness_id: str,
) -> CliCapabilitySnapshot | None:
    """Reject native starts when a built-in CLI contract is not proven."""
    if harness_id not in registry.ids():
        return None
    capability_probe = getattr(registry.get(harness_id), "capability_probe", None)
    if not callable(capability_probe):
        return None
    snapshot = capability_probe()
    if snapshot.compatible:
        return snapshot
    raise NativeProcessStartError(
        snapshot.warning or f"{harness_id} is not adapter-compatible"
    )


def _plan_with_native_telemetry(
    plan: NativeCommandPlan,
    snapshot: CliCapabilitySnapshot,
    *,
    api_mode: GigaChatApiMode,
) -> NativeCommandPlan:
    """Bind truthful native observability evidence to the durable process plan."""
    return replace(
        plan,
        metadata={
            **dict(plan.metadata),
            "telemetry": {
                "api_mode": api_mode.value,
                "binary_version": snapshot.parsed_version or snapshot.version,
                "event_schema": snapshot.native_event_schema,
                "structured_events": snapshot.native_structured_events,
                "transport": (
                    "structured"
                    if snapshot.native_structured_events
                    else "raw_terminal"
                ),
                "observability_limits": (
                    []
                    if snapshot.native_structured_events
                    else [
                        "tool_lifecycle_opaque",
                        "usage_unavailable",
                        "artifacts_unclassified",
                    ]
                ),
            },
        },
    )


def _native_process_policy_gate(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    policy_engine: PolicyEngine,
    runtime_store: RuntimeCoordinationStore | None,
) -> tuple[str, dict[str, Any]] | JSONResponse:
    """Resolve the Harness-owned spawn action before sidecars or CLIs start."""
    profile = permission_profile(payload.get("permission_profile"), origin="manual")
    run_id = _native_policy_run_id(payload, session.id)
    context = PolicyContext(
        project_id=_session_project_id(session),
        session_id=session.id,
        run_id=run_id,
        reason="Start or resume a managed native CLI process.",
        preview={
            "harness_id": payload.get("harness_id") or session.default_harness_id,
            "action": payload.get("action") or "start",
            "mode": payload.get("mode") or session.default_mode,
            "workspace": payload.get("workspace") or session.workspace,
            "workspace_policy": payload.get("workspace_policy") or "auto",
        },
        enforcement_owner=NATIVE_PROCESS_SPAWN_OWNER,
    )
    resolution = policy_engine.resolve(
        PermissionAction.PROCESS_SPAWN,
        profile=profile,
        context=context,
        enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
    )
    policy_metadata = {
        "action": resolution.action.value,
        "decision": resolution.decision.value,
        "enforcement": resolution.enforcement.value,
        "policy_source": resolution.policy_source,
        "permission_profile": profile.id,
    }
    if resolution.decision is PolicyDecision.DENY:
        raise HTTPException(
            status_code=403, detail="Native process spawn denied by policy"
        )
    if resolution.decision is PolicyDecision.ALLOW:
        return run_id, policy_metadata
    if runtime_store is None:
        raise HTTPException(
            status_code=409,
            detail="Durable runtime is required for native process approval",
        )
    approval = runtime_store.create_approval_request(resolution, context)
    return JSONResponse(
        status_code=202,
        content={
            "approval_required": True,
            "approval": approval_request_to_dict(approval),
            "retry": {
                "action": "retry_native_process_start",
                "idempotency_key": payload.get("idempotency_key"),
            },
        },
    )


def _native_policy_run_id(payload: Mapping[str, Any], session_id: str) -> str:
    """Return a stable approval scope without persisting prompt contents."""
    idempotency_key = _optional_text(payload.get("idempotency_key"))
    identity = {
        "session_id": session_id,
        "idempotency_key": idempotency_key,
        "action": payload.get("action") or "start",
        "harness_id": payload.get("harness_id"),
        "native_ref_id": payload.get("native_ref_id"),
        "prompt_sha256": hashlib.sha256(
            str(payload.get("prompt") or "").encode("utf-8")
        ).hexdigest(),
        "workspace": payload.get("workspace"),
        "mode": payload.get("mode"),
        "model": payload.get("model"),
        "api_mode": payload.get("api_mode"),
        "capability": payload.get("capability"),
        "workspace_policy": payload.get("workspace_policy"),
        "attachment_ids": payload.get("attachment_ids"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"run_native_{digest[:20]}"


def _native_permission_mode(value: Any) -> str:
    mode = str(value or "plan").strip().lower()
    if mode not in {"plan", "read", "edit"}:
        raise ValueError("native mode must be plan, read, or edit")
    return mode


def _native_resume_workspace_execution(options: Mapping[str, Any]) -> dict[str, Any]:
    ref = options.get("native_ref")
    if isinstance(ref, NativeSessionRef):
        plan_metadata = _metadata_mapping(ref.metadata.get("plan_metadata"))
        stored = _metadata_mapping(plan_metadata.get("workspace_execution"))
        if stored:
            return stored
        snapshot = ref.execution_snapshot
        if snapshot is not None and (
            snapshot.source_workspace is not None
            or snapshot.effective_workspace is not None
            or snapshot.workspace_policy is not None
        ):
            effective_workspace = snapshot.effective_workspace or snapshot.workspace
            return {
                "requested_policy": snapshot.workspace_policy or "current",
                "policy": snapshot.workspace_policy or "current",
                "source_workspace": snapshot.source_workspace or snapshot.workspace,
                "source_git_root": snapshot.source_workspace,
                "effective_workspace": effective_workspace,
                "worktree_path": (
                    effective_workspace
                    if snapshot.workspace_policy == "worktree"
                    else None
                ),
                "base_branch": None,
                "base_commit": None,
                "fallback_reason": None,
            }
    workspace = _optional_text(options.get("workspace"))
    return {
        "requested_policy": "current",
        "policy": "current",
        "source_workspace": workspace,
        "source_git_root": None,
        "effective_workspace": workspace,
        "worktree_path": None,
        "base_branch": None,
        "base_commit": None,
        "fallback_reason": "legacy native resume has no stored workspace isolation",
    }


def _native_process_start_options(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    config: HarnessConfig,
    registry: HarnessRegistry,
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
            registry=registry,
            native_registry=native_registry,
            native_index_store=native_index_store,
            store=store,
        )
    return _native_process_new_options(
        payload=payload,
        session=session,
        config=config,
        registry=registry,
        native_registry=native_registry,
        attachment_store=attachment_store,
        store=store,
    )


def _native_process_new_options(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    config: HarnessConfig,
    registry: HarnessRegistry,
    native_registry: NativeHistoryConnectorRegistry,
    attachment_store: FilesystemAttachmentStore,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    harness_id = _required_text(
        payload.get("harness_id") or session.default_harness_id,
        "harness_id is required",
    )
    connector = _native_connector_or_404(native_registry, harness_id)
    cli_capabilities = _require_native_cli_compatibility(registry, harness_id)
    api_mode = parse_api_mode(payload.get("api_mode") or session.default_api_mode)
    capability = parse_capability(
        payload.get("capability") or HarnessCapability.AGENT_CLI.value
    )
    workspace = resolve_workspace(
        _optional_text(payload.get("workspace")) or session.workspace
    )
    prompt = str(payload.get("prompt") or "")
    model = _optional_text(payload.get("model")) or session.default_model
    mode = _native_permission_mode(payload.get("mode") or session.default_mode)
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
    extra["native_prompt_idempotency_key"] = _native_prompt_idempotency_key(
        session.id,
        _optional_text(payload.get("idempotency_key"))
        or new_id("native_prompt_submit"),
    )
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
    if cli_capabilities is not None:
        attachment_error = attachment_capability_error(
            request,
            cli_capabilities.capabilities,
            surface="native",
        )
        if attachment_error is not None:
            raise NativeProcessStartError(attachment_error)
    context = config.to_context()
    route_preflight = None
    if bool(getattr(connector, "requires_proxy_preflight", False)):
        route_preflight = proxy.ensure_proxy_route_available(context, api_mode)
        if not route_preflight.ok:
            raise NativeProcessStartError(
                route_preflight.error or "Native proxy preflight failed"
            )
        context = replace(
            context,
            api_key=route_preflight.api_key or context.api_key,
        )
    try:
        plan = connector.build_start_command(request, context)
        if cli_capabilities is not None:
            plan = _plan_with_native_telemetry(
                plan,
                cli_capabilities,
                api_mode=api_mode,
            )
        if route_preflight is not None:
            plan = replace(
                plan,
                metadata={
                    **dict(plan.metadata),
                    "proxy_preflight": proxy.proxy_route_preflight_to_dict(
                        route_preflight
                    ),
                },
            )
        _reject_duplicate_native_prompt_delivery(
            store,
            session.id,
            plan.prompt_delivery,
        )
    except (OSError, ValueError):
        if route_preflight is not None:
            proxy.stop_owned_sidecar(route_preflight.startup)
        raise
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
        "connector": connector,
        "attachment_ids": attachment_ids,
        "attachments": attachment_payloads,
        "attachment_render_plan": attachment_render_plan_payload,
        "preflight": preflight_payload,
        "proxy_route_preflight": route_preflight,
    }


def _native_process_resume_options(
    *,
    payload: Mapping[str, Any],
    session: HarnessSession,
    config: HarnessConfig,
    registry: HarnessRegistry,
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
    cli_capabilities = _require_native_cli_compatibility(registry, ref.harness_id)
    ref = _native_ref_with_reviewed_resume_snapshot(
        ref=ref,
        payload=payload,
        session=session,
        data_dir=config.data_dir,
    )
    snapshot = ref.execution_snapshot
    _reject_resume_snapshot_overrides(payload, snapshot)
    api_mode = parse_api_mode(
        snapshot.api_mode
        if snapshot is not None
        else payload.get("api_mode") or session.default_api_mode
    )
    capability = parse_capability(
        payload.get("capability") or HarnessCapability.AGENT_CLI.value
    )
    workspace = resolve_workspace(
        snapshot.effective_workspace or snapshot.workspace
        if snapshot is not None
        else _optional_text(payload.get("workspace"))
        or ref.workspace
        or session.workspace
    )
    context = config.to_context()
    route_preflight = None
    if bool(getattr(connector, "requires_proxy_preflight", False)):
        route_preflight = proxy.ensure_proxy_route_available(context, api_mode)
        if not route_preflight.ok:
            raise NativeProcessStartError(
                route_preflight.error or "Native proxy preflight failed"
            )
        context = replace(
            context,
            api_key=route_preflight.api_key or context.api_key,
        )
    try:
        plan = connector.build_resume_command(ref, context)
        if cli_capabilities is not None:
            plan = _plan_with_native_telemetry(
                plan,
                cli_capabilities,
                api_mode=api_mode,
            )
    except (OSError, ValueError):
        if route_preflight is not None:
            proxy.stop_owned_sidecar(route_preflight.startup)
        raise
    if route_preflight is not None:
        plan = replace(
            plan,
            metadata={
                **dict(plan.metadata),
                "proxy_preflight": proxy.proxy_route_preflight_to_dict(route_preflight),
            },
        )
    prompt = (
        _optional_text(payload.get("prompt")) or f"Resume native session: {ref.title}"
    )
    return {
        "action": "resume",
        "plan": plan,
        "harness_id": ref.harness_id,
        "prompt": prompt,
        "model": (
            snapshot.model
            if snapshot is not None
            else _optional_text(payload.get("model"))
            or _optional_text(ref.metadata.get("model"))
            or session.default_model
        ),
        "api_mode": api_mode,
        "capability": capability,
        "mode": (
            snapshot.permission_mode
            if snapshot is not None
            else str(payload.get("mode") or session.default_mode)
        ),
        "workspace": workspace,
        "native_ref": ref,
        "native_session_id": ref.native_session_id,
        "attachment_ids": (),
        "attachments": (),
        "attachment_render_plan": None,
        "connector": connector,
        "proxy_route_preflight": route_preflight,
    }


def _native_process_run_metadata(
    options: Mapping[str, Any],
    process_ref: NativeProcessRef | None = None,
    *,
    prompt_delivery_status: NativePromptDeliveryStatus | None = None,
    prompt_delivery_error: str | None = None,
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
    if isinstance(plan, NativeCommandPlan) and plan.execution_snapshot is not None:
        metadata["execution_snapshot"] = execution_snapshot_to_dict(
            plan.execution_snapshot
        )
    if isinstance(plan, NativeCommandPlan):
        telemetry = plan.metadata.get("telemetry")
        if isinstance(telemetry, Mapping):
            metadata["telemetry"] = dict(telemetry)
    if isinstance(plan, NativeCommandPlan) and plan.prompt_delivery is not None:
        process_delivery = (
            process_ref.metadata.get("prompt_delivery")
            if process_ref is not None
            else None
        )
        if isinstance(process_delivery, Mapping) and prompt_delivery_status is None:
            metadata["prompt_delivery"] = dict(process_delivery)
        else:
            metadata["prompt_delivery"] = native_prompt_delivery_to_dict(
                plan.prompt_delivery,
                status=prompt_delivery_status,
                error=prompt_delivery_error,
            )
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
    route_preflight = options.get("proxy_route_preflight")
    if isinstance(route_preflight, proxy.ProxyRoutePreflight):
        metadata["proxy_preflight"] = proxy.proxy_route_preflight_to_dict(
            route_preflight
        )
    workspace_execution = options.get("workspace_execution")
    if isinstance(workspace_execution, Mapping):
        metadata["workspace_execution"] = dict(workspace_execution)
    policy = options.get("policy")
    if isinstance(policy, Mapping):
        metadata["policy"] = dict(policy)
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
    workspace_execution = options.get("workspace_execution")
    if isinstance(workspace_execution, Mapping):
        metadata["workspace_execution"] = dict(workspace_execution)
    policy = options.get("policy")
    if isinstance(policy, Mapping):
        metadata["policy"] = dict(policy)
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
        if options["plan"].prompt_delivery is not None:
            process_delivery = process_ref.metadata.get("prompt_delivery")
            metadata["prompt_delivery"] = (
                dict(process_delivery)
                if isinstance(process_delivery, Mapping)
                else native_prompt_delivery_to_dict(options["plan"].prompt_delivery)
            )
        if options["plan"].execution_snapshot is not None:
            snapshot = options["plan"].execution_snapshot
            metadata["execution_snapshot"] = execution_snapshot_to_dict(snapshot)
            metadata["limitations"] = [] if snapshot.route_known else ["route_unknown"]
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
            workspace=(
                _optional_text(options.get("source_workspace")) or session.workspace
            ),
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
        execution_snapshot=execution_snapshot_from_dict(
            _metadata_mapping(link.metadata.get("execution_snapshot"))
        ),
    )


def _native_ref_with_reviewed_resume_snapshot(
    *,
    ref: NativeSessionRef,
    payload: Mapping[str, Any],
    session: HarnessSession,
    data_dir: str,
) -> NativeSessionRef:
    if ref.execution_snapshot is not None:
        return ref
    if ref.harness_id not in {"codex-cli", "claude-code", "gemini-cli"}:
        return ref
    explicit_api_mode = _optional_text(payload.get("api_mode"))
    if explicit_api_mode is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "route_unknown: legacy native ref requires an explicit reviewed "
                "api_mode before resume"
            ),
        )
    api_mode = parse_api_mode(explicit_api_mode)
    workspace = resolve_workspace(
        _optional_text(payload.get("workspace")) or ref.workspace or session.workspace
    )
    project_id = _optional_text(ref.metadata.get("project_id"))
    if project_id is None:
        if workspace is None:
            raise HTTPException(
                status_code=400,
                detail="Legacy native ref is missing project identity",
            )
        project_id = resolve_project(workspace, data_dir=data_dir).id
    native_home = _optional_text(ref.metadata.get("native_home"))
    if native_home is None:
        family = {
            "codex-cli": "codex",
            "claude-code": "claude",
            "gemini-cli": "gemini",
        }[ref.harness_id]
        native_home = str(
            Path(data_dir).expanduser() / "native" / family / "homes" / project_id
        )
    snapshot = create_execution_snapshot(
        harness_id=ref.harness_id,
        api_mode=api_mode.value,
        model=_optional_text(payload.get("model"))
        or _optional_text(ref.metadata.get("model"))
        or session.default_model,
        native_home=native_home,
        workspace=workspace,
        project_id=project_id,
        permission_mode=str(payload.get("mode") or session.default_mode),
        tool_config_hash=_optional_text(ref.metadata.get("tool_config_hash")),
        route_known=False,
        warnings=(
            "Legacy native ref had no route snapshot; this explicit route override "
            "applies only to the reviewed resume.",
        ),
    )
    return replace(ref, execution_snapshot=snapshot)


def _reject_resume_snapshot_overrides(
    payload: Mapping[str, Any],
    snapshot: NativeExecutionSnapshot | None,
) -> None:
    if snapshot is None:
        return
    checks = {
        "api_mode": snapshot.api_mode,
        "model": snapshot.model,
        "mode": snapshot.permission_mode,
        "workspace": snapshot.workspace,
    }
    for key, expected in checks.items():
        if key not in payload or payload.get(key) is None:
            continue
        actual = str(payload[key]).strip()
        if key == "api_mode":
            actual = parse_api_mode(actual).value
        elif key == "workspace":
            actual = resolve_workspace(actual) or ""
        if actual != (expected or ""):
            raise HTTPException(
                status_code=400,
                detail=f"Native resume {key} contradicts the execution snapshot",
            )


def _native_snapshot_link_metadata(ref: NativeSessionRef) -> dict[str, Any]:
    if ref.execution_snapshot is None:
        return {"limitations": ["route_unknown"]} if ref.can_resume else {}
    return {
        "execution_snapshot": execution_snapshot_to_dict(ref.execution_snapshot),
        "limitations": (
            [] if ref.execution_snapshot.route_known else ["route_unknown"]
        ),
    }


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


def _native_prompt_idempotency_key(session_id: str, client_key: str) -> str:
    digest = hashlib.sha256(f"{session_id}\0{client_key}".encode("utf-8")).hexdigest()
    return f"nprompt_{digest[:32]}"


def _reject_duplicate_native_prompt_delivery(
    store: HarnessSessionStore,
    session_id: str,
    delivery: NativePromptDelivery | None,
) -> None:
    if delivery is None:
        return
    for existing_run in store.list_runs(session_id):
        existing = existing_run.metadata.get("prompt_delivery")
        if not isinstance(existing, Mapping):
            continue
        if existing.get("idempotency_key") != delivery.idempotency_key:
            continue
        if existing.get("prompt_sha256") != delivery.prompt_sha256:
            raise ValueError(
                "Native prompt idempotency key is already bound to a different prompt"
            )
        state = str(existing.get("status") or "pending")
        raise ValueError(f"Native prompt delivery was already recorded as {state}")


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
    *,
    native_registry: NativeHistoryConnectorRegistry | None = None,
    native_index_store: NativeSessionIndexStore | None = None,
):
    status = _run_status_from_process(process_ref)
    metadata = _existing_run_metadata(store, process_ref)
    metadata.update(
        {
            "invocation_mode": HarnessInvocationMode.NATIVE.value,
            "native_process": {
                "id": process_ref.id,
                "pid": process_ref.pid,
                "process_group_id": process_ref.process_group_id,
                "transport": process_ref.transport,
                "status": process_ref.status.value,
                "exit_code": process_ref.exit_code,
                "owner_id": process_ref.owner_id,
                "owner_process_id": process_ref.owner_process_id,
                "heartbeat_at": process_ref.heartbeat_at,
                "leased_until": process_ref.leased_until,
                "timeout_at": process_ref.timeout_at,
                "cancel_requested_at": process_ref.cancel_requested_at,
                "terminal_cursor": process_ref.terminal_cursor,
                "recovery_outcome": process_ref.recovery_outcome,
                "reconnectable": process_ref.reconnectable,
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
    if status is RunStatus.FAILED:
        if process_ref.recovery_outcome is not None:
            patch["error"] = (
                f"Native process could not be recovered: {process_ref.recovery_outcome}"
            )
        else:
            patch["error"] = (
                f"Native process exited with code {process_ref.exit_code}"
                if process_ref.exit_code is not None
                else "Native process failed"
            )
    try:
        run = store.update_run(process_ref.run_id, **patch)
    except RunNotFoundError:
        return None
    if run.status is RunStatus.FAILED:
        _ensure_native_process_error_message(store, run, process_ref)
    if native_registry is not None:
        run = _sync_native_process_transcript(
            store,
            native_registry,
            run,
            process_ref,
            native_index_store=native_index_store,
        )
    return run


def _sync_native_process_transcript(
    store: HarnessSessionStore,
    native_registry: NativeHistoryConnectorRegistry,
    run: HarnessRun,
    process_ref: NativeProcessRef,
    *,
    native_index_store: NativeSessionIndexStore | None = None,
) -> HarnessRun:
    if run.harness_id not in {"codex-cli", "claude-code", "gemini-cli"}:
        return run
    snapshot = execution_snapshot_from_dict(
        _metadata_mapping(run.metadata.get("execution_snapshot"))
    )
    if snapshot is None:
        return run
    workspace = snapshot.source_workspace or snapshot.workspace or run.workspace
    discovery = native_registry.discover(
        harness_id=run.harness_id,
        workspace=workspace,
        include_external=False,
    )
    candidates = [
        ref
        for ref in discovery.sessions
        if ref.execution_snapshot is not None
        and ref.execution_snapshot.id == snapshot.id
    ]
    if len(candidates) != 1:
        return run
    ref = candidates[0]
    if native_index_store is not None:
        ref = native_index_store.upsert_ref(
            ref,
            project_id=(
                _optional_text(ref.metadata.get("project_id"))
                or (
                    ref.execution_snapshot.project_id
                    if ref.execution_snapshot is not None
                    else None
                )
            ),
        )
        _append_reconciled_native_link(store, run, ref)
    if run.native_session_id != ref.native_session_id:
        run = store.update_run(
            run.id,
            native_session_id=ref.native_session_id,
            metadata={
                **dict(run.metadata),
                "native_history_reconciliation": {
                    "native_ref_id": ref.id,
                    "native_session_id": ref.native_session_id,
                    "updated_at": utc_now(),
                },
            },
        )
    if run.harness_id == "codex-cli":
        return run
    try:
        connector = native_registry.get(run.harness_id)
        transcript = connector.import_ref(ref)
    except (OSError, ValueError, UnknownNativeHistoryConnectorError):
        return run
    existing_messages = store.list_messages(run.session_id)
    known_keys = {
        str(message.metadata["native_message_key"])
        for message in existing_messages
        if message.run_id == run.id and message.metadata.get("native_message_key")
    }
    known_event_keys = {
        str(event.payload["native_event_key"])
        for event in store.list_events(run.session_id, run_id=run.id)
        if event.payload.get("native_event_key")
    }
    appended_message_count = 0
    appended_event_count = 0
    for message in transcript:
        if not _native_message_belongs_to_run(message, run):
            continue
        message_key = _native_message_key(ref, message)
        for tool_call in _native_tool_records(message.metadata.get("tool_calls")):
            event_key = _native_tool_event_key(
                message_key,
                HarnessEventType.TOOL_CALL_STARTED.value,
                tool_call,
            )
            if event_key in known_event_keys:
                continue
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type=HarnessEventType.TOOL_CALL_STARTED.value,
                    message="Native tool call started.",
                    payload={
                        **tool_call,
                        "native_event_key": event_key,
                        "native_message_key": message_key,
                        "native_ref_id": ref.id,
                        "native_session_id": ref.native_session_id,
                    },
                    created_at=message.created_at or utc_now(),
                )
            )
            known_event_keys.add(event_key)
            appended_event_count += 1
        for tool_result in _native_tool_records(message.metadata.get("tool_results")):
            event_key = _native_tool_event_key(
                message_key,
                HarnessEventType.TOOL_CALL_FINISHED.value,
                tool_result,
            )
            if event_key in known_event_keys:
                continue
            store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=run.session_id,
                    run_id=run.id,
                    type=HarnessEventType.TOOL_CALL_FINISHED.value,
                    message="Native tool call finished.",
                    payload={
                        **tool_result,
                        "native_event_key": event_key,
                        "native_message_key": message_key,
                        "native_ref_id": ref.id,
                        "native_session_id": ref.native_session_id,
                    },
                    created_at=message.created_at or utc_now(),
                )
            )
            known_event_keys.add(event_key)
            appended_event_count += 1
        if (
            _native_import_message_role(message.role) != "assistant"
            or not message.content.strip()
            or message_key in known_keys
        ):
            continue
        store.append_message(
            HarnessMessage(
                id=new_id("msg"),
                session_id=run.session_id,
                run_id=run.id,
                role="assistant",
                content=str(redact_for_storage(message.content)),
                created_at=message.created_at or utc_now(),
                harness_id=run.harness_id,
                model=run.model,
                api_mode=run.api_mode,
                metadata={
                    "source": "native_process",
                    "process_id": process_ref.id,
                    "native_ref_id": ref.id,
                    "native_session_id": ref.native_session_id,
                    "native_message_key": message_key,
                    "native_metadata": _redacted_mapping(message.metadata),
                },
            )
        )
        store.append_event(
            HarnessStoredEvent(
                id=new_id("evt"),
                session_id=run.session_id,
                run_id=run.id,
                type=HarnessEventType.MESSAGE_COMPLETED.value,
                message="Native assistant message synchronized.",
                payload={
                    "role": "assistant",
                    "process_id": process_ref.id,
                    "native_ref_id": ref.id,
                    "native_session_id": ref.native_session_id,
                },
                created_at=message.created_at or utc_now(),
            )
        )
        known_keys.add(message_key)
        appended_message_count += 1
    if (
        not appended_message_count
        and not appended_event_count
        and run.native_session_id == ref.native_session_id
    ):
        return run
    metadata = {
        **dict(run.metadata),
        "native_transcript_sync": {
            "native_ref_id": ref.id,
            "native_session_id": ref.native_session_id,
            "synced_message_count": len(known_keys),
            "synced_tool_event_count": len(known_event_keys),
            "updated_at": utc_now(),
        },
    }
    return store.update_run(
        run.id,
        native_session_id=ref.native_session_id,
        metadata=metadata,
    )


def _append_reconciled_native_link(
    store: HarnessSessionStore,
    run: HarnessRun,
    ref: NativeSessionRef,
) -> None:
    current = store.get_native_link(run.session_id, run.harness_id)
    if current is not None and current.native_ref_id == ref.id:
        return
    now = utc_now()
    metadata = dict(current.metadata) if current is not None else {}
    metadata.update(
        {
            "auto_reconciled": True,
            "project_id": ref.metadata.get("project_id"),
            "execution_snapshot": (
                execution_snapshot_to_dict(ref.execution_snapshot)
                if ref.execution_snapshot is not None
                else None
            ),
        }
    )
    store.append_native_link(
        run.session_id,
        HarnessNativeLink(
            id=new_id("nlink"),
            session_id=run.session_id,
            harness_id=run.harness_id,
            status=ref.status,
            created_at=current.created_at if current is not None else now,
            updated_at=now,
            native_session_id=ref.native_session_id,
            native_ref_id=ref.id,
            source="native_history_reconciliation",
            workspace=ref.workspace or run.workspace,
            metadata=metadata,
        ),
    )


def _native_message_belongs_to_run(
    message: NativeTranscriptMessage,
    run: HarnessRun,
) -> bool:
    if run.started_at is None:
        return True
    message_time = _parse_native_timestamp(message.created_at)
    run_time = _parse_native_timestamp(run.started_at)
    return (
        message_time is not None and run_time is not None and message_time >= run_time
    )


def _parse_native_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _native_message_key(
    ref: NativeSessionRef,
    message: NativeTranscriptMessage,
) -> str:
    native_message_id = _optional_text(message.metadata.get("native_message_id"))
    if native_message_id is not None:
        return f"{ref.id}:id:{native_message_id}"
    digest = hashlib.sha256(
        json.dumps(
            [
                message.role,
                message.created_at,
                message.content,
                message.metadata.get("tool_calls"),
                message.metadata.get("tool_results"),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"{ref.id}:sha256:{digest}"


def _native_run_messages(
    store: HarnessSessionStore,
    run: HarnessRun,
) -> tuple[HarnessMessage, ...]:
    return tuple(
        message
        for message in store.list_messages(run.session_id)
        if message.run_id == run.id and message.role in {"assistant", "error"}
    )


def _native_run_events(
    store: HarnessSessionStore,
    run: HarnessRun,
) -> tuple[HarnessStoredEvent, ...]:
    return store.list_events(run.session_id, run_id=run.id)


def _native_tool_records(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _native_tool_event_key(
    message_key: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> str:
    tool_call_id = _optional_text(payload.get("tool_call_id")) or "tool-call"
    return f"{message_key}:{event_type}:{tool_call_id}"


_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)?)")
_NATIVE_ERROR_OUTPUT_LIMIT = 4000


def _ensure_native_process_error_message(
    store: HarnessSessionStore,
    run: HarnessRun,
    process_ref: NativeProcessRef,
) -> None:
    messages = store.list_messages(run.session_id)
    if any(
        message.run_id == run.id and message.role == "error" for message in messages
    ):
        return
    content = _native_process_error_content(store, run, process_ref)
    store.append_message(
        HarnessMessage(
            id=new_id("msg"),
            session_id=run.session_id,
            run_id=run.id,
            role="error",
            content=content,
            created_at=utc_now(),
            harness_id=run.harness_id,
            model=run.model,
            api_mode=run.api_mode,
            metadata={
                "source": "native_process",
                "process_id": process_ref.id,
                "exit_code": process_ref.exit_code,
            },
        )
    )
    store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=run.session_id,
            run_id=run.id,
            type=HarnessEventType.ERROR.value,
            message="Native process failed.",
            payload={
                "process_id": process_ref.id,
                "exit_code": process_ref.exit_code,
                "role": "error",
            },
            created_at=utc_now(),
        )
    )


def _native_process_error_content(
    store: HarnessSessionStore,
    run: HarnessRun,
    process_ref: NativeProcessRef,
) -> str:
    summary = run.error or "Native process failed"
    output = "".join(
        str(event.payload.get("text") or "")
        for event in store.list_events(run.session_id, run_id=run.id)
        if event.type == "terminal_output"
        and event.payload.get("process_id") == process_ref.id
    )
    output = _ANSI_ESCAPE_RE.sub("", output)
    output = "".join(
        character
        for character in output
        if character in "\n\r\t" or ord(character) >= 32
    ).strip()
    if not output:
        return summary
    excerpt = output[-_NATIVE_ERROR_OUTPUT_LIMIT:]
    indented = "\n".join(f"    {line}" for line in excerpt.splitlines())
    return f"{summary}.\n\nTerminal output:\n\n{indented}"


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
    if process_ref.status in {
        NativeProcessStatus.TIMED_OUT,
        NativeProcessStatus.INTERRUPTED,
        NativeProcessStatus.UNKNOWN,
    }:
        return RunStatus.FAILED
    if process_ref.exit_code == 0:
        return RunStatus.SUCCEEDED
    return RunStatus.FAILED


def _native_timeout_seconds(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_seconds must be a positive number") from exc
    if timeout <= 0:
        raise ValueError("timeout_seconds must be a positive number")
    return timeout


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
    metadata.update(_native_snapshot_link_metadata(ref))
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
    payload["transport_by"] = _attachment_transport_by(registry, attachment)
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
        else:
            transport = _attachment_transport_for(spec, attachment)
            if (
                transport
                and not transport["rich"]
                and _effective_attachment_kind(attachment) in {"image", "document"}
            ):
                warnings.append(
                    f"{spec.id} uses path or metadata reference only for "
                    f"{_effective_attachment_kind(attachment)} attachments."
                )
    return warnings


def _attachment_transport_by(
    registry: HarnessRegistry,
    attachment: HarnessAttachment,
) -> dict[str, dict[str, Any]]:
    return {
        harness.spec().id: transport
        for harness in registry.list()
        if (transport := _attachment_transport_for(harness.spec(), attachment))
    }


def _attachment_transport_for(
    spec,
    attachment: HarnessAttachment,
) -> dict[str, Any]:
    capabilities = getattr(spec, "attachment_capabilities", {})
    if not isinstance(capabilities, Mapping):
        return {}
    support = capabilities.get(_effective_attachment_kind(attachment))
    if support is None:
        support = capabilities.get(attachment.kind)
    if support is None:
        return {}
    if isinstance(support, Mapping):
        headless = support.get("headless", ())
        native = support.get("native", ())
        rich = bool(support.get("rich", False))
        required = support.get("required_cli_capabilities", ())
        detail = str(support.get("detail") or "")
    else:
        headless = getattr(support, "headless", ())
        native = getattr(support, "native", ())
        rich = bool(getattr(support, "rich", False))
        required = getattr(support, "required_cli_capabilities", ())
        detail = str(getattr(support, "detail", ""))
    return {
        "headless": [str(item) for item in headless],
        "native": [str(item) for item in native],
        "rich": rich,
        "required_cli_capabilities": [str(item) for item in required],
        "detail": detail,
    }


def _effective_attachment_kind(attachment: HarnessAttachment) -> str:
    if attachment.kind == "workspace_file":
        detected = attachment.metadata.get("detected_kind")
        if isinstance(detected, str) and detected:
            return detected
    return attachment.kind


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
