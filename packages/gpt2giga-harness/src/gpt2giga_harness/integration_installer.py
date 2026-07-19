"""Transactional, target-scoped integration installation ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any

from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationPackage,
    IntegrationTrustDecision,
    assess_integration_package,
    integration_package_semantic_hash,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import utc_now


INSTALLATION_STATE_SCHEMA_VERSION = 1
MAX_INSTALL_MUTATIONS = 256
MAX_INSTALL_FILE_BYTES = 16 * 1024 * 1024
MAX_INSTALL_TOTAL_BYTES = 64 * 1024 * 1024
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_TRANSACTION_RE = re.compile(r"txn_[0-9a-f]{32}\Z")
_PLAN_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_SAFE_MODES = frozenset({0o600, 0o644, 0o700, 0o755})
_JOURNAL_STATUSES = frozenset(
    {"prepared", "applying", "verifying", "committed", "rolling_back", "rolled_back"}
)


class InstallationError(RuntimeError):
    """Base error for transactional integration installation."""


class InstallationScopeError(InstallationError):
    """Raised when a requested mutation root is outside its admitted scope."""


class InstallationConflictError(InstallationError):
    """Raised for stale previews, active targets, drift, or ownership conflicts."""


class InstallationVerificationError(InstallationError):
    """Raised when the target-specific verifier rejects the installed snapshot."""


class InstallationStateError(InstallationError):
    """Raised when durable installer state is corrupt, unsafe, or unsupported."""


@dataclass(frozen=True)
class FileInstallMutation:
    """One desired regular file, retained only in the caller request."""

    relative_path: str
    content: bytes
    mode: int = 0o600

    def __post_init__(self) -> None:
        normalized = _normalize_relative_path(self.relative_path)
        if not isinstance(self.content, bytes):
            raise TypeError("installation file content must be bytes")
        if len(self.content) > MAX_INSTALL_FILE_BYTES:
            raise ValueError("installation file content is too large")
        if self.mode not in _SAFE_MODES:
            raise ValueError("installation file mode is not allowed")
        object.__setattr__(self, "relative_path", normalized)


@dataclass(frozen=True)
class InstallationTarget:
    """One explicit target root and mutation ownership scope."""

    id: str
    scope: InstallationScope
    root: Path
    owner_id: str

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="installation target id")
        _validate_identity(self.owner_id, field_name="installation owner id")
        if not isinstance(self.scope, InstallationScope):
            raise ValueError("installation target scope is invalid")
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root))


@dataclass(frozen=True)
class InstallationRequest:
    """Frozen package plus target-specific desired files."""

    package: IntegrationPackage
    target: InstallationTarget
    mutations: tuple[FileInstallMutation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.package, IntegrationPackage):
            raise TypeError("installation request requires an IntegrationPackage")
        if not isinstance(self.target, InstallationTarget):
            raise TypeError("installation request target is invalid")
        mutations = tuple(sorted(self.mutations, key=lambda item: item.relative_path))
        if not mutations or len(mutations) > MAX_INSTALL_MUTATIONS:
            raise ValueError("installation request mutation count is invalid")
        if any(not isinstance(item, FileInstallMutation) for item in mutations):
            raise TypeError("installation request mutation is invalid")
        paths = [item.relative_path for item in mutations]
        if len(paths) != len(set(paths)):
            raise ValueError("installation request contains duplicate paths")
        if sum(len(item.content) for item in mutations) > MAX_INSTALL_TOTAL_BYTES:
            raise ValueError("installation request payload is too large")
        object.__setattr__(self, "mutations", mutations)


@dataclass(frozen=True)
class InstallationApproval:
    """Explicit authorization bound to one exact content-free preview."""

    plan_id: str
    authority: str
    allow_user_home: bool = False

    def __post_init__(self) -> None:
        if not _PLAN_RE.fullmatch(self.plan_id):
            raise ValueError("installation approval plan_id is invalid")
        _validate_identity(self.authority, field_name="installation approval authority")
        if not isinstance(self.allow_user_home, bool):
            raise ValueError("installation user-home approval must be a boolean")


@dataclass(frozen=True, order=True)
class InstallationFilePlan:
    """Content-free current and desired hashes for one file mutation."""

    relative_path: str
    current_sha256: str | None
    current_mode: int | None
    desired_sha256: str
    mode: int
    changed: bool


@dataclass(frozen=True)
class InstallationPlan:
    """Deterministic content-free preview bound to current target state."""

    plan_id: str
    transaction_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    target_id: str
    scope: InstallationScope
    owner_id: str
    owner_key: str
    root: Path
    expected_owner_revision: str | None
    mutations: tuple[InstallationFilePlan, ...]
    changed: bool


@dataclass(frozen=True)
class InstallationResult:
    """Content-free terminal transaction evidence."""

    transaction_id: str
    plan_id: str
    status: str
    package_id: str
    package_version: str
    target_id: str
    scope: InstallationScope
    owner_revision: str | None
    updated_at: str


@dataclass(frozen=True)
class InstalledIntegration:
    """Discovered durable ownership and exact-current readiness."""

    transaction_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    target_id: str
    scope: InstallationScope
    owner_id: str
    owner_revision: str
    relative_paths: tuple[str, ...]
    installed_at: str
    current: bool


@dataclass(frozen=True)
class InstallationRecoveryResult:
    """Content-free outcome for one reconciled interrupted transaction."""

    transaction_id: str
    outcome: str


InstallationVerifier = Callable[[Path, InstallationPlan], bool]
FaultInjector = Callable[[str, str], None]


class TransactionalIntegrationInstaller:
    """Own private journals and reversible file mutations for target drivers."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        project_roots: Sequence[str | Path] = (),
        user_home_root: str | Path | None = None,
        allow_user_home: bool = False,
        target_active: Callable[[Path], bool] | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.data_dir = _absolute_path(Path(data_dir))
        self.installations_root = self.data_dir / "integrations" / "installations"
        self.transactions_root = self.installations_root / "transactions"
        self.owners_root = self.installations_root / "owners"
        self.locks_root = self.installations_root / "locks"
        self.project_roots = tuple(
            sorted({_absolute_path(Path(item)) for item in project_roots}, key=str)
        )
        self.user_home_root = (
            _absolute_path(Path(user_home_root)) if user_home_root is not None else None
        )
        self.allow_user_home = allow_user_home
        self.target_active = target_active or (lambda _root: False)
        self.fault_injector = fault_injector or (lambda _phase, _transaction_id: None)

    def preview(self, request: InstallationRequest) -> InstallationPlan:
        """Build a deterministic content-free plan without changing the target."""
        root = self._validate_request_scope(request)
        self._ensure_state_root()
        owner_key = _owner_key(request.target, root)
        owner = self._read_owner(owner_key)
        mutations = tuple(
            self._preview_mutation(root, mutation) for mutation in request.mutations
        )
        manifest_hash = integration_package_semantic_hash(request.package)
        semantic = _plan_semantic(
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=manifest_hash,
            target_id=request.target.id,
            scope=request.target.scope,
            owner_id=request.target.owner_id,
            owner_key=owner_key,
            root=root,
            expected_owner_revision=(str(owner["revision"]) if owner else None),
            mutations=mutations,
        )
        plan_hash = _json_hash(semantic)
        return InstallationPlan(
            plan_id=f"plan_{plan_hash}",
            transaction_id=f"txn_{plan_hash[:32]}",
            package_id=request.package.id,
            package_version=request.package.version,
            manifest_sha256=manifest_hash,
            target_id=request.target.id,
            scope=request.target.scope,
            owner_id=request.target.owner_id,
            owner_key=owner_key,
            root=root,
            expected_owner_revision=(str(owner["revision"]) if owner else None),
            mutations=mutations,
            changed=any(item.changed for item in mutations),
        )

    def apply(
        self,
        request: InstallationRequest,
        plan: InstallationPlan,
        approval: InstallationApproval,
        *,
        verifier: InstallationVerifier,
    ) -> InstallationResult:
        """Apply one exact approved plan, or return its prior committed result."""
        if not callable(verifier):
            raise TypeError("installation verifier must be callable")
        self._validate_plan_request(request, plan)
        if approval.plan_id != plan.plan_id:
            raise InstallationConflictError(
                "installation approval does not match the current preview"
            )
        if plan.scope is InstallationScope.USER_HOME and not approval.allow_user_home:
            raise InstallationScopeError(
                "user-home installation requires explicit approval"
            )
        self._ensure_state_root()
        with exclusive_file_lock(self._lock_path(plan.owner_key)):
            existing_journal = self._load_journal_if_present(plan.transaction_id)
            if existing_journal is not None:
                self._assert_journal_matches_plan(existing_journal, plan)
                if existing_journal["status"] == "committed":
                    installed = self._installed_from_journal(existing_journal)
                    if not installed.current:
                        raise InstallationConflictError(
                            "installed target changed outside the installer"
                        )
                    return self._result_from_journal(existing_journal)
                raise InstallationConflictError(
                    "installation transaction is no longer applicable"
                )
            current_owner = self._read_owner(plan.owner_key)
            current_revision = str(current_owner["revision"]) if current_owner else None
            if current_revision != plan.expected_owner_revision:
                raise InstallationConflictError(
                    "installation ownership changed after preview"
                )
            if current_owner is not None:
                installed = self._installed_from_owner(current_owner)
                if installed.current and self._owner_matches_plan(current_owner, plan):
                    return self._result_from_owner(current_owner)
                raise InstallationConflictError(
                    "existing installation requires an explicit update transaction"
                )
            if self.target_active(plan.root):
                raise InstallationConflictError(
                    "installation target is active; stop its native process first"
                )
            self._assert_preview_current(plan)
            journal = self._prepare_transaction(request, plan, approval)
            try:
                journal = self._apply_staged(journal)
                journal = self._set_journal_status(journal, "verifying")
                if not verifier(plan.root, plan):
                    raise InstallationVerificationError(
                        "installation verification failed"
                    )
                owner = self._publish_owner(journal)
                journal["owner_revision"] = owner["revision"]
                journal = self._set_journal_status(journal, "committed")
            except Exception as exc:
                journal["failure"] = _bounded_failure(exc)
                self._write_journal(journal)
                self._rollback_from_journal(journal)
                raise
            return self._result_from_journal(journal)

    def discover(self) -> tuple[InstalledIntegration, ...]:
        """Discover all private ownership records and report exact hash drift."""
        self._ensure_state_root()
        owners = [
            self._load_owner_path(path)
            for path in sorted(self.owners_root.glob("*.json"))
        ]
        return tuple(self._installed_from_owner(owner) for owner in owners)

    def verify(self, transaction_id: str) -> InstalledIntegration:
        """Verify that one committed transaction still owns its exact files."""
        journal = self._load_journal(transaction_id)
        if journal["status"] != "committed":
            raise InstallationStateError("installation transaction is not committed")
        owner = self._read_owner(str(journal["owner_key"]))
        if owner is None or owner.get("transaction_id") != transaction_id:
            raise InstallationStateError("installation ownership record is missing")
        return self._installed_from_owner(owner)

    def rollback(self, transaction_id: str) -> InstallationResult:
        """Restore one committed transaction after exact ownership checks."""
        journal = self._load_journal(transaction_id)
        if journal["status"] == "rolled_back":
            return self._result_from_journal(journal)
        if journal["status"] != "committed":
            raise InstallationStateError("installation transaction cannot roll back")
        root = self._validate_journal_scope(journal)
        with exclusive_file_lock(self._lock_path(str(journal["owner_key"]))):
            if self.target_active(root):
                raise InstallationConflictError(
                    "installation target is active; stop its native process first"
                )
            owner = self._read_owner(str(journal["owner_key"]))
            if owner is None or owner.get("transaction_id") != transaction_id:
                raise InstallationConflictError(
                    "installation ownership changed outside the installer"
                )
            if not self._installed_from_owner(owner).current:
                raise InstallationConflictError(
                    "installed target changed outside the installer"
                )
            journal["failure"] = None
            return self._result_from_journal(self._rollback_from_journal(journal))

    def recover(
        self,
        verifiers: Mapping[str, InstallationVerifier] | None = None,
    ) -> tuple[InstallationRecoveryResult, ...]:
        """Reconcile every interrupted transaction without guessing authority."""
        self._ensure_state_root()
        verifier_map = dict(verifiers or {})
        journals = []
        for transaction_dir in sorted(self.transactions_root.glob("txn_*")):
            if transaction_dir.is_symlink() or not transaction_dir.is_dir():
                raise InstallationStateError("installation transaction path is unsafe")
            journal = self._load_journal(transaction_dir.name)
            if journal["status"] not in {"committed", "rolled_back"}:
                self._validate_journal_scope(journal)
                journals.append(journal)
        outcomes: list[InstallationRecoveryResult] = []
        for journal in journals:
            owner_key = str(journal["owner_key"])
            with exclusive_file_lock(self._lock_path(owner_key)):
                if journal["status"] == "rolling_back":
                    self._rollback_from_journal(journal)
                    outcome = "rolled_back"
                else:
                    verifier = verifier_map.get(str(journal["target_id"]))
                    if verifier is None:
                        self._assert_recoverable_files(journal)
                        self._rollback_from_journal(journal)
                        outcome = "restored"
                    else:
                        self._assert_recoverable_files(journal)
                        try:
                            journal = self._apply_staged(journal)
                            journal = self._set_journal_status(journal, "verifying")
                            plan = self._plan_from_journal(journal)
                            if not verifier(plan.root, plan):
                                raise InstallationVerificationError(
                                    "installation verification failed during recovery"
                                )
                            owner = self._publish_owner(journal)
                            journal["owner_revision"] = owner["revision"]
                            self._set_journal_status(journal, "committed")
                            outcome = "completed"
                        except Exception as exc:
                            journal["failure"] = _bounded_failure(exc)
                            self._write_journal(journal)
                            self._rollback_from_journal(journal)
                            outcome = "restored"
                outcomes.append(
                    InstallationRecoveryResult(
                        transaction_id=str(journal["transaction_id"]),
                        outcome=outcome,
                    )
                )
        return tuple(outcomes)

    def journal_path(self, transaction_id: str) -> Path:
        """Return the validated private journal path for diagnostics/tests."""
        _validate_transaction_id(transaction_id)
        return self.transactions_root / transaction_id / "journal.json"

    def _validate_request_scope(self, request: InstallationRequest) -> Path:
        if request.target.scope not in request.package.scopes:
            raise InstallationScopeError("package does not support requested scope")
        if not any(
            item.target_id == request.target.id
            for item in request.package.compatibility
        ):
            raise InstallationScopeError("package does not support requested target")
        if assess_integration_package(request.package).decision in {
            IntegrationTrustDecision.BLOCKED,
            IntegrationTrustDecision.PROVIDER_HANDOFF,
        }:
            raise InstallationScopeError(
                "package trust policy does not permit local installation"
            )
        return self._validate_scope_root(request.target.scope, request.target.root)

    def _validate_scope_root(self, scope: InstallationScope, raw_root: Path) -> Path:
        root = _absolute_path(raw_root)
        if scope is InstallationScope.MANAGED_HOME:
            admitted = self.data_dir / "native"
            if root == admitted or not _is_relative_to(root, admitted):
                raise InstallationScopeError(
                    "managed-home target must be inside Harness native state"
                )
            _assert_no_symlink_chain(root, admitted)
            return root
        if scope is InstallationScope.PROJECT:
            admitted = next(
                (
                    candidate
                    for candidate in self.project_roots
                    if root == candidate or _is_relative_to(root, candidate)
                ),
                None,
            )
            if admitted is None:
                raise InstallationScopeError(
                    "project target must be inside an explicitly admitted project root"
                )
            _assert_no_symlink_chain(root, admitted)
            return root
        if not self.allow_user_home or self.user_home_root is None:
            raise InstallationScopeError(
                "user-home installation is disabled by default"
            )
        if root != self.user_home_root:
            raise InstallationScopeError(
                "user-home target must match the explicitly configured root"
            )
        _assert_no_symlink_chain(root, root)
        return root

    def _validate_journal_scope(self, journal: Mapping[str, Any]) -> Path:
        try:
            scope = InstallationScope(str(journal["scope"]))
            root = Path(str(journal["root"]))
        except (KeyError, ValueError) as exc:
            raise InstallationStateError(
                "installation journal scope is invalid"
            ) from exc
        return self._validate_scope_root(scope, root)

    def _validate_plan_request(
        self, request: InstallationRequest, plan: InstallationPlan
    ) -> None:
        root = self._validate_request_scope(request)
        if root != plan.root:
            raise InstallationConflictError(
                "installation plan root does not match request"
            )
        manifest_hash = integration_package_semantic_hash(request.package)
        desired = {
            item.relative_path: (_bytes_hash(item.content), item.mode)
            for item in request.mutations
        }
        planned = {
            item.relative_path: (item.desired_sha256, item.mode)
            for item in plan.mutations
        }
        expected = (
            request.package.id,
            request.package.version,
            manifest_hash,
            request.target.id,
            request.target.scope,
            request.target.owner_id,
            _owner_key(request.target, root),
            desired,
        )
        actual = (
            plan.package_id,
            plan.package_version,
            plan.manifest_sha256,
            plan.target_id,
            plan.scope,
            plan.owner_id,
            plan.owner_key,
            planned,
        )
        if actual != expected:
            raise InstallationConflictError("installation plan does not match request")

    def _preview_mutation(
        self, root: Path, mutation: FileInstallMutation
    ) -> InstallationFilePlan:
        path = _target_path(root, mutation.relative_path)
        current = _read_regular_file(path)
        current_hash = _bytes_hash(current) if current is not None else None
        current_mode = stat_mode(path) if current is not None else None
        desired_hash = _bytes_hash(mutation.content)
        return InstallationFilePlan(
            relative_path=mutation.relative_path,
            current_sha256=current_hash,
            current_mode=current_mode,
            desired_sha256=desired_hash,
            mode=mutation.mode,
            changed=current_hash != desired_hash or current_mode != mutation.mode,
        )

    def _assert_preview_current(self, plan: InstallationPlan) -> None:
        for mutation in plan.mutations:
            path = _target_path(plan.root, mutation.relative_path)
            current = _read_regular_file(path)
            current_hash = _bytes_hash(current) if current is not None else None
            current_mode = stat_mode(path) if current is not None else None
            if (
                current_hash != mutation.current_sha256
                or current_mode != mutation.current_mode
            ):
                raise InstallationConflictError(
                    "installation target changed after preview; refresh the plan"
                )

    def _prepare_transaction(
        self,
        request: InstallationRequest,
        plan: InstallationPlan,
        approval: InstallationApproval,
    ) -> dict[str, Any]:
        transaction_dir = self.transactions_root / plan.transaction_id
        if transaction_dir.exists() or transaction_dir.is_symlink():
            raise InstallationStateError("installation transaction path already exists")
        transaction_dir.mkdir(mode=0o700)
        os.chmod(transaction_dir, 0o700)
        stage_dir = transaction_dir / "stage"
        backup_dir = transaction_dir / "backups"
        stage_dir.mkdir(mode=0o700)
        backup_dir.mkdir(mode=0o700)
        records = []
        by_path = {item.relative_path: item for item in request.mutations}
        for index, mutation_plan in enumerate(plan.mutations):
            mutation = by_path[mutation_plan.relative_path]
            stage_name = f"{index:04d}.payload"
            backup_name = f"{index:04d}.backup"
            _atomic_write_private_bytes(stage_dir / stage_name, mutation.content)
            target = _target_path(plan.root, mutation.relative_path)
            current = _read_regular_file(target)
            existed = current is not None
            if current is not None:
                _atomic_write_private_bytes(backup_dir / backup_name, current)
            records.append(
                {
                    **_file_plan_to_dict(mutation_plan),
                    "stage_file": stage_name,
                    "backup_file": backup_name if existed else None,
                    "existed": existed,
                }
            )
        now = utc_now()
        journal = {
            "schema_version": INSTALLATION_STATE_SCHEMA_VERSION,
            "transaction_id": plan.transaction_id,
            "plan_id": plan.plan_id,
            "status": "prepared",
            "package_id": plan.package_id,
            "package_version": plan.package_version,
            "manifest_sha256": plan.manifest_sha256,
            "target_id": plan.target_id,
            "scope": plan.scope.value,
            "owner_id": plan.owner_id,
            "owner_key": plan.owner_key,
            "root": str(plan.root),
            "expected_owner_revision": plan.expected_owner_revision,
            "approval_authority": approval.authority,
            "allow_user_home": approval.allow_user_home,
            "mutations": records,
            "applied_count": 0,
            "rollback_count": 0,
            "owner_revision": None,
            "failure": None,
            "created_at": now,
            "updated_at": now,
        }
        self._write_journal(journal)
        return journal

    def _apply_staged(self, journal: dict[str, Any]) -> dict[str, Any]:
        journal = self._set_journal_status(journal, "applying")
        root = self._validate_journal_scope(journal)
        transaction_dir = self.transactions_root / str(journal["transaction_id"])
        for index, record in enumerate(journal["mutations"]):
            stage = transaction_dir / "stage" / str(record["stage_file"])
            content = _read_private_payload(stage, str(record["desired_sha256"]))
            target = _target_path(
                root, str(record["relative_path"]), create_parents=True
            )
            _atomic_write_target(target, content, int(record["mode"]))
            journal["applied_count"] = index + 1
            journal["updated_at"] = utc_now()
            self._write_journal(journal)
            self.fault_injector(f"apply:{index + 1}", str(journal["transaction_id"]))
        return journal

    def _rollback_from_journal(self, journal: dict[str, Any]) -> dict[str, Any]:
        journal = self._set_journal_status(journal, "rolling_back")
        root = self._validate_journal_scope(journal)
        transaction_dir = self.transactions_root / str(journal["transaction_id"])
        for index, record in enumerate(reversed(journal["mutations"])):
            target = _target_path(
                root, str(record["relative_path"]), create_parents=True
            )
            if bool(record["existed"]):
                backup_name = record.get("backup_file")
                if not isinstance(backup_name, str):
                    raise InstallationStateError(
                        "installation backup reference is invalid"
                    )
                backup = transaction_dir / "backups" / backup_name
                content = _read_private_payload(backup, str(record["current_sha256"]))
                _atomic_write_target(target, content, int(record["current_mode"]))
            else:
                if target.is_symlink():
                    raise InstallationConflictError(
                        "installation target changed outside the installer"
                    )
                target.unlink(missing_ok=True)
                _prune_empty_parents(target.parent, root)
            journal["rollback_count"] = index + 1
            journal["updated_at"] = utc_now()
            self._write_journal(journal)
            self.fault_injector(f"rollback:{index + 1}", str(journal["transaction_id"]))
        self._delete_owner_if_owned(
            str(journal["owner_key"]), str(journal["transaction_id"])
        )
        journal["owner_revision"] = None
        return self._set_journal_status(journal, "rolled_back")

    def _assert_recoverable_files(self, journal: Mapping[str, Any]) -> None:
        root = self._validate_journal_scope(journal)
        for record in journal["mutations"]:
            target = _target_path(root, str(record["relative_path"]))
            current = _read_regular_file(target)
            current_hash = _bytes_hash(current) if current is not None else None
            if current_hash not in {
                record.get("current_sha256"),
                record.get("desired_sha256"),
            }:
                raise InstallationConflictError(
                    "interrupted installation target changed outside the installer"
                )
            if current is not None:
                allowed_modes = {int(record["mode"])}
                if record.get("current_mode") is not None:
                    allowed_modes.add(int(record["current_mode"]))
                if stat_mode(target) not in allowed_modes:
                    raise InstallationConflictError(
                        "interrupted installation target mode changed outside the installer"
                    )

    def _publish_owner(self, journal: Mapping[str, Any]) -> dict[str, Any]:
        files = [
            {
                "relative_path": str(record["relative_path"]),
                "sha256": str(record["desired_sha256"]),
                "mode": int(record["mode"]),
            }
            for record in journal["mutations"]
        ]
        payload = {
            "schema_version": INSTALLATION_STATE_SCHEMA_VERSION,
            "owner_key": str(journal["owner_key"]),
            "transaction_id": str(journal["transaction_id"]),
            "package_id": str(journal["package_id"]),
            "package_version": str(journal["package_version"]),
            "manifest_sha256": str(journal["manifest_sha256"]),
            "target_id": str(journal["target_id"]),
            "scope": str(journal["scope"]),
            "owner_id": str(journal["owner_id"]),
            "root": str(journal["root"]),
            "files": files,
            "installed_at": utc_now(),
        }
        payload["revision"] = _json_hash(payload)
        _atomic_write_private_json(self._owner_path(str(journal["owner_key"])), payload)
        return payload

    def _installed_from_journal(
        self, journal: Mapping[str, Any]
    ) -> InstalledIntegration:
        owner = self._read_owner(str(journal["owner_key"]))
        if owner is None or owner.get("transaction_id") != journal["transaction_id"]:
            raise InstallationStateError("installation ownership record is missing")
        return self._installed_from_owner(owner)

    def _installed_from_owner(self, owner: Mapping[str, Any]) -> InstalledIntegration:
        root = self._validate_scope_root(
            InstallationScope(str(owner["scope"])), Path(str(owner["root"]))
        )
        current = True
        paths = []
        for record in owner["files"]:
            relative_path = str(record["relative_path"])
            paths.append(relative_path)
            try:
                target = _target_path(root, relative_path)
                content = _read_regular_file(target)
            except InstallationError:
                current = False
                continue
            if (
                content is None
                or _bytes_hash(content) != record["sha256"]
                or stat_mode(target) != record["mode"]
            ):
                current = False
        return InstalledIntegration(
            transaction_id=str(owner["transaction_id"]),
            package_id=str(owner["package_id"]),
            package_version=str(owner["package_version"]),
            manifest_sha256=str(owner["manifest_sha256"]),
            target_id=str(owner["target_id"]),
            scope=InstallationScope(str(owner["scope"])),
            owner_id=str(owner["owner_id"]),
            owner_revision=str(owner["revision"]),
            relative_paths=tuple(paths),
            installed_at=str(owner["installed_at"]),
            current=current,
        )

    def _owner_matches_plan(
        self, owner: Mapping[str, Any], plan: InstallationPlan
    ) -> bool:
        return (
            owner.get("package_id") == plan.package_id
            and owner.get("package_version") == plan.package_version
            and owner.get("manifest_sha256") == plan.manifest_sha256
            and owner.get("target_id") == plan.target_id
            and owner.get("scope") == plan.scope.value
            and {
                str(item["relative_path"]): str(item["sha256"])
                for item in owner["files"]
            }
            == {item.relative_path: item.desired_sha256 for item in plan.mutations}
        )

    def _result_from_owner(self, owner: Mapping[str, Any]) -> InstallationResult:
        journal = self._load_journal(str(owner["transaction_id"]))
        return self._result_from_journal(journal)

    def _result_from_journal(self, journal: Mapping[str, Any]) -> InstallationResult:
        return InstallationResult(
            transaction_id=str(journal["transaction_id"]),
            plan_id=str(journal["plan_id"]),
            status=str(journal["status"]),
            package_id=str(journal["package_id"]),
            package_version=str(journal["package_version"]),
            target_id=str(journal["target_id"]),
            scope=InstallationScope(str(journal["scope"])),
            owner_revision=(
                str(journal["owner_revision"])
                if journal.get("owner_revision") is not None
                else None
            ),
            updated_at=str(journal["updated_at"]),
        )

    def _plan_from_journal(self, journal: Mapping[str, Any]) -> InstallationPlan:
        mutations = tuple(
            InstallationFilePlan(
                relative_path=str(item["relative_path"]),
                current_sha256=(
                    str(item["current_sha256"])
                    if item.get("current_sha256") is not None
                    else None
                ),
                current_mode=(
                    int(item["current_mode"])
                    if item.get("current_mode") is not None
                    else None
                ),
                desired_sha256=str(item["desired_sha256"]),
                mode=int(item["mode"]),
                changed=bool(item["changed"]),
            )
            for item in journal["mutations"]
        )
        return InstallationPlan(
            plan_id=str(journal["plan_id"]),
            transaction_id=str(journal["transaction_id"]),
            package_id=str(journal["package_id"]),
            package_version=str(journal["package_version"]),
            manifest_sha256=str(journal["manifest_sha256"]),
            target_id=str(journal["target_id"]),
            scope=InstallationScope(str(journal["scope"])),
            owner_id=str(journal["owner_id"]),
            owner_key=str(journal["owner_key"]),
            root=Path(str(journal["root"])),
            expected_owner_revision=(
                str(journal["expected_owner_revision"])
                if journal.get("expected_owner_revision") is not None
                else None
            ),
            mutations=mutations,
            changed=any(item.changed for item in mutations),
        )

    def _set_journal_status(
        self, journal: dict[str, Any], status: str
    ) -> dict[str, Any]:
        if status not in _JOURNAL_STATUSES:
            raise InstallationStateError("installation journal status is invalid")
        journal["status"] = status
        journal["updated_at"] = utc_now()
        self._write_journal(journal)
        return journal

    def _write_journal(self, journal: Mapping[str, Any]) -> None:
        transaction_id = str(journal.get("transaction_id") or "")
        _validate_transaction_id(transaction_id)
        _atomic_write_private_json(self.journal_path(transaction_id), journal)

    def _load_journal_if_present(self, transaction_id: str) -> dict[str, Any] | None:
        if not self.journal_path(transaction_id).exists():
            return None
        return self._load_journal(transaction_id)

    def _load_journal(self, transaction_id: str) -> dict[str, Any]:
        path = self.journal_path(transaction_id)
        payload = _read_json(path, label="installation journal")
        _validate_journal(payload, transaction_id)
        return payload

    def _assert_journal_matches_plan(
        self, journal: Mapping[str, Any], plan: InstallationPlan
    ) -> None:
        if (
            journal.get("plan_id") != plan.plan_id
            or journal.get("owner_key") != plan.owner_key
            or journal.get("manifest_sha256") != plan.manifest_sha256
        ):
            raise InstallationStateError("installation journal does not match plan")

    def _read_owner(self, owner_key: str) -> dict[str, Any] | None:
        path = self._owner_path(owner_key)
        if not path.exists():
            return None
        return self._load_owner_path(path)

    def _load_owner_path(self, path: Path) -> dict[str, Any]:
        payload = _read_json(path, label="installation ownership record")
        _validate_owner(payload, path.stem)
        return payload

    def _delete_owner_if_owned(self, owner_key: str, transaction_id: str) -> None:
        owner = self._read_owner(owner_key)
        if owner is None:
            return
        if owner.get("transaction_id") != transaction_id:
            raise InstallationConflictError(
                "installation ownership changed outside the installer"
            )
        self._owner_path(owner_key).unlink()

    def _owner_path(self, owner_key: str) -> Path:
        if not _HASH_RE.fullmatch(owner_key):
            raise InstallationStateError("installation owner key is invalid")
        return self.owners_root / f"{owner_key}.json"

    def _lock_path(self, owner_key: str) -> Path:
        if not _HASH_RE.fullmatch(owner_key):
            raise InstallationStateError("installation owner key is invalid")
        return self.locks_root / owner_key

    def _ensure_state_root(self) -> None:
        if self.data_dir.is_symlink():
            raise InstallationStateError(
                "installation data directory cannot be a symlink"
            )
        for path in (
            self.installations_root,
            self.transactions_root,
            self.owners_root,
            self.locks_root,
        ):
            if path.is_symlink():
                raise InstallationStateError("installation state cannot be a symlink")
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(path, 0o700)
            except OSError:  # pragma: no cover - best-effort hardening
                pass


