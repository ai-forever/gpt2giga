"""Truthful, content-free cross-Harness handoff capsules."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, Sequence

from gpt2giga_harness.environments import (
    EnvironmentCaptureError,
    EnvironmentSnapshot,
    GitEnvironmentProvider,
)
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.policy import ApprovalStatus
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions.models import HarnessRun, HarnessStoredEvent
from gpt2giga_harness.sessions.store import HarnessSessionStore
from gpt2giga_harness.types import spec_to_dict
from gpt2giga_harness.worktrees import run_diff_response


HANDOFF_CAPSULE_SCHEMA_VERSION = 1
MAX_CAPSULE_ARTIFACTS = 100
MAX_CAPSULE_QUESTIONS = 100
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@~-]{0,255}\Z")
_QUESTION_REQUEST_MARKERS = ("elicitation", "input_request", "input_requested")
_QUESTION_RESOLUTION_MARKERS = (
    "elicitation_response",
    "input_answer",
    "input_response",
)


class HandoffCapsuleError(ValueError):
    """Raised when a handoff capsule cannot be built or verified truthfully."""


class EnvironmentSnapshotProvider(Protocol):
    """Minimal read-only Environment owner used by capsule construction."""

    def snapshot(self, workspace: str | Path) -> EnvironmentSnapshot: ...


@dataclass(frozen=True)
class HandoffCapsule:
    """Strict schema-v1 capsule whose identity excludes all raw content."""

    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible capsule document."""
        return json.loads(json.dumps(self.payload))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HandoffCapsule:
        """Verify and parse one exact schema-v1 capsule."""
        return cls(payload=verify_handoff_capsule(payload))


