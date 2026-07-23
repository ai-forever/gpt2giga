"""Content-addressed one-axis Trace-to-Replay contracts and comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.managed_mcp import HeadlessManagedMCPSnapshotStore
from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.provenance import build_replay_request
from gpt2giga_harness.runtime.worker import DurableJobDispatcher
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessRawRecord,
    HarnessRun,
    HarnessStoredEvent,
)
from gpt2giga_harness.sessions.store import (
    HarnessSessionStore,
    title_from_prompt,
    utc_now,
)


TRACE_REPLAY_SCHEMA_VERSION = 1
MAX_TRACE_REPLAY_TARGET_CHARS = 512
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+~-]{0,255}\Z")
_ACTIVE_STATUSES = frozenset({"queued", "running", "retry_wait"})
_TRACE_REPLAY_FIELDS = frozenset({"axis", "target", "manifest_sha256"})


class TraceReplayAxis(str, Enum):
    """One execution dimension that a Trace-to-Replay may change."""

    MODEL = "model"
    PROVIDER = "provider"
    HARNESS = "harness"
    EXTENSIONS = "extensions"


class TraceReplayConflictError(ValueError):
    """Raised when retained evidence no longer matches an reviewed manifest."""


@dataclass(frozen=True)
class TraceReplayManifest:
    """Immutable replay identity with one changed and all unchanged dimensions."""

    source_run_id: str
    source_session_id: str
    task_sha256: str
    source_evidence_sha256: str
    axis: TraceReplayAxis
    source_dimensions: Mapping[str, Any]
    target_dimensions: Mapping[str, Any]
    fixed_dimensions: Mapping[str, Any]
    unchanged_snapshot_sha256: str
    created_at: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the manifest without retaining prompt or tool contents."""
        return {
            "schema_version": TRACE_REPLAY_SCHEMA_VERSION,
            "source_run_id": self.source_run_id,
            "source_session_id": self.source_session_id,
            "task_sha256": self.task_sha256,
            "source_evidence_sha256": self.source_evidence_sha256,
            "axis": self.axis.value,
            "source_dimensions": dict(self.source_dimensions),
            "target_dimensions": dict(self.target_dimensions),
            "fixed_dimensions": dict(self.fixed_dimensions),
            "unchanged_snapshot_sha256": self.unchanged_snapshot_sha256,
            "created_at": self.created_at,
            "manifest_sha256": self.manifest_sha256,
            "content_free": True,
        }


