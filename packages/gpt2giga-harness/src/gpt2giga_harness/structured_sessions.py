"""Provider-neutral structured-session contracts and durable links."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from gpt2giga_harness.execution import (
    ExecutionSnapshot,
    ExecutionTransport,
    SnapshotEvidenceRef,
    execution_snapshot_from_dict,
    execution_snapshot_to_dict,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock


CAPABILITY_SNAPSHOT_SCHEMA_VERSION = 1
CONFIG_SNAPSHOT_SCHEMA_VERSION = 1
STRUCTURED_SESSION_LINK_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StructuredSessionError(RuntimeError):
    """Base error for provider-neutral structured-session operations."""


class UnsupportedSessionCapability(StructuredSessionError):
    """Raised when an optional driver capability is not available."""


class SessionSnapshotMismatch(StructuredSessionError):
    """Raised when continuation is attempted with changed immutable inputs."""


class SessionLinkConflict(StructuredSessionError):
    """Raised when a durable link revision changed concurrently."""


class RecoveryState(str, Enum):
    """Describe the durable ownership/recovery state of a structured session."""

    ACTIVE = "active"
    OWNER_LOST = "owner_lost"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    DEGRADED = "degraded"
    CLOSED = "closed"


@dataclass(frozen=True)
class AdapterCapabilitySnapshot:
    """Immutable truth about one probed structured-session driver."""

    adapter_id: str
    adapter_version: str
    protocol: str
    protocol_version: str
    structured_events: bool
    partial_output: bool
    interactive_input: bool
    live_approvals: bool
    durable_approval: bool
    interrupt: bool
    steer: bool
    resume: bool
    fork: bool
    session_list: bool
    session_close: bool
    native_auth: bool
    provider_ui_handoff: bool
    dynamic_model: bool
    dynamic_mcp: bool
    recovery_after_process_loss: bool
    attachment_kinds: tuple[str, ...] = ()
    attachment_transports: tuple[str, ...] = ()
    min_link_schema_version: int = STRUCTURED_SESSION_LINK_SCHEMA_VERSION
    max_link_schema_version: int = STRUCTURED_SESSION_LINK_SCHEMA_VERSION
    schema_version: int = CAPABILITY_SNAPSHOT_SCHEMA_VERSION
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CAPABILITY_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported capability snapshot schema_version")
        for name in ("adapter_id", "adapter_version", "protocol", "protocol_version"):
            _validate_identity(getattr(self, name), field_name=name)
        for name in _CAPABILITY_BOOLEAN_FIELDS:
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        object.__setattr__(
            self,
            "attachment_kinds",
            _normalize_identities(self.attachment_kinds, field_name="attachment kind"),
        )
        object.__setattr__(
            self,
            "attachment_transports",
            _normalize_identities(
                self.attachment_transports,
                field_name="attachment transport",
            ),
        )
        if (
            not isinstance(self.min_link_schema_version, int)
            or isinstance(self.min_link_schema_version, bool)
            or not isinstance(self.max_link_schema_version, int)
            or isinstance(self.max_link_schema_version, bool)
            or self.min_link_schema_version < 1
            or self.max_link_schema_version < self.min_link_schema_version
        ):
            raise ValueError("capability link schema window is invalid")
        object.__setattr__(
            self, "snapshot_hash", _canonical_hash(_capability_payload(self))
        )

    def supports_link_schema(self, version: int) -> bool:
        """Return whether the driver admits one canonical link schema."""
        return self.min_link_schema_version <= version <= self.max_link_schema_version


@dataclass(frozen=True)
class StructuredSessionConfigSnapshot:
    """Immutable content-free driver configuration for continuation."""

    adapter_id: str
    adapter_version: str
    protocol: str
    protocol_version: str
    cli_sdk_version: str
    managed_home_id: str | None = None
    schema_version: int = CONFIG_SNAPSHOT_SCHEMA_VERSION
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CONFIG_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported config snapshot schema_version")
        for name in (
            "adapter_id",
            "adapter_version",
            "protocol",
            "protocol_version",
            "cli_sdk_version",
        ):
            _validate_identity(getattr(self, name), field_name=name)
        if self.managed_home_id is not None:
            _validate_identity(self.managed_home_id, field_name="managed_home_id")
        object.__setattr__(
            self, "snapshot_hash", _canonical_hash(_config_payload(self))
        )


@dataclass(frozen=True)
class StructuredSessionLink:
    """Redaction-safe durable binding to one external structured session."""

    id: str
    harness_session_id: str
    harness_run_id: str
    execution_snapshot: ExecutionSnapshot
    config_snapshot: StructuredSessionConfigSnapshot
    capability_snapshot: AdapterCapabilitySnapshot
    external_session_id: str
    latest_external_turn_id: str | None
    supervisor_owner: str
    heartbeat_at: str
    recovery_state: RecoveryState = RecoveryState.ACTIVE
    forked_from_link_id: str | None = None
    forked_from_external_turn_id: str | None = None
    degradation_evidence: tuple[SnapshotEvidenceRef, ...] = ()
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    revision: int = 1
    schema_version: int = STRUCTURED_SESSION_LINK_SCHEMA_VERSION
    link_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != STRUCTURED_SESSION_LINK_SCHEMA_VERSION:
            raise ValueError("unsupported structured session link schema_version")
        for name in (
            "id",
            "harness_session_id",
            "harness_run_id",
            "external_session_id",
            "supervisor_owner",
        ):
            _validate_identity(getattr(self, name), field_name=name)
        for name in (
            "latest_external_turn_id",
            "forked_from_link_id",
            "forked_from_external_turn_id",
        ):
            value = getattr(self, name)
            if value is not None:
                _validate_identity(value, field_name=name)
        if not isinstance(self.execution_snapshot, ExecutionSnapshot):
            raise ValueError("link execution_snapshot must be an ExecutionSnapshot")
        if not self.execution_snapshot.is_executable:
            raise ValueError("structured session link requires an executable snapshot")
        if (
            self.execution_snapshot.transport
            is not ExecutionTransport.NATIVE_STRUCTURED
        ):
            raise ValueError(
                "structured session link requires native_structured transport"
            )
        if not isinstance(self.config_snapshot, StructuredSessionConfigSnapshot):
            raise ValueError("link config_snapshot is invalid")
        if not isinstance(self.capability_snapshot, AdapterCapabilitySnapshot):
            raise ValueError("link capability_snapshot is invalid")
        if self.config_snapshot.adapter_id != self.capability_snapshot.adapter_id:
            raise ValueError("config and capability adapter identities differ")
        if (
            self.config_snapshot.adapter_version
            != self.capability_snapshot.adapter_version
        ):
            raise ValueError("config and capability adapter versions differ")
        if self.config_snapshot.protocol != self.capability_snapshot.protocol:
            raise ValueError("config and capability protocols differ")
        if (
            self.config_snapshot.protocol_version
            != self.capability_snapshot.protocol_version
        ):
            raise ValueError("config and capability protocol versions differ")
        if not self.capability_snapshot.supports_link_schema(self.schema_version):
            raise ValueError("driver does not support the structured link schema")
        if not isinstance(self.recovery_state, RecoveryState):
            raise ValueError("link recovery_state is invalid")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("link revision must be a positive integer")
        _validate_timestamp(self.created_at, field_name="created_at")
        _validate_timestamp(self.updated_at, field_name="updated_at")
        evidence = _normalize_evidence(self.degradation_evidence)
        object.__setattr__(self, "degradation_evidence", evidence)
        object.__setattr__(self, "link_hash", _canonical_hash(_link_payload(self)))

    def require_continuation_snapshots(
        self,
        execution_snapshot: ExecutionSnapshot,
        config_snapshot: StructuredSessionConfigSnapshot,
    ) -> None:
        """Fail closed unless both immutable continuation snapshots match."""
        if (
            execution_snapshot.snapshot_hash != self.execution_snapshot.snapshot_hash
            or config_snapshot.snapshot_hash != self.config_snapshot.snapshot_hash
        ):
            raise SessionSnapshotMismatch(
                "Structured session snapshot changed; fork or start a new session explicitly."
            )


@dataclass(frozen=True)
class StructuredSessionState:
    """Content-free session identity returned by a structured driver."""

    external_session_id: str
    latest_external_turn_id: str | None = None
    degradation_evidence: tuple[SnapshotEvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.external_session_id, field_name="external_session_id")
        if self.latest_external_turn_id is not None:
            _validate_identity(
                self.latest_external_turn_id,
                field_name="latest_external_turn_id",
            )
        object.__setattr__(
            self,
            "degradation_evidence",
            _normalize_evidence(self.degradation_evidence),
        )


@dataclass(frozen=True)
class StructuredTurnInput:
    """Ephemeral turn input that must not be persisted in a session link."""

    id: str
    content: str

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="turn input id")
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("turn input content is required")


@dataclass(frozen=True)
class StructuredTurnResult:
    """Content-free identity and outcome of one completed driver turn."""

    external_turn_id: str
    status: str

    def __post_init__(self) -> None:
        _validate_identity(self.external_turn_id, field_name="external_turn_id")
        _validate_identity(self.status, field_name="turn status")


EventSink = Callable[[Mapping[str, Any]], None]
ApprovalBridge = Callable[[Mapping[str, Any]], str]


class StructuredSessionDriver(Protocol):
    """Required operations implemented by every structured-session driver."""

    def probe(self) -> AdapterCapabilitySnapshot:
        """Return immutable capability and version evidence."""

    def open_or_resume(
        self,
        execution_snapshot: ExecutionSnapshot,
        session_link: StructuredSessionLink | None,
    ) -> StructuredSessionState:
        """Open a new external session or resume an exact bound link."""

    def start_turn(
        self,
        turn_input: StructuredTurnInput,
        event_sink: EventSink,
        approval_bridge: ApprovalBridge,
    ) -> StructuredTurnResult:
        """Start one turn using ephemeral input and bridges."""

    def respond_to_input(self, request_id: str, answer: str) -> None:
        """Respond to one provider input request."""

    def respond_to_approval(self, request_id: str, decision: str) -> None:
        """Respond to one provider approval request."""

    def interrupt(self, turn_id: str) -> None:
        """Interrupt one active provider turn."""

    def recover(self, session_link: StructuredSessionLink) -> StructuredSessionState:
        """Recover ownership after a supervised process loss."""

    def close(self) -> None:
        """Close resources owned by this driver instance."""


@runtime_checkable
class SteerCapableStructuredSessionDriver(Protocol):
    """Optional live steering operation."""

    def steer(self, turn_id: str, turn_input: StructuredTurnInput) -> None:
        """Steer one active turn."""


@runtime_checkable
class ForkCapableStructuredSessionDriver(Protocol):
    """Optional provider-native session fork operation."""

    def fork(
        self,
        session_link: StructuredSessionLink,
        turn_id: str | None,
    ) -> StructuredSessionState:
        """Fork one external session at an optional turn."""


@runtime_checkable
class ProviderHandoffStructuredSessionDriver(Protocol):
    """Optional provider-UI handoff operation."""

    def open_in_provider(self) -> str | None:
        """Open or identify the provider-owned UI without exposing credentials."""


class StructuredSessionLinkStore:
    """Persist strict structured-session links with optimistic revisions."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = (
            Path(data_dir).expanduser().resolve() / "structured_sessions" / "links"
        )

    def load(self, link_id: str) -> StructuredSessionLink | None:
        """Load and verify one link, returning ``None`` when absent."""
        _validate_identity(link_id, field_name="link id")
        try:
            data = json.loads(self._path(link_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError) as exc:
            raise StructuredSessionError(
                "Structured session link is unreadable"
            ) from exc
        link = structured_session_link_from_dict(data)
        if link.id != link_id:
            raise StructuredSessionError("Structured session link identity mismatch")
        return link

    def create(self, link: StructuredSessionLink) -> StructuredSessionLink:
        """Create a new link without replacing an existing identity."""
        with exclusive_file_lock(self._lock_path(link.id)):
            if self._path(link.id).exists():
                raise SessionLinkConflict("Structured session link already exists")
            if link.revision != 1:
                raise SessionLinkConflict(
                    "New structured session link must use revision 1"
                )
            self._write(link)
        return link

    def replace(
        self,
        link: StructuredSessionLink,
        *,
        expected_revision: int,
    ) -> StructuredSessionLink:
        """Replace a link only when the durable revision still matches."""
        with exclusive_file_lock(self._lock_path(link.id)):
            current = self.load(link.id)
            if current is None or current.revision != expected_revision:
                raise SessionLinkConflict("Structured session link revision changed")
            updated = replace(
                link,
                revision=expected_revision + 1,
                updated_at=_utc_now(),
            )
            self._write(updated)
        return updated

    def _write(self, link: StructuredSessionLink) -> None:
        payload = (
            json.dumps(
                structured_session_link_to_dict(link),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix=f".{self._key(link.id)}.", dir=self.root)
        temporary = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(link.id))
        finally:
            temporary.unlink(missing_ok=True)

    def _path(self, link_id: str) -> Path:
        return self.root / f"{self._key(link_id)}.json"

    def _lock_path(self, link_id: str) -> Path:
        return self.root / f".{self._key(link_id)}"

    @staticmethod
    def _key(link_id: str) -> str:
        return hashlib.sha256(link_id.encode("utf-8")).hexdigest()


class StructuredSessionCoordinator:
    """Enforce capabilities and snapshot-bound durable driver lifecycle."""

    def __init__(
        self,
        driver: StructuredSessionDriver,
        store: StructuredSessionLinkStore,
        *,
        owner_id: str,
    ) -> None:
        _validate_identity(owner_id, field_name="owner id")
        self.driver = driver
        self.store = store
        self.owner_id = owner_id

    def open_or_resume(
        self,
        *,
        link_id: str,
        harness_session_id: str,
        harness_run_id: str,
        execution_snapshot: ExecutionSnapshot,
        config_snapshot: StructuredSessionConfigSnapshot,
        existing_link: StructuredSessionLink | None = None,
    ) -> StructuredSessionLink:
        """Open or resume one exact immutable session binding."""
        capabilities = self.driver.probe()
        _validate_driver_snapshots(execution_snapshot, config_snapshot, capabilities)
        if existing_link is not None:
            self._require_current(existing_link)
            if not capabilities.resume:
                raise UnsupportedSessionCapability("resume is not supported")
            existing_link.require_continuation_snapshots(
                execution_snapshot,
                config_snapshot,
            )
            if existing_link.id != link_id:
                raise ValueError("existing link id does not match requested link id")
        state = self.driver.open_or_resume(execution_snapshot, existing_link)
        if existing_link is None:
            link = StructuredSessionLink(
                id=link_id,
                harness_session_id=harness_session_id,
                harness_run_id=harness_run_id,
                execution_snapshot=execution_snapshot,
                config_snapshot=config_snapshot,
                capability_snapshot=capabilities,
                external_session_id=state.external_session_id,
                latest_external_turn_id=state.latest_external_turn_id,
                supervisor_owner=self.owner_id,
                heartbeat_at=_utc_now(),
                degradation_evidence=state.degradation_evidence,
            )
            return self.store.create(link)
        updated = replace(
            existing_link,
            harness_run_id=harness_run_id,
            capability_snapshot=capabilities,
            external_session_id=state.external_session_id,
            latest_external_turn_id=state.latest_external_turn_id,
            supervisor_owner=self.owner_id,
            heartbeat_at=_utc_now(),
            recovery_state=RecoveryState.ACTIVE,
            degradation_evidence=state.degradation_evidence,
        )
        return self.store.replace(updated, expected_revision=existing_link.revision)

    def start_turn(
        self,
        link: StructuredSessionLink,
        turn_input: StructuredTurnInput,
        event_sink: EventSink,
        approval_bridge: ApprovalBridge,
    ) -> tuple[StructuredSessionLink, StructuredTurnResult]:
        """Run one turn and persist only its external identity."""
        self._require_owner(link)
        self._require_current(link)
        result = self.driver.start_turn(turn_input, event_sink, approval_bridge)
        updated = replace(
            link,
            latest_external_turn_id=result.external_turn_id,
            heartbeat_at=_utc_now(),
        )
        return self.store.replace(updated, expected_revision=link.revision), result

    def respond_to_input(
        self, link: StructuredSessionLink, request_id: str, answer: str
    ) -> None:
        """Forward interactive input only when it was probed as supported."""
        self._require_owner(link)
        self._require_current(link)
        _require_capability(
            link.capability_snapshot.interactive_input, "interactive input"
        )
        self.driver.respond_to_input(request_id, answer)

    def respond_to_approval(
        self,
        link: StructuredSessionLink,
        request_id: str,
        decision: str,
    ) -> None:
        """Forward an approval only when a supported approval mode exists."""
        self._require_owner(link)
        self._require_current(link)
        _require_capability(
            link.capability_snapshot.live_approvals
            or link.capability_snapshot.durable_approval,
            "approval response",
        )
        self.driver.respond_to_approval(request_id, decision)

    def interrupt(self, link: StructuredSessionLink, turn_id: str) -> None:
        """Interrupt one turn only when advertised by the driver."""
        self._require_owner(link)
        self._require_current(link)
        _require_capability(link.capability_snapshot.interrupt, "interrupt")
        self.driver.interrupt(turn_id)

    def steer(
        self,
        link: StructuredSessionLink,
        turn_id: str,
        turn_input: StructuredTurnInput,
    ) -> None:
        """Use optional live steering without replay emulation."""
        self._require_owner(link)
        self._require_current(link)
        _require_capability(link.capability_snapshot.steer, "steer")
        if not isinstance(self.driver, SteerCapableStructuredSessionDriver):
            raise UnsupportedSessionCapability("steer is not implemented by the driver")
        self.driver.steer(turn_id, turn_input)

    def fork(
        self,
        source: StructuredSessionLink,
        *,
        new_link_id: str,
        harness_session_id: str,
        harness_run_id: str,
        turn_id: str | None = None,
    ) -> StructuredSessionLink:
        """Create an explicit provider-native fork with immutable lineage."""
        self._require_current(source)
        _require_capability(source.capability_snapshot.fork, "fork")
        if not isinstance(self.driver, ForkCapableStructuredSessionDriver):
            raise UnsupportedSessionCapability("fork is not implemented by the driver")
        state = self.driver.fork(source, turn_id)
        link = StructuredSessionLink(
            id=new_link_id,
            harness_session_id=harness_session_id,
            harness_run_id=harness_run_id,
            execution_snapshot=source.execution_snapshot,
            config_snapshot=source.config_snapshot,
            capability_snapshot=source.capability_snapshot,
            external_session_id=state.external_session_id,
            latest_external_turn_id=state.latest_external_turn_id,
            supervisor_owner=self.owner_id,
            heartbeat_at=_utc_now(),
            forked_from_link_id=source.id,
            forked_from_external_turn_id=turn_id,
            degradation_evidence=state.degradation_evidence,
        )
        return self.store.create(link)

    def recover(self, link: StructuredSessionLink) -> StructuredSessionLink:
        """Recover an owner-lost link only when the capability is explicit."""
        self._require_current(link)
        _require_capability(
            link.capability_snapshot.recovery_after_process_loss,
            "recovery after process loss",
        )
        state = self.driver.recover(link)
        updated = replace(
            link,
            external_session_id=state.external_session_id,
            latest_external_turn_id=state.latest_external_turn_id,
            supervisor_owner=self.owner_id,
            heartbeat_at=_utc_now(),
            recovery_state=RecoveryState.RECOVERED,
            degradation_evidence=state.degradation_evidence,
        )
        return self.store.replace(updated, expected_revision=link.revision)

    def close(self, link: StructuredSessionLink) -> StructuredSessionLink:
        """Close driver resources and persist the terminal link state."""
        self._require_owner(link)
        self._require_current(link)
        self.driver.close()
        updated = replace(
            link,
            heartbeat_at=_utc_now(),
            recovery_state=RecoveryState.CLOSED,
        )
        return self.store.replace(updated, expected_revision=link.revision)

    def open_in_provider(self, link: StructuredSessionLink) -> str | None:
        """Use optional provider UI handoff without inventing a fallback."""
        self._require_current(link)
        _require_capability(
            link.capability_snapshot.provider_ui_handoff,
            "provider UI handoff",
        )
        if not isinstance(self.driver, ProviderHandoffStructuredSessionDriver):
            raise UnsupportedSessionCapability(
                "provider UI handoff is not implemented by the driver"
            )
        return self.driver.open_in_provider()

    def _require_owner(self, link: StructuredSessionLink) -> None:
        if link.supervisor_owner != self.owner_id:
            raise StructuredSessionError(
                "Structured session is owned by another supervisor"
            )

    def _require_current(self, link: StructuredSessionLink) -> None:
        current = self.store.load(link.id)
        if (
            current is None
            or current.revision != link.revision
            or current.link_hash != link.link_hash
        ):
            raise SessionLinkConflict("Structured session link revision changed")


def capability_snapshot_to_dict(snapshot: AdapterCapabilitySnapshot) -> dict[str, Any]:
    """Serialize and hash one capability snapshot."""
    return {**_capability_payload(snapshot), "snapshot_hash": snapshot.snapshot_hash}


def capability_snapshot_from_dict(data: Mapping[str, Any]) -> AdapterCapabilitySnapshot:
    """Strictly parse and verify one capability snapshot."""
    allowed = {
        "schema_version",
        "adapter_id",
        "adapter_version",
        "protocol",
        "protocol_version",
        *_CAPABILITY_BOOLEAN_FIELDS,
        "attachment_kinds",
        "attachment_transports",
        "min_link_schema_version",
        "max_link_schema_version",
        "snapshot_hash",
    }
    mapping = _strict_mapping(data, allowed=allowed, field_name="capability snapshot")
    supplied_hash = _required_hash(
        mapping.get("snapshot_hash"), field_name="capability snapshot_hash"
    )
    values = {
        name: _required_bool(mapping.get(name), field_name=name)
        for name in _CAPABILITY_BOOLEAN_FIELDS
    }
    snapshot = AdapterCapabilitySnapshot(
        adapter_id=_required_text(mapping.get("adapter_id"), field_name="adapter_id"),
        adapter_version=_required_text(
            mapping.get("adapter_version"), field_name="adapter_version"
        ),
        protocol=_required_text(mapping.get("protocol"), field_name="protocol"),
        protocol_version=_required_text(
            mapping.get("protocol_version"), field_name="protocol_version"
        ),
        attachment_kinds=_string_tuple(
            mapping.get("attachment_kinds"), field_name="attachment_kinds"
        ),
        attachment_transports=_string_tuple(
            mapping.get("attachment_transports"), field_name="attachment_transports"
        ),
        min_link_schema_version=_required_int(
            mapping.get("min_link_schema_version"), field_name="min_link_schema_version"
        ),
        max_link_schema_version=_required_int(
            mapping.get("max_link_schema_version"), field_name="max_link_schema_version"
        ),
        schema_version=_required_int(
            mapping.get("schema_version"), field_name="schema_version"
        ),
        **values,
    )
    if snapshot.snapshot_hash != supplied_hash:
        raise ValueError("capability snapshot hash mismatch")
    return snapshot


def config_snapshot_to_dict(
    snapshot: StructuredSessionConfigSnapshot,
) -> dict[str, Any]:
    """Serialize and hash one content-free driver configuration."""
    return {**_config_payload(snapshot), "snapshot_hash": snapshot.snapshot_hash}


def config_snapshot_from_dict(
    data: Mapping[str, Any],
) -> StructuredSessionConfigSnapshot:
    """Strictly parse and verify one driver configuration snapshot."""
    mapping = _strict_mapping(
        data,
        allowed={
            "schema_version",
            "adapter_id",
            "adapter_version",
            "protocol",
            "protocol_version",
            "cli_sdk_version",
            "managed_home_id",
            "snapshot_hash",
        },
        field_name="config snapshot",
    )
    supplied_hash = _required_hash(
        mapping.get("snapshot_hash"), field_name="config snapshot_hash"
    )
    snapshot = StructuredSessionConfigSnapshot(
        adapter_id=_required_text(mapping.get("adapter_id"), field_name="adapter_id"),
        adapter_version=_required_text(
            mapping.get("adapter_version"), field_name="adapter_version"
        ),
        protocol=_required_text(mapping.get("protocol"), field_name="protocol"),
        protocol_version=_required_text(
            mapping.get("protocol_version"), field_name="protocol_version"
        ),
        cli_sdk_version=_required_text(
            mapping.get("cli_sdk_version"), field_name="cli_sdk_version"
        ),
        managed_home_id=_optional_text(mapping.get("managed_home_id")),
        schema_version=_required_int(
            mapping.get("schema_version"), field_name="schema_version"
        ),
    )
    if snapshot.snapshot_hash != supplied_hash:
        raise ValueError("config snapshot hash mismatch")
    return snapshot


def structured_session_link_to_dict(link: StructuredSessionLink) -> dict[str, Any]:
    """Serialize one canonical structured-session link."""
    return {**_link_payload(link), "link_hash": link.link_hash}


def structured_session_link_from_dict(data: Mapping[str, Any]) -> StructuredSessionLink:
    """Migrate, strictly parse, and verify one structured-session link."""
    mapping = migrate_structured_session_link_payload(data)
    supplied_hash = _required_hash(mapping.get("link_hash"), field_name="link_hash")
    link = StructuredSessionLink(
        id=_required_text(mapping.get("id"), field_name="link id"),
        harness_session_id=_required_text(
            mapping.get("harness_session_id"), field_name="harness_session_id"
        ),
        harness_run_id=_required_text(
            mapping.get("harness_run_id"), field_name="harness_run_id"
        ),
        execution_snapshot=execution_snapshot_from_dict(
            _required_mapping(
                mapping.get("execution_snapshot"), field_name="execution_snapshot"
            )
        ),
        config_snapshot=config_snapshot_from_dict(
            _required_mapping(
                mapping.get("config_snapshot"), field_name="config_snapshot"
            )
        ),
        capability_snapshot=capability_snapshot_from_dict(
            _required_mapping(
                mapping.get("capability_snapshot"), field_name="capability_snapshot"
            )
        ),
        external_session_id=_required_text(
            mapping.get("external_session_id"), field_name="external_session_id"
        ),
        latest_external_turn_id=_optional_text(mapping.get("latest_external_turn_id")),
        supervisor_owner=_required_text(
            mapping.get("supervisor_owner"), field_name="supervisor_owner"
        ),
        heartbeat_at=_required_text(
            mapping.get("heartbeat_at"), field_name="heartbeat_at"
        ),
        recovery_state=_required_enum(
            mapping.get("recovery_state"), RecoveryState, field_name="recovery_state"
        ),
        forked_from_link_id=_optional_text(mapping.get("forked_from_link_id")),
        forked_from_external_turn_id=_optional_text(
            mapping.get("forked_from_external_turn_id")
        ),
        degradation_evidence=_evidence_from_list(mapping.get("degradation_evidence")),
        created_at=_required_text(mapping.get("created_at"), field_name="created_at"),
        updated_at=_required_text(mapping.get("updated_at"), field_name="updated_at"),
        revision=_required_int(mapping.get("revision"), field_name="revision"),
        schema_version=_required_int(
            mapping.get("schema_version"), field_name="schema_version"
        ),
    )
    if link.link_hash != supplied_hash:
        raise ValueError("structured session link hash mismatch")
    return link


def migrate_structured_session_link_payload(data: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate the reviewed content-free v0 link shape to canonical v1."""
    mapping = _required_mapping(data, field_name="structured session link")
    version = mapping.get("schema_version")
    if version == STRUCTURED_SESSION_LINK_SCHEMA_VERSION:
        return dict(
            _strict_mapping(
                mapping,
                allowed=_LINK_FIELDS | {"link_hash"},
                field_name="structured session link",
            )
        )
    if version != 0:
        raise ValueError("unsupported structured session link schema_version")
    legacy = _strict_mapping(
        mapping,
        allowed=(
            _LINK_FIELDS
            - {
                "recovery_state",
                "degradation_evidence",
                "forked_from_link_id",
                "forked_from_external_turn_id",
                "link_hash",
            }
        ),
        field_name="structured session link v0",
    )
    migrated = {
        **legacy,
        "schema_version": STRUCTURED_SESSION_LINK_SCHEMA_VERSION,
        "recovery_state": RecoveryState.ACTIVE.value,
        "degradation_evidence": [],
        "forked_from_link_id": None,
        "forked_from_external_turn_id": None,
    }
    # Parse nested snapshots before accepting the unhashed legacy envelope.
    execution_snapshot_from_dict(
        _required_mapping(
            migrated.get("execution_snapshot"), field_name="execution_snapshot"
        )
    )
    config_snapshot_from_dict(
        _required_mapping(migrated.get("config_snapshot"), field_name="config_snapshot")
    )
    capability_snapshot_from_dict(
        _required_mapping(
            migrated.get("capability_snapshot"), field_name="capability_snapshot"
        )
    )
    link = StructuredSessionLink(
        id=_required_text(migrated.get("id"), field_name="link id"),
        harness_session_id=_required_text(
            migrated.get("harness_session_id"), field_name="harness_session_id"
        ),
        harness_run_id=_required_text(
            migrated.get("harness_run_id"), field_name="harness_run_id"
        ),
        execution_snapshot=execution_snapshot_from_dict(migrated["execution_snapshot"]),
        config_snapshot=config_snapshot_from_dict(migrated["config_snapshot"]),
        capability_snapshot=capability_snapshot_from_dict(
            migrated["capability_snapshot"]
        ),
        external_session_id=_required_text(
            migrated.get("external_session_id"), field_name="external_session_id"
        ),
        latest_external_turn_id=_optional_text(migrated.get("latest_external_turn_id")),
        supervisor_owner=_required_text(
            migrated.get("supervisor_owner"), field_name="supervisor_owner"
        ),
        heartbeat_at=_required_text(
            migrated.get("heartbeat_at"), field_name="heartbeat_at"
        ),
        created_at=_required_text(migrated.get("created_at"), field_name="created_at"),
        updated_at=_required_text(migrated.get("updated_at"), field_name="updated_at"),
        revision=_required_int(migrated.get("revision"), field_name="revision"),
    )
    return structured_session_link_to_dict(link)


_CAPABILITY_BOOLEAN_FIELDS = (
    "structured_events",
    "partial_output",
    "interactive_input",
    "live_approvals",
    "durable_approval",
    "interrupt",
    "steer",
    "resume",
    "fork",
    "session_list",
    "session_close",
    "native_auth",
    "provider_ui_handoff",
    "dynamic_model",
    "dynamic_mcp",
    "recovery_after_process_loss",
)
_LINK_FIELDS = {
    "schema_version",
    "id",
    "harness_session_id",
    "harness_run_id",
    "execution_snapshot",
    "config_snapshot",
    "capability_snapshot",
    "external_session_id",
    "latest_external_turn_id",
    "supervisor_owner",
    "heartbeat_at",
    "recovery_state",
    "forked_from_link_id",
    "forked_from_external_turn_id",
    "degradation_evidence",
    "created_at",
    "updated_at",
    "revision",
}


def _capability_payload(snapshot: AdapterCapabilitySnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "adapter_id": snapshot.adapter_id,
        "adapter_version": snapshot.adapter_version,
        "protocol": snapshot.protocol,
        "protocol_version": snapshot.protocol_version,
        **{name: getattr(snapshot, name) for name in _CAPABILITY_BOOLEAN_FIELDS},
        "attachment_kinds": list(snapshot.attachment_kinds),
        "attachment_transports": list(snapshot.attachment_transports),
        "min_link_schema_version": snapshot.min_link_schema_version,
        "max_link_schema_version": snapshot.max_link_schema_version,
    }


def _config_payload(snapshot: StructuredSessionConfigSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "adapter_id": snapshot.adapter_id,
        "adapter_version": snapshot.adapter_version,
        "protocol": snapshot.protocol,
        "protocol_version": snapshot.protocol_version,
        "cli_sdk_version": snapshot.cli_sdk_version,
        "managed_home_id": snapshot.managed_home_id,
    }


def _link_payload(link: StructuredSessionLink) -> dict[str, Any]:
    return {
        "schema_version": link.schema_version,
        "id": link.id,
        "harness_session_id": link.harness_session_id,
        "harness_run_id": link.harness_run_id,
        "execution_snapshot": execution_snapshot_to_dict(link.execution_snapshot),
        "config_snapshot": config_snapshot_to_dict(link.config_snapshot),
        "capability_snapshot": capability_snapshot_to_dict(link.capability_snapshot),
        "external_session_id": link.external_session_id,
        "latest_external_turn_id": link.latest_external_turn_id,
        "supervisor_owner": link.supervisor_owner,
        "heartbeat_at": link.heartbeat_at,
        "recovery_state": link.recovery_state.value,
        "forked_from_link_id": link.forked_from_link_id,
        "forked_from_external_turn_id": link.forked_from_external_turn_id,
        "degradation_evidence": [
            _evidence_to_dict(item) for item in link.degradation_evidence
        ],
        "created_at": link.created_at,
        "updated_at": link.updated_at,
        "revision": link.revision,
    }


def _evidence_to_dict(item: SnapshotEvidenceRef) -> dict[str, str]:
    return {
        "id": item.id,
        "revision": item.revision,
        "status": item.status,
        "source": item.source,
    }


def _evidence_from_list(value: Any) -> tuple[SnapshotEvidenceRef, ...]:
    if not isinstance(value, list):
        raise ValueError("degradation_evidence must be a list")
    items = []
    for raw in value:
        mapping = _strict_mapping(
            raw,
            allowed={"id", "revision", "status", "source"},
            field_name="degradation evidence",
        )
        items.append(
            SnapshotEvidenceRef(
                _required_text(mapping.get("id"), field_name="evidence id"),
                _required_text(mapping.get("revision"), field_name="evidence revision"),
                _required_text(mapping.get("status"), field_name="evidence status"),
                _required_text(mapping.get("source"), field_name="evidence source"),
            )
        )
    return tuple(items)


def _normalize_evidence(
    items: tuple[SnapshotEvidenceRef, ...],
) -> tuple[SnapshotEvidenceRef, ...]:
    if not isinstance(items, tuple) or any(
        not isinstance(item, SnapshotEvidenceRef) for item in items
    ):
        raise ValueError("degradation_evidence must contain evidence references")
    normalized = tuple(sorted(items))
    identities = [(item.id, item.source) for item in normalized]
    if len(identities) != len(set(identities)):
        raise ValueError("degradation_evidence contains duplicates")
    return normalized


def _validate_driver_snapshots(
    execution: ExecutionSnapshot,
    config: StructuredSessionConfigSnapshot,
    capabilities: AdapterCapabilitySnapshot,
) -> None:
    if (
        not execution.is_executable
        or execution.transport is not ExecutionTransport.NATIVE_STRUCTURED
    ):
        raise ValueError(
            "structured driver requires executable native_structured transport"
        )
    if config.adapter_id != execution.harness_id:
        raise ValueError("structured config adapter does not match execution harness")
    if (
        config.adapter_id != capabilities.adapter_id
        or config.adapter_version != capabilities.adapter_version
    ):
        raise ValueError("structured config does not match probed adapter")
    if (
        config.protocol != capabilities.protocol
        or config.protocol_version != capabilities.protocol_version
    ):
        raise ValueError("structured config does not match probed protocol")
    if not capabilities.structured_events:
        raise UnsupportedSessionCapability("structured events are required")


def _require_capability(value: bool, name: str) -> None:
    if not value:
        raise UnsupportedSessionCapability(f"{name} is not supported")


def _normalize_identities(
    items: tuple[str, ...], *, field_name: str
) -> tuple[str, ...]:
    if not isinstance(items, tuple):
        raise ValueError(f"{field_name}s must be a tuple")
    normalized = tuple(sorted(items))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name}s contain duplicates")
    for item in normalized:
        _validate_identity(item, field_name=field_name)
    return normalized


def _validate_identity(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")


def _validate_timestamp(value: str, *, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional text value must be a string or null")
    return value.strip() or None


def _required_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _required_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_hash(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _required_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _strict_mapping(
    value: Any, *, allowed: set[str], field_name: str
) -> Mapping[str, Any]:
    mapping = _required_mapping(value, field_name=field_name)
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"unknown {field_name} fields: {', '.join(sorted(unknown))}")
    return mapping


def _string_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return tuple(value)


def _required_enum(value: Any, enum_type: type[Enum], *, field_name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
