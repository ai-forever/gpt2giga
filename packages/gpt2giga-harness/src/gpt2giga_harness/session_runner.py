"""Session orchestration for the Unified Harness chat cockpit."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Mapping

from gpt2giga_harness import proxy
from gpt2giga_harness.attachments import (
    AttachmentNotFoundError,
    FilesystemAttachmentStore,
    HarnessAttachment,
    attachment_to_dict,
    render_attachments_for_harness,
    render_plan_to_dict,
)
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.codex_app_server import build_execution_snapshot
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.managed_mcp import HeadlessManagedMCPSnapshotStore
from gpt2giga_harness.mcp import build_mcp_inventory
from gpt2giga_harness.native.models import parse_invocation_mode
from gpt2giga_harness.project import load_project_config, resolve_project
from gpt2giga_harness.project_memory import (
    FilesystemProjectMemoryStore,
    ProjectMemoryEntry,
    memory_entries_to_context,
    memory_entries_to_prompt,
)
from gpt2giga_harness.preflight import (
    PreflightBlockedError,
    build_preflight_report,
    preflight_report_to_dict,
)
from gpt2giga_harness.pr_artifacts import build_pr_artifact, pr_artifact_to_dict
from gpt2giga_harness.provenance import (
    build_run_provenance,
    run_provenance_to_dict,
)
from gpt2giga_harness.readiness import build_execution_readiness
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.structured import (
    DurableStructuredHarness,
    requested_execution_transport,
)
from gpt2giga_harness.sessions.conversation import (
    active_conversation_messages,
    edited_message_metadata,
    history_before_edited_message,
)
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessRun,
    HarnessSession,
    HarnessSessionBundle,
    HarnessStoredEvent,
    bundle_to_dict,
    run_to_dict,
)
from gpt2giga_harness.sessions.store import (
    HarnessSessionStore,
    SessionNotFoundError,
    new_id,
    title_from_prompt,
    utc_now,
)
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessChatMessage,
    HarnessEvent,
    HarnessEventType,
    HeadlessContinuationStrategy,
    HarnessRequest,
    HarnessResult,
    event_to_dict,
    parse_api_mode,
    parse_builtin_tools,
    parse_capability,
    result_to_dict,
)
from gpt2giga_harness.worktrees import (
    WorkspaceExecution,
    WorkspacePolicy,
    capture_workspace_diff,
    parse_workspace_policy,
    prepare_workspace_execution,
)
from gpt2giga_harness.workspace import resolve_workspace

MAX_HISTORY_MESSAGES = 20
MAX_REASONING_CHARACTERS = 32_768


@dataclass(frozen=True)
class HarnessSessionRunResult:
    """Result of running one harness inside one session."""

    session: HarnessSession
    run: HarnessRun
    result: HarnessResult
    bundle: HarnessSessionBundle

    def to_dict(self) -> dict[str, Any]:
        """Serialize the run result for API responses."""
        payload = bundle_to_dict(self.bundle)
        payload.update(
            {
                "session": payload["session"],
                "run": run_to_dict(self.run),
                "result": result_to_dict(self.result),
            }
        )
        attachments = self.run.metadata.get("attachments")
        if attachments:
            payload["attachments"] = attachments
        attachment_render_plan = self.run.metadata.get("attachment_render_plan")
        if attachment_render_plan:
            payload["attachment_render_plan"] = attachment_render_plan
        return payload


@dataclass(frozen=True)
class QueuedHarnessRun:
    """Prepared durable run and its single logical user message."""

    session: HarnessSession
    run: HarnessRun
    user_message: HarnessMessage


class HarnessSessionRunner:
    """Create and run normalized harness sessions."""

    def __init__(
        self,
        *,
        registry: HarnessRegistry,
        config: HarnessConfig,
        store: HarnessSessionStore,
        attachment_store: FilesystemAttachmentStore | None = None,
        memory_store: FilesystemProjectMemoryStore | None = None,
    ) -> None:
        self.registry = registry
        self.config = config
        self.store = store
        self.attachment_store = attachment_store or FilesystemAttachmentStore(
            config.data_dir
        )
        self.memory_store = memory_store or FilesystemProjectMemoryStore()

    def preflight(
        self,
        payload: Mapping[str, Any],
        *,
        session_id: str | None = None,
        durable: bool = False,
    ):
        """Build a pre-run safety report without invoking a harness."""
        session = self.store.get_session(session_id) if session_id is not None else None
        options = self._run_options(payload, session=session)
        previous_messages = ()
        if session is not None and not bool(
            _mapping(options["extra"]).get("isolated_history")
        ):
            previous_messages = _previous_messages_for_turn(
                self.store.list_messages(session.id),
                edit_message_id=_edit_message_id(options),
            )
        if options["attachment_ids"] and session is None:
            raise ValueError("session_id is required for attachment preflight")
        attachments = (
            self._load_attachments(session.id, options["attachment_ids"])
            if session is not None
            else ()
        )
        project_memory = self._load_project_memory(options["workspace"])
        return build_preflight_report(
            prompt=options["prompt"],
            workspace=options["workspace"],
            previous_messages=previous_messages,
            attachments=attachments,
            project_memory=project_memory,
            data_dir=self.config.data_dir,
            max_history_messages=MAX_HISTORY_MESSAGES,
            readiness=self._execution_readiness(options, durable=durable),
        )

    def create_session(
        self,
        *,
        title: str | None = None,
        workspace: str | None = None,
        default_harness_id: str = "echo",
        default_model: str | None = None,
        default_api_mode: GigaChatApiMode | str | None = None,
        default_mode: str = "plan",
    ) -> HarnessSession:
        """Create a new empty session."""
        resolved_workspace = resolve_workspace(workspace)
        return self.store.create_session(
            title=title,
            workspace=resolved_workspace,
            default_harness_id=default_harness_id,
            default_model=default_model,
            default_api_mode=parse_api_mode(default_api_mode),
            default_mode=default_mode,
            metadata=_project_metadata(
                resolved_workspace,
                data_dir=self.config.data_dir,
            ),
        )

    def create_and_run(
        self,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any | None = None,
    ) -> HarnessSessionRunResult:
        """Create a session from a prompt and immediately run it."""
        options = self._run_options(payload, session=None)
        title = _optional_text(payload.get("title")) or title_from_prompt(
            options["prompt"]
        )
        session = self.create_session(
            title=title,
            workspace=options["workspace"],
            default_harness_id=options["harness_id"],
            default_model=options["model"],
            default_api_mode=options["api_mode"],
            default_mode=options["mode"],
        )
        return self.run_in_session(session.id, payload, cancel_event=cancel_event)

    def enqueue_in_session(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        run_id: str,
    ) -> QueuedHarnessRun:
        """Prepare one durable headless run without executing its harness."""
        session = self.store.get_session(session_id)
        options = self._run_options(payload, session=session)
        if (
            options["invocation_mode"].value != "headless"
            and options["execution_transport"]
            is not ExecutionTransport.NATIVE_STRUCTURED
        ):
            raise ValueError(
                "durable jobs exclude native terminal execution without a proven "
                "native_structured transport"
            )
        report = self.preflight(payload, session_id=session_id, durable=True)
        if report.hard_block:
            raise PreflightBlockedError(report)
        managed_mcp_snapshot = self._prepare_managed_mcp_snapshot(options)
        _validate_continuation_identity(session, options)
        message_id = new_id("msg")
        run = self.store.create_run(
            run_id=run_id,
            session_id=session.id,
            harness_id=options["harness_id"],
            status="queued",
            prompt=options["prompt"],
            model=options["model"],
            api_mode=options["api_mode"],
            capability=options["capability"],
            mode=options["mode"],
            workspace=options["workspace"],
            invocation_mode=options["invocation_mode"],
            metadata={
                "invocation_mode": options["invocation_mode"].value,
                "execution_transport": (
                    options["execution_transport"].value
                    if options["execution_transport"] is not None
                    else None
                ),
                "preflight": preflight_report_to_dict(report),
                "durable": True,
                **(
                    {"managed_mcp_snapshot": managed_mcp_snapshot}
                    if managed_mcp_snapshot is not None
                    else {}
                ),
                **edited_message_metadata(_edit_message_id(options)),
                **_agent_metadata(options),
            },
        )
        user_message = self.store.append_message(
            HarnessMessage(
                id=message_id,
                session_id=session.id,
                run_id=run.id,
                role="user",
                content=options["prompt"],
                created_at=utc_now(),
                harness_id=options["harness_id"],
                model=options["model"],
                api_mode=options["api_mode"],
                metadata=edited_message_metadata(_edit_message_id(options)),
            )
        )
        updated_session = self.store.update_session(
            session.id,
            default_harness_id=options["harness_id"],
            default_model=options["model"],
            default_api_mode=options["api_mode"],
            default_mode=options["mode"],
            workspace=options["workspace"],
            title=(
                title_from_prompt(options["prompt"])
                if session.title == "Untitled session"
                and not _generate_session_title_requested(options["extra"])
                else session.title
            ),
        )
        self._schedule_session_title(session, run.id, options)
        return QueuedHarnessRun(
            session=updated_session, run=run, user_message=user_message
        )

    def run_in_session(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any | None = None,
        existing_run_id: str | None = None,
        user_message_id: str | None = None,
        excluded_history_run_ids: tuple[str, ...] = (),
        runtime_metadata: Mapping[str, Any] | None = None,
        process_sink: Any | None = None,
        durable: bool = False,
    ) -> HarnessSessionRunResult:
        """Run one prompt inside an existing session."""
        session = self.store.get_session(session_id)
        options = self._run_options(payload, session=session)
        harness = self.registry.get(options["harness_id"])
        logical_user_message_id = user_message_id or new_id("msg")
        previous_messages = ()
        if not bool(_mapping(options["extra"]).get("isolated_history")):
            previous_messages = tuple(
                message
                for message in _previous_messages_for_turn(
                    self.store.list_messages(session.id),
                    edit_message_id=_edit_message_id(options),
                    current_user_message_id=user_message_id,
                )
                if message.run_id not in excluded_history_run_ids
            )
        attachments = self._load_attachments(
            session.id,
            options["attachment_ids"],
        )
        attachment_payloads = tuple(
            _run_attachment_metadata(attachment) for attachment in attachments
        )
        attachment_render_plan = (
            render_attachments_for_harness(
                options["harness_id"],
                attachments,
                self.attachment_store,
                prompt=options["prompt"],
            )
            if attachment_payloads
            else None
        )
        attachment_render_plan_payload = (
            render_plan_to_dict(attachment_render_plan)
            if attachment_render_plan is not None
            else None
        )
        project_memory = self._load_project_memory(options["workspace"])
        project_memory_payload = (
            memory_entries_to_context(project_memory) if project_memory else None
        )
        readiness: Mapping[str, Any] | None = None
        if durable and existing_run_id is not None:
            candidate_run_ids = (
                existing_run_id,
                *reversed(excluded_history_run_ids),
            )
            for candidate_run_id in candidate_run_ids:
                try:
                    queued_run = self.store.get_run(candidate_run_id)
                except KeyError:
                    continue
                if queued_run.session_id != session.id:
                    continue
                queued_preflight = _mapping(queued_run.metadata).get("preflight")
                if not isinstance(queued_preflight, Mapping):
                    continue
                queued_readiness = queued_preflight.get("readiness")
                if isinstance(queued_readiness, Mapping):
                    # Durable submission already performed admission checks before
                    # creating the first queued run. Retries reuse the last retained
                    # attempt's immutable evidence before their new run exists.
                    readiness = dict(queued_readiness)
                    break
        if readiness is None:
            readiness = self._execution_readiness(options, durable=durable)
        preflight = build_preflight_report(
            prompt=options["prompt"],
            workspace=options["workspace"],
            previous_messages=previous_messages,
            attachments=attachments,
            project_memory=project_memory,
            data_dir=self.config.data_dir,
            max_history_messages=MAX_HISTORY_MESSAGES,
            readiness=readiness,
        )
        if preflight.hard_block:
            raise PreflightBlockedError(preflight)
        managed_mcp_snapshot = self._prepare_managed_mcp_snapshot(options)
        _validate_continuation_identity(session, options)
        preflight_payload = preflight_report_to_dict(preflight)
        effective_prompt = _prompt_with_project_memory(
            options["prompt"],
            project_memory,
        )
        run_metadata: dict[str, Any] = {
            "invocation_mode": options["invocation_mode"].value,
            "execution_transport": (
                options["execution_transport"].value
                if options["execution_transport"] is not None
                else None
            ),
            "native_resume": _native_resume_metadata(options["harness_id"]),
            "preflight": preflight_payload,
            **(
                {"managed_mcp_snapshot": managed_mcp_snapshot}
                if managed_mcp_snapshot is not None
                else {}
            ),
            **_agent_metadata(options),
        }
        edit_message_id = _edit_message_id(options)
        if edit_message_id is not None:
            run_metadata["edited_from_message_id"] = edit_message_id
        if options["builtin_tools"]:
            run_metadata["builtin_tools"] = [
                tool.value for tool in options["builtin_tools"]
            ]
        if runtime_metadata:
            run_metadata["runtime"] = dict(runtime_metadata)
        if project_memory_payload:
            run_metadata["project_memory"] = project_memory_payload
        if attachment_payloads:
            run_metadata["attachment_ids"] = list(options["attachment_ids"])
            run_metadata["attachments"] = list(attachment_payloads)
        if attachment_render_plan_payload:
            run_metadata["attachment_render_plan"] = attachment_render_plan_payload
        if existing_run_id is not None:
            try:
                run = self.store.get_run(existing_run_id)
            except KeyError:
                run = self.store.create_run(
                    run_id=existing_run_id,
                    session_id=session.id,
                    harness_id=options["harness_id"],
                    status="running",
                    prompt=options["prompt"],
                    model=options["model"],
                    api_mode=options["api_mode"],
                    capability=options["capability"],
                    mode=options["mode"],
                    workspace=options["workspace"],
                    invocation_mode=options["invocation_mode"],
                    started_at=utc_now(),
                    metadata=run_metadata,
                )
            else:
                run = self.store.update_run(
                    run.id,
                    status="running",
                    started_at=run.started_at or utc_now(),
                    metadata={**dict(run.metadata), **run_metadata},
                )
        else:
            run = self.store.create_run(
                session_id=session.id,
                harness_id=options["harness_id"],
                status="running",
                prompt=options["prompt"],
                model=options["model"],
                api_mode=options["api_mode"],
                capability=options["capability"],
                mode=options["mode"],
                workspace=options["workspace"],
                invocation_mode=options["invocation_mode"],
                started_at=utc_now(),
                metadata=run_metadata,
            )
        workspace_execution = _continued_workspace_execution(
            session,
            options,
            data_dir=self.config.data_dir,
        )
        if workspace_execution is None:
            workspace_execution = prepare_workspace_execution(
                requested_policy=options["workspace_policy"],
                harness_kind=options["harness_kind"],
                mode=options["mode"],
                workspace=options["workspace"],
                data_dir=self.config.data_dir,
                session_id=session.id,
                run_id=run.id,
                dry_run=bool(options["extra"].get("dry_run")),
            )
        run_metadata["workspace_execution"] = workspace_execution.to_metadata()
        run = self.store.update_run(run.id, metadata=run_metadata)
        if user_message_id is None:
            self.store.append_message(
                HarnessMessage(
                    id=logical_user_message_id,
                    session_id=session.id,
                    run_id=run.id,
                    role="user",
                    content=options["prompt"],
                    created_at=utc_now(),
                    harness_id=options["harness_id"],
                    model=options["model"],
                    api_mode=options["api_mode"],
                    metadata={
                        **_message_attachment_metadata(attachment_payloads),
                        **edited_message_metadata(edit_message_id),
                    },
                )
            )
        self._append_event(
            session.id,
            run.id,
            HarnessEventType.RUN_STARTED.value,
            "Harness run started.",
            {
                "harness_id": options["harness_id"],
                "model": options["model"],
                "api_mode": options["api_mode"].value,
                "mode": options["mode"],
                "invocation_mode": options["invocation_mode"].value,
                "workspace_policy": workspace_execution.policy.value,
                "requested_workspace_policy": workspace_execution.requested_policy.value,
                "attachment_count": len(attachment_payloads),
                "builtin_tools": [tool.value for tool in options["builtin_tools"]],
            },
        )
        if existing_run_id is None:
            self._schedule_session_title(session, run.id, options)
        if workspace_execution.fallback_reason:
            self._append_event(
                session.id,
                run.id,
                HarnessEventType.WARNING.value,
                "Workspace execution policy fell back to current workspace.",
                {
                    "requested_policy": workspace_execution.requested_policy.value,
                    "fallback_reason": workspace_execution.fallback_reason,
                },
            )
        request_messages = self._build_request_messages(
            previous_messages,
            prompt=effective_prompt,
        )
        request_extra = _request_extra(
            options["extra"],
            attachment_payloads,
            attachment_render_plan_payload,
        )
        request_extra["workspace_execution"] = workspace_execution.to_metadata()
        if runtime_metadata:
            request_extra["runtime"] = dict(runtime_metadata)
        if project_memory_payload:
            request_extra["project_memory"] = project_memory_payload
        request_extra["preflight"] = preflight_payload
        emitted_event_counts: Counter[str] = Counter()
        latest_usage: dict[str, Any] = {}
        reasoning_parts: dict[str, list[str]] = {"summary": [], "text": [], "model": []}

        def event_sink(event: HarnessEvent) -> None:
            self._append_event(
                session.id,
                run.id,
                event.type,
                event.message,
                event_to_dict(event)["payload"],
            )
            emitted_event_counts[_event_fingerprint(event)] += 1
            usage = _usage_from_event(event)
            if usage is not None:
                _merge_usage(latest_usage, usage)
            _collect_reasoning(reasoning_parts, event)

        request = HarnessRequest(
            prompt=effective_prompt,
            model=options["model"],
            api_mode=options["api_mode"],
            capability=options["capability"],
            mode=options["mode"],
            invocation_mode=options["invocation_mode"],
            execution_transport=options["execution_transport"],
            stream=options["stream"],
            workspace=workspace_execution.request_workspace,
            messages=request_messages,
            attachments=attachment_payloads,
            attachment_render_plan=attachment_render_plan_payload,
            builtin_tools=options["builtin_tools"],
            session_id=session.id,
            run_id=run.id,
            native_session_id=options["native_session_id"],
            cancel_event=cancel_event,
            event_sink=event_sink,
            process_sink=process_sink,
            extra=request_extra,
        )
        continuation = _continuation_plan(
            request,
            harness=harness,
            session=session,
            previous_messages=previous_messages,
            prompt_id=logical_user_message_id,
            edit_source=_edit_continuation_source(
                self.store,
                edit_message_id=edit_message_id,
                previous_messages=previous_messages,
            ),
        )
        request_extra["continuation"] = continuation
        request = replace(request, extra=request_extra)
        run_metadata["continuation"] = _public_continuation(continuation)
        run = self.store.update_run(run.id, metadata=run_metadata)
        if previous_messages and continuation.get("strategy") in {
            HeadlessContinuationStrategy.UNSUPPORTED.value,
            HeadlessContinuationStrategy.DEGRADED_REPLAY.value,
            HeadlessContinuationStrategy.ONE_SHOT.value,
        }:
            self._append_event(
                session.id,
                run.id,
                HarnessEventType.WARNING.value,
                str(continuation.get("reason") or "Headless continuity is degraded."),
                {
                    "strategy": continuation.get("strategy"),
                    "continuity_proven": False,
                },
            )
        raw_request = {
            "harness_id": options["harness_id"],
            "prompt": effective_prompt,
            "model": options["model"],
            "api_mode": options["api_mode"].value,
            "capability": options["capability"].value,
            "mode": options["mode"],
            "invocation_mode": options["invocation_mode"].value,
            "execution_transport": (
                options["execution_transport"].value
                if options["execution_transport"] is not None
                else None
            ),
            "stream": options["stream"],
            "workspace": options["workspace"],
            "effective_workspace": workspace_execution.request_workspace,
            "workspace_policy": workspace_execution.policy.value,
            "requested_workspace_policy": workspace_execution.requested_policy.value,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request_messages
            ],
            "builtin_tools": [tool.value for tool in options["builtin_tools"]],
            "extra": options["extra"],
            "continuation": _public_continuation(continuation),
        }
        if effective_prompt != options["prompt"]:
            raw_request["original_prompt"] = options["prompt"]
        if project_memory_payload:
            raw_request["project_memory"] = project_memory_payload
        if attachment_payloads:
            raw_request["attachment_ids"] = list(options["attachment_ids"])
            raw_request["attachments"] = list(attachment_payloads)
        if attachment_render_plan_payload:
            raw_request["attachment_render_plan"] = attachment_render_plan_payload
        raw_request["preflight"] = preflight_payload
        raw_request_record = self.store.append_raw_request(
            session_id=session.id,
            run_id=run.id,
            payload=raw_request,
        )
        self._append_event(
            session.id,
            run.id,
            HarnessEventType.RAW_REQUEST.value,
            "Stored redacted harness request.",
            {
                "message_count": len(request_messages),
                "attachment_count": len(attachment_payloads),
                "memory_count": len(project_memory),
                "preflight_finding_count": len(preflight.findings),
            },
        )
        if preflight.findings:
            self._append_event(
                session.id,
                run.id,
                HarnessEventType.WARNING.value,
                "Preflight completed with warnings.",
                {
                    "max_severity": preflight.max_severity,
                    "finding_count": len(preflight.findings),
                    "codes": sorted({finding.code for finding in preflight.findings}),
                },
            )
        try:
            if _cancel_requested(cancel_event):
                result = HarnessResult(ok=False, text="", error="Harness run canceled.")
            elif (
                durable
                and options["execution_transport"]
                is ExecutionTransport.NATIVE_STRUCTURED
            ):
                if not isinstance(harness, DurableStructuredHarness):
                    raise ValueError(
                        "durable structured admission changed after submission"
                    )
                result = harness.run_durable_structured(
                    request, self.config.to_context()
                )
            else:
                result = harness.run(request, self.config.to_context())
        except Exception as exc:
            result = HarnessResult(ok=False, text="", error=str(exc))
        if _cancel_requested(cancel_event):
            result = HarnessResult(
                ok=False,
                text="",
                raw=result.raw,
                events=result.events,
                command=result.command,
                error="Harness run canceled.",
            )

        raw_response_record = self.store.append_raw_response(
            session_id=session.id,
            run_id=run.id,
            payload=result_to_dict(result),
        )
        self._append_event(
            session.id,
            run.id,
            HarnessEventType.RAW_RESPONSE.value,
            "Stored redacted harness response.",
            {"ok": result.ok},
        )
        for event in result.events:
            fingerprint = _event_fingerprint(event)
            if emitted_event_counts[fingerprint] > 0:
                emitted_event_counts[fingerprint] -= 1
                continue
            self._append_event(
                session.id,
                run.id,
                event.type,
                event.message,
                event_to_dict(event)["payload"],
            )
            usage = _usage_from_event(event)
            if usage is not None:
                _merge_usage(latest_usage, usage)
            _collect_reasoning(reasoning_parts, event)

        if _cancel_requested(cancel_event):
            status = "canceled"
            role = "error"
            content = "Harness run canceled."
            event_type = HarnessEventType.RUN_CANCELED.value
            event_message = "Harness run canceled."
            error = content
        elif result.ok:
            status = "succeeded"
            role = "assistant"
            content = result.text
            event_type = HarnessEventType.MESSAGE_COMPLETED.value
            event_message = "Assistant message completed."
            error = None
        else:
            status = "failed"
            role = "error"
            content = result.error or result.text or "Harness run failed"
            event_type = HarnessEventType.ERROR.value
            event_message = "Harness run failed."
            error = content
        message_metadata: dict[str, Any] = {}
        if role == "assistant" and latest_usage:
            message_metadata["usage"] = dict(latest_usage)
        reasoning = _final_reasoning(reasoning_parts)
        if role == "assistant" and reasoning:
            message_metadata["reasoning"] = reasoning
        self.store.append_message(
            HarnessMessage(
                id=new_id("msg"),
                session_id=session.id,
                run_id=run.id,
                role=role,
                content=content,
                created_at=utc_now(),
                harness_id=options["harness_id"],
                model=options["model"],
                api_mode=options["api_mode"],
                metadata=message_metadata,
            )
        )
        self._append_event(
            session.id,
            run.id,
            event_type,
            event_message,
            {"role": role},
        )
        metadata = dict(run_metadata)
        app_server_thread = _mapping(result.raw).get("app_server_thread")
        structured_session_link = _mapping(result.raw).get("structured_session_link")
        if isinstance(app_server_thread, Mapping) and app_server_thread:
            metadata["app_server_thread"] = dict(app_server_thread)
        if isinstance(structured_session_link, Mapping) and structured_session_link:
            metadata["structured_session_link"] = dict(structured_session_link)
        if latest_usage:
            metadata["usage"] = dict(latest_usage)
        if options["mode"] == "edit":
            workspace_diff = capture_workspace_diff(workspace_execution)
            if workspace_diff is not None:
                workspace_metadata = {
                    **dict(metadata.get("workspace_execution", {})),
                    **workspace_diff.to_metadata(),
                }
                metadata["workspace_execution"] = workspace_metadata
                metadata["diff"] = workspace_diff.patch
                metadata["diff_captured"] = workspace_diff.captured
                if workspace_diff.captured:
                    self._append_event(
                        session.id,
                        run.id,
                        HarnessEventType.FILE_CHANGED.value,
                        "Captured workspace diff.",
                        {
                            "changed_files": list(workspace_diff.changed_files),
                            "untracked_files": list(workspace_diff.untracked_files),
                            "workspace_policy": workspace_execution.policy.value,
                        },
                    )
        pr_artifact_run = HarnessRun(
            id=run.id,
            session_id=session.id,
            harness_id=options["harness_id"],
            status=status,
            prompt=options["prompt"],
            model=options["model"],
            api_mode=options["api_mode"],
            capability=options["capability"],
            mode=options["mode"],
            workspace=options["workspace"],
            created_at=run.created_at,
            updated_at=run.updated_at,
            invocation_mode=options["invocation_mode"],
            started_at=run.started_at,
            finished_at=utc_now(),
            error=error,
            command=result.command,
            native_session_id=run.native_session_id,
            metadata=metadata,
        )
        metadata["pr_artifact"] = pr_artifact_to_dict(
            build_pr_artifact(
                pr_artifact_run,
                result_text=content if role == "assistant" else None,
                result_raw=result.raw,
            )
        )
        updated_run = self.store.update_run(
            run.id,
            status=status,
            finished_at=utc_now(),
            error=error,
            command=result.command,
            metadata=metadata,
        )
        session_patch: dict[str, Any] = {
            "default_harness_id": options["harness_id"],
            "default_model": options["model"],
            "default_api_mode": options["api_mode"],
            "default_mode": options["mode"],
            "workspace": options["workspace"],
        }
        project_metadata = _project_metadata(
            options["workspace"],
            data_dir=self.config.data_dir,
        )
        session_metadata = {**session.metadata, **project_metadata}
        if isinstance(app_server_thread, Mapping) and app_server_thread:
            session_metadata["app_server_thread"] = dict(app_server_thread)
            session_metadata.pop("app_server_fork", None)
        if isinstance(structured_session_link, Mapping) and structured_session_link:
            session_metadata["structured_session_link"] = dict(structured_session_link)
        if session_metadata:
            session_patch["metadata"] = session_metadata
        if (
            session.title == "Untitled session"
            and not _generate_session_title_requested(options["extra"])
        ):
            session_patch["title"] = title_from_prompt(options["prompt"])
        updated_session = self.store.update_session(session.id, **session_patch)
        self._append_event(
            session.id,
            run.id,
            HarnessEventType.RUN_FINISHED.value,
            "Harness run finished.",
            {"status": status},
        )
        provenance = build_run_provenance(
            updated_run,
            session=updated_session,
            spec=harness.spec(),
            raw_requests=(raw_request_record,),
            raw_responses=(raw_response_record,),
            events=self.store.list_events(session.id, run_id=run.id),
            data_dir=self.config.data_dir,
        )
        metadata = {
            **dict(updated_run.metadata),
            "provenance": run_provenance_to_dict(provenance),
        }
        updated_run = self.store.update_run(run.id, metadata=metadata)
        bundle = self.store.get_session_bundle(session.id)
        return HarnessSessionRunResult(
            session=updated_session,
            run=updated_run,
            result=result,
            bundle=bundle,
        )

    def _run_options(
        self,
        payload: Mapping[str, Any],
        *,
        session: HarnessSession | None,
    ) -> dict[str, Any]:
        prompt = str(payload.get("prompt") or "")
        harness_id = str(
            payload.get("harness_id")
            or (session.default_harness_id if session else "echo")
        )
        spec = self.registry.get(harness_id).spec()
        model = _optional_text(payload.get("model"))
        if model is None and session is not None:
            model = session.default_model
        if model is None:
            model = self.config.default_model
        api_mode = parse_api_mode(
            payload.get("api_mode")
            or (session.default_api_mode if session else self.config.default_api_mode)
        )
        builtin_tools = parse_builtin_tools(payload.get("builtin_tools"))
        if builtin_tools and api_mode is not GigaChatApiMode.V2:
            raise ValueError("built-in tools require /v2/chat/completions")
        supported_builtin_tools = set(getattr(spec, "supported_builtin_tools", ()))
        unsupported_builtin_tools = [
            tool.value for tool in builtin_tools if tool not in supported_builtin_tools
        ]
        if unsupported_builtin_tools:
            raise ValueError(
                f"{harness_id} does not support built-in tools: "
                + ", ".join(unsupported_builtin_tools)
            )
        capability = parse_capability(
            payload.get("capability")
            or (spec.capabilities[0].value if spec.capabilities else None)
        )
        mode = str(payload.get("mode") or (session.default_mode if session else "plan"))
        invocation_mode = parse_invocation_mode(payload.get("invocation_mode"))
        execution_transport = requested_execution_transport(payload)
        workspace = _optional_text(payload.get("workspace"))
        if workspace is None and session is not None:
            workspace = session.workspace
        workspace = resolve_workspace(workspace)
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        extra = dict(extra)
        if bool(payload.get("dry_run")):
            extra["dry_run"] = True
        if "continue_native" in payload:
            extra["continue_native"] = bool(payload.get("continue_native"))
        attachment_ids = _attachment_ids(payload.get("attachment_ids"))
        workspace_policy = parse_workspace_policy(
            payload.get("workspace_policy") or extra.get("workspace_policy")
        )
        return {
            "prompt": prompt,
            "harness_id": harness_id,
            "harness_kind": spec.kind,
            "model": model,
            "api_mode": api_mode,
            "builtin_tools": builtin_tools,
            "capability": capability,
            "mode": mode,
            "invocation_mode": invocation_mode,
            "execution_transport": execution_transport,
            "workspace": workspace,
            "stream": bool(payload.get("stream")),
            "extra": extra,
            "native_session_id": _optional_text(payload.get("native_session_id")),
            "attachment_ids": attachment_ids,
            "workspace_policy": workspace_policy,
            "agent_id": _optional_text(payload.get("agent_id")),
            "agent_profile_snapshot": (
                dict(payload["agent_profile_snapshot"])
                if isinstance(payload.get("agent_profile_snapshot"), Mapping)
                else None
            ),
            "agent_execution_plan": (
                dict(payload["agent_execution_plan"])
                if isinstance(payload.get("agent_execution_plan"), Mapping)
                else None
            ),
        }

    def _build_request_messages(
        self,
        previous_messages: tuple[HarnessMessage, ...],
        *,
        prompt: str,
    ) -> tuple[HarnessChatMessage, ...]:
        history = [
            HarnessChatMessage(role=message.role, content=message.content)
            for message in previous_messages
            if message.role in {"user", "assistant"} and message.content
        ]
        history.append(HarnessChatMessage(role="user", content=prompt))
        return tuple(history[-MAX_HISTORY_MESSAGES:])

    def _execution_readiness(
        self,
        options: Mapping[str, Any],
        *,
        durable: bool,
    ) -> dict[str, Any]:
        return build_execution_readiness(
            self.config,
            self.registry,
            harness_id=str(options["harness_id"]),
            invocation_mode=options["invocation_mode"],
            execution_transport=options["execution_transport"],
            api_mode=options["api_mode"],
            model=options["model"],
            mode=str(options["mode"]),
            workspace=options["workspace"],
            workspace_policy=options["workspace_policy"],
            durable=durable,
            dry_run=bool(_mapping(options["extra"]).get("dry_run")),
        )

    def _schedule_session_title(
        self,
        session: HarnessSession,
        run_id: str,
        options: Mapping[str, Any],
    ) -> None:
        """Generate the first UI title off the run's critical path."""
        if session.title != "Untitled session" or not _generate_session_title_requested(
            options["extra"]
        ):
            return
        prompt = str(options["prompt"])
        model = (
            _optional_text(options["extra"].get("session_title_model"))
            or _optional_text(options.get("model"))
            or self.config.default_model
        )

        def generate() -> None:
            try:
                title = _generate_session_title(self.config, prompt, model=model)
                updated = self.store.update_session_if_title(
                    session.id,
                    "Untitled session",
                    title=title,
                )
                if updated is None:
                    return
                self._append_event(
                    session.id,
                    run_id,
                    HarnessEventType.SESSION_UPDATED.value,
                    "Session title revision stored.",
                    {
                        "session_id": session.id,
                        "revision": updated.updated_at,
                        "changed_fields": ["title"],
                    },
                )
            except (OSError, SessionNotFoundError, ValueError):
                return

        threading.Thread(
            target=generate,
            name=f"harness-session-title-{session.id}",
            daemon=True,
        ).start()

    def _load_attachments(
        self,
        session_id: str,
        attachment_ids: tuple[str, ...],
    ) -> tuple[HarnessAttachment, ...]:
        session = self.store.get_session(session_id)
        shared_parent_session_id = _optional_text(
            session.metadata.get("arena_parent_session_id")
        )
        shared_attachment_session_id = _optional_text(
            session.metadata.get("shared_attachment_session_id")
        )
        allowed_session_ids = {
            session_id,
            shared_parent_session_id,
            shared_attachment_session_id,
        }
        attachments: list[HarnessAttachment] = []
        for attachment_id in attachment_ids:
            try:
                attachment = self.attachment_store.get_attachment(attachment_id)
            except AttachmentNotFoundError as exc:
                raise ValueError(f"Unknown attachment id: {attachment_id}") from exc
            if attachment.session_id not in allowed_session_ids:
                raise ValueError(
                    f"Attachment does not belong to session: {attachment_id}"
                )
            attachments.append(attachment)
        return tuple(attachments)

    def _load_project_memory(
        self,
        workspace: str | None,
    ) -> tuple[ProjectMemoryEntry, ...]:
        if workspace is None:
            return ()
        try:
            project = resolve_project(
                workspace,
                data_dir=self.config.data_dir,
                load_config_name=False,
            )
        except ValueError:
            return ()
        return self.memory_store.enabled_for_prompt(project)

    def _prepare_managed_mcp_snapshot(
        self,
        options: dict[str, Any],
    ) -> Mapping[str, Any] | None:
        """Resolve or freeze the selected managed tools before run creation."""
        extra = dict(_mapping(options.get("extra")))
        reference = extra.get("managed_mcp_snapshot")
        store = HeadlessManagedMCPSnapshotStore(self.config.data_dir)
        if isinstance(reference, Mapping):
            snapshot = store.load(reference)
            if snapshot.harness_id != options["harness_id"]:
                raise ValueError("Managed MCP snapshot harness does not match run")
            project = resolve_project(
                options.get("workspace"),
                data_dir=self.config.data_dir,
                load_config_name=False,
            )
            if snapshot.project_id != project.id:
                raise ValueError("Managed MCP snapshot project does not match run")
            public_ref = snapshot.public_ref()
            extra["managed_mcp_snapshot"] = public_ref
            extra["tool_ids"] = list(snapshot.server_ids)
            options["extra"] = extra
            return public_ref
        tool_ids = _managed_tool_ids(extra.get("tool_ids"))
        if not tool_ids:
            return None
        if options["invocation_mode"].value != "headless":
            raise ValueError(
                "Managed MCP run snapshots currently require headless mode"
            )
        if options["harness_id"] not in {
            "codex-cli",
            "claude-code",
            "gemini-cli",
        }:
            raise ValueError(
                f"{options['harness_id']} does not support managed MCP snapshots"
            )
        project = resolve_project(
            options.get("workspace"),
            data_dir=self.config.data_dir,
            load_config_name=False,
        )
        loaded = load_project_config(project.root)
        descriptors, errors = build_mcp_inventory(loaded.tool_profiles)
        selected_errors = {
            str(item.get("server_id")): str(item.get("error"))
            for item in errors
            if str(item.get("server_id")) in tool_ids
        }
        if selected_errors:
            details = "; ".join(
                f"{server_id}: {selected_errors[server_id]}"
                for server_id in sorted(selected_errors)
            )
            raise ValueError(f"Managed MCP inventory is invalid: {details}")
        snapshot = store.create(
            project_id=project.id,
            harness_id=options["harness_id"],
            descriptors=descriptors,
            server_ids=tool_ids,
        )
        public_ref = snapshot.public_ref()
        extra["managed_mcp_snapshot"] = public_ref
        extra["tool_ids"] = list(snapshot.server_ids)
        options["extra"] = extra
        return public_ref

    def _append_event(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        message: str,
        payload: Mapping[str, Any],
    ) -> HarnessStoredEvent:
        return self.store.append_event(
            HarnessStoredEvent(
                id=new_id("evt"),
                session_id=session_id,
                run_id=run_id,
                type=event_type,
                message=message,
                payload=payload,
                created_at=utc_now(),
            )
        )


