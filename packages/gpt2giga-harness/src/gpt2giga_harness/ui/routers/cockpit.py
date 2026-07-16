"""Bounded read projections for the packaged Cockpit V2 client."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any, Callable, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from gpt2giga_harness.sessions.filesystem import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessRun,
    HarnessSession,
    HarnessStoredEvent,
    event_to_dict,
    message_to_dict,
    run_to_dict,
)
from gpt2giga_harness.sessions.read_index import (
    SessionIndexCursor,
    StaleReadSnapshotError,
)
from gpt2giga_harness.sessions.store import (
    HarnessSessionStore,
    RunNotFoundError,
    SessionNotFoundError,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.worktrees import run_diff_response


router = APIRouter(route_class=ConformantAPIRoute)

_DEFAULT_PAGE_BYTES = 256 * 1024
_MAX_PAGE_BYTES = 1024 * 1024
_ITEM_TEXT_BYTES = 32 * 1024
_REVISION_NAMESPACE = secrets.token_hex(16)


@router.get("/api/cockpit/sessions")
def cockpit_sessions(
    request: Request,
    project_id: str | None = Query(default=None),
    workspace: str | None = Query(default=None),
    harness_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Return indexed session summaries without loading complete bundles."""
    store = _store(request)
    scope = _scope_hash(project_id, workspace, harness_id, q, include_archived)
    if isinstance(store, FilesystemHarnessSessionStore):
        decoded = _decode_cursor(cursor, "sessions", scope) if cursor else None
        index_cursor = (
            SessionIndexCursor(
                generation=int(decoded["generation"]),
                pinned=int(decoded["pinned"]),
                updated_at=str(decoded["updated_at"]),
                session_id=str(decoded["session_id"]),
            )
            if decoded is not None
            else None
        )
        try:
            page = store.list_sessions_page(
                project_id=project_id,
                workspace=workspace,
                harness_id=harness_id,
                q=q,
                include_archived=include_archived,
                cursor=index_cursor,
                limit=limit,
            )
        except StaleReadSnapshotError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        summaries, byte_count, byte_limited = _fit_items(
            [_session_summary(item) for item in page.items], max_bytes
        )
        has_more = page.has_more or byte_limited
        revision = _revision("sessions", str(page.generation), scope)
        last = page.items[len(summaries) - 1] if summaries else None
        next_cursor = (
            _encode_cursor(
                "sessions",
                scope,
                generation=page.generation,
                pinned=int(last.pinned),
                updated_at=last.updated_at,
                session_id=last.id,
            )
            if has_more and last is not None
            else None
        )
    else:
        all_items = store.list_sessions(
            project_id=project_id,
            workspace=workspace,
            harness_id=harness_id,
            q=q,
            include_archived=include_archived,
        )
        revision = _revision(
            "sessions-memory",
            *(f"{item.id}:{item.updated_at}" for item in all_items),
            scope,
        )
        decoded = _decode_cursor(cursor, "sessions-memory", scope) if cursor else None
        if decoded is not None and decoded.get("revision") != revision:
            raise HTTPException(
                status_code=409, detail="session cursor snapshot is stale"
            )
        offset = int(decoded.get("offset", 0)) if decoded else 0
        candidates = [
            _session_summary(item) for item in all_items[offset : offset + limit]
        ]
        summaries, byte_count, byte_limited = _fit_items(candidates, max_bytes)
        next_offset = offset + len(summaries)
        has_more = byte_limited or next_offset < len(all_items)
        next_cursor = (
            _encode_cursor(
                "sessions-memory", scope, revision=revision, offset=next_offset
            )
            if has_more and summaries
            else None
        )
    return _etag_response(
        request,
        revision,
        {
            "sessions": summaries,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "snapshot_revision": revision,
            "byte_count": byte_count,
            "order": "pinned_desc_updated_at_desc_id_desc",
        },
    )


