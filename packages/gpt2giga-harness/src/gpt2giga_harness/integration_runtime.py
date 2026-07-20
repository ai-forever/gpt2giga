"""Immutable integration snapshots selected by provider-native sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any

from gpt2giga_harness.integration_installer import (
    InstallationPlan,
    TransactionalIntegrationInstaller,
)
from gpt2giga_harness.integration_packages import InstallationScope
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import utc_now


INTEGRATION_RUNTIME_SCHEMA_VERSION = 1
MAX_RUNTIME_FILES = 256
MAX_RUNTIME_FILE_BYTES = 16 * 1024 * 1024
MAX_RUNTIME_TOTAL_BYTES = 64 * 1024 * 1024
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT_RE = re.compile(r"isnap_[0-9a-f]{32}\Z")
_TRANSACTION_RE = re.compile(r"txn_[0-9a-f]{32}\Z")
_SAFE_MODES = frozenset({0o600, 0o644, 0o700, 0o755})


class IntegrationRuntimeError(RuntimeError):
    """Base error for immutable integration runtime state."""


class IntegrationRuntimeConflictError(IntegrationRuntimeError):
    """Raised when current ownership or a session binding changed."""


class IntegrationRuntimeStateError(IntegrationRuntimeError):
    """Raised when private runtime state is invalid or unsafe."""


class IntegrationRuntimeActivationError(IntegrationRuntimeError):
    """Raised when target-owned discovery or behavior proof fails."""


@dataclass(frozen=True)
class IntegrationRuntimeFile:
    """One private immutable regular file in a runtime snapshot."""

    relative_path: str
    sha256: str
    mode: int
    content: bytes


@dataclass(frozen=True)
class IntegrationRuntimeSnapshot:
    """Exact installed package bytes available to selected native sessions."""

    id: str
    snapshot_hash: str
    package_id: str
    package_version: str
    manifest_sha256: str
    target_id: str
    scope: InstallationScope
    owner_id: str
    owner_key: str
    root_identity: str
    owner_revision: str
    source_transaction_id: str
    previous_snapshot_id: str | None
    created_at: str
    files: tuple[IntegrationRuntimeFile, ...]

    def public_ref(self) -> dict[str, Any]:
        """Return a content-free integrity reference for clients and sessions."""
        return {
            "schema_version": INTEGRATION_RUNTIME_SCHEMA_VERSION,
            "snapshot_id": self.id,
            "snapshot_hash": self.snapshot_hash,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "manifest_sha256": self.manifest_sha256,
            "target_id": self.target_id,
            "scope": self.scope.value,
            "source_transaction_id": self.source_transaction_id,
            "previous_snapshot_id": self.previous_snapshot_id,
            "file_count": len(self.files),
            "created_at": self.created_at,
            "content_free": True,
        }


@dataclass(frozen=True)
class IntegrationRuntimeProbeResult:
    """Content-free target-owned discovery and behavior evidence."""

    discovered: bool
    behavior_verified: bool
    surface: str

    def __post_init__(self) -> None:
        _validate_identity(self.surface, field_name="runtime probe surface")


@dataclass(frozen=True)
class IntegrationRuntimeBinding:
    """Immutable binding between one selected session and one snapshot."""

    session_id: str
    harness_id: str
    snapshot_id: str
    snapshot_hash: str
    owner_key: str
    home: str
    forked_from_session_id: str | None
    discovery_status: str
    behavior_status: str
    probe_surface: str
    bound_at: str

    def public_projection(self) -> dict[str, Any]:
        """Return bounded session activation evidence."""
        return {
            "session_id": self.session_id,
            "harness_id": self.harness_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "forked_from_session_id": self.forked_from_session_id,
            "discovery_status": self.discovery_status,
            "behavior_status": self.behavior_status,
            "probe_surface": self.probe_surface,
            "bound_at": self.bound_at,
            "content_free": True,
        }


IntegrationRuntimeProbe = Callable[
    [Path, IntegrationRuntimeSnapshot], IntegrationRuntimeProbeResult
]


class IntegrationRuntimeStore:
    """Capture, activate, fork, and roll back immutable integration snapshots."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "integrations" / "runtime"
        self.snapshots_root = self.root / "snapshots"
        self.sessions_root = self.root / "sessions"
        self.active_path = self.root / "active.json"
        self.bindings_path = self.root / "bindings.json"
        self.lock_path = self.root / ".runtime.lock"

    def capture(
        self,
        installer: TransactionalIntegrationInstaller,
        transaction_id: str,
    ) -> IntegrationRuntimeSnapshot:
        """Freeze one exact current committed installer transaction."""
        _validate_transaction_id(transaction_id)
        installed = installer.verify(transaction_id)
        plan = installer.transaction_plan(transaction_id)
        if plan.transaction_id != transaction_id:
            raise IntegrationRuntimeStateError("runtime transaction identity changed")
        files = _capture_files(plan)
        installed_again = installer.verify(transaction_id)
        if installed_again != installed:
            raise IntegrationRuntimeConflictError(
                "installation changed while the runtime snapshot was captured"
            )
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            active = self._read_active_unlocked()
            previous_id = active.get(plan.owner_key)
            previous = (
                self._load_id_unlocked(previous_id) if previous_id is not None else None
            )
            if previous is not None:
                _assert_same_owner(previous, plan)
                if previous.source_transaction_id == transaction_id:
                    return previous
            semantic = _snapshot_semantic(
                plan,
                owner_revision=installed.owner_revision,
                previous_snapshot_id=previous_id,
                files=files,
            )
            snapshot_hash = _json_hash(semantic)
            snapshot = IntegrationRuntimeSnapshot(
                id=f"isnap_{snapshot_hash[:32]}",
                snapshot_hash=snapshot_hash,
                package_id=plan.package_id,
                package_version=plan.package_version,
                manifest_sha256=plan.manifest_sha256,
                target_id=plan.target_id,
                scope=plan.scope,
                owner_id=plan.owner_id,
                owner_key=plan.owner_key,
                root_identity=_root_identity(plan.root),
                owner_revision=installed.owner_revision,
                source_transaction_id=transaction_id,
                previous_snapshot_id=previous_id,
                created_at=utc_now(),
                files=files,
            )
            path = self._snapshot_path(snapshot.id)
            if path.exists():
                stored = self._load_id_unlocked(snapshot.id)
                if stored != snapshot:
                    raise IntegrationRuntimeStateError(
                        "runtime snapshot id collides with different state"
                    )
            else:
                _atomic_json_write(path, _snapshot_to_record(snapshot))
            active[plan.owner_key] = snapshot.id
            self._write_active_unlocked(active)
            return snapshot

    def load(self, reference: Mapping[str, Any]) -> IntegrationRuntimeSnapshot:
        """Load and integrity-check one exact public snapshot reference."""
        snapshot_id = str(reference.get("snapshot_id") or "")
        _validate_snapshot_id(snapshot_id)
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            snapshot = self._load_id_unlocked(snapshot_id)
        expected_hash = str(reference.get("snapshot_hash") or "")
        if expected_hash != snapshot.snapshot_hash:
            raise IntegrationRuntimeStateError("runtime snapshot hash does not match")
        for field_name in (
            "package_id",
            "package_version",
            "manifest_sha256",
            "target_id",
            "source_transaction_id",
        ):
            expected = reference.get(field_name)
            if expected is not None and str(expected) != str(
                getattr(snapshot, field_name)
            ):
                raise IntegrationRuntimeStateError(
                    f"runtime snapshot {field_name} does not match"
                )
        return snapshot

    def active_for(self, reference: Mapping[str, Any]) -> IntegrationRuntimeSnapshot:
        """Return the current immutable snapshot for the referenced owner."""
        snapshot = self.load(reference)
        with exclusive_file_lock(self.lock_path):
            active_id = self._read_active_unlocked().get(snapshot.owner_key)
            if active_id is None:
                raise IntegrationRuntimeStateError(
                    "runtime owner has no active snapshot"
                )
            return self._load_id_unlocked(active_id)

    def activate_session(
        self,
        *,
        session_id: str,
        harness_id: str,
        snapshot_reference: Mapping[str, Any],
        probe: IntegrationRuntimeProbe,
        forked_from_session_id: str | None = None,
    ) -> IntegrationRuntimeBinding:
        """Materialize and prove one exact snapshot for a selected native session."""
        _validate_identity(session_id, field_name="runtime session id")
        _validate_identity(harness_id, field_name="runtime harness id")
        if forked_from_session_id is not None:
            _validate_identity(
                forked_from_session_id,
                field_name="runtime source session id",
            )
        if not callable(probe):
            raise TypeError("runtime activation probe must be callable")
        snapshot = self.load(snapshot_reference)
        if _target_harness(snapshot.target_id) != harness_id:
            raise IntegrationRuntimeConflictError(
                "runtime snapshot target does not match the selected harness"
            )
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            bindings = self._read_bindings_unlocked()
            existing = bindings.get(session_id)
            if existing is not None:
                if (
                    existing.snapshot_id == snapshot.id
                    and existing.harness_id == harness_id
                    and existing.forked_from_session_id == forked_from_session_id
                ):
                    self._assert_binding_current(existing, snapshot)
                    return existing
                raise IntegrationRuntimeConflictError(
                    "selected native session already declares another snapshot"
                )
            if forked_from_session_id is not None:
                source = bindings.get(forked_from_session_id)
                if source is None:
                    raise IntegrationRuntimeConflictError(
                        "runtime fork source session is not bound"
                    )
                source_snapshot = self._load_id_unlocked(source.snapshot_id)
                if source_snapshot.owner_key != snapshot.owner_key:
                    raise IntegrationRuntimeConflictError(
                        "runtime fork cannot change integration ownership"
                    )
            home = self._session_home(session_id)
            recovered = self._recover_binding_marker(
                home,
                session_id=session_id,
                harness_id=harness_id,
                snapshot=snapshot,
                forked_from_session_id=forked_from_session_id,
            )
            if recovered is not None:
                bindings[session_id] = recovered
                self._write_bindings_unlocked(bindings)
                return recovered
            if home.exists() or home.is_symlink():
                raise IntegrationRuntimeStateError(
                    "runtime session home exists without a valid binding"
                )
            binding = self._materialize_and_probe(
                home,
                session_id=session_id,
                harness_id=harness_id,
                snapshot=snapshot,
                forked_from_session_id=forked_from_session_id,
                probe=probe,
            )
            bindings[session_id] = binding
            self._write_bindings_unlocked(bindings)
            return binding

    def fork_session(
        self,
        *,
        source_session_id: str,
        session_id: str,
        snapshot_reference: Mapping[str, Any],
        probe: IntegrationRuntimeProbe,
    ) -> IntegrationRuntimeBinding:
        """Explicitly fork a prior session onto one reviewed snapshot."""
        _validate_identity(source_session_id, field_name="runtime source session id")
        with exclusive_file_lock(self.lock_path):
            source = self._read_bindings_unlocked().get(source_session_id)
        if source is None:
            raise IntegrationRuntimeConflictError(
                "runtime fork source session is not bound"
            )
        return self.activate_session(
            session_id=session_id,
            harness_id=source.harness_id,
            snapshot_reference=snapshot_reference,
            probe=probe,
            forked_from_session_id=source_session_id,
        )

    def binding(self, session_id: str) -> IntegrationRuntimeBinding:
        """Return one exact persisted session binding."""
        _validate_identity(session_id, field_name="runtime session id")
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            binding = self._read_bindings_unlocked().get(session_id)
            if binding is None:
                raise IntegrationRuntimeStateError(
                    "runtime session binding was not found"
                )
            snapshot = self._load_id_unlocked(binding.snapshot_id)
            self._assert_binding_current(binding, snapshot)
            return binding

    def rollback(
        self,
        installer: TransactionalIntegrationInstaller,
        snapshot_reference: Mapping[str, Any],
    ) -> IntegrationRuntimeSnapshot:
        """Restore the predecessor through N4-02 and move the active pointer."""
        current = self.load(snapshot_reference)
        if current.previous_snapshot_id is None:
            raise IntegrationRuntimeConflictError(
                "runtime snapshot has no predecessor to restore"
            )
        with exclusive_file_lock(self.lock_path):
            active = self._read_active_unlocked()
            if active.get(current.owner_key) != current.id:
                raise IntegrationRuntimeConflictError(
                    "runtime snapshot is no longer active"
                )
            previous = self._load_id_unlocked(current.previous_snapshot_id)
            installer.rollback(current.source_transaction_id)
            restored = installer.verify(previous.source_transaction_id)
            plan = installer.transaction_plan(previous.source_transaction_id)
            if (
                restored.owner_revision != previous.owner_revision
                or restored.manifest_sha256 != previous.manifest_sha256
                or plan.owner_key != previous.owner_key
                or _root_identity(plan.root) != previous.root_identity
            ):
                raise IntegrationRuntimeStateError(
                    "rolled-back installation does not match the predecessor snapshot"
                )
            _assert_snapshot_files(previous, plan.root)
            active[current.owner_key] = previous.id
            self._write_active_unlocked(active)
        return previous

    def _materialize_and_probe(
        self,
        home: Path,
        *,
        session_id: str,
        harness_id: str,
        snapshot: IntegrationRuntimeSnapshot,
        forked_from_session_id: str | None,
        probe: IntegrationRuntimeProbe,
    ) -> IntegrationRuntimeBinding:
        self.sessions_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.sessions_root, 0o700)
        raw = tempfile.mkdtemp(prefix=".runtime-session-", dir=self.sessions_root)
        temporary = Path(raw)
        try:
            os.chmod(temporary, 0o700)
            _materialize_files(snapshot, temporary)
            try:
                evidence = probe(temporary, snapshot)
            except Exception as exc:
                raise IntegrationRuntimeActivationError(
                    "runtime activation probe failed; details were omitted"
                ) from exc
            if not isinstance(evidence, IntegrationRuntimeProbeResult):
                raise IntegrationRuntimeActivationError(
                    "runtime activation probe returned an invalid result"
                )
            if not evidence.discovered or not evidence.behavior_verified:
                raise IntegrationRuntimeActivationError(
                    "runtime activation did not prove discovery and behavior"
                )
            binding = IntegrationRuntimeBinding(
                session_id=session_id,
                harness_id=harness_id,
                snapshot_id=snapshot.id,
                snapshot_hash=snapshot.snapshot_hash,
                owner_key=snapshot.owner_key,
                home=str(home),
                forked_from_session_id=forked_from_session_id,
                discovery_status="verified",
                behavior_status="verified",
                probe_surface=evidence.surface,
                bound_at=utc_now(),
            )
            _atomic_json_write(
                temporary / ".gigaloom-integration-runtime.json",
                _binding_to_record(binding),
            )
            os.replace(temporary, home)
            return binding
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _recover_binding_marker(
        self,
        home: Path,
        *,
        session_id: str,
        harness_id: str,
        snapshot: IntegrationRuntimeSnapshot,
        forked_from_session_id: str | None,
    ) -> IntegrationRuntimeBinding | None:
        if not home.exists():
            return None
        if home.is_symlink() or not home.is_dir():
            raise IntegrationRuntimeStateError("runtime session home is unsafe")
        marker = home / ".gigaloom-integration-runtime.json"
        if marker.is_symlink() or not marker.is_file():
            return None
        binding = _binding_from_record(_read_json(marker, label="runtime marker"))
        if (
            binding.session_id != session_id
            or binding.harness_id != harness_id
            or binding.snapshot_id != snapshot.id
            or binding.snapshot_hash != snapshot.snapshot_hash
            or binding.forked_from_session_id != forked_from_session_id
        ):
            raise IntegrationRuntimeStateError("runtime session marker does not match")
        _assert_snapshot_files(snapshot, home)
        return binding

    def _assert_binding_current(
        self,
        binding: IntegrationRuntimeBinding,
        snapshot: IntegrationRuntimeSnapshot,
    ) -> None:
        home = Path(binding.home)
        expected_home = self._session_home(binding.session_id)
        if home != expected_home or home.is_symlink() or not home.is_dir():
            raise IntegrationRuntimeStateError("runtime session home is unsafe")
        marker = home / ".gigaloom-integration-runtime.json"
        persisted = _binding_from_record(_read_json(marker, label="runtime marker"))
        if persisted != binding or binding.snapshot_hash != snapshot.snapshot_hash:
            raise IntegrationRuntimeStateError("runtime session marker does not match")
        _assert_snapshot_files(snapshot, home)

    def _load_id_unlocked(self, snapshot_id: str) -> IntegrationRuntimeSnapshot:
        _validate_snapshot_id(snapshot_id)
        path = self._snapshot_path(snapshot_id)
        if path.is_symlink():
            raise IntegrationRuntimeStateError("runtime snapshot path is unsafe")
        record = _read_json(path, label="runtime snapshot")
        snapshot = _snapshot_from_record(record)
        if snapshot.id != snapshot_id:
            raise IntegrationRuntimeStateError("runtime snapshot id does not match")
        return snapshot

    def _read_active_unlocked(self) -> dict[str, str]:
        if not self.active_path.exists():
            return {}
        payload = _read_json(self.active_path, label="runtime active state")
        if payload.get("schema_version") != INTEGRATION_RUNTIME_SCHEMA_VERSION:
            raise IntegrationRuntimeStateError("runtime active schema is unsupported")
        owners = payload.get("owners")
        if not isinstance(owners, Mapping):
            raise IntegrationRuntimeStateError("runtime active state is invalid")
        parsed: dict[str, str] = {}
        for owner_key, snapshot_id in owners.items():
            _validate_hash(str(owner_key), field_name="runtime owner key")
            _validate_snapshot_id(str(snapshot_id))
            parsed[str(owner_key)] = str(snapshot_id)
        return parsed

    def _write_active_unlocked(self, active: Mapping[str, str]) -> None:
        _atomic_json_write(
            self.active_path,
            {
                "schema_version": INTEGRATION_RUNTIME_SCHEMA_VERSION,
                "owners": dict(sorted(active.items())),
            },
        )

    def _read_bindings_unlocked(self) -> dict[str, IntegrationRuntimeBinding]:
        if not self.bindings_path.exists():
            return {}
        payload = _read_json(self.bindings_path, label="runtime binding state")
        if payload.get("schema_version") != INTEGRATION_RUNTIME_SCHEMA_VERSION:
            raise IntegrationRuntimeStateError("runtime binding schema is unsupported")
        records = payload.get("bindings")
        if not isinstance(records, list):
            raise IntegrationRuntimeStateError("runtime binding state is invalid")
        bindings = tuple(_binding_from_record(item) for item in records)
        if len({item.session_id for item in bindings}) != len(bindings):
            raise IntegrationRuntimeStateError(
                "runtime binding state contains duplicate sessions"
            )
        if any(
            Path(item.home) != self._session_home(item.session_id) for item in bindings
        ):
            raise IntegrationRuntimeStateError(
                "runtime binding state contains an unsafe home"
            )
        return {item.session_id: item for item in bindings}

    def _write_bindings_unlocked(
        self, bindings: Mapping[str, IntegrationRuntimeBinding]
    ) -> None:
        _atomic_json_write(
            self.bindings_path,
            {
                "schema_version": INTEGRATION_RUNTIME_SCHEMA_VERSION,
                "bindings": [
                    _binding_to_record(item)
                    for item in sorted(
                        bindings.values(), key=lambda value: value.session_id
                    )
                ],
            },
        )

    def _snapshot_path(self, snapshot_id: str) -> Path:
        return self.snapshots_root / f"{snapshot_id}.json"

    def _session_home(self, session_id: str) -> Path:
        key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
        return self.sessions_root / key

    def _ensure_root(self) -> None:
        for path in (self.root, self.snapshots_root, self.sessions_root):
            if path.is_symlink():
                raise IntegrationRuntimeStateError("runtime state root is unsafe")
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)


