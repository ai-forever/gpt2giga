"""Multi-harness arena orchestration and storage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.runtime.structured import (
    admitted_durable_structured_capabilities,
    requested_execution_transport,
)
from gpt2giga_harness.runtime.worker import DurableJobDispatcher
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import new_id, title_from_prompt, utc_now
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions.models import HarnessRun
from gpt2giga_harness.sessions.store import HarnessSessionStore, SessionNotFoundError
from gpt2giga_harness.types import GigaChatApiMode, parse_api_mode
from gpt2giga_harness.workspace import resolve_workspace


class ArenaNotFoundError(KeyError):
    """Raised when an arena run does not exist."""


class ArenaReviewConflictError(ValueError):
    """Raised when reviewed Arena evidence no longer matches current runs."""


ARENA_REVIEW_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HarnessArenaRequest:
    """Request to compare several harnesses on the same prompt."""

    prompt: str
    harness_ids: tuple[str, ...]
    model: str | None = None
    api_mode: GigaChatApiMode = GigaChatApiMode.V2
    mode: str = "plan"
    workspace: str | None = None
    attachment_ids: tuple[str, ...] = ()
    workspace_policy: str = "auto"
    execution_transport: ExecutionTransport | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessArenaChildRun:
    """One child run inside an arena comparison."""

    harness_id: str
    index: int
    session_id: str | None
    run_id: str | None
    status: str
    error: str | None = None
    result_text: str | None = None


@dataclass(frozen=True)
class HarnessArenaRun:
    """Persisted arena parent object linking child runs."""

    id: str
    session_id: str
    status: str
    prompt: str
    harness_ids: tuple[str, ...]
    model: str | None
    api_mode: GigaChatApiMode
    mode: str
    workspace: str | None
    attachment_ids: tuple[str, ...]
    workspace_policy: str
    execution_transport: ExecutionTransport | None
    created_at: str
    updated_at: str
    child_runs: tuple[HarnessArenaChildRun, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class FilesystemHarnessArenaStore:
    """Persist arena parent records as transparent JSON files."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.arenas_dir = self.data_dir / "arenas"

    def create(
        self,
        request: HarnessArenaRequest,
        *,
        session_id: str,
    ) -> HarnessArenaRun:
        """Create one arena record."""
        now = utc_now()
        arena = HarnessArenaRun(
            id=new_id("arena"),
            session_id=session_id,
            status="running",
            prompt=str(redact_for_storage(request.prompt)),
            harness_ids=request.harness_ids,
            model=request.model,
            api_mode=request.api_mode,
            mode=request.mode,
            workspace=request.workspace,
            attachment_ids=request.attachment_ids,
            workspace_policy=request.workspace_policy,
            execution_transport=request.execution_transport,
            created_at=now,
            updated_at=now,
            metadata={
                **_redacted_mapping(request.extra),
                "reviewed_arena": {
                    "schema_version": ARENA_REVIEW_SCHEMA_VERSION,
                    "task_sha256": _arena_task_sha256(request),
                },
            },
        )
        self.save(arena)
        return arena

    def get(self, arena_id: str) -> HarnessArenaRun:
        """Return one arena record."""
        path = self._path(arena_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArenaNotFoundError(arena_id) from exc
        return arena_from_dict(data)

    def list(
        self,
        *,
        workspace: str | None = None,
        limit: int | None = None,
    ) -> tuple[HarnessArenaRun, ...]:
        """List persisted arena records newest first."""
        arenas: list[HarnessArenaRun] = []
        if not self.arenas_dir.exists():
            return ()
        for path in self.arenas_dir.glob("*.json"):
            try:
                arena = arena_from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                continue
            if workspace is not None and arena.workspace != workspace:
                continue
            arenas.append(arena)
        arenas.sort(
            key=lambda arena: (arena.updated_at, arena.created_at), reverse=True
        )
        if limit is not None:
            arenas = arenas[: max(limit, 0)]
        return tuple(arenas)

    def save(self, arena: HarnessArenaRun) -> HarnessArenaRun:
        """Persist one arena record."""
        self.arenas_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(arena.id)
        with exclusive_file_lock(path):
            _write_json_atomic(path, arena_to_dict(arena))
        return arena

    def upsert_child(
        self, arena_id: str, child: HarnessArenaChildRun
    ) -> HarnessArenaRun:
        """Process-safely insert or replace one arena child by index."""
        path = self._path(arena_id)
        with exclusive_file_lock(path):
            arena = arena_from_dict(json.loads(path.read_text(encoding="utf-8")))
            children = [item for item in arena.child_runs if item.index != child.index]
            children.append(child)
            children.sort(key=lambda item: item.index)
            updated = replace(
                arena,
                child_runs=tuple(children),
                status=_arena_status(
                    tuple(children), expected_count=len(arena.harness_ids)
                ),
                updated_at=utc_now(),
            )
            _write_json_atomic(path, arena_to_dict(updated))
        return updated

    def record_verdict(
        self,
        arena_id: str,
        *,
        candidate_set_sha256: str,
        selected_child_index: int,
        selected_run_id: str,
        scores: tuple[Mapping[str, Any], ...],
        verdict_sha256: str,
    ) -> HarnessArenaRun:
        """Atomically persist one immutable operator verdict."""
        path = self._path(arena_id)
        with exclusive_file_lock(path):
            arena = arena_from_dict(json.loads(path.read_text(encoding="utf-8")))
            reviewed = dict(_mapping(arena.metadata.get("reviewed_arena")))
            existing = _mapping(reviewed.get("verdict"))
            if existing:
                if existing.get("verdict_sha256") != verdict_sha256:
                    raise ArenaReviewConflictError("arena verdict is already immutable")
                return arena
            reviewed["verdict"] = {
                "schema_version": ARENA_REVIEW_SCHEMA_VERSION,
                "candidate_set_sha256": candidate_set_sha256,
                "selected_child_index": selected_child_index,
                "selected_run_id": selected_run_id,
                "scores": [dict(item) for item in scores],
                "decided_at": utc_now(),
                "verdict_sha256": verdict_sha256,
            }
            updated = replace(
                arena,
                metadata={**dict(arena.metadata), "reviewed_arena": reviewed},
                updated_at=utc_now(),
            )
            _write_json_atomic(path, arena_to_dict(updated))
        return updated

    def append_child(
        self,
        arena: HarnessArenaRun,
        child: HarnessArenaChildRun,
    ) -> HarnessArenaRun:
        """Append one child run and update arena status."""
        children = (*arena.child_runs, child)
        updated = replace(
            arena,
            child_runs=children,
            status=_arena_status(children, expected_count=len(arena.harness_ids)),
            updated_at=utc_now(),
        )
        return self.save(updated)

    def _path(self, arena_id: str) -> Path:
        return self.arenas_dir / f"{arena_id}.json"


def run_arena(
    *,
    runner: HarnessSessionRunner,
    arena_store: FilesystemHarnessArenaStore,
    payload: Mapping[str, Any],
    session_id: str | None = None,
) -> HarnessArenaRun:
    """Run a multi-harness comparison with isolated concurrent children."""
    request = arena_request_from_payload(payload)
    if request.execution_transport is ExecutionTransport.NATIVE_STRUCTURED:
        raise ValueError("native_structured Arena requires the durable runtime")
    session = (
        runner.store.get_session(session_id)
        if session_id is not None
        else runner.create_session(
            title=title_from_prompt(request.prompt),
            workspace=request.workspace,
            default_harness_id=request.harness_ids[0],
            default_model=request.model,
            default_api_mode=request.api_mode,
            default_mode=request.mode,
        )
    )
    arena = arena_store.create(request, session_id=session.id)
    children = _create_arena_child_sessions(runner, arena, request)
    for child in children:
        arena_store.upsert_child(arena.id, child)
    with ThreadPoolExecutor(
        max_workers=min(len(children), 4),
        thread_name_prefix=f"{arena.id}-child",
    ) as executor:
        futures = {
            executor.submit(
                _run_arena_child,
                runner=runner,
                session_id=child.session_id or "",
                arena=arena,
                request=request,
                harness_id=child.harness_id,
                index=child.index,
                turn_index=0,
            ): child.index
            for child in children
        }
        for future in as_completed(futures):
            arena_store.upsert_child(arena.id, future.result())
    return arena_store.get(arena.id)


def queue_arena(
    *,
    runner: HarnessSessionRunner,
    dispatcher: DurableJobDispatcher,
    arena_store: FilesystemHarnessArenaStore,
    payload: Mapping[str, Any],
    session_id: str | None = None,
) -> HarnessArenaRun:
    """Queue arena children as independent durable jobs."""
    request = arena_request_from_payload(payload)
    if request.execution_transport is ExecutionTransport.NATIVE_STRUCTURED:
        for harness_id in request.harness_ids:
            admitted_durable_structured_capabilities(runner.registry.get(harness_id))
    session = (
        runner.store.get_session(session_id)
        if session_id is not None
        else runner.create_session(
            title=title_from_prompt(request.prompt),
            workspace=request.workspace,
            default_harness_id=request.harness_ids[0],
            default_model=request.model,
            default_api_mode=request.api_mode,
            default_mode=request.mode,
        )
    )
    arena = arena_store.create(request, session_id=session.id)
    children = _create_arena_child_sessions(runner, arena, request)
    for child in children:
        child_payload = _arena_child_payload(
            arena=arena,
            request=request,
            harness_id=child.harness_id,
            index=child.index,
            turn_index=0,
        )
        submission = dispatcher.submit(
            child.session_id or "",
            child_payload,
            idempotency_key=f"arena:{arena.id}:{child.index}:turn:0",
            origin="manual",
        )
        arena = arena_store.upsert_child(
            arena.id,
            HarnessArenaChildRun(
                harness_id=child.harness_id,
                index=child.index,
                session_id=child.session_id,
                run_id=submission.queued.run.id,
                status="queued",
            ),
        )
    return arena


def continue_arena(
    *,
    runner: HarnessSessionRunner,
    arena_store: FilesystemHarnessArenaStore,
    arena: HarnessArenaRun,
    payload: Mapping[str, Any],
) -> HarnessArenaRun:
    """Fan one shared follow-up out to every isolated child concurrently."""
    if arena.execution_transport is ExecutionTransport.NATIVE_STRUCTURED:
        raise ValueError("native_structured Arena requires the durable runtime")
    request, turn_index = _follow_up_request(arena_store, arena, payload)
    children = _require_arena_children(arena_store.get(arena.id))
    for child in children:
        arena_store.upsert_child(arena.id, replace(child, status="running", error=None))
    with ThreadPoolExecutor(
        max_workers=min(len(children), 4),
        thread_name_prefix=f"{arena.id}-follow-up",
    ) as executor:
        futures = [
            executor.submit(
                _run_arena_child,
                runner=runner,
                session_id=child.session_id or "",
                arena=arena,
                request=request,
                harness_id=child.harness_id,
                index=child.index,
                turn_index=turn_index,
            )
            for child in children
        ]
        for future in as_completed(futures):
            arena_store.upsert_child(arena.id, future.result())
    return arena_store.get(arena.id)


def queue_arena_follow_up(
    *,
    runner: HarnessSessionRunner,
    dispatcher: DurableJobDispatcher,
    arena_store: FilesystemHarnessArenaStore,
    arena: HarnessArenaRun,
    payload: Mapping[str, Any],
) -> HarnessArenaRun:
    """Queue one shared follow-up as independent durable child jobs."""
    request, turn_index = _follow_up_request(arena_store, arena, payload)
    for child in _require_arena_children(arena_store.get(arena.id)):
        child_payload = _arena_child_payload(
            arena=arena,
            request=request,
            harness_id=child.harness_id,
            index=child.index,
            turn_index=turn_index,
        )
        submission = dispatcher.submit(
            child.session_id or "",
            child_payload,
            idempotency_key=f"arena:{arena.id}:{child.index}:turn:{turn_index}",
            origin="manual",
        )
        arena_store.upsert_child(
            arena.id,
            HarnessArenaChildRun(
                harness_id=child.harness_id,
                index=child.index,
                session_id=child.session_id,
                run_id=submission.queued.run.id,
                status="queued",
            ),
        )
    return arena_store.get(arena.id)


def sync_durable_arena_child(
    data_dir: str,
    payload: Mapping[str, Any],
    run: HarnessRun,
    result_text: str,
) -> None:
    """Project one finished durable run into its arena parent record."""
    extra = payload.get("extra")
    arena_meta = extra.get("arena") if isinstance(extra, Mapping) else None
    if not isinstance(arena_meta, Mapping) or not arena_meta.get("arena_id"):
        return
    FilesystemHarnessArenaStore(data_dir).upsert_child(
        str(arena_meta["arena_id"]),
        _child_from_run(
            run.harness_id,
            int(arena_meta.get("child_index") or 0),
            run,
            result_text,
        ),
    )


def arena_has_verdict(arena: HarnessArenaRun) -> bool:
    """Return whether an immutable reviewed verdict already exists."""
    reviewed = _mapping(arena.metadata.get("reviewed_arena"))
    return bool(_mapping(reviewed.get("verdict")))


def arena_review_projection(
    arena: HarnessArenaRun,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    """Project immutable task, candidate, verdict, and promotion evidence."""
    reviewed = _mapping(arena.metadata.get("reviewed_arena"))
    task_sha256 = str(reviewed.get("task_sha256") or "")
    candidates = [_arena_candidate_evidence(child, store) for child in arena.child_runs]
    candidate_set_sha256 = _mapping_sha256(
        {
            "schema_version": ARENA_REVIEW_SCHEMA_VERSION,
            "arena_id": arena.id,
            "task_sha256": task_sha256,
            "candidates": candidates,
        }
    )
    verdict = dict(_mapping(reviewed.get("verdict")))
    if verdict:
        verdict["current"] = verdict.get("candidate_set_sha256") == candidate_set_sha256
        selected_run_id = str(verdict.get("selected_run_id") or "")
        verdict["promotion"] = _arena_promotion_projection(selected_run_id)
    return {
        "schema_version": ARENA_REVIEW_SCHEMA_VERSION,
        "task_sha256": task_sha256,
        "candidate_set_sha256": candidate_set_sha256,
        "candidates": candidates,
        "verdict": verdict or None,
    }


def record_arena_verdict(
    *,
    arena_store: FilesystemHarnessArenaStore,
    session_store: HarnessSessionStore,
    arena: HarnessArenaRun,
    payload: Mapping[str, Any],
) -> HarnessArenaRun:
    """Validate and persist one exact operator-scored Arena verdict."""
    if arena.status not in {"succeeded", "partial", "failed", "canceled"}:
        raise ValueError("arena candidates are still active")
    review = arena_review_projection(arena, session_store)
    expected = str(payload.get("candidate_set_sha256") or "")
    if not expected or expected != review["candidate_set_sha256"]:
        raise ArenaReviewConflictError("arena candidate evidence changed")
    selected_index = _bounded_child_index(payload.get("selected_child_index"))
    candidates = review["candidates"]
    selected = next(
        (item for item in candidates if item["child_index"] == selected_index),
        None,
    )
    if selected is None:
        raise ValueError("selected_child_index is not an arena candidate")
    if selected["status"] != "succeeded" or not selected["run_id"]:
        raise ValueError("only a succeeded candidate can be selected")
    scores = _arena_scores(payload.get("scores"), candidates)
    verdict_payload = {
        "schema_version": ARENA_REVIEW_SCHEMA_VERSION,
        "candidate_set_sha256": expected,
        "selected_child_index": selected_index,
        "selected_run_id": selected["run_id"],
        "scores": [dict(item) for item in scores],
    }
    return arena_store.record_verdict(
        arena.id,
        candidate_set_sha256=expected,
        selected_child_index=selected_index,
        selected_run_id=str(selected["run_id"]),
        scores=scores,
        verdict_sha256=_mapping_sha256(verdict_payload),
    )


def arena_request_from_payload(payload: Mapping[str, Any]) -> HarnessArenaRequest:
    """Parse an API payload into an arena request."""
    prompt = str(payload.get("prompt") or "")
    harness_ids = _harness_ids(payload.get("harness_ids"))
    if not prompt.strip():
        raise ValueError("prompt is required")
    if not harness_ids:
        raise ValueError("harness_ids must contain at least one harness")
    extra = payload.get("extra") if isinstance(payload.get("extra"), Mapping) else {}
    return HarnessArenaRequest(
        prompt=prompt,
        harness_ids=harness_ids,
        model=_optional_text(payload.get("model")),
        api_mode=parse_api_mode(payload.get("api_mode")),
        mode=str(payload.get("mode") or "plan"),
        workspace=resolve_workspace(_optional_text(payload.get("workspace"))),
        attachment_ids=_text_tuple(payload.get("attachment_ids"), "attachment_ids"),
        workspace_policy=_arena_workspace_policy(
            str(payload.get("workspace_policy") or "auto"),
            mode=str(payload.get("mode") or "plan"),
            execution_transport=requested_execution_transport(payload),
        ),
        execution_transport=requested_execution_transport(payload),
        extra=dict(extra),
    )


def arena_to_dict(arena: HarnessArenaRun) -> dict[str, Any]:
    """Serialize an arena run."""
    return {
        "id": arena.id,
        "session_id": arena.session_id,
        "status": arena.status,
        "prompt": arena.prompt,
        "harness_ids": list(arena.harness_ids),
        "model": arena.model,
        "api_mode": arena.api_mode.value,
        "mode": arena.mode,
        "workspace": arena.workspace,
        "attachment_ids": list(arena.attachment_ids),
        "workspace_policy": arena.workspace_policy,
        "execution_transport": (
            arena.execution_transport.value
            if arena.execution_transport is not None
            else None
        ),
        "created_at": arena.created_at,
        "updated_at": arena.updated_at,
        "child_runs": [arena_child_to_dict(child) for child in arena.child_runs],
        "metadata": dict(arena.metadata),
    }


def arena_from_dict(data: Mapping[str, Any]) -> HarnessArenaRun:
    """Parse a persisted arena run."""
    return HarnessArenaRun(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        status=str(data.get("status") or "running"),
        prompt=str(data.get("prompt") or ""),
        harness_ids=tuple(str(item) for item in data.get("harness_ids", ())),
        model=_optional_text(data.get("model")),
        api_mode=parse_api_mode(data.get("api_mode")),
        mode=str(data.get("mode") or "plan"),
        workspace=_optional_text(data.get("workspace")),
        attachment_ids=tuple(str(item) for item in data.get("attachment_ids", ())),
        workspace_policy=str(data.get("workspace_policy") or "auto"),
        execution_transport=requested_execution_transport(data),
        created_at=str(data["created_at"]),
        updated_at=str(data.get("updated_at") or data["created_at"]),
        child_runs=tuple(
            arena_child_from_dict(item) for item in data.get("child_runs", ())
        ),
        metadata=_mapping(data.get("metadata")),
    )


def arena_child_to_dict(child: HarnessArenaChildRun) -> dict[str, Any]:
    """Serialize one arena child run."""
    return {
        "harness_id": child.harness_id,
        "index": child.index,
        "session_id": child.session_id,
        "run_id": child.run_id,
        "status": child.status,
        "error": child.error,
        "result_text": child.result_text,
    }


def arena_child_from_dict(data: Mapping[str, Any]) -> HarnessArenaChildRun:
    """Parse one arena child run."""
    return HarnessArenaChildRun(
        harness_id=str(data["harness_id"]),
        index=int(data.get("index") or 0),
        session_id=_optional_text(data.get("session_id")),
        run_id=_optional_text(data.get("run_id")),
        status=str(data.get("status") or "queued"),
        error=_optional_text(data.get("error")),
        result_text=_optional_text(data.get("result_text")),
    )


def _run_arena_child(
    *,
    runner: HarnessSessionRunner,
    session_id: str,
    arena: HarnessArenaRun,
    request: HarnessArenaRequest,
    harness_id: str,
    index: int,
    turn_index: int,
) -> HarnessArenaChildRun:
    child_payload = _arena_child_payload(
        arena=arena,
        request=request,
        harness_id=harness_id,
        index=index,
        turn_index=turn_index,
    )
    try:
        result = runner.run_in_session(session_id, child_payload)
    except SessionNotFoundError:
        raise
    except Exception as exc:
        return HarnessArenaChildRun(
            harness_id=harness_id,
            index=index,
            session_id=session_id,
            run_id=None,
            status="failed",
            error=str(redact_for_storage(str(exc))),
        )
    return _child_from_run(harness_id, index, result.run, result.result.text)


def _arena_child_payload(
    *,
    arena: HarnessArenaRun,
    request: HarnessArenaRequest,
    harness_id: str,
    index: int,
    turn_index: int,
) -> dict[str, Any]:
    return {
        "harness_id": harness_id,
        "prompt": request.prompt,
        "model": request.model,
        "api_mode": request.api_mode.value,
        "mode": request.mode,
        "workspace": request.workspace,
        "workspace_policy": request.workspace_policy,
        "attachment_ids": list(request.attachment_ids),
        "invocation_mode": (
            "native"
            if request.execution_transport is ExecutionTransport.NATIVE_STRUCTURED
            else "headless"
        ),
        "execution_transport": (
            request.execution_transport.value
            if request.execution_transport is not None
            else None
        ),
        "extra": {
            **dict(request.extra),
            "arena": {
                "arena_id": arena.id,
                "child_index": index,
                "child_count": len(request.harness_ids),
                "parent_session_id": arena.session_id,
                "turn_index": turn_index,
            },
        },
    }


def _create_arena_child_sessions(
    runner: HarnessSessionRunner,
    arena: HarnessArenaRun,
    request: HarnessArenaRequest,
) -> tuple[HarnessArenaChildRun, ...]:
    children: list[HarnessArenaChildRun] = []
    for index, harness_id in enumerate(request.harness_ids):
        session = runner.create_session(
            title=f"{title_from_prompt(request.prompt)} · {harness_id}",
            workspace=request.workspace,
            default_harness_id=harness_id,
            default_model=request.model,
            default_api_mode=request.api_mode,
            default_mode=request.mode,
        )
        runner.store.update_session(
            session.id,
            metadata={
                **dict(session.metadata),
                "arena_id": arena.id,
                "arena_parent_session_id": arena.session_id,
                "arena_child_index": index,
            },
        )
        children.append(
            HarnessArenaChildRun(
                harness_id=harness_id,
                index=index,
                session_id=session.id,
                run_id=None,
                status="queued",
            )
        )
    return tuple(children)


def _follow_up_request(
    arena_store: FilesystemHarnessArenaStore,
    arena: HarnessArenaRun,
    payload: Mapping[str, Any],
) -> tuple[HarnessArenaRequest, int]:
    prompt = str(payload.get("prompt") or "")
    if not prompt.strip():
        raise ValueError("prompt is required")
    attachment_ids = _text_tuple(payload.get("attachment_ids"), "attachment_ids")
    model = _optional_text(payload.get("model")) if "model" in payload else arena.model
    turn_index = max(int(arena.metadata.get("turn_count") or 0), 0) + 1
    updated = replace(
        arena,
        model=model,
        updated_at=utc_now(),
        metadata={**dict(arena.metadata), "turn_count": turn_index},
    )
    arena_store.save(updated)
    return (
        HarnessArenaRequest(
            prompt=prompt,
            harness_ids=arena.harness_ids,
            model=model,
            api_mode=arena.api_mode,
            mode=arena.mode,
            workspace=arena.workspace,
            attachment_ids=attachment_ids,
            workspace_policy=arena.workspace_policy,
            execution_transport=arena.execution_transport,
            extra={},
        ),
        turn_index,
    )


def _require_arena_children(
    arena: HarnessArenaRun,
) -> tuple[HarnessArenaChildRun, ...]:
    children = tuple(
        child for child in arena.child_runs if child.session_id is not None
    )
    if len(children) != len(arena.harness_ids):
        raise ValueError("arena child sessions are incomplete")
    return children


def _child_from_run(
    harness_id: str,
    index: int,
    run: HarnessRun,
    result_text: str,
) -> HarnessArenaChildRun:
    return HarnessArenaChildRun(
        harness_id=harness_id,
        index=index,
        session_id=run.session_id,
        run_id=run.id,
        status=run.status,
        error=run.error,
        result_text=(
            str(redact_for_storage(result_text)) if run.status == "succeeded" else None
        ),
    )


def _arena_status(
    children: tuple[HarnessArenaChildRun, ...],
    *,
    expected_count: int,
) -> str:
    if len(children) < expected_count:
        return "running"
    statuses = {child.status for child in children}
    if statuses & {"queued", "running", "retry_wait"}:
        return "running"
    if statuses == {"succeeded"}:
        return "succeeded"
    if "succeeded" in statuses:
        return "partial"
    if "canceled" in statuses:
        return "canceled"
    return "failed"


def _harness_ids(value: Any) -> tuple[str, ...]:
    ids = _text_tuple(value, "harness_ids")
    seen: set[str] = set()
    unique: list[str] = []
    for harness_id in ids:
        if harness_id in seen:
            continue
        seen.add(harness_id)
        unique.append(harness_id)
    return tuple(unique)


def _text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    values: list[str] = []
    for item in value:
        text = _optional_text(item)
        if text is None:
            raise ValueError(f"{field_name} must contain non-empty strings")
        values.append(text)
    return tuple(values)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _arena_workspace_policy(
    requested: str,
    *,
    mode: str,
    execution_transport: ExecutionTransport | None,
) -> str:
    if execution_transport is ExecutionTransport.NATIVE_STRUCTURED and mode == "edit":
        return "worktree"
    return requested


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _redacted_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_for_storage(dict(value))
    if isinstance(redacted, Mapping):
        return dict(redacted)
    return {}


def _arena_task_sha256(request: HarnessArenaRequest) -> str:
    return _mapping_sha256(
        {
            "schema_version": ARENA_REVIEW_SCHEMA_VERSION,
            "prompt": request.prompt,
            "model": request.model,
            "api_mode": request.api_mode.value,
            "mode": request.mode,
            "workspace": request.workspace,
            "attachment_ids": list(request.attachment_ids),
            "workspace_policy": request.workspace_policy,
            "execution_transport": (
                request.execution_transport.value
                if request.execution_transport is not None
                else None
            ),
        }
    )


def _arena_candidate_evidence(
    child: HarnessArenaChildRun,
    store: HarnessSessionStore,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "child_index": child.index,
        "harness_id": child.harness_id,
        "session_id": child.session_id,
        "run_id": child.run_id,
        "status": child.status,
        "configuration_sha256": None,
        "artifact_sha256": None,
        "metrics": {},
        "cost": {"confidence": "unknown", "value": None, "unit": None},
    }
    if child.run_id is None:
        return evidence
    try:
        run = store.get_run(child.run_id)
    except (KeyError, SessionNotFoundError):
        return evidence
    metadata = dict(run.metadata)
    usage = _mapping(metadata.get("usage"))
    evidence["configuration_sha256"] = _mapping_sha256(
        {
            "harness_id": run.harness_id,
            "model": run.model,
            "api_mode": run.api_mode.value,
            "mode": run.mode,
            "invocation_mode": run.invocation_mode.value,
            "workspace_policy": _mapping(metadata.get("workspace_execution")).get(
                "requested_policy"
            ),
        }
    )
    workspace_execution = _mapping(metadata.get("workspace_execution"))
    patch = workspace_execution.get("patch")
    if isinstance(patch, str) and patch and patch != "No diff captured.":
        evidence["artifact_sha256"] = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    metrics: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = value
    changed_files = workspace_execution.get("changed_files")
    if isinstance(changed_files, list):
        metrics["changed_files"] = len(changed_files)
    duration_ms = _run_duration_ms(run)
    if duration_ms is not None:
        metrics["duration_ms"] = duration_ms
    evidence["metrics"] = metrics
    cost = usage.get("cost_usd", metadata.get("cost_usd"))
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        evidence["cost"] = {
            "confidence": "exact",
            "value": float(cost),
            "unit": "USD",
        }
    return evidence


def _run_duration_ms(run: HarnessRun) -> int | None:
    from datetime import datetime

    if not run.started_at or not run.finished_at:
        return None
    try:
        started = datetime.fromisoformat(run.started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(run.finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(int((finished - started).total_seconds() * 1000), 0)


def _arena_scores(
    value: Any,
    candidates: list[dict[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise ValueError("scores must be a list")
    expected = {int(item["child_index"]) for item in candidates}
    parsed: dict[int, float] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("scores must contain objects")
        index = _bounded_child_index(item.get("child_index"))
        score = item.get("score")
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 0 <= float(score) <= 1
        ):
            raise ValueError("every score must be between 0 and 1")
        if index in parsed:
            raise ValueError("scores contain a duplicate child_index")
        parsed[index] = round(float(score), 6)
    if set(parsed) != expected:
        raise ValueError("scores must cover every arena candidate exactly once")
    return tuple(
        {"child_index": index, "score": parsed[index]} for index in sorted(parsed)
    )


def _bounded_child_index(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("selected_child_index must be an integer")
    try:
        index = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("selected_child_index must be an integer") from exc
    if index < 0 or index > 31:
        raise ValueError("selected_child_index is out of bounds")
    return index


def _arena_promotion_projection(run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    return {
        "selected_run_id": run_id,
        "configuration_preview_url": f"/api/runs/{run_id}/promotions/preview",
        "artifact_review_url": f"/api/runs/{run_id}/diff",
        "run_url": f"/cockpit-v2/runs/{run_id}",
        "automatic_apply": False,
    }


def _mapping_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