class TraceReplayService:
    """Preview, execute, and compare one-axis replays through existing owners."""

    def __init__(
        self,
        runner: HarnessSessionRunner,
        *,
        dispatcher: DurableJobDispatcher | None = None,
    ) -> None:
        self.runner = runner
        self.store: HarnessSessionStore = runner.store
        self.dispatcher = dispatcher
        self.snapshot_store = HeadlessManagedMCPSnapshotStore(runner.config.data_dir)

    def preview(
        self,
        source_run_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build a stale-safe preview without creating a session or worktree."""
        source_run = self.store.get_run(source_run_id)
        raw_request = _latest_raw_request(self.store, source_run)
        source_messages = _run_messages(self.store, source_run)
        source_events = self.store.list_events(
            source_run.session_id, run_id=source_run.id
        )
        axis = _trace_replay_axis(payload.get("axis"))
        target = _required_target(payload.get("target"))
        target_extension = self._target_extension(
            source_run,
            axis=axis,
            target=target,
        )
        manifest, replay_payload = prepare_trace_replay(
            source_run,
            raw_request=raw_request,
            payload=payload,
            source_messages=source_messages,
            source_events=source_events,
            target_extension=target_extension,
            created_at=utc_now(),
        )
        expected = str(payload.get("manifest_sha256") or "").strip()
        if expected and expected != manifest.manifest_sha256:
            raise TraceReplayConflictError("trace replay source evidence changed")
        admission = self._admission(
            manifest,
            replay_payload=replay_payload,
        )
        return {
            "manifest": manifest.to_dict(),
            "admission": admission,
            "execution": {
                "new_session": True,
                "workspace_policy": replay_payload.get("workspace_policy"),
                "provider_session": "new",
                "external_telemetry_required": False,
                "automatic_apply": False,
            },
        }

    def start(
        self,
        source_run_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Start one exact reviewed replay through the existing runner/dispatcher."""
        expected = _required_hash(payload.get("manifest_sha256"), "manifest_sha256")
        preview = self.preview(source_run_id, payload)
        manifest = manifest_from_dict(_mapping(preview["manifest"]))
        if expected != manifest.manifest_sha256:
            raise TraceReplayConflictError("trace replay preview is stale")
        admission = _mapping(preview["admission"])
        if not bool(admission.get("admitted")):
            raise ValueError(
                str(admission.get("reason_code") or "trace_replay_not_admitted")
            )
        source_run = self.store.get_run(source_run_id)
        raw_request = _latest_raw_request(self.store, source_run)
        axis = manifest.axis
        target_extension = self._target_extension(
            source_run,
            axis=axis,
            target=_required_target(payload.get("target")),
        )
        _, replay_payload = prepare_trace_replay(
            source_run,
            raw_request=raw_request,
            payload=payload,
            source_messages=_run_messages(self.store, source_run),
            source_events=self.store.list_events(
                source_run.session_id, run_id=source_run.id
            ),
            target_extension=target_extension,
            created_at=manifest.created_at,
        )
        replay_session = self.runner.create_session(
            title=f"Trace replay: {title_from_prompt(source_run.prompt)}",
            workspace=source_run.workspace,
            default_harness_id=str(replay_payload["harness_id"]),
            default_model=(
                str(replay_payload["model"])
                if replay_payload.get("model") is not None
                else None
            ),
            default_api_mode=source_run.api_mode,
            default_mode=source_run.mode,
        )
        replay_session = self.store.update_session(
            replay_session.id,
            metadata={
                **dict(replay_session.metadata),
                "shared_attachment_session_id": source_run.session_id,
                "trace_replay": {
                    "manifest": manifest.to_dict(),
                    "source_run_id": source_run.id,
                    "source_session_id": source_run.session_id,
                    "destination_run_id": None,
                },
            },
        )
        if (
            replay_payload.get("execution_transport")
            == ExecutionTransport.NATIVE_STRUCTURED.value
        ):
            if self.dispatcher is None:
                raise ValueError(
                    "native_structured trace replay requires the durable runtime"
                )
            submission = self.dispatcher.submit(
                replay_session.id,
                replay_payload,
                idempotency_key=(
                    f"trace-replay:{manifest.manifest_sha256}:{replay_session.id}"
                ),
                origin="manual",
            )
            destination_run = submission.queued.run
        else:
            destination_run = self.runner.run_in_session(
                replay_session.id,
                replay_payload,
            ).run
        self.store.update_session(
            replay_session.id,
            metadata={
                **dict(replay_session.metadata),
                "trace_replay": {
                    "manifest": manifest.to_dict(),
                    "source_run_id": source_run.id,
                    "source_session_id": source_run.session_id,
                    "destination_run_id": destination_run.id,
                },
            },
        )
        return self.projection(destination_run.id)

    def projection(self, destination_run_id: str) -> dict[str, Any]:
        """Read one retained replay and compute its bounded comparison."""
        destination_run = self.store.get_run(destination_run_id)
        destination_session = self.store.get_session(destination_run.session_id)
        retained = _mapping(destination_session.metadata.get("trace_replay"))
        manifest = manifest_from_dict(_mapping(retained.get("manifest")))
        if retained.get("destination_run_id") not in {None, destination_run.id}:
            raise TraceReplayConflictError("trace replay destination identity changed")
        source_run = self.store.get_run(manifest.source_run_id)
        return trace_replay_projection(
            manifest,
            source_run=source_run,
            destination_run=destination_run,
            source_raw_request=_latest_raw_request(self.store, source_run),
            destination_raw_request=_latest_raw_request(self.store, destination_run),
            source_messages=_run_messages(self.store, source_run),
            destination_messages=_run_messages(self.store, destination_run),
            source_events=self.store.list_events(
                source_run.session_id, run_id=source_run.id
            ),
            destination_events=self.store.list_events(
                destination_run.session_id, run_id=destination_run.id
            ),
        )

    def _target_extension(
        self,
        source_run: HarnessRun,
        *,
        axis: TraceReplayAxis,
        target: str,
    ) -> Mapping[str, Any] | None:
        if axis is not TraceReplayAxis.EXTENSIONS:
            return None
        reference = extension_target_reference(target)
        if reference is None:
            return None
        if source_run.workspace is None:
            raise ValueError("extension replay requires a project workspace")
        raw_request = _latest_raw_request(self.store, source_run)
        source_extension = _extension_source_reference(
            source_run,
            _mapping(raw_request.payload if raw_request is not None else None),
        )
        if source_extension:
            reference["project_id"] = str(source_extension.get("project_id") or "")
            reference["harness_id"] = source_run.harness_id
        snapshot = self.snapshot_store.load(reference)
        source_project = resolve_project(
            source_run.workspace,
            data_dir=self.runner.config.data_dir,
            load_config_name=False,
        )
        if snapshot.project_id != source_project.id:
            raise ValueError("extension replay target belongs to another project")
        if snapshot.harness_id != source_run.harness_id:
            raise ValueError("extension replay target belongs to another harness")
        return snapshot.public_ref()

    def _admission(
        self,
        manifest: TraceReplayManifest,
        *,
        replay_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            self.runner.registry.get(str(replay_payload["harness_id"]))
        except KeyError:
            return {
                "admitted": False,
                "reason_code": "unknown_target_harness",
            }
        if manifest.axis is TraceReplayAxis.PROVIDER:
            return {
                "admitted": False,
                "reason_code": "provider_axis_requires_route_authority",
            }
        source_extensions = manifest.source_dimensions["extensions"]
        if manifest.axis is TraceReplayAxis.HARNESS and source_extensions is not None:
            return {
                "admitted": False,
                "reason_code": "harness_axis_extension_snapshot_incompatible",
            }
        return {"admitted": True, "reason_code": None}


def prepare_trace_replay(
    source_run: HarnessRun,
    *,
    raw_request: HarnessRawRecord | None,
    payload: Mapping[str, Any],
    source_messages: Sequence[HarnessMessage] = (),
    source_events: Sequence[HarnessStoredEvent] = (),
    target_extension: Mapping[str, Any] | None = None,
    created_at: str,
) -> tuple[TraceReplayManifest, dict[str, Any]]:
    """Build one strict replay manifest and its existing-runner request."""
    _reject_unknown_fields(payload, _TRACE_REPLAY_FIELDS)
    if source_run.status.value in _ACTIVE_STATUSES:
        raise ValueError("trace replay requires a terminal source run")
    axis = _trace_replay_axis(payload.get("axis"))
    target = _required_target(payload.get("target"))
    source_request = _mapping(raw_request.payload if raw_request is not None else None)
    source_dimensions = _execution_dimensions(source_run, source_request)
    fixed_dimensions = _fixed_dimensions(source_run, source_request)
    target_dimensions = _target_dimensions(
        source_dimensions,
        axis=axis,
        target=target,
        target_extension=target_extension,
    )
    if source_dimensions == target_dimensions:
        raise ValueError("trace replay must change exactly one execution axis")
    changed = tuple(
        key
        for key in TraceReplayAxis
        if source_dimensions[key.value] != target_dimensions[key.value]
    )
    if changed != (axis,):
        raise ValueError("trace replay must change exactly the selected axis")
    task_sha256 = _task_sha256(source_run, source_request)
    source_evidence_sha256 = trace_evidence_sha256(
        source_run,
        messages=source_messages,
        events=source_events,
    )
    source_unchanged = _unchanged_dimensions(
        source_dimensions,
        axis=axis,
        task_sha256=task_sha256,
        fixed_dimensions=fixed_dimensions,
    )
    target_unchanged = _unchanged_dimensions(
        target_dimensions,
        axis=axis,
        task_sha256=task_sha256,
        fixed_dimensions=fixed_dimensions,
    )
    if source_unchanged != target_unchanged:
        raise ValueError("unchanged trace replay dimensions do not match")
    unchanged_sha256 = _json_sha256(source_unchanged)
    semantic = {
        "schema_version": TRACE_REPLAY_SCHEMA_VERSION,
        "source_run_id": source_run.id,
        "source_session_id": source_run.session_id,
        "task_sha256": task_sha256,
        "source_evidence_sha256": source_evidence_sha256,
        "axis": axis.value,
        "source_dimensions": source_dimensions,
        "target_dimensions": target_dimensions,
        "fixed_dimensions": fixed_dimensions,
        "unchanged_snapshot_sha256": unchanged_sha256,
    }
    manifest = TraceReplayManifest(
        source_run_id=source_run.id,
        source_session_id=source_run.session_id,
        task_sha256=task_sha256,
        source_evidence_sha256=source_evidence_sha256,
        axis=axis,
        source_dimensions=source_dimensions,
        target_dimensions=target_dimensions,
        fixed_dimensions=fixed_dimensions,
        unchanged_snapshot_sha256=unchanged_sha256,
        created_at=created_at,
        manifest_sha256=_json_sha256(semantic),
    )
    replay_payload = build_replay_request(source_run, raw_request=raw_request)
    replay_payload["workspace_policy"] = (
        "worktree" if source_run.workspace is not None else "current"
    )
    replay_payload["model"] = target_dimensions["model"]
    replay_payload["harness_id"] = target_dimensions["harness"]
    extra = dict(_mapping(replay_payload.get("extra")))
    extra["trace_replay"] = {
        "schema_version": TRACE_REPLAY_SCHEMA_VERSION,
        "manifest_sha256": manifest.manifest_sha256,
        "source_run_id": source_run.id,
        "axis": axis.value,
        "provider": target_dimensions["provider"],
        "extensions": target_dimensions["extensions"],
        "content_free": True,
    }
    if axis is TraceReplayAxis.PROVIDER:
        extra["provider_ref"] = dict(_mapping(target_dimensions["provider"]))
    if axis is TraceReplayAxis.EXTENSIONS:
        if target_extension is None:
            extra.pop("managed_mcp_snapshot", None)
            extra.pop("tool_ids", None)
        else:
            extra["managed_mcp_snapshot"] = dict(target_extension)
            extra["tool_ids"] = list(target_extension.get("server_ids") or ())
    replay_payload["extra"] = extra
    return manifest, replay_payload


def trace_replay_projection(
    manifest: TraceReplayManifest,
    *,
    source_run: HarnessRun,
    destination_run: HarnessRun,
    source_raw_request: HarnessRawRecord | None,
    destination_raw_request: HarnessRawRecord | None,
    source_messages: Sequence[HarnessMessage],
    destination_messages: Sequence[HarnessMessage],
    source_events: Sequence[HarnessStoredEvent],
    destination_events: Sequence[HarnessStoredEvent],
) -> dict[str, Any]:
    """Compare one destination with the immutable source replay manifest."""
    source_current_evidence = trace_evidence_sha256(
        source_run,
        messages=source_messages,
        events=source_events,
    )
    actual_dimensions = None
    equality = {
        "status": "pending",
        "changed_axes": [],
        "unchanged_verified": False,
        "target_verified": False,
    }
    if destination_raw_request is not None:
        destination_request = _mapping(destination_raw_request.payload)
        actual_dimensions = _execution_dimensions(destination_run, destination_request)
        changed_axes = [
            axis.value
            for axis in TraceReplayAxis
            if manifest.source_dimensions[axis.value] != actual_dimensions[axis.value]
        ]
        actual_unchanged = _json_sha256(
            _unchanged_dimensions(
                actual_dimensions,
                axis=manifest.axis,
                task_sha256=_task_sha256(destination_run, destination_request),
                fixed_dimensions=_fixed_dimensions(
                    destination_run, destination_request
                ),
            )
        )
        equality = {
            "status": (
                "verified"
                if actual_dimensions == manifest.target_dimensions
                and actual_unchanged == manifest.unchanged_snapshot_sha256
                else "mismatch"
            ),
            "changed_axes": changed_axes,
            "unchanged_verified": (
                actual_unchanged == manifest.unchanged_snapshot_sha256
            ),
            "target_verified": actual_dimensions == manifest.target_dimensions,
        }
    destination_terminal = destination_run.status.value not in _ACTIVE_STATUSES
    return {
        "schema_version": TRACE_REPLAY_SCHEMA_VERSION,
        "manifest": manifest.to_dict(),
        "source": _run_ref(source_run),
        "destination": _run_ref(destination_run),
        "source_evidence_current": (
            source_current_evidence == manifest.source_evidence_sha256
        ),
        "snapshot_equality": equality,
        "comparison_status": "ready" if destination_terminal else "pending",
        "comparison": _comparison(
            source_run,
            destination_run,
            source_messages=source_messages,
            destination_messages=destination_messages,
            source_events=source_events,
            destination_events=destination_events,
            destination_terminal=destination_terminal,
        ),
        "external_telemetry_required": False,
        "automatic_apply": False,
    }


def manifest_from_dict(value: Mapping[str, Any]) -> TraceReplayManifest:
    """Strictly load one retained Trace-to-Replay manifest."""
    data = _mapping(value)
    allowed = {
        "schema_version",
        "source_run_id",
        "source_session_id",
        "task_sha256",
        "source_evidence_sha256",
        "axis",
        "source_dimensions",
        "target_dimensions",
        "fixed_dimensions",
        "unchanged_snapshot_sha256",
        "created_at",
        "manifest_sha256",
        "content_free",
    }
    _reject_unknown_fields(data, allowed)
    if data.get("schema_version") != TRACE_REPLAY_SCHEMA_VERSION:
        raise ValueError("unsupported trace replay schema_version")
    manifest = TraceReplayManifest(
        source_run_id=_required_identity(data.get("source_run_id"), "source run id"),
        source_session_id=_required_identity(
            data.get("source_session_id"), "source session id"
        ),
        task_sha256=_required_hash(data.get("task_sha256"), "task_sha256"),
        source_evidence_sha256=_required_hash(
            data.get("source_evidence_sha256"), "source_evidence_sha256"
        ),
        axis=_trace_replay_axis(data.get("axis")),
        source_dimensions=_strict_dimensions(data.get("source_dimensions")),
        target_dimensions=_strict_dimensions(data.get("target_dimensions")),
        fixed_dimensions=_strict_fixed_dimensions(data.get("fixed_dimensions")),
        unchanged_snapshot_sha256=_required_hash(
            data.get("unchanged_snapshot_sha256"),
            "unchanged_snapshot_sha256",
        ),
        created_at=_required_text(data.get("created_at"), "created_at"),
        manifest_sha256=_required_hash(data.get("manifest_sha256"), "manifest_sha256"),
    )
    semantic = manifest.to_dict()
    semantic.pop("created_at")
    semantic.pop("manifest_sha256")
    semantic.pop("content_free")
    if _json_sha256(semantic) != manifest.manifest_sha256:
        raise ValueError("trace replay manifest hash mismatch")
    changed = tuple(
        axis
        for axis in TraceReplayAxis
        if manifest.source_dimensions[axis.value]
        != manifest.target_dimensions[axis.value]
    )
    if changed != (manifest.axis,):
        raise ValueError("trace replay manifest does not contain exactly one axis")
    return manifest


def trace_evidence_sha256(
    run: HarnessRun,
    *,
    messages: Sequence[HarnessMessage],
    events: Sequence[HarnessStoredEvent],
) -> str:
    """Return a bounded content-free identity for retained comparison evidence."""
    return _json_sha256(
        {
            "run_id": run.id,
            "status": run.status.value,
            "semantic": _semantic_evidence(run.id, messages),
            "tools": _tool_evidence(events),
            "diff": _diff_evidence(run),
            "latency": _latency_evidence(run),
            "cost": _cost_evidence(run),
        }
    )


def extension_target_reference(target: str) -> dict[str, str] | None:
    """Parse a content-free managed MCP target reference from UI/API text."""
    normalized = target.strip()
    if normalized == "none":
        return None
    snapshot_id, separator, snapshot_hash = normalized.partition("@")
    if (
        not separator
        or not snapshot_id.startswith("mcp_")
        or not snapshot_id[4:].isalnum()
    ):
        raise ValueError("extension target must be none or mcp_<id>@<sha256>")
    return {
        "snapshot_id": snapshot_id,
        "snapshot_hash": _required_hash(snapshot_hash, "extension snapshot hash"),
    }


def _target_dimensions(
    source: Mapping[str, Any],
    *,
    axis: TraceReplayAxis,
    target: str,
    target_extension: Mapping[str, Any] | None,
) -> dict[str, Any]:
    dimensions = dict(source)
    if axis is TraceReplayAxis.MODEL:
        dimensions["model"] = _bounded_text(target, "model")
    elif axis is TraceReplayAxis.HARNESS:
        dimensions["harness"] = _required_identity(target, "harness")
    elif axis is TraceReplayAxis.PROVIDER:
        provider_id, separator, revision = target.partition("@")
        if not separator:
            raise ValueError("provider target must be <id>@<revision>")
        dimensions["provider"] = {
            "id": _required_identity(provider_id, "provider id"),
            "revision": _required_identity(revision, "provider revision"),
        }
    else:
        dimensions["extensions"] = _extension_dimensions(target_extension)
    return dimensions


def _execution_dimensions(
    run: HarnessRun,
    raw_request: Mapping[str, Any],
) -> dict[str, Any]:
    extra = _mapping(raw_request.get("extra"))
    return {
        "model": run.model,
        "provider": _provider_dimensions(run, extra),
        "harness": run.harness_id,
        "extensions": _extension_dimensions(
            _mapping(extra.get("managed_mcp_snapshot"))
            or _mapping(run.metadata.get("managed_mcp_snapshot"))
            or None
        ),
    }


def _fixed_dimensions(
    run: HarnessRun,
    raw_request: Mapping[str, Any],
) -> dict[str, Any]:
    extra = _mapping(raw_request.get("extra"))
    execution_snapshot = _mapping(run.metadata.get("execution_snapshot"))
    return {
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "invocation_mode": run.invocation_mode.value,
        "execution_transport": (
            raw_request.get("execution_transport")
            or run.metadata.get("execution_transport")
        ),
        "stream": bool(raw_request.get("stream")),
        "workspace_sha256": (
            hashlib.sha256(run.workspace.encode("utf-8")).hexdigest()
            if run.workspace is not None
            else None
        ),
        "permission_profile": (
            extra.get("permission_profile")
            or execution_snapshot.get("permission_profile")
        ),
    }


def _extension_source_reference(
    run: HarnessRun,
    raw_request: Mapping[str, Any],
) -> Mapping[str, Any]:
    extra = _mapping(raw_request.get("extra"))
    return _mapping(extra.get("managed_mcp_snapshot")) or _mapping(
        run.metadata.get("managed_mcp_snapshot")
    )


def _provider_dimensions(
    run: HarnessRun,
    extra: Mapping[str, Any],
) -> dict[str, str] | None:
    direct = _mapping(extra.get("provider_ref"))
    if direct:
        return {
            "id": _required_identity(direct.get("id"), "provider id"),
            "revision": _required_identity(direct.get("revision"), "provider revision"),
        }
    for candidate in (
        _mapping(run.metadata.get("execution_snapshot")),
        _mapping(
            _mapping(run.metadata.get("structured_session_link")).get(
                "execution_snapshot"
            )
        ),
    ):
        provider = _mapping(candidate.get("provider"))
        if provider:
            return {
                "id": _required_identity(provider.get("id"), "provider id"),
                "revision": _required_identity(
                    provider.get("revision"), "provider revision"
                ),
            }
    return None


def _extension_dimensions(
    reference: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not reference:
        return None
    snapshot_id = _required_identity(reference.get("snapshot_id"), "snapshot id")
    snapshot_hash = _required_hash(reference.get("snapshot_hash"), "snapshot hash")
    server_ids = reference.get("server_ids")
    return {
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "server_ids": (
            sorted(
                {_required_identity(item, "extension server id") for item in server_ids}
            )
            if isinstance(server_ids, Sequence)
            and not isinstance(server_ids, (str, bytes, bytearray))
            else []
        ),
    }


def _task_sha256(run: HarnessRun, raw_request: Mapping[str, Any]) -> str:
    attachments = raw_request.get("attachments")
    safe_attachments: list[dict[str, Any]] = []
    if isinstance(attachments, Sequence) and not isinstance(
        attachments, (str, bytes, bytearray)
    ):
        for item in attachments[:64]:
            attachment = _mapping(item)
            safe_attachments.append(
                {
                    "id": attachment.get("id"),
                    "sha256": attachment.get("sha256"),
                    "size_bytes": attachment.get("size_bytes"),
                }
            )
    prompt = (
        str(raw_request.get("original_prompt") or "")
        or str(raw_request.get("prompt") or "")
        or run.prompt
    )
    return _json_sha256(
        {
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "attachments": safe_attachments,
        }
    )


def _unchanged_dimensions(
    dimensions: Mapping[str, Any],
    *,
    axis: TraceReplayAxis,
    task_sha256: str,
    fixed_dimensions: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "task_sha256": task_sha256,
        "fixed_dimensions": dict(fixed_dimensions),
        "dimensions": {
            key: value for key, value in dimensions.items() if key != axis.value
        },
    }


def _comparison(
    source_run: HarnessRun,
    destination_run: HarnessRun,
    *,
    source_messages: Sequence[HarnessMessage],
    destination_messages: Sequence[HarnessMessage],
    source_events: Sequence[HarnessStoredEvent],
    destination_events: Sequence[HarnessStoredEvent],
    destination_terminal: bool,
) -> dict[str, Any]:
    source_semantic = _semantic_evidence(source_run.id, source_messages)
    target_semantic = (
        _semantic_evidence(destination_run.id, destination_messages)
        if destination_terminal
        else None
    )
    source_tools = _tool_evidence(source_events)
    target_tools = _tool_evidence(destination_events) if destination_terminal else None
    source_diff = _diff_evidence(source_run)
    target_diff = _diff_evidence(destination_run) if destination_terminal else None
    source_latency = _latency_evidence(source_run)
    target_latency = (
        _latency_evidence(destination_run) if destination_terminal else None
    )
    source_cost = _cost_evidence(source_run)
    target_cost = _cost_evidence(destination_run) if destination_terminal else None
    return {
        "semantic": _paired_evidence(source_semantic, target_semantic),
        "tools": _paired_evidence(source_tools, target_tools),
        "diff": _paired_evidence(source_diff, target_diff),
        "latency": _paired_numeric(source_latency, target_latency, "milliseconds"),
        "cost": _paired_cost(source_cost, target_cost),
    }


def _semantic_evidence(
    run_id: str,
    messages: Sequence[HarnessMessage],
) -> dict[str, Any]:
    texts = [
        message.content
        for message in messages
        if message.run_id == run_id and message.role == "assistant"
    ]
    encoded = "\n".join(texts).encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "message_count": len(texts),
        "byte_count": len(encoded),
    }


def _tool_evidence(events: Sequence[HarnessStoredEvent]) -> dict[str, Any]:
    types: dict[str, int] = {}
    for event in events:
        normalized = event.type.lower()
        payload = _mapping(event.payload)
        if "tool" not in normalized and not any(
            key in payload for key in ("tool", "tool_id", "tool_name", "server_id")
        ):
            continue
        types[event.type] = types.get(event.type, 0) + 1
    return {"event_count": sum(types.values()), "types": dict(sorted(types.items()))}


def _diff_evidence(run: HarnessRun) -> dict[str, Any]:
    workspace = _mapping(run.metadata.get("workspace_execution"))
    patch = workspace.get("patch")
    if not isinstance(patch, str):
        patch = run.metadata.get("diff")
    if not isinstance(patch, str):
        return {
            "sha256": None,
            "available": False,
            "changed_file_count": 0,
            "truncated": bool(workspace.get("truncated")),
        }
    changed_files = workspace.get("changed_files")
    return {
        "sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "available": True,
        "changed_file_count": (
            len(changed_files)
            if isinstance(changed_files, Sequence)
            and not isinstance(changed_files, (str, bytes, bytearray))
            else 0
        ),
        "truncated": bool(workspace.get("truncated")),
    }


def _latency_evidence(run: HarnessRun) -> int | None:
    if run.started_at is None or run.finished_at is None:
        return None
    try:
        started = datetime.fromisoformat(run.started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(run.finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(int((finished - started).total_seconds() * 1000), 0)


def _cost_evidence(run: HarnessRun) -> dict[str, Any]:
    metadata = _mapping(run.metadata)
    value = metadata.get("cost_microunits", metadata.get("cost"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"value": None, "unit": None, "confidence": "unknown"}
    confidence = str(metadata.get("cost_confidence") or "measured")
    if confidence not in {"measured", "estimated", "unknown"}:
        confidence = "unknown"
    return {
        "value": value,
        "unit": "microunits" if "cost_microunits" in metadata else "provider_units",
        "confidence": confidence,
    }


def _paired_evidence(
    source: Mapping[str, Any],
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source": dict(source),
        "target": dict(target) if target is not None else None,
        "changed": dict(source) != dict(target) if target is not None else None,
    }


def _paired_numeric(
    source: int | None,
    target: int | None,
    unit: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "delta": (
            target - source if source is not None and target is not None else None
        ),
        "unit": unit,
    }


def _paired_cost(
    source: Mapping[str, Any],
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_value = source.get("value")
    target_value = target.get("value") if target is not None else None
    return {
        "source": dict(source),
        "target": dict(target) if target is not None else None,
        "delta": (
            target_value - source_value
            if isinstance(source_value, (int, float))
            and not isinstance(source_value, bool)
            and isinstance(target_value, (int, float))
            and not isinstance(target_value, bool)
            else None
        ),
    }


def _run_ref(run: HarnessRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "session_id": run.session_id,
        "status": run.status.value,
        "harness_id": run.harness_id,
        "model": run.model,
        "workspace_isolated": bool(
            _mapping(run.metadata.get("workspace_execution")).get("worktree_path")
        ),
    }


def _latest_raw_request(
    store: HarnessSessionStore,
    run: HarnessRun,
) -> HarnessRawRecord | None:
    records = tuple(
        record
        for record in store.list_raw_requests(run.session_id)
        if record.run_id == run.id
    )
    return records[-1] if records else None


def _run_messages(
    store: HarnessSessionStore,
    run: HarnessRun,
) -> tuple[HarnessMessage, ...]:
    return tuple(
        message
        for message in store.list_messages(run.session_id)
        if message.run_id == run.id
    )


def _strict_dimensions(value: Any) -> dict[str, Any]:
    dimensions = _mapping(value)
    if set(dimensions) != {axis.value for axis in TraceReplayAxis}:
        raise ValueError("trace replay dimensions are incomplete")
    return {
        "model": (
            _bounded_text(dimensions.get("model"), "model")
            if dimensions.get("model") is not None
            else None
        ),
        "provider": (
            {
                "id": _required_identity(
                    _mapping(dimensions.get("provider")).get("id"), "provider id"
                ),
                "revision": _required_identity(
                    _mapping(dimensions.get("provider")).get("revision"),
                    "provider revision",
                ),
            }
            if dimensions.get("provider") is not None
            else None
        ),
        "harness": _required_identity(dimensions.get("harness"), "harness"),
        "extensions": _extension_dimensions(
            _mapping(dimensions.get("extensions")) or None
        ),
    }


def _strict_fixed_dimensions(value: Any) -> dict[str, Any]:
    dimensions = _mapping(value)
    expected = {
        "api_mode",
        "capability",
        "mode",
        "invocation_mode",
        "execution_transport",
        "stream",
        "workspace_sha256",
        "permission_profile",
    }
    if set(dimensions) != expected:
        raise ValueError("trace replay fixed dimensions are incomplete")
    if not isinstance(dimensions.get("stream"), bool):
        raise ValueError("trace replay stream dimension must be a boolean")
    workspace_sha256 = dimensions.get("workspace_sha256")
    permission_profile = dimensions.get("permission_profile")
    execution_transport = dimensions.get("execution_transport")
    return {
        "api_mode": _required_identity(dimensions.get("api_mode"), "api mode"),
        "capability": _required_identity(dimensions.get("capability"), "capability"),
        "mode": _required_identity(dimensions.get("mode"), "mode"),
        "invocation_mode": _required_identity(
            dimensions.get("invocation_mode"), "invocation mode"
        ),
        "execution_transport": (
            _required_identity(execution_transport, "execution transport")
            if execution_transport is not None
            else None
        ),
        "stream": dimensions["stream"],
        "workspace_sha256": (
            _required_hash(workspace_sha256, "workspace_sha256")
            if workspace_sha256 is not None
            else None
        ),
        "permission_profile": (
            _required_identity(permission_profile, "permission profile")
            if permission_profile is not None
            else None
        ),
    }


def _trace_replay_axis(value: Any) -> TraceReplayAxis:
    try:
        return TraceReplayAxis(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(
            "trace replay axis must be model, provider, harness, or extensions"
        ) from exc


def _required_target(value: Any) -> str:
    target = _required_text(value, "target")
    if len(target) > MAX_TRACE_REPLAY_TARGET_CHARS:
        raise ValueError("trace replay target exceeds the length limit")
    return target


def _required_identity(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not _IDENTITY_RE.fullmatch(text):
        raise ValueError(f"{field_name} is invalid")
    return text


def _bounded_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) > 255 or any(char in text for char in "\r\n\x00"):
        raise ValueError(f"{field_name} is invalid")
    return text


def _required_hash(value: Any, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _HASH_RE.fullmatch(text):
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    return text


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _reject_unknown_fields(
    value: Mapping[str, Any], allowed: set[str] | frozenset[str]
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"unknown trace replay fields: {', '.join(unknown)}")


def _mapping(value: Any) -> Mapping[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