class HandoffCapsuleService:
    """Build one immutable handoff view from existing run authorities."""

    def __init__(
        self,
        *,
        store: HarnessSessionStore,
        registry: HarnessRegistry,
        runtime_store: RuntimeCoordinationStore | None = None,
        environment_provider: EnvironmentSnapshotProvider | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.runtime_store = runtime_store
        self.environment_provider = environment_provider

    def build(self, run_id: str, target_harness_id: str) -> dict[str, Any]:
        """Build a deterministic capsule without starting or mutating a Harness."""
        run = self.store.get_run(_required_identity(run_id, "run_id"))
        target_id = _required_identity(target_harness_id, "target_harness_id")
        if target_id == run.harness_id:
            raise HandoffCapsuleError(
                "cross-Harness handoff requires a different target harness"
            )
        source_harness = self.registry.get(run.harness_id)
        target_harness = self.registry.get(target_id)
        environment = self._environment(run)
        events = self.store.list_events(run.session_id, run_id=run.id)
        approvals = self._pending_approvals(run)
        questions = _unresolved_questions(events)
        artifacts = _artifact_projection(run, events, environment)
        tool_snapshot = _tool_extension_projection(run)
        source_spec_hash = _semantic_hash(
            "source-harness-contract", spec_to_dict(source_harness.spec())
        )
        target_spec_hash = _semantic_hash(
            "target-harness-contract", spec_to_dict(target_harness.spec())
        )
        body = {
            "schema_version": HANDOFF_CAPSULE_SCHEMA_VERSION,
            "kind": "agent_workbench.handoff_capsule.v1",
            "content_free": True,
            "summary": {
                "source_status": run.status.value,
                "mode": run.mode,
                "capability": run.capability.value,
                "invocation_mode": run.invocation_mode.value,
                "task_sha256": _semantic_hash("task", run.prompt),
                "artifact_count": len(artifacts),
                "pending_approval_count": len(approvals),
                "unresolved_question_count": len(questions),
            },
            "diff_and_artifacts": {
                "diff": _diff_projection(run),
                "artifacts": artifacts,
            },
            "tool_extension_snapshot": tool_snapshot,
            "provenance": {
                "source": {
                    "run_id": run.id,
                    "session_id": run.session_id,
                    "harness_id": run.harness_id,
                    "harness_contract_sha256": source_spec_hash,
                    "provider": _provider_projection(run),
                },
                "target": {
                    "harness_id": target_id,
                    "harness_contract_sha256": target_spec_hash,
                    "session_requirement": "new_or_explicit_import",
                },
            },
            "unresolved": {
                "approvals": approvals,
                "questions": questions,
                "approval_source": (
                    "runtime_store" if self.runtime_store is not None else "unavailable"
                ),
            },
            "environment": environment,
            "continuity": {
                "native_session_identity_preserved": False,
                "provider_session_identity_preserved": False,
                "harness_session_identity_preserved": False,
                "source_native_session_present": bool(run.native_session_id),
                "claim": "evidence_handoff_only",
            },
        }
        capsule_sha256 = _json_hash(body)
        return verify_handoff_capsule(
            {
                **body,
                "capsule_id": f"handoff_{capsule_sha256[:32]}",
                "capsule_sha256": capsule_sha256,
            }
        )

    def _environment(self, run: HarnessRun) -> dict[str, Any]:
        if run.workspace is None:
            raise HandoffCapsuleError(
                "handoff capsule requires a workspace-bound source run"
            )
        try:
            provider = self.environment_provider or GitEnvironmentProvider()
            snapshot = provider.snapshot(run.workspace)
        except EnvironmentCaptureError as exc:
            raise HandoffCapsuleError(
                f"environment capture failed: {exc.code}"
            ) from exc
        semantic = {
            key: value
            for key, value in snapshot.to_dict().items()
            if key not in {"captured_at", "repository_root", "worktree_root"}
        }
        return {
            "provider_id": snapshot.provider_id,
            "workspace_sha256": _semantic_hash(
                "workspace", str(Path(run.workspace).expanduser().resolve())
            ),
            "branch": snapshot.branch,
            "detached": snapshot.detached,
            "head": snapshot.head,
            "base_identity": snapshot.base_identity,
            "upstream": snapshot.upstream,
            "ahead": snapshot.ahead,
            "behind": snapshot.behind,
            "diff_sha256": snapshot.diff_sha256,
            "changed_paths": list(snapshot.changed_paths),
            "changed_paths_truncated": snapshot.changed_paths_truncated,
            "snapshot_sha256": _semantic_hash("environment", semantic),
        }

    def _pending_approvals(self, run: HarnessRun) -> list[dict[str, Any]]:
        if self.runtime_store is None:
            return []
        job_id = _optional_identity(run.metadata.get("job_id"))
        requests = self.runtime_store.list_run_approval_requests(
            run_id=run.id,
            job_id=job_id,
            limit=MAX_CAPSULE_ARTIFACTS,
        )
        return [
            {
                "id": item.id,
                "action": item.action.value,
                "enforcement": item.enforcement.value,
                "enforcement_owner": item.enforcement_owner,
                "created_at": item.created_at,
                "expires_at": item.expires_at,
            }
            for item in requests
            if item.status is ApprovalStatus.PENDING
        ]


def verify_handoff_capsule(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the exact schema, semantic hash, and truthful continuity claim."""
    if not isinstance(payload, Mapping):
        raise HandoffCapsuleError("handoff capsule must be an object")
    expected = {
        "schema_version",
        "kind",
        "content_free",
        "capsule_id",
        "capsule_sha256",
        "summary",
        "diff_and_artifacts",
        "tool_extension_snapshot",
        "provenance",
        "unresolved",
        "environment",
        "continuity",
    }
    if set(payload) != expected:
        raise HandoffCapsuleError("handoff capsule fields are invalid")
    if payload.get("schema_version") != HANDOFF_CAPSULE_SCHEMA_VERSION:
        raise HandoffCapsuleError("unsupported handoff capsule schema_version")
    if payload.get("kind") != "agent_workbench.handoff_capsule.v1":
        raise HandoffCapsuleError("handoff capsule kind is invalid")
    if payload.get("content_free") is not True:
        raise HandoffCapsuleError("handoff capsule must be content-free")
    capsule_sha256 = _required_hash(payload.get("capsule_sha256"), "capsule_sha256")
    if payload.get("capsule_id") != f"handoff_{capsule_sha256[:32]}":
        raise HandoffCapsuleError("handoff capsule id does not match")
    continuity = _mapping(payload.get("continuity"), "continuity")
    _validate_capsule_shape(payload)
    for key in (
        "native_session_identity_preserved",
        "provider_session_identity_preserved",
        "harness_session_identity_preserved",
    ):
        if continuity.get(key) is not False:
            raise HandoffCapsuleError(
                "handoff capsule cannot preserve cross-Harness session identity"
            )
    provenance = _mapping(payload.get("provenance"), "provenance")
    source = _mapping(provenance.get("source"), "provenance.source")
    target = _mapping(provenance.get("target"), "provenance.target")
    if source.get("harness_id") == target.get("harness_id"):
        raise HandoffCapsuleError("handoff capsule target must differ from source")
    body = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "capsule_id",
            "capsule_sha256",
        }
    }
    if _json_hash(body) != capsule_sha256:
        raise HandoffCapsuleError("handoff capsule hash does not match")
    return json.loads(json.dumps(payload))


def _validate_capsule_shape(payload: Mapping[str, Any]) -> None:
    summary = _exact_mapping(
        payload.get("summary"),
        "summary",
        {
            "source_status",
            "mode",
            "capability",
            "invocation_mode",
            "task_sha256",
            "artifact_count",
            "pending_approval_count",
            "unresolved_question_count",
        },
    )
    _required_hash(summary.get("task_sha256"), "summary.task_sha256")
    for key in (
        "artifact_count",
        "pending_approval_count",
        "unresolved_question_count",
    ):
        _non_negative_integer(summary.get(key), f"summary.{key}")
    diff_and_artifacts = _exact_mapping(
        payload.get("diff_and_artifacts"),
        "diff_and_artifacts",
        {"diff", "artifacts"},
    )
    diff = _exact_mapping(
        diff_and_artifacts.get("diff"),
        "diff_and_artifacts.diff",
        {
            "sha256",
            "byte_count",
            "captured",
            "truncated",
            "changed_file_count",
            "untracked_file_count",
            "path_identities",
        },
    )
    _required_hash(diff.get("sha256"), "diff_and_artifacts.diff.sha256")
    for key in ("byte_count", "changed_file_count", "untracked_file_count"):
        _non_negative_integer(diff.get(key), f"diff_and_artifacts.diff.{key}")
    for key in ("captured", "truncated"):
        if not isinstance(diff.get(key), bool):
            raise HandoffCapsuleError(
                f"handoff capsule diff_and_artifacts.diff.{key} must be a boolean"
            )
    _hash_list(diff.get("path_identities"), "diff_and_artifacts.diff.path_identities")
    artifacts = _object_list(
        diff_and_artifacts.get("artifacts"),
        "diff_and_artifacts.artifacts",
        limit=MAX_CAPSULE_ARTIFACTS,
    )
    for index, artifact in enumerate(artifacts):
        _exact_fields(
            artifact,
            f"diff_and_artifacts.artifacts[{index}]",
            {"type", "identity_sha256", "byte_count"},
        )
        _required_hash(
            artifact.get("identity_sha256"),
            f"diff_and_artifacts.artifacts[{index}].identity_sha256",
        )
        if artifact.get("byte_count") is not None:
            _non_negative_integer(
                artifact.get("byte_count"),
                f"diff_and_artifacts.artifacts[{index}].byte_count",
            )
    if summary["artifact_count"] != len(artifacts):
        raise HandoffCapsuleError("handoff capsule artifact count does not match")
    tools = _exact_mapping(
        payload.get("tool_extension_snapshot"),
        "tool_extension_snapshot",
        {
            "managed_mcp_snapshot_id",
            "snapshot_sha256",
            "server_count",
            "server_identities",
            "descriptor_contents_included",
            "secret_values_included",
            "projection_sha256",
        },
    )
    if tools.get("snapshot_sha256") is not None:
        _required_hash(
            tools.get("snapshot_sha256"),
            "tool_extension_snapshot.snapshot_sha256",
        )
    server_ids = _hash_list(
        tools.get("server_identities"),
        "tool_extension_snapshot.server_identities",
    )
    if _non_negative_integer(
        tools.get("server_count"), "tool_extension_snapshot.server_count"
    ) != len(server_ids):
        raise HandoffCapsuleError("handoff capsule server count does not match")
    if (
        tools.get("descriptor_contents_included") is not False
        or tools.get("secret_values_included") is not False
    ):
        raise HandoffCapsuleError("handoff capsule tool snapshot is not content-free")
    _required_hash(
        tools.get("projection_sha256"),
        "tool_extension_snapshot.projection_sha256",
    )
    unresolved = _exact_mapping(
        payload.get("unresolved"),
        "unresolved",
        {"approvals", "questions", "approval_source"},
    )
    approvals = _object_list(
        unresolved.get("approvals"),
        "unresolved.approvals",
        limit=MAX_CAPSULE_ARTIFACTS,
    )
    questions = _object_list(
        unresolved.get("questions"),
        "unresolved.questions",
        limit=MAX_CAPSULE_QUESTIONS,
    )
    if summary["pending_approval_count"] != len(approvals):
        raise HandoffCapsuleError("handoff capsule approval count does not match")
    if summary["unresolved_question_count"] != len(questions):
        raise HandoffCapsuleError("handoff capsule question count does not match")
    for index, question in enumerate(questions):
        _exact_fields(
            question,
            f"unresolved.questions[{index}]",
            {"id", "type", "created_at", "content_included"},
        )
        _required_hash(question.get("id"), f"unresolved.questions[{index}].id")
        if question.get("content_included") is not False:
            raise HandoffCapsuleError("handoff capsule question contains content")
    environment = _exact_mapping(
        payload.get("environment"),
        "environment",
        {
            "provider_id",
            "workspace_sha256",
            "branch",
            "detached",
            "head",
            "base_identity",
            "upstream",
            "ahead",
            "behind",
            "diff_sha256",
            "changed_paths",
            "changed_paths_truncated",
            "snapshot_sha256",
        },
    )
    for key in ("workspace_sha256", "diff_sha256", "snapshot_sha256"):
        _required_hash(environment.get(key), f"environment.{key}")
    _non_negative_integer(environment.get("ahead"), "environment.ahead")
    _non_negative_integer(environment.get("behind"), "environment.behind")
    if not isinstance(environment.get("detached"), bool) or not isinstance(
        environment.get("changed_paths_truncated"), bool
    ):
        raise HandoffCapsuleError("handoff capsule environment flags are invalid")
    if not isinstance(environment.get("changed_paths"), list) or any(
        not isinstance(item, str) for item in environment["changed_paths"]
    ):
        raise HandoffCapsuleError("handoff capsule environment paths are invalid")
    provenance = _mapping(payload.get("provenance"), "provenance")
    source = _exact_mapping(
        provenance.get("source"),
        "provenance.source",
        {
            "run_id",
            "session_id",
            "harness_id",
            "harness_contract_sha256",
            "provider",
        },
    )
    target = _exact_mapping(
        provenance.get("target"),
        "provenance.target",
        {"harness_id", "harness_contract_sha256", "session_requirement"},
    )
    for key in ("run_id", "session_id", "harness_id"):
        _required_identity(source.get(key), f"provenance.source.{key}")
    _required_identity(target.get("harness_id"), "provenance.target.harness_id")
    _required_hash(
        source.get("harness_contract_sha256"),
        "provenance.source.harness_contract_sha256",
    )
    _required_hash(
        target.get("harness_contract_sha256"),
        "provenance.target.harness_contract_sha256",
    )
    if target.get("session_requirement") != "new_or_explicit_import":
        raise HandoffCapsuleError(
            "handoff capsule target session requirement is invalid"
        )
    continuity = _exact_mapping(
        payload.get("continuity"),
        "continuity",
        {
            "native_session_identity_preserved",
            "provider_session_identity_preserved",
            "harness_session_identity_preserved",
            "source_native_session_present",
            "claim",
        },
    )
    if not isinstance(continuity.get("source_native_session_present"), bool):
        raise HandoffCapsuleError("handoff capsule native session presence is invalid")
    if continuity.get("claim") != "evidence_handoff_only":
        raise HandoffCapsuleError("handoff capsule continuity claim is invalid")


def _diff_projection(run: HarnessRun) -> dict[str, Any]:
    diff = run_diff_response(run.metadata)
    execution = _mapping_or_empty(diff.get("workspace_execution"))
    patch = str(diff.get("patch") or "")
    return {
        "sha256": _semantic_hash("run-diff", patch),
        "byte_count": len(patch.encode("utf-8")),
        "captured": bool(patch and patch != "No diff captured."),
        "truncated": bool(execution.get("truncated")),
        "changed_file_count": len(_string_sequence(diff.get("changed_files"))),
        "untracked_file_count": len(_string_sequence(diff.get("untracked_files"))),
        "path_identities": sorted(
            _semantic_hash("run-diff-path", path)
            for path in (
                *_string_sequence(diff.get("changed_files")),
                *_string_sequence(diff.get("untracked_files")),
            )
        )[:MAX_CAPSULE_ARTIFACTS],
    }


def _artifact_projection(
    run: HarnessRun,
    events: Sequence[HarnessStoredEvent],
    environment: Mapping[str, Any],
) -> list[dict[str, Any]]:
    diff = _diff_projection(run)
    artifacts: list[dict[str, Any]] = []
    if diff["captured"]:
        artifacts.append(
            {
                "type": "diff",
                "identity_sha256": diff["sha256"],
                "byte_count": diff["byte_count"],
            }
        )
    execution = _mapping_or_empty(run.metadata.get("workspace_execution"))
    if execution.get("worktree_path"):
        artifacts.append(
            {
                "type": "worktree",
                "identity_sha256": environment["snapshot_sha256"],
                "byte_count": None,
            }
        )
    for key, artifact_type in (
        ("pr_artifact", "pr_report"),
        ("report", "report"),
        ("test_report", "test_report"),
    ):
        value = run.metadata.get(key)
        if value is not None:
            artifacts.append(
                {
                    "type": artifact_type,
                    "identity_sha256": _semantic_hash(artifact_type, value),
                    "byte_count": _encoded_size(value),
                }
            )
    for event in events:
        normalized = event.type.casefold().replace(".", "_").replace("-", "_")
        if normalized not in {"generated_file", "file_changed"}:
            continue
        artifacts.append(
            {
                "type": normalized,
                "identity_sha256": _semantic_hash(
                    f"event-artifact:{event.id}", event.payload
                ),
                "byte_count": None,
            }
        )
        if len(artifacts) >= MAX_CAPSULE_ARTIFACTS:
            break
    return sorted(
        artifacts[:MAX_CAPSULE_ARTIFACTS],
        key=lambda item: (str(item["type"]), str(item["identity_sha256"])),
    )


def _tool_extension_projection(run: HarnessRun) -> dict[str, Any]:
    metadata = _mapping_or_empty(run.metadata)
    provenance = _mapping_or_empty(metadata.get("provenance"))
    execution = _mapping_or_empty(provenance.get("execution"))
    managed = _mapping_or_empty(metadata.get("managed_mcp_snapshot"))
    if not managed:
        managed = _mapping_or_empty(execution.get("managed_mcp_snapshot"))
    snapshot_hash = _first_hash(
        managed.get("snapshot_hash"),
        metadata.get("extension_snapshot_hash"),
        execution.get("extension_snapshot_hash"),
    )
    server_ids = _string_sequence(managed.get("server_ids"))
    projection = {
        "managed_mcp_snapshot_id": _optional_identity(managed.get("snapshot_id")),
        "snapshot_sha256": snapshot_hash,
        "server_count": len(server_ids),
        "server_identities": sorted(
            _semantic_hash("managed-mcp-server", item) for item in server_ids
        ),
        "descriptor_contents_included": False,
        "secret_values_included": False,
    }
    return {
        **projection,
        "projection_sha256": _semantic_hash("tool-extension-snapshot", projection),
    }


def _provider_projection(run: HarnessRun) -> dict[str, Any]:
    metadata = _mapping_or_empty(run.metadata)
    provenance = _mapping_or_empty(metadata.get("provenance"))
    request = _mapping_or_empty(provenance.get("request"))
    extra = _mapping_or_empty(request.get("extra"))
    provider_ref = _mapping_or_empty(
        metadata.get("provider_ref") or extra.get("provider_ref")
    )
    return {
        "id": _optional_identity(
            provider_ref.get("id")
            or provider_ref.get("provider_id")
            or metadata.get("provider_id")
        ),
        "revision": _optional_identity(provider_ref.get("revision")),
        "model_sha256": (
            _semantic_hash("model", run.model) if run.model is not None else None
        ),
    }


def _unresolved_questions(
    events: Sequence[HarnessStoredEvent],
) -> list[dict[str, Any]]:
    pending: dict[str, HarnessStoredEvent] = {}
    for event in events:
        normalized = event.type.casefold().replace(".", "_").replace("-", "_")
        request_id = _question_identity(event)
        if any(marker in normalized for marker in _QUESTION_RESOLUTION_MARKERS):
            pending.pop(request_id, None)
        elif any(marker in normalized for marker in _QUESTION_REQUEST_MARKERS):
            pending[request_id] = event
    return [
        {
            "id": _semantic_hash("question-id", request_id),
            "type": event.type,
            "created_at": event.created_at,
            "content_included": False,
        }
        for request_id, event in sorted(pending.items())[:MAX_CAPSULE_QUESTIONS]
    ]


def _question_identity(event: HarnessStoredEvent) -> str:
    for key in ("request_id", "input_id", "elicitation_id", "id"):
        value = _optional_identity(event.payload.get(key))
        if value is not None:
            return value
    return event.id


def _semantic_hash(domain: str, value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + encoded).hexdigest()


def _json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encoded_size(value: Any) -> int:
    return len(
        json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode(
            "utf-8"
        )
    )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HandoffCapsuleError(f"handoff capsule {field_name} must be an object")
    return value


def _exact_mapping(
    value: Any,
    field_name: str,
    expected: set[str],
) -> Mapping[str, Any]:
    mapping = _mapping(value, field_name)
    _exact_fields(mapping, field_name, expected)
    return mapping


def _exact_fields(
    value: Mapping[str, Any],
    field_name: str,
    expected: set[str],
) -> None:
    if set(value) != expected:
        raise HandoffCapsuleError(f"handoff capsule {field_name} fields are invalid")


def _object_list(value: Any, field_name: str, *, limit: int) -> list[Mapping[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise HandoffCapsuleError(f"handoff capsule {field_name} is invalid")
    return value


def _hash_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise HandoffCapsuleError(f"handoff capsule {field_name} must be a list")
    hashes = [_required_hash(item, field_name) for item in value]
    if hashes != sorted(set(hashes)):
        raise HandoffCapsuleError(f"handoff capsule {field_name} is not canonical")
    return hashes


def _non_negative_integer(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HandoffCapsuleError(
            f"handoff capsule {field_name} must be a non-negative integer"
        )
    return value


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _required_identity(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if _IDENTITY_RE.fullmatch(text) is None:
        raise HandoffCapsuleError(f"{field_name} is invalid")
    return text


def _optional_identity(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if _IDENTITY_RE.fullmatch(text) is not None else None


def _required_hash(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if _HASH_RE.fullmatch(text) is None:
        raise HandoffCapsuleError(f"{field_name} is invalid")
    return text


def _first_hash(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if _HASH_RE.fullmatch(text) is not None:
            return text
    return None
