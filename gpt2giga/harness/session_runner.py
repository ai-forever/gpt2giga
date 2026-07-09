"""Session orchestration for the Unified Harness chat cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga.harness.attachments import (
    AttachmentNotFoundError,
    FilesystemAttachmentStore,
    HarnessAttachment,
    attachment_to_dict,
    render_attachments_for_harness,
    render_plan_to_dict,
)
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.native.models import parse_invocation_mode
from gpt2giga.harness.project import resolve_project
from gpt2giga.harness.pr_artifacts import build_pr_artifact, pr_artifact_to_dict
from gpt2giga.harness.registry import HarnessRegistry
from gpt2giga.harness.sessions.models import (
    HarnessMessage,
    HarnessRun,
    HarnessSession,
    HarnessSessionBundle,
    HarnessStoredEvent,
    bundle_to_dict,
    run_to_dict,
)
from gpt2giga.harness.sessions.store import (
    HarnessSessionStore,
    new_id,
    title_from_prompt,
    utc_now,
)
from gpt2giga.harness.types import (
    GigaChatApiMode,
    HarnessChatMessage,
    HarnessEventType,
    HarnessRequest,
    HarnessResult,
    event_to_dict,
    parse_api_mode,
    parse_capability,
    result_to_dict,
)
from gpt2giga.harness.worktrees import (
    capture_workspace_diff,
    parse_workspace_policy,
    prepare_workspace_execution,
)
from gpt2giga.harness.workspace import resolve_workspace

MAX_HISTORY_MESSAGES = 20


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


class HarnessSessionRunner:
    """Create and run normalized harness sessions."""

    def __init__(
        self,
        *,
        registry: HarnessRegistry,
        config: HarnessConfig,
        store: HarnessSessionStore,
        attachment_store: FilesystemAttachmentStore | None = None,
    ) -> None:
        self.registry = registry
        self.config = config
        self.store = store
        self.attachment_store = attachment_store or FilesystemAttachmentStore(
            config.data_dir
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

    def run_in_session(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any | None = None,
    ) -> HarnessSessionRunResult:
        """Run one prompt inside an existing session."""
        session = self.store.get_session(session_id)
        options = self._run_options(payload, session=session)
        harness = self.registry.get(options["harness_id"])
        previous_messages = (
            ()
            if bool(_mapping(options["extra"]).get("isolated_history"))
            else self.store.list_messages(session.id)
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
        run_metadata: dict[str, Any] = {
            "invocation_mode": options["invocation_mode"].value,
            "native_resume": _native_resume_metadata(options["harness_id"]),
        }
        if attachment_payloads:
            run_metadata["attachment_ids"] = list(options["attachment_ids"])
            run_metadata["attachments"] = list(attachment_payloads)
        if attachment_render_plan_payload:
            run_metadata["attachment_render_plan"] = attachment_render_plan_payload
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
        self.store.append_message(
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
                metadata=_message_attachment_metadata(attachment_payloads),
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
            },
        )
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
            prompt=options["prompt"],
        )
        request_extra = _request_extra(
            options["extra"],
            attachment_payloads,
            attachment_render_plan_payload,
        )
        request_extra["workspace_execution"] = workspace_execution.to_metadata()
        request = HarnessRequest(
            prompt=options["prompt"],
            model=options["model"],
            api_mode=options["api_mode"],
            capability=options["capability"],
            mode=options["mode"],
            invocation_mode=options["invocation_mode"],
            stream=options["stream"],
            workspace=workspace_execution.request_workspace,
            messages=request_messages,
            attachments=attachment_payloads,
            attachment_render_plan=attachment_render_plan_payload,
            session_id=session.id,
            run_id=run.id,
            native_session_id=options["native_session_id"],
            cancel_event=cancel_event,
            extra=request_extra,
        )
        raw_request = {
            "harness_id": options["harness_id"],
            "prompt": options["prompt"],
            "model": options["model"],
            "api_mode": options["api_mode"].value,
            "capability": options["capability"].value,
            "mode": options["mode"],
            "invocation_mode": options["invocation_mode"].value,
            "stream": options["stream"],
            "workspace": options["workspace"],
            "effective_workspace": workspace_execution.request_workspace,
            "workspace_policy": workspace_execution.policy.value,
            "requested_workspace_policy": workspace_execution.requested_policy.value,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request_messages
            ],
            "extra": options["extra"],
        }
        if attachment_payloads:
            raw_request["attachment_ids"] = list(options["attachment_ids"])
            raw_request["attachments"] = list(attachment_payloads)
        if attachment_render_plan_payload:
            raw_request["attachment_render_plan"] = attachment_render_plan_payload
        self.store.append_raw_request(
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
            },
        )
        try:
            result = (
                HarnessResult(ok=False, text="", error="Harness run canceled.")
                if _cancel_requested(cancel_event)
                else harness.run(request, self.config.to_context())
            )
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

        self.store.append_raw_response(
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
            self._append_event(
                session.id,
                run.id,
                event.type,
                event.message,
                event_to_dict(event)["payload"],
            )

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
        self._append_event(
            session.id,
            run.id,
            HarnessEventType.RUN_FINISHED.value,
            "Harness run finished.",
            {"status": status},
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
        if project_metadata:
            session_patch["metadata"] = {**session.metadata, **project_metadata}
        if session.title == "Untitled session":
            session_patch["title"] = title_from_prompt(options["prompt"])
        updated_session = self.store.update_session(session.id, **session_patch)
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
        capability = parse_capability(
            payload.get("capability")
            or (spec.capabilities[0].value if spec.capabilities else None)
        )
        mode = str(payload.get("mode") or (session.default_mode if session else "plan"))
        invocation_mode = parse_invocation_mode(payload.get("invocation_mode"))
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
            "capability": capability,
            "mode": mode,
            "invocation_mode": invocation_mode,
            "workspace": workspace,
            "stream": bool(payload.get("stream")),
            "extra": extra,
            "native_session_id": _optional_text(payload.get("native_session_id")),
            "attachment_ids": attachment_ids,
            "workspace_policy": workspace_policy,
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

    def _load_attachments(
        self,
        session_id: str,
        attachment_ids: tuple[str, ...],
    ) -> tuple[HarnessAttachment, ...]:
        attachments: list[HarnessAttachment] = []
        for attachment_id in attachment_ids:
            try:
                attachment = self.attachment_store.get_attachment(attachment_id)
            except AttachmentNotFoundError as exc:
                raise ValueError(f"Unknown attachment id: {attachment_id}") from exc
            if attachment.session_id != session_id:
                raise ValueError(
                    f"Attachment does not belong to session: {attachment_id}"
                )
            attachments.append(attachment)
        return tuple(attachments)

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


def _project_metadata(workspace: str | None, *, data_dir: str) -> dict[str, str]:
    if workspace is None:
        return {}
    project = resolve_project(workspace, data_dir=data_dir)
    return {
        "project_id": project.id,
        "project_root": project.root,
        "project_name": project.name,
    }


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


def _request_extra(
    extra: Mapping[str, Any],
    attachments: tuple[Mapping[str, Any], ...],
    attachment_render_plan: Mapping[str, Any] | None = None,
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


def _cancel_requested(cancel_event: Any | None) -> bool:
    if cancel_event is None:
        return False
    is_set = getattr(cancel_event, "is_set", None)
    return bool(is_set()) if callable(is_set) else False