def _capture_files(plan: InstallationPlan) -> tuple[IntegrationRuntimeFile, ...]:
    if not plan.mutations or len(plan.mutations) > MAX_RUNTIME_FILES:
        raise IntegrationRuntimeStateError("runtime snapshot file count is invalid")
    captured: list[IntegrationRuntimeFile] = []
    total = 0
    for mutation in plan.mutations:
        relative_path = _normalize_relative_path(mutation.relative_path)
        path = _runtime_path(plan.root, relative_path)
        if path.is_symlink() or not path.is_file():
            raise IntegrationRuntimeStateError("runtime source file is unsafe")
        mode = stat.S_IMODE(path.stat().st_mode)
        content = path.read_bytes()
        total += len(content)
        if len(content) > MAX_RUNTIME_FILE_BYTES or total > MAX_RUNTIME_TOTAL_BYTES:
            raise IntegrationRuntimeStateError("runtime snapshot payload is too large")
        digest = hashlib.sha256(content).hexdigest()
        if digest != mutation.desired_sha256 or mode != mutation.mode:
            raise IntegrationRuntimeConflictError(
                "installed file changed before runtime snapshot capture"
            )
        captured.append(
            IntegrationRuntimeFile(
                relative_path=relative_path,
                sha256=digest,
                mode=mode,
                content=content,
            )
        )
    return tuple(captured)