def _native_resume_metadata(harness_id: str) -> dict[str, Any]:
    if harness_id in {"codex-cli", "claude-code", "gemini-cli"}:
        return {
            "supported": False,
            "reason": "normalized gpt2giga history is enabled; native resume is not implemented yet",
        }
    return {
        "supported": False,
        "reason": "native sessions do not apply to this harness",
    }


def _validate_continuation_identity(
    session: HarnessSession,
    options: Mapping[str, Any],
) -> None:
    """Reject incompatible structured continuation before run side effects."""
    if session.metadata.get("app_server_fork"):
        return
    link = _mapping(session.metadata.get("app_server_thread"))
    snapshot = _mapping(link.get("snapshot"))
    if not link or options.get("harness_id") != "codex-cli":
        return
    extra = _mapping(options.get("extra"))
    managed_mcp = _mapping(extra.get("managed_mcp_snapshot"))
    actual = {
        "harness_id": options.get("harness_id"),
        "api_mode": getattr(options.get("api_mode"), "value", options.get("api_mode")),
        "model": options.get("model"),
        "source_workspace": options.get("workspace"),
        "permission_mode": options.get("mode"),
        "tool_snapshot_hash": managed_mcp.get("snapshot_hash"),
    }
    mismatched = [key for key, value in actual.items() if snapshot.get(key) != value]
    if mismatched:
        raise ValueError(
            "Codex app-server continuation changed "
            + ", ".join(mismatched)
            + "; fork explicitly."
        )


