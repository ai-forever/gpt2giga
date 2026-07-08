"""Session orchestration for the Unified Harness chat cockpit."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Any, Mapping

from gpt2giga.harness.attachments import (
    AttachmentNotFoundError,
    FilesystemAttachmentStore,
    HarnessAttachment,
    attachment_to_dict,
)
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.project import resolve_project
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
    HarnessRequest,
    HarnessResult,
    event_to_dict,
    parse_api_mode,
    parse_capability,
    result_to_dict,
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
        return self.run_in_session(session.id, payload)

    def run_in_session(
        self,
        session_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessSessionRunResult:
        """Run one prompt inside an existing session."""
        session = self.store.get_session(session_id)
        options = self._run_options(payload, session=session)
        harness = self.registry.get(options["harness_id"])
        previous_messages = self.store.list_messages(session.id)
        attachments = self._load_attachments(
            session.id,
            options["attachment_ids"],
        )
        attachment_payloads = tuple(
            _run_attachment_metadata(attachment) for attachment in attachments
        )
        run_metadata: dict[str, Any] = {
            "native_resume": _native_resume_metadata(options["harness_id"])
        }
        if attachment_payloads:
            run_metadata["attachment_ids"] = list(options["attachment_ids"])
            run_metadata["attachments"] = list(attachment_payloads)
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
            started_at=utc_now(),
            metadata=run_metadata,
        )
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
            "run_started",
            "Harness run started.",
            {
                "harness_id": options["harness_id"],
                "model": options["model"],
                "api_mode": options["api_mode"].value,
                "mode": options["mode"],
                "attachment_count": len(attachment_payloads),
            },
        )
        request_messages = self._build_request_messages(
            previous_messages,
            prompt=options["prompt"],
        )
        request = HarnessRequest(
            prompt=options["prompt"],
            model=options["model"],
            api_mode=options["api_mode"],
            capability=options["capability"],
            mode=options["mode"],
            stream=options["stream"],
            workspace=options["workspace"],
            messages=request_messages,
            attachments=attachment_payloads,
            session_id=session.id,
            run_id=run.id,
            native_session_id=options["native_session_id"],
            extra=_request_extra(options["extra"], attachment_payloads),
        )
        raw_request = {
            "harness_id": options["harness_id"],
            "prompt": options["prompt"],
            "model": options["model"],
            "api_mode": options["api_mode"].value,
            "capability": options["capability"].value,
            "mode": options["mode"],
            "stream": options["stream"],
            "workspace": options["workspace"],
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request_messages
            ],
            "extra": options["extra"],
        }
        if attachment_payloads:
            raw_request["attachment_ids"] = list(options["attachment_ids"])
            raw_request["attachments"] = list(attachment_payloads)
        self.store.append_raw_request(
            session_id=session.id,
            run_id=run.id,
            payload=raw_request,
        )
        self._append_event(
            session.id,
            run.id,
            "raw_request",
            "Stored redacted harness request.",
            {
                "message_count": len(request_messages),
                "attachment_count": len(attachment_payloads),
            },
        )
        try:
            result = harness.run(request, self.config.to_context())
        except Exception as exc:
            result = HarnessResult(ok=False, text="", error=str(exc))

        self.store.append_raw_response(
            session_id=session.id,
            run_id=run.id,
            payload=result_to_dict(result),
        )
        self._append_event(
            session.id,
            run.id,
            "raw_response",
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

        if result.ok:
            status = "succeeded"
            role = "assistant"
            content = result.text
            event_type = "message_completed"
            event_message = "Assistant message completed."
            error = None
        else:
            status = "failed"
            role = "error"
            content = result.error or result.text or "Harness run failed"
            event_type = "error"
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
        diff = _capture_git_diff(
            options["workspace"], enabled=options["mode"] == "edit"
        )
        if diff is not None:
            metadata["diff"] = diff
            metadata["diff_captured"] = bool(diff.strip())
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
            "run_finished",
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
        return {
            "prompt": prompt,
            "harness_id": harness_id,
            "model": model,
            "api_mode": api_mode,
            "capability": capability,
            "mode": mode,
            "workspace": workspace,
            "stream": bool(payload.get("stream")),
            "extra": extra,
            "native_session_id": _optional_text(payload.get("native_session_id")),
            "attachment_ids": attachment_ids,
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
) -> dict[str, Any]:
    payload = dict(extra)
    if attachments:
        payload["attachment_ids"] = [
            str(attachment["id"]) for attachment in attachments
        ]
        payload["attachments"] = [dict(attachment) for attachment in attachments]
    return payload


def _capture_git_diff(workspace: str | None, *, enabled: bool) -> str | None:
    if not enabled or workspace is None:
        return None
    try:
        root = subprocess.run(
            ["git", "-C", workspace, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if root.returncode != 0:
            return "No diff captured."
        diff = subprocess.run(
            ["git", "-C", workspace, "diff", "--"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "No diff captured."
    if diff.returncode != 0:
        return "No diff captured."
    text = diff.stdout.strip()
    if not text:
        return "No diff captured."
    return text[-20000:]
