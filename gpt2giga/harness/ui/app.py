"""FastAPI app for the minimal Unified Harness browser UI."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from gpt2giga.harness import proxy
from gpt2giga.harness.attachments import (
    AttachmentLimits,
    AttachmentNotFoundError,
    AttachmentSessionNotFoundError,
    AttachmentValidationError,
    FilesystemAttachmentStore,
    HarnessAttachment,
    attachment_to_dict,
    limits_from_project_settings,
)
from gpt2giga.harness.config import (
    DEFAULT_MODEL_HINTS,
    HarnessConfig,
    pass_model_env_note,
)
from gpt2giga.harness.project import (
    init_project_config,
    load_project_config,
    project_config_to_dict,
    project_to_dict,
    resolve_project,
)
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.sessions import (
    FilesystemHarnessSessionStore,
    HarnessSessionStore,
    SessionNotFoundError,
)
from gpt2giga.harness.sessions.models import (
    HarnessSession,
    bundle_to_dict,
    session_to_dict,
)
from gpt2giga.harness.types import (
    HarnessCapability,
    HarnessRequest,
    availability_to_dict,
    parse_api_mode,
    parse_capability,
    result_to_dict,
    spec_to_dict,
)
from gpt2giga.harness.ui.static import INDEX_HTML
from gpt2giga.harness.workspace import (
    resolve_workspace,
    workspace_file_metadata,
    workspace_tree,
)


def create_app(
    config: HarnessConfig | None = None,
    registry: HarnessRegistry | None = None,
    store: HarnessSessionStore | None = None,
) -> FastAPI:
    """Create the Unified Harness UI app."""
    config = config or HarnessConfig.from_env()
    registry = registry or create_default_registry()
    store = store or FilesystemHarnessSessionStore(config.data_dir)
    attachment_store = FilesystemAttachmentStore(config.data_dir)
    runner = HarnessSessionRunner(
        registry=registry,
        config=config,
        store=store,
        attachment_store=attachment_store,
    )
    app = FastAPI(title="gpt2giga Unified Harness", docs_url=None, redoc_url=None)
    app.state.harness_config = config
    app.state.harness_registry = registry
    app.state.harness_session_store = store
    app.state.harness_session_runner = runner
    app.state.harness_attachment_store = attachment_store

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    @app.get("/api/harnesses")
    async def harnesses() -> dict[str, Any]:
        return {
            "harnesses": [
                {
                    "spec": spec_to_dict(harness.spec()),
                    "availability": availability_to_dict(harness.availability()),
                }
                for harness in registry.list()
            ],
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

    @app.get("/api/sessions")
    async def sessions(
        project_id: str | None = Query(default=None),
        workspace: str | None = Query(default=None),
        harness_id: str | None = Query(default=None),
        q: str | None = Query(default=None),
        include_archived: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        resolved_workspace = resolve_workspace(_optional_text(workspace))
        items = store.list_sessions(
            project_id=_optional_text(project_id),
            workspace=resolved_workspace,
            harness_id=_optional_text(harness_id),
            q=_optional_text(q),
            include_archived=include_archived,
            limit=limit,
        )
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
        request = HarnessRequest(
            prompt=str(payload.get("prompt") or ""),
            model=_optional_text(payload.get("model")),
            api_mode=api_mode,
            capability=capability,
            mode=str(payload.get("mode") or "plan"),
            stream=bool(payload.get("stream")),
            workspace=resolve_workspace(_optional_text(payload.get("workspace"))),
            extra=extra,
        )
        try:
            result = harness.run(request, config.to_context())
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Harness run failed",
            ) from exc
        return result_to_dict(result)

    return app


def validate_ui_bind(host: str, *, allow_remote: bool) -> None:
    """Reject unsafe remote UI binding unless explicitly allowed."""
    if host == "0.0.0.0" and not allow_remote:
        raise ValueError(
            "Refusing to bind UI to 0.0.0.0 without --allow-remote. "
            "The UI may expose local harness execution."
        )


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
        "defaults": config_payload["defaults"],
        "presets": list(config_payload["presets"].values()),
    }


def _fallback_models(config: HarnessConfig) -> list[str]:
    return list(
        dict.fromkeys(
            model for model in (config.default_model, *DEFAULT_MODEL_HINTS) if model
        )
    )