def _edit_message_id(options: Mapping[str, Any]) -> str | None:
    return _optional_text(_mapping(options.get("extra")).get("edit_message_id"))


def _previous_messages_for_turn(
    messages: tuple[HarnessMessage, ...],
    *,
    edit_message_id: str | None,
    current_user_message_id: str | None = None,
) -> tuple[HarnessMessage, ...]:
    active = active_conversation_messages(messages)
    if current_user_message_id is not None:
        current = next(
            (message for message in active if message.id == current_user_message_id),
            None,
        )
        if current is not None:
            edited_from = _optional_text(current.metadata.get("edited_from_message_id"))
            if edit_message_id is not None and edited_from != edit_message_id:
                raise ValueError("Edited user message branch does not match its source")
            return tuple(
                message for message in active if message.id != current_user_message_id
            )
    if edit_message_id is not None:
        return history_before_edited_message(active, edit_message_id)
    return active


def _edit_continuation_source(
    store: HarnessSessionStore,
    *,
    edit_message_id: str | None,
    previous_messages: tuple[HarnessMessage, ...],
) -> Mapping[str, Any] | None:
    if edit_message_id is None:
        return None
    for message in reversed(previous_messages):
        if message.run_id is None:
            continue
        try:
            run = store.get_run(message.run_id)
        except KeyError:
            continue
        link = _mapping(run.metadata.get("app_server_thread"))
        if link.get("thread_id"):
            return {
                "action": "fork",
                "link": link,
                "thread_id": link["thread_id"],
                "turn_id": link.get("latest_turn_id"),
            }
    return {"action": "start"}