def _snapshot_semantic(
    plan: InstallationPlan,
    *,
    owner_revision: str,
    previous_snapshot_id: str | None,
    files: tuple[IntegrationRuntimeFile, ...],
) -> dict[str, Any]:
    return {
        "schema_version": INTEGRATION_RUNTIME_SCHEMA_VERSION,
        "package_id": plan.package_id,
        "package_version": plan.package_version,
        "manifest_sha256": plan.manifest_sha256,
        "target_id": plan.target_id,
        "scope": plan.scope.value,
        "owner_id": plan.owner_id,
        "owner_key": plan.owner_key,
        "root_identity": _root_identity(plan.root),
        "owner_revision": owner_revision,
        "source_transaction_id": plan.transaction_id,
        "previous_snapshot_id": previous_snapshot_id,
        "files": [_file_to_record(item) for item in files],
    }


def _snapshot_to_record(snapshot: IntegrationRuntimeSnapshot) -> dict[str, Any]:
    semantic = {
        "schema_version": INTEGRATION_RUNTIME_SCHEMA_VERSION,
        "package_id": snapshot.package_id,
        "package_version": snapshot.package_version,
        "manifest_sha256": snapshot.manifest_sha256,
        "target_id": snapshot.target_id,
        "scope": snapshot.scope.value,
        "owner_id": snapshot.owner_id,
        "owner_key": snapshot.owner_key,
        "root_identity": snapshot.root_identity,
        "owner_revision": snapshot.owner_revision,
        "source_transaction_id": snapshot.source_transaction_id,
        "previous_snapshot_id": snapshot.previous_snapshot_id,
        "files": [_file_to_record(item) for item in snapshot.files],
    }
    return {
        **semantic,
        "snapshot_id": snapshot.id,
        "snapshot_hash": snapshot.snapshot_hash,
        "created_at": snapshot.created_at,
    }