@router.get("/api/cockpit/sessions/{session_id}")
def cockpit_session(session_id: str, request: Request) -> Response:
    """Return one lightweight session overview and its lazy request graph."""
    try:
        session = _store(request).get_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    revision = _revision("session", session.id, session.updated_at)
    return _etag_response(
        request,
        revision,
        {
            "session": _session_summary(session),
            "snapshot_revision": revision,
            "projections": {
                name: f"/api/cockpit/sessions/{session.id}/{name}"
                for name in ("messages", "runs", "events", "artifacts")
            },
        },
    )


@router.get("/api/cockpit/sessions/{session_id}/messages")
def cockpit_messages(
    session_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Return append-order cursor-paged message projections."""
    return _record_page(
        request,
        session_id,
        "messages",
        cursor,
        limit,
        max_bytes,
        _message_projection,
    )


@router.get("/api/cockpit/sessions/{session_id}/runs")
def cockpit_session_runs(
    session_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Return append-order cursor-paged run summaries."""
    return _record_page(
        request, session_id, "runs", cursor, limit, max_bytes, _run_summary
    )


@router.get("/api/cockpit/sessions/{session_id}/events")
def cockpit_events(
    session_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Return bounded trace/event nodes; payloads remain lazy."""
    return _record_page(
        request, session_id, "events", cursor, limit, max_bytes, _event_projection
    )


@router.get("/api/cockpit/sessions/{session_id}/artifacts")
def cockpit_artifacts(
    session_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Return content-free artifact availability metadata by retained run."""
    return _record_page(
        request, session_id, "runs", cursor, limit, max_bytes, _artifact_projection
    )


@router.get("/api/cockpit/runs/{run_id}")
def cockpit_run(run_id: str, request: Request) -> Response:
    """Resolve one run through the direct read index, without a session scan."""
    run = _get_run(request, run_id)
    revision = _run_revision(run)
    return _etag_response(
        request,
        revision,
        {
            "run": _run_summary(run),
            "snapshot_revision": revision,
            "projections": {
                name: f"/api/cockpit/runs/{run.id}/{name}"
                for name in ("raw", "diff", "report")
            },
        },
    )


@router.get("/api/cockpit/runs/{run_id}/raw")
def cockpit_run_raw(
    run_id: str,
    request: Request,
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Lazily return bounded redacted raw request/response evidence."""
    store = _store(request)
    run = _get_run(request, run_id)
    records = [
        ("request", item)
        for item in store.list_raw_requests(run.session_id)
        if item.run_id == run.id
    ]
    records.extend(
        ("response", item)
        for item in store.list_raw_responses(run.session_id)
        if item.run_id == run.id
    )
    records.sort(key=lambda item: (item[1].created_at, item[1].id, item[0]))
    per_record = max(512, (max_bytes - 1024) // max(len(records), 1))
    items = []
    for direction, record in records:
        serialized = json.dumps(record.payload, ensure_ascii=False, sort_keys=True)
        items.append(
            {
                "id": record.id,
                "direction": direction,
                "created_at": record.created_at,
                "payload": _text_projection(serialized, per_record),
            }
        )
    items, byte_count, truncated = _fit_items(items, max_bytes)
    revision = _revision(
        "raw",
        _run_revision(run),
        *(f"{item[1].id}:{item[1].created_at}" for item in records),
    )
    return _etag_response(
        request,
        revision,
        {
            "run_id": run.id,
            "records": items,
            "has_more": truncated,
            "snapshot_revision": revision,
            "byte_count": byte_count,
        },
    )


@router.get("/api/cockpit/runs/{run_id}/diff")
def cockpit_run_diff(
    run_id: str,
    request: Request,
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Lazily return one bounded diff projection."""
    run = _get_run(request, run_id)
    diff = run_diff_response(run.metadata)
    patch = str(diff.get("patch") or "")
    revision = _revision(
        "diff", _run_revision(run), hashlib.sha256(patch.encode()).hexdigest()
    )
    return _etag_response(
        request,
        revision,
        {
            "run_id": run.id,
            "patch": _text_projection(patch, max_bytes - 1024),
            "changed_files": list(diff.get("changed_files") or ())[:100],
            "untracked_files": list(diff.get("untracked_files") or ())[:100],
            "can_apply": bool(diff.get("can_apply")),
            "can_discard": bool(diff.get("can_discard")),
            "snapshot_revision": revision,
        },
    )


@router.get("/api/cockpit/runs/{run_id}/report")
def cockpit_run_report(
    run_id: str,
    request: Request,
    max_bytes: int = Query(default=_DEFAULT_PAGE_BYTES, ge=1024, le=_MAX_PAGE_BYTES),
) -> Response:
    """Lazily return a bounded retained report projection."""
    run = _get_run(request, run_id)
    report = _retained_report(run.metadata)
    revision = _revision(
        "report", _run_revision(run), hashlib.sha256(report.encode()).hexdigest()
    )
    return _etag_response(
        request,
        revision,
        {
            "run_id": run.id,
            "report": _text_projection(report, max_bytes - 1024),
            "snapshot_revision": revision,
        },
    )


def _record_page(
    request: Request,
    session_id: str,
    record_type: str,
    cursor: str | None,
    limit: int,
    max_bytes: int,
    projector: Callable[[Any], dict[str, Any]],
) -> Response:
    store = _store(request)
    scope = _scope_hash(session_id, record_type)
    decoded = _decode_cursor(cursor, "records", scope) if cursor else None
    if isinstance(store, FilesystemHarnessSessionStore):
        try:
            page = store.list_record_page(
                session_id,
                record_type=record_type,
                projector=projector,
                offset=int(decoded.get("offset", 0)) if decoded else 0,
                snapshot_revision=str(decoded["revision"]) if decoded else None,
                limit=limit,
                max_bytes=max_bytes,
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except StaleReadSnapshotError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = list(page.items)
        revision = page.snapshot_revision
        has_more = page.has_more
        byte_count = page.byte_count
        next_cursor = (
            _encode_cursor(
                "records",
                scope,
                revision=revision,
                offset=page.next_offset,
            )
            if page.has_more and page.next_offset is not None
            else None
        )
    else:
        try:
            records = _memory_records(store, session_id, record_type)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        revision = _revision(
            record_type,
            *(
                f"{getattr(item, 'id', '')}:{getattr(item, 'created_at', '')}"
                for item in records
            ),
        )
        if decoded is not None and decoded.get("revision") != revision:
            raise HTTPException(
                status_code=409, detail=f"{record_type} cursor snapshot is stale"
            )
        offset = int(decoded.get("offset", 0)) if decoded else 0
        candidates = [projector(item) for item in records[offset : offset + limit]]
        items, byte_count, byte_limited = _fit_items(candidates, max_bytes)
        next_offset = offset + len(items)
        has_more = byte_limited or next_offset < len(records)
        next_cursor = (
            _encode_cursor("records", scope, revision=revision, offset=next_offset)
            if has_more and items
            else None
        )
    return _etag_response(
        request,
        revision,
        {
            record_type: items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "snapshot_revision": revision,
            "byte_count": byte_count,
            "order": "append_created_at_asc_id_asc",
        },
    )


def _store(request: Request) -> HarnessSessionStore:
    return request.app.state.harness_session_store


def _get_run(request: Request, run_id: str) -> HarnessRun:
    try:
        return _store(request).get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def _memory_records(
    store: HarnessSessionStore, session_id: str, record_type: str
) -> tuple[Any, ...]:
    readers = {
        "messages": store.list_messages,
        "runs": store.list_runs,
        "events": store.list_events,
    }
    reader = readers.get(record_type)
    if reader is None:
        raise ValueError(f"unsupported session record type: {record_type}")
    return tuple(reader(session_id))


def _session_summary(session: HarnessSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": _bounded_text(session.title, 512),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "default_harness_id": session.default_harness_id,
        "default_model": session.default_model,
        "default_api_mode": session.default_api_mode.value,
        "default_mode": session.default_mode,
        "pinned": session.pinned,
        "archived": session.archived,
        "tags": [_bounded_text(item, 128) for item in session.tags[:20]],
        "project_id": str(session.metadata.get("project_id") or "") or None,
        "workspace_bound": session.workspace is not None,
    }


def _message_projection(message: HarnessMessage) -> dict[str, Any]:
    payload = message_to_dict(message)
    content = str(payload.pop("content") or "")
    payload.pop("metadata", None)
    payload["content"] = _text_projection(content, _ITEM_TEXT_BYTES)
    return payload


def _run_summary(run: HarnessRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "session_id": run.session_id,
        "harness_id": run.harness_id,
        "status": run.status.value,
        "model": run.model,
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "invocation_mode": run.invocation_mode.value,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": _text_projection(run.error or "", 4096) if run.error else None,
        "artifacts": _artifact_metadata(run),
    }


def _event_projection(event: HarnessStoredEvent) -> dict[str, Any]:
    payload = event_to_dict(event)
    payload.pop("payload", None)
    payload["message"] = _bounded_text(str(payload.get("message") or ""), 4096)
    payload["payload_url"] = f"/api/runs/{event.run_id}/events/{event.id}"
    return payload


def _artifact_projection(run: HarnessRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "created_at": run.created_at,
        "artifacts": _artifact_metadata(run),
    }


def _artifact_metadata(run: HarnessRun) -> list[dict[str, Any]]:
    metadata = dict(run.metadata)
    execution = metadata.get("workspace_execution")
    execution = dict(execution) if isinstance(execution, Mapping) else {}
    artifacts: list[dict[str, Any]] = []
    patch = str(execution.get("patch") or metadata.get("diff") or "")
    if patch:
        artifacts.append(
            {
                "type": "diff",
                "byte_count": len(patch.encode("utf-8")),
                "projection_url": f"/api/cockpit/runs/{run.id}/diff",
            }
        )
    if execution.get("worktree_path"):
        artifacts.append({"type": "worktree", "byte_count": None})
    if isinstance(metadata.get("pr_artifact"), Mapping):
        artifacts.append(
            {
                "type": "pr_report",
                "byte_count": len(_retained_report(metadata).encode("utf-8")),
                "projection_url": f"/api/cockpit/runs/{run.id}/report",
            }
        )
    return artifacts


def _retained_report(metadata: Mapping[str, Any]) -> str:
    for key in ("pr_artifact", "report", "test_report", "summary"):
        value = metadata.get(key)
        if value:
            return (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            )
    return ""


def _run_revision(run: HarnessRun) -> str:
    return _revision(
        "run",
        json.dumps(run_to_dict(run), ensure_ascii=False, sort_keys=True),
    )


def _fit_items(
    items: list[dict[str, Any]], max_bytes: int
) -> tuple[list[dict[str, Any]], int, bool]:
    fitted: list[dict[str, Any]] = []
    byte_count = 0
    for item in items:
        size = len(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if fitted and byte_count + size > max_bytes:
            return fitted, byte_count, True
        if size > max_bytes:
            raise HTTPException(
                status_code=413, detail="one projection exceeds max_bytes"
            )
        fitted.append(item)
        byte_count += size
    return fitted, byte_count, False


def _text_projection(value: str, max_bytes: int) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {
        "text": _bounded_text(value, max_bytes),
        "byte_count": len(encoded),
        "truncated": len(encoded) > max_bytes,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _bounded_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[: max(max_bytes, 0)].decode("utf-8", errors="ignore")


def _scope_hash(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _revision(*parts: str) -> str:
    return hashlib.sha256(
        "\0".join((_REVISION_NAMESPACE, *parts)).encode("utf-8")
    ).hexdigest()


def _encode_cursor(kind: str, scope: str, **payload: Any) -> str:
    raw = json.dumps(
        {"v": 1, "kind": kind, "scope": scope, **payload},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str, kind: str, scope: str) -> dict[str, Any]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid cockpit cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("kind") != kind
        or payload.get("scope") != scope
    ):
        raise HTTPException(status_code=400, detail="cockpit cursor scope mismatch")
    return payload


def _etag_response(
    request: Request,
    revision: str,
    payload: Mapping[str, Any],
) -> Response:
    etag = f'"{revision}"'
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"}
        )
    return JSONResponse(
        content=dict(payload),
        headers={"ETag": etag, "Cache-Control": "private, no-cache"},
    )