def _continuation_plan(
    request: HarnessRequest,
    *,
    harness: Any,
    session: HarnessSession,
    previous_messages: tuple[HarnessMessage, ...],
    prompt_id: str,
    edit_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select one truthful, machine-readable headless continuation strategy."""
    if (
        request.execution_transport is ExecutionTransport.NATIVE_STRUCTURED
        and harness.spec().id != "codex-cli"
    ):
        return {
            "strategy": ExecutionTransport.NATIVE_STRUCTURED.value,
            "supported": True,
            "continuity_proven": True,
            "action": (
                "start"
                if edit_source is not None
                else "continue"
                if previous_messages
                else "start"
            ),
            "prompt_id": prompt_id,
            "history_replayed": edit_source is not None and bool(previous_messages),
        }
    if (
        request.invocation_mode.value != "headless"
        and request.execution_transport is not ExecutionTransport.NATIVE_STRUCTURED
    ):
        return {
            "strategy": HeadlessContinuationStrategy.NATIVE_CLI_RESUME.value,
            "supported": bool(request.native_session_id),
            "reason": "Native continuity is owned by the managed native connector.",
        }
    spec = harness.spec()
    configured = getattr(
        spec,
        "headless_continuation",
        HeadlessContinuationStrategy.ONE_SHOT,
    )
    strategy = (
        configured.value
        if isinstance(configured, HeadlessContinuationStrategy)
        else str(configured)
    )
    if strategy == HeadlessContinuationStrategy.STRUCTURED_THREAD.value:
        probe = getattr(harness, "capability_probe", None)
        snapshot = probe() if callable(probe) else None
        capabilities = getattr(snapshot, "capabilities", {})
        if not isinstance(capabilities, Mapping) or not capabilities.get("app-server"):
            return {
                "strategy": HeadlessContinuationStrategy.DEGRADED_REPLAY.value,
                "supported": True,
                "continuity_proven": False,
                "reason": (
                    "Codex app-server is unavailable; normalized history is replayed "
                    "into a fresh codex exec --ephemeral process."
                ),
            }
        managed_mcp = _mapping(request.extra.get("managed_mcp_snapshot"))
        home_identity = (
            "apphome_"
            + hashlib.sha256(
                (
                    f"{request.api_mode.value}\0"
                    f"{managed_mcp.get('snapshot_hash') or 'no-tools'}"
                ).encode("utf-8")
            ).hexdigest()[:24]
        )
        execution_snapshot = build_execution_snapshot(
            request,
            managed_home_id=home_identity,
        )
        link = _mapping(session.metadata.get("app_server_thread"))
        fork = _mapping(session.metadata.get("app_server_fork"))
        native_operation = str(
            request.extra.get("native_session_operation") or ""
        ).strip()
        if request.native_session_id and not link and not fork:
            if native_operation == "resume":
                link = {
                    "schema_version": 1,
                    "protocol": "codex-app-server-json-rpc-v2",
                    "thread_id": request.native_session_id,
                    "snapshot": execution_snapshot,
                    "snapshot_hash": execution_snapshot["snapshot_hash"],
                    "runtime_status": "external",
                }
            elif native_operation == "fork":
                fork = {"thread_id": request.native_session_id}
            else:
                raise ValueError(
                    "Codex native session identity requires resume or fork"
                )
        if edit_source is not None:
            link = _mapping(edit_source.get("link"))
            fork = (
                {
                    "thread_id": edit_source.get("thread_id"),
                    "turn_id": edit_source.get("turn_id"),
                }
                if edit_source.get("action") == "fork"
                else {}
            )
        if link:
            expected = str(link.get("snapshot_hash") or "")
            if expected != execution_snapshot["snapshot_hash"]:
                raise ValueError(
                    "Codex app-server continuation changed route, model, workspace, "
                    "permission mode, managed home, or tool snapshot; fork explicitly."
                )
        action = (
            "fork"
            if fork
            else "resume"
            if native_operation == "resume" and link
            else "continue"
            if link
            else "start"
        )
        return {
            "strategy": HeadlessContinuationStrategy.STRUCTURED_THREAD.value,
            "supported": True,
            "continuity_proven": True,
            "action": action,
            "prompt_id": prompt_id,
            "snapshot": execution_snapshot,
            "link": link or None,
            "fork_thread_id": fork.get("thread_id"),
            "fork_turn_id": fork.get("turn_id"),
            "protocol": "codex-app-server-json-rpc-v2",
            "cli_version": str(getattr(snapshot, "version", None) or "unknown"),
            "normalized_history_canonical": True,
            "history_replayed": False,
        }
    if strategy == HeadlessContinuationStrategy.STRUCTURED_REPLAY.value:
        return {
            "strategy": strategy,
            "supported": True,
            "continuity_proven": True,
            "history_replayed": bool(previous_messages),
            "reason": "Normalized Harness messages are sent as one structured request.",
        }
    if strategy == HeadlessContinuationStrategy.UNSUPPORTED.value:
        return {
            "strategy": strategy,
            "supported": False,
            "continuity_proven": False,
            "reason": (
                f"{spec.title} headless mode does not consume a stable external "
                "session id or normalized prior turns; this run is one-shot."
            ),
        }
    return {
        "strategy": HeadlessContinuationStrategy.ONE_SHOT.value,
        "supported": False,
        "continuity_proven": False,
        "reason": "This adapter advertises one-shot execution only.",
    }


def _public_continuation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Remove delivery-only ids while retaining truthful continuity evidence."""
    return {
        key: item for key, item in value.items() if key not in {"prompt_id", "link"}
    }


def _continued_workspace_execution(
    session: HarnessSession,
    options: Mapping[str, Any],
    *,
    data_dir: str,
) -> WorkspaceExecution | None:
    """Reuse the first isolated edit worktree for later app-server turns."""
    link = _mapping(session.metadata.get("app_server_thread"))
    snapshot = _mapping(link.get("snapshot"))
    if not link or snapshot.get("permission_mode") != "edit":
        return None
    if options.get("harness_id") != "codex-cli" or options.get("mode") != "edit":
        return None
    source = _optional_text(snapshot.get("source_workspace"))
    effective = _optional_text(snapshot.get("workspace"))
    requested_source = _optional_text(options.get("workspace"))
    if source != requested_source or effective is None:
        raise ValueError(
            "Codex app-server edit continuation changed its source workspace; "
            "fork explicitly."
        )
    effective_path = Path(effective).expanduser().resolve()
    owned_root = Path(data_dir).expanduser().resolve() / "worktrees"
    try:
        effective_path.relative_to(owned_root)
    except ValueError as exc:
        raise ValueError(
            "Stored Codex app-server worktree is outside Harness ownership"
        ) from exc
    if not effective_path.is_dir():
        raise ValueError(
            "Stored Codex app-server worktree is unavailable; fork explicitly."
        )
    requested_policy = parse_workspace_policy(options.get("workspace_policy"))
    return WorkspaceExecution(
        requested_policy=requested_policy,
        policy=WorkspacePolicy.WORKTREE,
        source_workspace=source,
        source_git_root=_optional_text(snapshot.get("source_git_root")),
        effective_workspace=str(effective_path),
        worktree_path=str(effective_path),
    )


def _project_metadata(workspace: str | None, *, data_dir: str) -> dict[str, str]:
    if workspace is None:
        return {}
    project = resolve_project(workspace, data_dir=data_dir)
    return {
        "project_id": project.id,
        "project_root": project.root,
        "project_name": project.name,
    }


def _prompt_with_project_memory(
    prompt: str,
    entries: tuple[ProjectMemoryEntry, ...],
) -> str:
    if not entries:
        return prompt
    memory_text = memory_entries_to_prompt(entries)
    return (
        f"Project memory to honor for this run:\n{memory_text}\n\nUser task:\n{prompt}"
    )


def _generate_session_title_requested(extra: Mapping[str, Any]) -> bool:
    return bool(extra.get("generate_session_title"))


def _generate_session_title(
    config: HarnessConfig,
    prompt: str,
    *,
    model: str | None,
) -> str:
    """Generate a compact title through the local proxy with a safe fallback."""
    fallback = title_from_prompt(prompt)
    if model is None:
        return fallback
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Create a concise session title of 3 to 7 words in the user's "
                    "language. Return only the title without quotes or punctuation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": 32,
    }
    api_key = config.api_key or proxy.cached_sidecar_api_key(config.proxy_url)
    try:
        response = proxy.request_json(
            "POST",
            proxy.build_chat_completions_url(config.proxy_url, GigaChatApiMode.V2),
            payload=payload,
            api_key=api_key,
            timeout=min(config.timeout_seconds, 15.0),
        )
    except (OSError, proxy.ProxyRequestError, ValueError):
        return fallback
    generated = proxy.extract_text(response).strip().strip("\"'`").strip()
    return title_from_prompt(generated) if generated else fallback


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


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