def _snapshot_from_record(payload: Mapping[str, Any]) -> IntegrationRuntimeSnapshot:
    try:
        if payload.get("schema_version") != INTEGRATION_RUNTIME_SCHEMA_VERSION:
            raise IntegrationRuntimeStateError("runtime snapshot schema is unsupported")
        files_raw = payload.get("files")
        if not isinstance(files_raw, list):
            raise IntegrationRuntimeStateError("runtime snapshot files are invalid")
        files = tuple(_file_from_record(item) for item in files_raw)
        if not files or len(files) > MAX_RUNTIME_FILES:
            raise IntegrationRuntimeStateError("runtime snapshot file count is invalid")
        if sum(len(item.content) for item in files) > MAX_RUNTIME_TOTAL_BYTES:
            raise IntegrationRuntimeStateError("runtime snapshot payload is too large")
        if len({item.relative_path for item in files}) != len(files):
            raise IntegrationRuntimeStateError(
                "runtime snapshot contains duplicate paths"
            )
        _reject_path_collisions(item.relative_path for item in files)
        snapshot = IntegrationRuntimeSnapshot(
            id=str(payload["snapshot_id"]),
            snapshot_hash=str(payload["snapshot_hash"]),
            package_id=str(payload["package_id"]),
            package_version=str(payload["package_version"]),
            manifest_sha256=str(payload["manifest_sha256"]),
            target_id=str(payload["target_id"]),
            scope=InstallationScope(str(payload["scope"])),
            owner_id=str(payload["owner_id"]),
            owner_key=str(payload["owner_key"]),
            root_identity=str(payload["root_identity"]),
            owner_revision=str(payload["owner_revision"]),
            source_transaction_id=str(payload["source_transaction_id"]),
            previous_snapshot_id=(
                str(payload["previous_snapshot_id"])
                if payload.get("previous_snapshot_id") is not None
                else None
            ),
            created_at=str(payload["created_at"]),
            files=files,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrationRuntimeStateError("runtime snapshot is invalid") from exc
    _validate_snapshot(snapshot)
    semantic = dict(payload)
    for key in ("snapshot_id", "snapshot_hash", "created_at"):
        semantic.pop(key, None)
    expected_hash = _json_hash(semantic)
    if snapshot.snapshot_hash != expected_hash:
        raise IntegrationRuntimeStateError("runtime snapshot integrity check failed")
    if snapshot.id != f"isnap_{expected_hash[:32]}":
        raise IntegrationRuntimeStateError("runtime snapshot id does not match content")
    return snapshot


def _validate_snapshot(snapshot: IntegrationRuntimeSnapshot) -> None:
    _validate_snapshot_id(snapshot.id)
    _validate_hash(snapshot.snapshot_hash, field_name="runtime snapshot hash")
    _validate_hash(snapshot.manifest_sha256, field_name="runtime manifest hash")
    _validate_hash(snapshot.owner_key, field_name="runtime owner key")
    _validate_hash(snapshot.root_identity, field_name="runtime root identity")
    _validate_hash(snapshot.owner_revision, field_name="runtime owner revision")
    _validate_transaction_id(snapshot.source_transaction_id)
    for field_name in ("package_id", "package_version", "target_id", "owner_id"):
        _validate_identity(getattr(snapshot, field_name), field_name=field_name)
    if snapshot.previous_snapshot_id is not None:
        _validate_snapshot_id(snapshot.previous_snapshot_id)
    if not snapshot.created_at:
        raise IntegrationRuntimeStateError("runtime snapshot timestamp is invalid")


def _file_to_record(file: IntegrationRuntimeFile) -> dict[str, Any]:
    return {
        "relative_path": file.relative_path,
        "sha256": file.sha256,
        "mode": file.mode,
        "content_base64": base64.b64encode(file.content).decode("ascii"),
    }


def _file_from_record(payload: object) -> IntegrationRuntimeFile:
    if not isinstance(payload, Mapping):
        raise IntegrationRuntimeStateError("runtime snapshot file is invalid")
    try:
        relative_path = _normalize_relative_path(str(payload["relative_path"]))
        digest = str(payload["sha256"])
        mode = int(payload["mode"])
        content = base64.b64decode(str(payload["content_base64"]), validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrationRuntimeStateError("runtime snapshot file is invalid") from exc
    _validate_hash(digest, field_name="runtime file hash")
    if mode not in _SAFE_MODES or len(content) > MAX_RUNTIME_FILE_BYTES:
        raise IntegrationRuntimeStateError("runtime snapshot file is invalid")
    if hashlib.sha256(content).hexdigest() != digest:
        raise IntegrationRuntimeStateError("runtime snapshot file integrity failed")
    return IntegrationRuntimeFile(relative_path, digest, mode, content)


def _materialize_files(snapshot: IntegrationRuntimeSnapshot, root: Path) -> None:
    for file in snapshot.files:
        path = _runtime_path(root, file.relative_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        if path.exists() or path.is_symlink():
            raise IntegrationRuntimeStateError("runtime target file already exists")
        with path.open("xb") as handle:
            handle.write(file.content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, file.mode)
    _assert_snapshot_files(snapshot, root)


def _assert_snapshot_files(snapshot: IntegrationRuntimeSnapshot, root: Path) -> None:
    for file in snapshot.files:
        path = _runtime_path(root, file.relative_path)
        if path.is_symlink() or not path.is_file():
            raise IntegrationRuntimeStateError("runtime snapshot file is missing")
        content = path.read_bytes()
        mode = stat.S_IMODE(path.stat().st_mode)
        if hashlib.sha256(content).hexdigest() != file.sha256 or mode != file.mode:
            raise IntegrationRuntimeStateError("runtime snapshot file changed")


def _binding_to_record(binding: IntegrationRuntimeBinding) -> dict[str, Any]:
    return asdict(binding)


def _binding_from_record(payload: object) -> IntegrationRuntimeBinding:
    if not isinstance(payload, Mapping):
        raise IntegrationRuntimeStateError("runtime binding is invalid")
    try:
        binding = IntegrationRuntimeBinding(
            session_id=str(payload["session_id"]),
            harness_id=str(payload["harness_id"]),
            snapshot_id=str(payload["snapshot_id"]),
            snapshot_hash=str(payload["snapshot_hash"]),
            owner_key=str(payload["owner_key"]),
            home=str(payload["home"]),
            forked_from_session_id=(
                str(payload["forked_from_session_id"])
                if payload.get("forked_from_session_id") is not None
                else None
            ),
            discovery_status=str(payload["discovery_status"]),
            behavior_status=str(payload["behavior_status"]),
            probe_surface=str(payload["probe_surface"]),
            bound_at=str(payload["bound_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrationRuntimeStateError("runtime binding is invalid") from exc
    for field_name in ("session_id", "harness_id", "probe_surface"):
        _validate_identity(getattr(binding, field_name), field_name=field_name)
    _validate_snapshot_id(binding.snapshot_id)
    _validate_hash(binding.snapshot_hash, field_name="runtime binding hash")
    _validate_hash(binding.owner_key, field_name="runtime binding owner")
    if binding.forked_from_session_id is not None:
        _validate_identity(
            binding.forked_from_session_id,
            field_name="runtime source session id",
        )
    if binding.discovery_status != "verified" or binding.behavior_status != "verified":
        raise IntegrationRuntimeStateError("runtime binding evidence is invalid")
    if not Path(binding.home).is_absolute() or not binding.bound_at:
        raise IntegrationRuntimeStateError("runtime binding location is invalid")
    return binding


def _assert_same_owner(
    snapshot: IntegrationRuntimeSnapshot, plan: InstallationPlan
) -> None:
    if (
        snapshot.owner_key != plan.owner_key
        or snapshot.target_id != plan.target_id
        or snapshot.scope is not plan.scope
        or snapshot.owner_id != plan.owner_id
        or snapshot.root_identity != _root_identity(plan.root)
    ):
        raise IntegrationRuntimeConflictError(
            "runtime update does not match the active integration owner"
        )


def _target_harness(target_id: str) -> str:
    if target_id.startswith("codex-"):
        return "codex-cli"
    if target_id.startswith("claude-"):
        return "claude-code"
    if target_id.startswith("gemini-"):
        return "gemini-cli"
    raise IntegrationRuntimeConflictError(
        "runtime target has no provider-native session mapping"
    )


def _root_identity(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()


def _normalize_relative_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise IntegrationRuntimeStateError("runtime relative path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise IntegrationRuntimeStateError("runtime relative path is invalid")
    normalized = path.as_posix()
    if len(normalized) > 1024:
        raise IntegrationRuntimeStateError("runtime relative path is too long")
    return normalized


def _runtime_path(root: Path, relative_path: str) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise IntegrationRuntimeStateError("runtime file root is unsafe")
    path = root
    for part in PurePosixPath(relative_path).parts:
        path = path / part
        if path.is_symlink():
            raise IntegrationRuntimeStateError("runtime file path is unsafe")
    return path


def _reject_path_collisions(paths: Iterable[str]) -> None:
    normalized = sorted(str(item) for item in paths)
    for index, path in enumerate(normalized[:-1]):
        if normalized[index + 1].startswith(f"{path}/"):
            raise IntegrationRuntimeStateError(
                "runtime snapshot paths contain a file-directory collision"
            )


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise IntegrationRuntimeStateError(f"{label} path is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IntegrationRuntimeStateError(f"{label} was not found") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationRuntimeStateError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise IntegrationRuntimeStateError(f"{label} is invalid")
    return payload


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        raise IntegrationRuntimeStateError("runtime state path is unsafe")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_identity(value: str, *, field_name: str) -> None:
    if not _IDENTITY_RE.fullmatch(value):
        raise IntegrationRuntimeStateError(f"{field_name} is invalid")


def _validate_hash(value: str, *, field_name: str) -> None:
    if not _HASH_RE.fullmatch(value):
        raise IntegrationRuntimeStateError(f"{field_name} is invalid")


def _validate_snapshot_id(value: str) -> None:
    if not _SNAPSHOT_RE.fullmatch(value):
        raise IntegrationRuntimeStateError("runtime snapshot id is invalid")


def _validate_transaction_id(value: str) -> None:
    if not _TRANSACTION_RE.fullmatch(value):
        raise IntegrationRuntimeStateError("runtime transaction id is invalid")


__all__ = [
    "INTEGRATION_RUNTIME_SCHEMA_VERSION",
    "IntegrationRuntimeActivationError",
    "IntegrationRuntimeBinding",
    "IntegrationRuntimeConflictError",
    "IntegrationRuntimeError",
    "IntegrationRuntimeFile",
    "IntegrationRuntimeProbe",
    "IntegrationRuntimeProbeResult",
    "IntegrationRuntimeSnapshot",
    "IntegrationRuntimeStateError",
    "IntegrationRuntimeStore",
]
