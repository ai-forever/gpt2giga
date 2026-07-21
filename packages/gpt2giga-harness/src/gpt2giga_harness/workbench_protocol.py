"""Provider-neutral action, event, and projection backbone for the Workbench."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from enum import Enum
import json
import re
import threading
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from gpt2giga_harness.sessions.redaction import redact_event_payload


MAX_DELTA_EVENTS = 32
MAX_SNAPSHOT_EVENTS = 24
MAX_ACTION_RECEIPTS = 512
MAX_ACTION_BYTES = 64 * 1024
MAX_EVENT_BYTES = 8 * 1024
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9._:@+~-]{1,256}$")


class WorkbenchProtocolError(ValueError):
    """Raised when a Workbench contract is malformed or stale."""


class ResnapshotRequired(WorkbenchProtocolError):
    """Raised when an event cannot be applied to the presented state."""


class WorkbenchActionKind(str, Enum):
    """Stable application intents understood by the shared Workbench boundary."""

    TURN_SUBMIT = "turn.submit"
    TURN_STEER = "turn.steer"
    TURN_CANCEL = "turn.cancel"
    APPROVAL_DECIDE = "approval.decide"
    INPUT_ANSWER = "input.answer"
    SESSION_SELECT = "session.select"
    PREFERENCE_SET = "preference.set"


@dataclass(frozen=True)
class WorkbenchAction:
    """One idempotent intent bound to an exact Workbench generation."""

    id: str
    idempotency_key: str
    kind: WorkbenchActionKind
    generation: int
    expected_revision: int
    session_id: str | None = None
    workspace_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identity(self.id, "action id")
        _identity(self.idempotency_key, "idempotency key")
        _positive(self.generation, "generation")
        _non_negative(self.expected_revision, "expected revision")
        if not isinstance(self.kind, WorkbenchActionKind):
            raise WorkbenchProtocolError("action kind is invalid")
        if self.session_id is not None:
            _identity(self.session_id, "session id")
        if self.workspace_id is not None:
            _identity(self.workspace_id, "workspace id")
        object.__setattr__(self, "payload", _bounded_action_payload(self.payload))


@dataclass(frozen=True)
class ArtifactReference:
    """Bounded retained artifact identity; artifact content stays with its owner."""

    id: str
    kind: str
    media_type: str
    byte_count: int
    truncated: bool = False

    def __post_init__(self) -> None:
        _identity(self.id, "artifact id")
        _identity(self.kind, "artifact kind")
        if not self.media_type or len(self.media_type) > 128:
            raise WorkbenchProtocolError("artifact media type is invalid")
        _non_negative(self.byte_count, "artifact byte count")


@dataclass(frozen=True)
class WorkbenchEventDraft:
    """Normalized provider or application event before sequencing."""

    payload_type: str
    payload: Mapping[str, Any]
    provider: str
    session_id: str
    workspace_id: str
    source: str
    correlation_id: str
    idempotency_key: str | None = None
    artifacts: tuple[ArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.payload_type, "payload type"),
            (self.provider, "provider"),
            (self.session_id, "session id"),
            (self.workspace_id, "workspace id"),
            (self.source, "event source"),
            (self.correlation_id, "correlation id"),
        ):
            _identity(value, label)
        if self.idempotency_key is not None:
            _identity(self.idempotency_key, "event idempotency key")
        if len(self.artifacts) > 64:
            raise WorkbenchProtocolError("event artifacts exceed the Workbench limit")
        object.__setattr__(self, "payload", _bounded_payload(self.payload))


@dataclass(frozen=True)
class WorkbenchEventEnvelope:
    """One ordered, revision-bound normalized event consumed by projections."""

    id: str
    sequence: int
    revision: int
    generation: int
    provider: str
    session_id: str
    workspace_id: str
    source: str
    correlation_id: str
    payload_type: str
    payload: Mapping[str, Any]
    idempotency_key: str | None = None
    artifacts: tuple[ArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "event id"),
            (self.provider, "provider"),
            (self.session_id, "session id"),
            (self.workspace_id, "workspace id"),
            (self.source, "event source"),
            (self.correlation_id, "correlation id"),
            (self.payload_type, "payload type"),
        ):
            _identity(value, label)
        _positive(self.sequence, "event sequence")
        _positive(self.revision, "event revision")
        _positive(self.generation, "event generation")
        if self.idempotency_key is not None:
            _identity(self.idempotency_key, "event idempotency key")
        if len(self.artifacts) > 64:
            raise WorkbenchProtocolError("event artifacts exceed the Workbench limit")
        object.__setattr__(self, "payload", _bounded_payload(self.payload))


@dataclass(frozen=True)
class WorkbenchProjections:
    """Provider-neutral read models shared by every Workbench transport."""

    command_catalog: Mapping[str, Any] = field(default_factory=dict)
    runtime_controls: Mapping[str, Any] = field(default_factory=dict)
    transcript_items: tuple[Mapping[str, Any], ...] = ()
    sessions: tuple[Mapping[str, Any], ...] = ()
    tasks_processes: tuple[Mapping[str, Any], ...] = ()
    usage_limits: Mapping[str, Any] = field(default_factory=dict)
    preferences: Mapping[str, Any] = field(default_factory=dict)
    raw_terminal_frames: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "command_catalog",
            "runtime_controls",
            "usage_limits",
            "preferences",
        ):
            object.__setattr__(self, name, _freeze_mapping(getattr(self, name)))
        for name in (
            "transcript_items",
            "sessions",
            "tasks_processes",
            "raw_terminal_frames",
        ):
            object.__setattr__(
                self,
                name,
                tuple(_freeze_mapping(item) for item in getattr(self, name)),
            )


@dataclass(frozen=True)
class WorkbenchSnapshot:
    """Bounded authoritative state used for initial load and gap recovery."""

    revision: int = 0
    generation: int = 1
    sequence: int = 0
    cursor: str = "wb1.1.0.0"
    projections: WorkbenchProjections = field(default_factory=WorkbenchProjections)
    applied_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkbenchStatePage:
    """One full snapshot plus optional ordered deltas after a known cursor."""

    snapshot: WorkbenchSnapshot
    deltas: tuple[WorkbenchEventEnvelope, ...]
    cursor: str
    has_more: bool = False
    resnapshot_reason: str | None = None


class ProviderEventDecoder(Protocol):
    """Boundary that prevents widgets from receiving raw provider payloads."""

    def decode(self, raw_event: Mapping[str, Any]) -> WorkbenchEventDraft:
        """Normalize one provider event without exposing the raw value downstream."""


@dataclass(frozen=True)
class WorkbenchActionReceipt:
    """Content-free lifecycle state for one idempotent Workbench action."""

    action_id: str
    idempotency_key: str
    status: str


class WorkbenchActionRegistry:
    """Bounded idempotency and cancellation state owned by application services."""

    def __init__(self, *, max_receipts: int = MAX_ACTION_RECEIPTS) -> None:
        self.max_receipts = max(1, max_receipts)
        self._lock = threading.RLock()
        self._by_key: OrderedDict[str, WorkbenchActionReceipt] = OrderedDict()
        self._cancelled: set[str] = set()

    def begin(self, action: WorkbenchAction) -> WorkbenchActionReceipt:
        """Accept one action or return its existing exactly-once receipt."""
        with self._lock:
            existing = self._by_key.get(action.idempotency_key)
            if existing is not None:
                if existing.action_id != action.id:
                    raise WorkbenchProtocolError(
                        "idempotency key belongs to another action"
                    )
                return existing
            receipt = WorkbenchActionReceipt(
                action_id=action.id,
                idempotency_key=action.idempotency_key,
                status="accepted",
            )
            self._by_key[action.idempotency_key] = receipt
            while len(self._by_key) > self.max_receipts:
                _, evicted = self._by_key.popitem(last=False)
                self._cancelled.discard(evicted.action_id)
            return receipt

    def cancel(self, action_id: str) -> WorkbenchActionReceipt:
        """Mark an accepted action canceled for its application owner to observe."""
        _identity(action_id, "action id")
        with self._lock:
            for key, receipt in self._by_key.items():
                if receipt.action_id == action_id:
                    cancelled = replace(receipt, status="canceled")
                    self._by_key[key] = cancelled
                    self._cancelled.add(action_id)
                    return cancelled
        raise WorkbenchProtocolError("action is not retained")

    def cancellation_requested(self, action_id: str) -> bool:
        """Return the content-free cancellation signal for an application owner."""
        with self._lock:
            return action_id in self._cancelled


class WorkbenchBackbone:
    """Thread-safe bounded event log and deterministic projection reducer."""

    def __init__(
        self,
        *,
        generation: int = 1,
        max_deltas: int = MAX_DELTA_EVENTS,
        max_snapshot_events: int = MAX_SNAPSHOT_EVENTS,
    ) -> None:
        _positive(generation, "generation")
        self.max_deltas = max(1, max_deltas)
        self.max_snapshot_events = max(1, max_snapshot_events)
        self._lock = threading.RLock()
        self._snapshot = WorkbenchSnapshot(
            generation=generation,
            cursor=_cursor(generation, 0, 0),
        )
        self._deltas: list[WorkbenchEventEnvelope] = []
        self._by_idempotency: dict[str, WorkbenchEventEnvelope] = {}
        self.actions = WorkbenchActionRegistry()

    @property
    def snapshot(self) -> WorkbenchSnapshot:
        """Return the current immutable authoritative snapshot."""
        with self._lock:
            return self._snapshot

    def publish(self, draft: WorkbenchEventDraft) -> WorkbenchEventEnvelope:
        """Sequence, redact, reduce, and retain one normalized event exactly once."""
        with self._lock:
            if draft.idempotency_key is not None:
                existing = self._by_idempotency.get(draft.idempotency_key)
                if existing is not None:
                    if existing.correlation_id != draft.correlation_id:
                        raise WorkbenchProtocolError(
                            "event idempotency key belongs to another correlation"
                        )
                    return existing
            sequence = self._snapshot.sequence + 1
            revision = self._snapshot.revision + 1
            envelope = WorkbenchEventEnvelope(
                id=f"wbe_{self._snapshot.generation}_{sequence}",
                sequence=sequence,
                revision=revision,
                generation=self._snapshot.generation,
                provider=draft.provider,
                session_id=draft.session_id,
                workspace_id=draft.workspace_id,
                source=draft.source,
                correlation_id=draft.correlation_id,
                idempotency_key=draft.idempotency_key,
                payload_type=draft.payload_type,
                payload=draft.payload,
                artifacts=draft.artifacts,
            )
            self._snapshot = reduce_workbench_event(
                self._snapshot,
                envelope,
                max_events=self.max_snapshot_events,
            )
            self._deltas.append(envelope)
            self._deltas = self._deltas[-self.max_deltas :]
            if draft.idempotency_key is not None:
                self._by_idempotency[draft.idempotency_key] = envelope
            return envelope

    def accept_action(self, action: WorkbenchAction) -> WorkbenchActionReceipt:
        """Bind an idempotent action to the current generation and revision."""
        with self._lock:
            if action.generation != self._snapshot.generation:
                raise ResnapshotRequired("action generation changed")
            if action.expected_revision != self._snapshot.revision:
                raise ResnapshotRequired("action revision changed")
            return self.actions.begin(action)

    def cancel_action(self, action_id: str) -> WorkbenchActionReceipt:
        """Expose a content-free cancellation signal to the application owner."""
        return self.actions.cancel(action_id)

    def publish_provider_event(
        self,
        decoder: ProviderEventDecoder,
        raw_event: Mapping[str, Any],
    ) -> WorkbenchEventEnvelope:
        """Decode at the provider boundary and retain only the normalized draft."""
        return self.publish(decoder.decode(raw_event))

    def read(
        self,
        cursor: str | None = None,
        *,
        limit: int = MAX_DELTA_EVENTS,
    ) -> WorkbenchStatePage:
        """Return ordered deltas or a bounded authoritative resnapshot on any gap."""
        bounded_limit = min(max(1, limit), self.max_deltas)
        with self._lock:
            snapshot = self._snapshot
            if cursor is None:
                return WorkbenchStatePage(snapshot, (), snapshot.cursor)
            parsed = _parse_cursor(cursor)
            if parsed is None:
                return WorkbenchStatePage(
                    snapshot, (), snapshot.cursor, resnapshot_reason="cursor_gap"
                )
            generation, sequence, revision = parsed
            if generation != snapshot.generation:
                return WorkbenchStatePage(
                    snapshot,
                    (),
                    snapshot.cursor,
                    resnapshot_reason="generation_changed",
                )
            if (
                sequence != revision
                or sequence > snapshot.sequence
                or revision > snapshot.revision
            ):
                return WorkbenchStatePage(
                    snapshot, (), snapshot.cursor, resnapshot_reason="cursor_gap"
                )
            retained_floor = self._deltas[0].sequence - 1 if self._deltas else sequence
            if sequence < retained_floor:
                return WorkbenchStatePage(
                    snapshot, (), snapshot.cursor, resnapshot_reason="slow_consumer"
                )
            available = [event for event in self._deltas if event.sequence > sequence]
            deltas = tuple(available[:bounded_limit])
            has_more = len(available) > len(deltas)
            next_cursor = (
                _cursor(generation, deltas[-1].sequence, deltas[-1].revision)
                if deltas
                else cursor
            )
            return WorkbenchStatePage(snapshot, deltas, next_cursor, has_more)


def reduce_workbench_event(
    snapshot: WorkbenchSnapshot,
    event: WorkbenchEventEnvelope,
    *,
    max_events: int = MAX_SNAPSHOT_EVENTS,
) -> WorkbenchSnapshot:
    """Apply one normalized event exactly once and fail closed on ordering gaps."""
    if event.id in snapshot.applied_event_ids:
        return snapshot
    if event.generation != snapshot.generation:
        raise ResnapshotRequired("event generation changed")
    if event.sequence != snapshot.sequence + 1:
        raise ResnapshotRequired("event sequence gap")
    if event.revision != snapshot.revision + 1:
        raise ResnapshotRequired("event revision gap")

    projections = _reduce_projection(snapshot.projections, event, max_events=max_events)
    retained_ids = (*snapshot.applied_event_ids, event.id)[-max(1, max_events) :]
    return WorkbenchSnapshot(
        revision=event.revision,
        generation=event.generation,
        sequence=event.sequence,
        cursor=_cursor(event.generation, event.sequence, event.revision),
        projections=projections,
        applied_event_ids=retained_ids,
    )


def workbench_state_page_to_dict(page: WorkbenchStatePage) -> dict[str, Any]:
    """Serialize one transport-neutral state page."""
    return {
        "snapshot": workbench_snapshot_to_dict(page.snapshot),
        "deltas": [workbench_event_to_dict(event) for event in page.deltas],
        "cursor": page.cursor,
        "has_more": page.has_more,
        "resnapshot_reason": page.resnapshot_reason,
    }


def workbench_state_page_from_dict(value: Mapping[str, Any]) -> WorkbenchStatePage:
    """Parse a strict attach response into the shared in-process contract."""
    snapshot = workbench_snapshot_from_dict(_mapping(value.get("snapshot")))
    raw_deltas = value.get("deltas", ())
    if not isinstance(raw_deltas, list) or len(raw_deltas) > MAX_DELTA_EVENTS:
        raise WorkbenchProtocolError("workbench deltas are invalid")
    deltas = tuple(workbench_event_from_dict(_mapping(item)) for item in raw_deltas)
    cursor = _text(value.get("cursor"), "workbench cursor")
    if _parse_cursor(cursor) is None:
        raise WorkbenchProtocolError("workbench cursor is invalid")
    reason = value.get("resnapshot_reason")
    if reason is not None and reason not in {
        "cursor_gap",
        "generation_changed",
        "slow_consumer",
    }:
        raise WorkbenchProtocolError("resnapshot reason is invalid")
    return WorkbenchStatePage(
        snapshot=snapshot,
        deltas=deltas,
        cursor=cursor,
        has_more=bool(value.get("has_more", False)),
        resnapshot_reason=reason,
    )


def workbench_snapshot_to_dict(snapshot: WorkbenchSnapshot) -> dict[str, Any]:
    """Serialize a bounded projection snapshot."""
    projections = snapshot.projections
    return {
        "revision": snapshot.revision,
        "generation": snapshot.generation,
        "sequence": snapshot.sequence,
        "cursor": snapshot.cursor,
        "applied_event_ids": list(snapshot.applied_event_ids),
        "projections": {
            "command_catalog": _thaw(projections.command_catalog),
            "runtime_controls": _thaw(projections.runtime_controls),
            "transcript_items": _thaw(projections.transcript_items),
            "sessions": _thaw(projections.sessions),
            "tasks_processes": _thaw(projections.tasks_processes),
            "usage_limits": _thaw(projections.usage_limits),
            "preferences": _thaw(projections.preferences),
            "raw_terminal_frames": _thaw(projections.raw_terminal_frames),
        },
    }


def workbench_snapshot_from_dict(value: Mapping[str, Any]) -> WorkbenchSnapshot:
    """Parse a strict bounded snapshot returned by the attach API."""
    generation = _int(value.get("generation"), "generation", positive=True)
    sequence = _int(value.get("sequence"), "sequence")
    revision = _int(value.get("revision"), "revision")
    cursor = _text(value.get("cursor"), "workbench cursor")
    if _parse_cursor(cursor) != (generation, sequence, revision):
        raise WorkbenchProtocolError("snapshot cursor does not match its revision")
    projections = _mapping(value.get("projections"))
    raw_event_ids = value.get("applied_event_ids", ())
    if not isinstance(raw_event_ids, list) or len(raw_event_ids) > MAX_SNAPSHOT_EVENTS:
        raise WorkbenchProtocolError("applied event identities are invalid")
    return WorkbenchSnapshot(
        revision=revision,
        generation=generation,
        sequence=sequence,
        cursor=cursor,
        applied_event_ids=tuple(
            _identity(item, "applied event id") for item in raw_event_ids
        ),
        projections=WorkbenchProjections(
            command_catalog=_mapping(projections.get("command_catalog")),
            runtime_controls=_mapping(projections.get("runtime_controls")),
            transcript_items=_mapping_tuple(projections.get("transcript_items")),
            sessions=_mapping_tuple(projections.get("sessions")),
            tasks_processes=_mapping_tuple(projections.get("tasks_processes")),
            usage_limits=_mapping(projections.get("usage_limits")),
            preferences=_mapping(projections.get("preferences")),
            raw_terminal_frames=_mapping_tuple(projections.get("raw_terminal_frames")),
        ),
    )


def workbench_event_to_dict(event: WorkbenchEventEnvelope) -> dict[str, Any]:
    """Serialize one normalized event without a provider-specific envelope."""
    return {
        "id": event.id,
        "sequence": event.sequence,
        "revision": event.revision,
        "generation": event.generation,
        "provider": event.provider,
        "session_id": event.session_id,
        "workspace_id": event.workspace_id,
        "source": event.source,
        "correlation_id": event.correlation_id,
        "idempotency_key": event.idempotency_key,
        "payload_type": event.payload_type,
        "payload": _thaw(event.payload),
        "artifacts": [artifact.__dict__ for artifact in event.artifacts],
    }


def workbench_event_from_dict(value: Mapping[str, Any]) -> WorkbenchEventEnvelope:
    """Parse one strict normalized delta from the attach API."""
    raw_artifacts = value.get("artifacts", ())
    if not isinstance(raw_artifacts, list) or len(raw_artifacts) > 64:
        raise WorkbenchProtocolError("event artifacts are invalid")
    artifacts = tuple(
        ArtifactReference(
            id=_text(item.get("id"), "artifact id"),
            kind=_text(item.get("kind"), "artifact kind"),
            media_type=_text(item.get("media_type"), "artifact media type"),
            byte_count=_int(item.get("byte_count"), "artifact byte count"),
            truncated=bool(item.get("truncated", False)),
        )
        for item in (_mapping(raw) for raw in raw_artifacts)
    )
    return WorkbenchEventEnvelope(
        id=_text(value.get("id"), "event id"),
        sequence=_int(value.get("sequence"), "event sequence", positive=True),
        revision=_int(value.get("revision"), "event revision", positive=True),
        generation=_int(value.get("generation"), "event generation", positive=True),
        provider=_text(value.get("provider"), "provider"),
        session_id=_text(value.get("session_id"), "session id"),
        workspace_id=_text(value.get("workspace_id"), "workspace id"),
        source=_text(value.get("source"), "event source"),
        correlation_id=_text(value.get("correlation_id"), "correlation id"),
        idempotency_key=(
            _text(value.get("idempotency_key"), "event idempotency key")
            if value.get("idempotency_key") is not None
            else None
        ),
        payload_type=_text(value.get("payload_type"), "payload type"),
        payload=_mapping(value.get("payload")),
        artifacts=artifacts,
    )


def _reduce_projection(
    projections: WorkbenchProjections,
    event: WorkbenchEventEnvelope,
    *,
    max_events: int,
) -> WorkbenchProjections:
    payload = dict(event.payload)
    kind = event.payload_type
    if kind == "command.catalog":
        return replace(projections, command_catalog=payload)
    if kind == "runtime.controls":
        return replace(projections, runtime_controls=payload)
    if kind == "transcript.item":
        return replace(
            projections,
            transcript_items=(*projections.transcript_items, payload)[-max_events:],
        )
    if kind == "sessions.snapshot":
        return replace(projections, sessions=_items(payload, "items", max_events))
    if kind == "tasks_processes.snapshot":
        return replace(
            projections,
            tasks_processes=_items(payload, "items", max_events),
        )
    if kind == "usage.limits":
        return replace(projections, usage_limits=payload)
    if kind == "preferences.snapshot":
        return replace(projections, preferences=payload)
    if kind == "raw-terminal-v1":
        return replace(
            projections,
            raw_terminal_frames=(*projections.raw_terminal_frames, payload)[
                -max_events:
            ],
        )
    return projections


def _bounded_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    redacted = redact_event_payload(value)
    encoded = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_EVENT_BYTES:
        raise WorkbenchProtocolError("event payload exceeds the Workbench limit")
    return _freeze_mapping(redacted)


def _bounded_action_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    thawed = _thaw(value)
    try:
        encoded = json.dumps(thawed, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkbenchProtocolError("action payload is not JSON-compatible") from exc
    if len(encoded.encode("utf-8")) > MAX_ACTION_BYTES:
        raise WorkbenchProtocolError("action payload exceeds the Workbench limit")
    return _freeze_mapping(thawed)


def _items(
    payload: Mapping[str, Any], key: str, limit: int
) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(key, ())
    if not isinstance(value, (list, tuple)):
        raise WorkbenchProtocolError(f"{key} projection is invalid")
    return tuple(_mapping(item) for item in value[:limit])


def _mapping_tuple(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or len(value) > MAX_SNAPSHOT_EVENTS:
        raise WorkbenchProtocolError("projection items are invalid")
    return tuple(_mapping(item) for item in value)


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkbenchProtocolError("expected an object")
    return {str(key): item for key, item in value.items()}


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _cursor(generation: int, sequence: int, revision: int) -> str:
    return f"wb1.{generation}.{sequence}.{revision}"


def _parse_cursor(value: str) -> tuple[int, int, int] | None:
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != "wb1":
        return None
    try:
        generation, sequence, revision = (int(item) for item in parts[1:])
    except ValueError:
        return None
    if generation < 1 or sequence < 0 or revision < 0:
        return None
    return generation, sequence, revision


def _identity(value: str, label: str) -> str:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise WorkbenchProtocolError(f"{label} is invalid")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkbenchProtocolError(f"{label} is invalid")
    return value


def _int(value: Any, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorkbenchProtocolError(f"{label} is invalid")
    if value < (1 if positive else 0):
        raise WorkbenchProtocolError(f"{label} is invalid")
    return value


def _positive(value: int, label: str) -> None:
    _int(value, label, positive=True)


def _non_negative(value: int, label: str) -> None:
    _int(value, label)