def _validate_journal(payload: dict[str, Any], transaction_id: str) -> None:
    required = {
        "schema_version",
        "transaction_id",
        "plan_id",
        "status",
        "package_id",
        "package_version",
        "manifest_sha256",
        "target_id",
        "scope",
        "owner_id",
        "owner_key",
        "root",
        "expected_owner_revision",
        "approval_authority",
        "allow_user_home",
        "mutations",
        "applied_count",
        "rollback_count",
        "owner_revision",
        "failure",
        "created_at",
        "updated_at",
    }
    if set(payload) != required:
        raise InstallationStateError("installation journal fields are invalid")
    if payload["schema_version"] != INSTALLATION_STATE_SCHEMA_VERSION:
        raise InstallationStateError("installation journal schema is unsupported")
    if payload["transaction_id"] != transaction_id:
        raise InstallationStateError("installation journal identity is invalid")
    if not _PLAN_RE.fullmatch(str(payload["plan_id"])):
        raise InstallationStateError("installation journal plan is invalid")
    if payload["status"] not in _JOURNAL_STATUSES:
        raise InstallationStateError("installation journal status is invalid")
    for field_name in (
        "package_id",
        "package_version",
        "target_id",
        "owner_id",
        "approval_authority",
    ):
        try:
            _validate_identity(str(payload[field_name]), field_name=field_name)
        except ValueError as exc:
            raise InstallationStateError(
                "installation journal identity is invalid"
            ) from exc
    for field_name in ("manifest_sha256", "owner_key"):
        if not _HASH_RE.fullmatch(str(payload[field_name])):
            raise InstallationStateError("installation journal hash is invalid")
    for field_name in ("expected_owner_revision", "owner_revision"):
        value = payload[field_name]
        if value is not None and not _HASH_RE.fullmatch(str(value)):
            raise InstallationStateError("installation journal revision is invalid")
    try:
        scope = InstallationScope(str(payload["scope"]))
    except ValueError as exc:
        raise InstallationStateError("installation journal scope is invalid") from exc
    root = Path(str(payload["root"]))
    if not root.is_absolute() or _absolute_path(root) != root:
        raise InstallationStateError("installation journal root is invalid")
    mutations = payload["mutations"]
    if (
        not isinstance(mutations, list)
        or not mutations
        or len(mutations) > MAX_INSTALL_MUTATIONS
    ):
        raise InstallationStateError("installation journal mutations are invalid")
    for record in mutations:
        _validate_journal_mutation(record)
    relative_paths = [str(record["relative_path"]) for record in mutations]
    if relative_paths != sorted(set(relative_paths)):
        raise InstallationStateError("installation journal paths are invalid")
    for index, record in enumerate(mutations):
        if record["stage_file"] != f"{index:04d}.payload" or (
            record["existed"] and record["backup_file"] != f"{index:04d}.backup"
        ):
            raise InstallationStateError(
                "installation journal payload order is invalid"
            )
    for field_name in ("applied_count", "rollback_count"):
        value = payload[field_name]
        if not isinstance(value, int) or not 0 <= value <= len(mutations):
            raise InstallationStateError("installation journal counter is invalid")
    if not isinstance(payload["allow_user_home"], bool):
        raise InstallationStateError("installation journal approval is invalid")
    expected_owner_key = _json_hash(
        {
            "target_id": str(payload["target_id"]),
            "scope": scope.value,
            "owner_id": str(payload["owner_id"]),
            "root_sha256": _text_hash(str(root)),
        }
    )
    if payload["owner_key"] != expected_owner_key:
        raise InstallationStateError("installation journal owner binding is invalid")
    plan_mutations = tuple(
        InstallationFilePlan(
            relative_path=str(item["relative_path"]),
            current_sha256=(
                str(item["current_sha256"])
                if item["current_sha256"] is not None
                else None
            ),
            current_mode=(
                int(item["current_mode"]) if item["current_mode"] is not None else None
            ),
            desired_sha256=str(item["desired_sha256"]),
            mode=int(item["mode"]),
            changed=bool(item["changed"]),
        )
        for item in mutations
    )
    semantic = _plan_semantic(
        package_id=str(payload["package_id"]),
        package_version=str(payload["package_version"]),
        manifest_sha256=str(payload["manifest_sha256"]),
        target_id=str(payload["target_id"]),
        scope=scope,
        owner_id=str(payload["owner_id"]),
        owner_key=str(payload["owner_key"]),
        root=root,
        expected_owner_revision=(
            str(payload["expected_owner_revision"])
            if payload["expected_owner_revision"] is not None
            else None
        ),
        mutations=plan_mutations,
    )
    expected_plan_id = f"plan_{_json_hash(semantic)}"
    if payload["plan_id"] != expected_plan_id or transaction_id != (
        f"txn_{expected_plan_id[5:37]}"
    ):
        raise InstallationStateError("installation journal plan binding is invalid")
    failure = payload["failure"]
    if failure is not None and (
        not isinstance(failure, dict)
        or set(failure) != {"code", "error_type"}
        or not all(isinstance(value, str) and value for value in failure.values())
    ):
        raise InstallationStateError("installation journal failure is invalid")