def _managed_tool_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("tool_ids must be a list")
    result: list[str] = []
    for item in value:
        server_id = _optional_text(item)
        if server_id is None:
            raise ValueError("tool_ids must contain non-empty strings")
        if server_id not in result:
            result.append(server_id)
    return tuple(result)


def _run_attachment_metadata(
    attachment: HarnessAttachment,
) -> dict[str, Any]:
    payload = attachment_to_dict(attachment)
    payload.pop("storage_path", None)
    return payload


def _message_attachment_metadata(
    attachments: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    if not attachments:
        return {}
    return {
        "attachment_ids": [str(attachment["id"]) for attachment in attachments],
        "attachments": [dict(attachment) for attachment in attachments],
    }


def _agent_metadata(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return immutable, redacted AgentProfile identity for run history."""
    agent_id = _optional_text(options.get("agent_id"))
    snapshot = options.get("agent_profile_snapshot")
    if agent_id is None or not isinstance(snapshot, Mapping):
        return {}
    metadata = {
        "agent_id": agent_id,
        "agent_profile_snapshot": dict(snapshot),
    }
    execution_plan = options.get("agent_execution_plan")
    if isinstance(execution_plan, Mapping):
        metadata["agent_execution_plan"] = dict(execution_plan)
    return metadata


def _request_extra(
    extra: Mapping[str, Any],
    attachments: tuple[Mapping[str, Any], ...],
    attachment_render_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(extra)
    payload.pop("edit_message_id", None)
    if attachments:
        payload["attachment_ids"] = [
            str(attachment["id"]) for attachment in attachments
        ]
        payload["attachments"] = [dict(attachment) for attachment in attachments]
    if attachment_render_plan:
        payload["attachment_render_plan"] = dict(attachment_render_plan)
    return payload


def _cancel_requested(cancel_event: Any | None) -> bool:
    if cancel_event is None:
        return False
    is_set = getattr(cancel_event, "is_set", None)
    return bool(is_set()) if callable(is_set) else False


def _event_fingerprint(event: HarnessEvent) -> str:
    """Return a stable fingerprint used to suppress already-streamed events."""
    return json.dumps(
        event_to_dict(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _usage_from_event(event: HarnessEvent) -> dict[str, Any] | None:
    """Extract safe token counters from one normalized usage event."""
    if event.type != HarnessEventType.USAGE.value:
        return None
    payload = event_to_dict(event)["payload"]
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
        "cached_input_tokens": ("cached_input_tokens", "cached_tokens"),
        "reasoning_output_tokens": (
            "reasoning_output_tokens",
            "reasoning_tokens",
            "thoughts_tokens",
        ),
        "tool_tokens": ("tool_tokens",),
    }
    usage: dict[str, Any] = {}
    for target, keys in aliases.items():
        value = next(
            (payload[key] for key in keys if _is_nonnegative_integer(payload.get(key))),
            None,
        )
        if value is not None:
            usage[target] = value
    if (
        "total_tokens" not in usage
        and {
            "input_tokens",
            "output_tokens",
        }
        <= usage.keys()
    ):
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    source = payload.get("source")
    if isinstance(source, str) and source:
        usage["source"] = source
    return usage or None


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _collect_reasoning(
    target: dict[str, list[str]],
    event: HarnessEvent,
) -> None:
    if event.type != HarnessEventType.REASONING_DELTA.value:
        return
    payload = event_to_dict(event)["payload"]
    delta = payload.get("delta")
    if not isinstance(delta, str) or not delta:
        return
    kind = str(payload.get("kind") or "model")
    target.setdefault(kind, []).append(delta)


def _final_reasoning(parts: Mapping[str, list[str]]) -> str:
    selected = parts.get("summary") or parts.get("model") or parts.get("text") or []
    return "".join(selected)[:MAX_REASONING_CHARACTERS]


def _merge_usage(target: dict[str, Any], update: Mapping[str, Any]) -> None:
    """Merge partial usage snapshots and keep the aggregate total consistent."""
    explicit_total = "total_tokens" in update
    target.update(update)
    if (
        not explicit_total
        and _is_nonnegative_integer(target.get("input_tokens"))
        and _is_nonnegative_integer(target.get("output_tokens"))
    ):
        target["total_tokens"] = target["input_tokens"] + target["output_tokens"]