def _validate_journal_mutation(record: Any) -> None:
    required = {
        "relative_path",
        "current_sha256",
        "desired_sha256",
        "mode",
        "changed",
        "stage_file",
        "backup_file",
        "existed",
        "current_mode",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise InstallationStateError("installation journal mutation is invalid")
    try:
        _normalize_relative_path(str(record["relative_path"]))
    except ValueError as exc:
        raise InstallationStateError("installation journal path is invalid") from exc
    if not _HASH_RE.fullmatch(str(record["desired_sha256"])):
        raise InstallationStateError("installation journal desired hash is invalid")
    current = record["current_sha256"]
    if current is not None and not _HASH_RE.fullmatch(str(current)):
        raise InstallationStateError("installation journal current hash is invalid")
    if record["mode"] not in _SAFE_MODES or not isinstance(record["changed"], bool):
        raise InstallationStateError("installation journal file metadata is invalid")
    if not re.fullmatch(r"[0-9]{4}\.payload", str(record["stage_file"])):
        raise InstallationStateError("installation journal stage path is invalid")
    existed = record["existed"]
    if not isinstance(existed, bool):
        raise InstallationStateError("installation journal existence is invalid")
    if existed:
        if current is None:
            raise InstallationStateError("installation journal prior hash is missing")
        if not re.fullmatch(r"[0-9]{4}\.backup", str(record["backup_file"])):
            raise InstallationStateError("installation journal backup path is invalid")
        if (
            not isinstance(record["current_mode"], int)
            or not 0 <= record["current_mode"] <= 0o777
        ):
            raise InstallationStateError("installation journal prior mode is invalid")
    elif record["backup_file"] is not None or record["current_mode"] is not None:
        raise InstallationStateError(
            "installation journal absent-file state is invalid"
        )
    elif current is not None:
        raise InstallationStateError("installation journal absent-file hash is invalid")
    changed = (
        current != record["desired_sha256"] or record["current_mode"] != record["mode"]
    )
    if record["changed"] is not changed:
        raise InstallationStateError("installation journal change flag is invalid")


def _validate_owner(payload: dict[str, Any], owner_key: str) -> None:
    required = {
        "schema_version",
        "owner_key",
        "transaction_id",
        "package_id",
        "package_version",
        "manifest_sha256",
        "target_id",
        "scope",
        "owner_id",
        "root",
        "files",
        "installed_at",
        "revision",
    }
    if set(payload) != required:
        raise InstallationStateError("installation ownership fields are invalid")
    if payload["schema_version"] != INSTALLATION_STATE_SCHEMA_VERSION:
        raise InstallationStateError("installation ownership schema is unsupported")
    if payload["owner_key"] != owner_key or not _HASH_RE.fullmatch(owner_key):
        raise InstallationStateError("installation ownership identity is invalid")
    _validate_transaction_id(str(payload["transaction_id"]))
    for field_name in ("package_id", "package_version", "target_id", "owner_id"):
        try:
            _validate_identity(str(payload[field_name]), field_name=field_name)
        except ValueError as exc:
            raise InstallationStateError(
                "installation ownership identity is invalid"
            ) from exc
    if not _HASH_RE.fullmatch(str(payload["manifest_sha256"])):
        raise InstallationStateError("installation ownership hash is invalid")
    try:
        scope = InstallationScope(str(payload["scope"]))
    except ValueError as exc:
        raise InstallationStateError("installation ownership scope is invalid") from exc
    root = Path(str(payload["root"]))
    if not root.is_absolute() or _absolute_path(root) != root:
        raise InstallationStateError("installation ownership root is invalid")
    expected_owner_key = _json_hash(
        {
            "target_id": str(payload["target_id"]),
            "scope": scope.value,
            "owner_id": str(payload["owner_id"]),
            "root_sha256": _text_hash(str(root)),
        }
    )
    if owner_key != expected_owner_key:
        raise InstallationStateError("installation ownership binding is invalid")
    files = payload["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_INSTALL_MUTATIONS:
        raise InstallationStateError("installation ownership files are invalid")
    for item in files:
        if not isinstance(item, dict) or set(item) != {
            "relative_path",
            "sha256",
            "mode",
        }:
            raise InstallationStateError("installation ownership file is invalid")
        _normalize_relative_path(str(item["relative_path"]))
        if (
            not _HASH_RE.fullmatch(str(item["sha256"]))
            or item["mode"] not in _SAFE_MODES
        ):
            raise InstallationStateError("installation ownership file hash is invalid")
    relative_paths = [str(item["relative_path"]) for item in files]
    if relative_paths != sorted(set(relative_paths)):
        raise InstallationStateError("installation ownership paths are invalid")
    if not isinstance(payload["installed_at"], str) or not payload["installed_at"]:
        raise InstallationStateError("installation ownership timestamp is invalid")
    revision = str(payload["revision"])
    expected = _json_hash(
        {key: value for key, value in payload.items() if key != "revision"}
    )
    if revision != expected:
        raise InstallationStateError("installation ownership revision is invalid")


def _file_plan_to_dict(plan: InstallationFilePlan) -> dict[str, Any]:
    return {
        "relative_path": plan.relative_path,
        "current_sha256": plan.current_sha256,
        "current_mode": plan.current_mode,
        "desired_sha256": plan.desired_sha256,
        "mode": plan.mode,
        "changed": plan.changed,
    }


def _plan_semantic(
    *,
    package_id: str,
    package_version: str,
    manifest_sha256: str,
    target_id: str,
    scope: InstallationScope,
    owner_id: str,
    owner_key: str,
    root: Path,
    expected_owner_revision: str | None,
    mutations: Sequence[InstallationFilePlan],
) -> dict[str, Any]:
    return {
        "package_id": package_id,
        "package_version": package_version,
        "manifest_sha256": manifest_sha256,
        "target_id": target_id,
        "scope": scope.value,
        "owner_id": owner_id,
        "owner_key": owner_key,
        "root_sha256": _text_hash(str(root)),
        "expected_owner_revision": expected_owner_revision,
        "mutations": [_file_plan_to_dict(item) for item in mutations],
    }


def _owner_key(target: InstallationTarget, root: Path) -> str:
    return _json_hash(
        {
            "target_id": target.id,
            "scope": target.scope.value,
            "owner_id": target.owner_id,
            "root_sha256": _text_hash(str(root)),
        }
    )


def _target_path(
    root: Path, relative_path: str, *, create_parents: bool = False
) -> Path:
    normalized = _normalize_relative_path(relative_path)
    target = root.joinpath(*PurePosixPath(normalized).parts)
    _assert_no_symlink_chain(target, root)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise InstallationScopeError("installation target must be a regular file")
    if create_parents:
        _mkdir_private_parents(target.parent, root)
    return target


def _read_regular_file(path: Path) -> bytes | None:
    if path.is_symlink():
        raise InstallationScopeError("installation target cannot be a symlink")
    if not path.exists():
        return None
    try:
        if not path.is_file():
            raise InstallationScopeError("installation target must be a regular file")
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(content) > MAX_INSTALL_FILE_BYTES:
        raise InstallationScopeError("installation target file is too large")
    return content


def _assert_no_symlink_chain(path: Path, stop: Path) -> None:
    path = _absolute_path(path)
    stop = _absolute_path(stop)
    if path != stop and not _is_relative_to(path, stop):
        raise InstallationScopeError("installation target escapes its scope")
    current = path
    while True:
        if current.is_symlink():
            raise InstallationScopeError("installation target path contains a symlink")
        if current == stop:
            return
        parent = current.parent
        if parent == current:
            raise InstallationScopeError("installation target escapes its scope")
        current = parent


def _mkdir_private_parents(path: Path, root: Path) -> None:
    if not root.exists():
        if root.is_symlink():
            raise InstallationScopeError("installation target path contains a symlink")
        root.mkdir(parents=True, mode=0o700)
        if root.is_symlink():
            raise InstallationScopeError("installation target path contains a symlink")
        os.chmod(root, 0o700)
    missing = []
    current = path
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent
    _assert_no_symlink_chain(current, root)
    for item in reversed(missing):
        item.mkdir(mode=0o700)


def _prune_empty_parents(path: Path, root: Path) -> None:
    current = path
    while current != root and _is_relative_to(current, root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _atomic_write_target(path: Path, content: bytes, mode: int) -> None:
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_private_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    content = (
        json.dumps(
            payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )
    _atomic_write_private_bytes(path, content)


def _read_private_payload(path: Path, expected_hash: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise InstallationStateError("installation transaction payload is missing")
    content = path.read_bytes()
    if len(content) > MAX_INSTALL_FILE_BYTES or _bytes_hash(content) != expected_hash:
        raise InstallationStateError("installation transaction payload hash is invalid")
    return content


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise InstallationStateError(f"{label} cannot be a symlink")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise InstallationStateError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise InstallationStateError(f"{label} must be an object")
    return payload


def _bounded_failure(exc: Exception) -> dict[str, str]:
    if isinstance(exc, InstallationVerificationError):
        code = "verification_failed"
    elif isinstance(exc, InstallationConflictError):
        code = "installation_conflict"
    elif isinstance(exc, InstallationStateError):
        code = "state_invalid"
    else:
        code = "apply_failed"
    return {"code": code, "error_type": type(exc).__name__[:128]}


def _normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("installation relative path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("installation relative path is invalid")
    normalized = path.as_posix()
    if len(normalized) > 512:
        raise ValueError("installation relative path is too long")
    return normalized


def _validate_identity(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")


def _validate_transaction_id(value: str) -> None:
    if not _TRANSACTION_RE.fullmatch(value):
        raise InstallationStateError("installation transaction id is invalid")


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _bytes_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text_hash(value: str) -> str:
    return _bytes_hash(value.encode("utf-8"))


def _json_hash(value: Any) -> str:
    content = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return _bytes_hash(content)


def stat_mode(path: Path) -> int:
    """Return only portable permission bits for one existing regular file."""
    return path.stat(follow_symlinks=False).st_mode & 0o777
