"""Application-owned add-integration previews and lifecycle operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from gpt2giga_harness.builtin_skills import (
    BUILTIN_SKILL_SOURCE_ID,
    build_builtin_skill_installation_request,
    import_builtin_skills,
)
from gpt2giga_harness.claude_mcp_target import CLAUDE_MCP_TARGET_DESCRIPTOR
from gpt2giga_harness.claude_plugin_target import CLAUDE_PLUGIN_TARGET_DESCRIPTOR
from gpt2giga_harness.codex_mcp_target import CODEX_MCP_TARGET_DESCRIPTOR
from gpt2giga_harness.codex_plugin_target import CODEX_PLUGIN_TARGET_DESCRIPTOR
from gpt2giga_harness.gemini_extension_target import (
    GEMINI_EXTENSION_TARGET_DESCRIPTOR,
)
from gpt2giga_harness.gemini_mcp_target import GEMINI_MCP_TARGET_DESCRIPTOR
from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    IntegrationCatalogStore,
)
from gpt2giga_harness.integration_installer import (
    InstallationApproval,
    InstallationConflictError,
    TransactionalIntegrationInstaller,
)
from gpt2giga_harness.integration_packages import (
    ExtensionTargetDescriptor,
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationPolicyClass,
    IntegrationRequirement,
    IntegrationRequirementType,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationTrustEvidence,
    IntegrationTrustKind,
    IntegrationTrustDecision,
    IntegrationTrustStatus,
    IntegrationUpdatePolicy,
    assess_integration_package,
    extension_target_descriptor_to_dict,
    integration_package_from_dict,
    integration_package_semantic_hash,
    integration_package_to_dict,
)
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
    SkillCapabilitySnapshot,
    discover_generated_skill,
    generated_skill_verifier,
    probe_skill_target,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock


INTEGRATION_FLOW_SCHEMA_VERSION = 1
MAX_INTEGRATION_FLOWS = 500
MAX_FLOW_EVENTS = 50
MAX_CONFIGURATION_FIELDS = 64
_FLOW_ID_RE = re.compile(r"flow_[0-9a-f]{32}\Z")
_PLAN_ID_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")
_SENSITIVE_FIELD_RE = re.compile(
    r"(?:password|passwd|secret|token|credential|api[_-]?key)", re.IGNORECASE
)


class IntegrationFlowError(RuntimeError):
    """Base error for application-owned integration flows."""


class IntegrationFlowNotFoundError(IntegrationFlowError):
    """Raised when a flow id does not exist."""


class IntegrationFlowConflictError(IntegrationFlowError):
    """Raised when an approval or lifecycle transition is stale."""


class IntegrationFlowSource(str, Enum):
    """Product source choices exposed consistently to Web, CLI, and API."""

    CATALOG = "catalog"
    MARKETPLACE = "marketplace"
    GIT = "git"
    LOCAL = "local"
    PACKAGE = "package"
    RAW_DESCRIPTOR = "raw_descriptor"


class IntegrationFlowStatus(str, Enum):
    """Durable operation states rendered by every client."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    VERIFIED = "verified"
    HANDOFF_REQUIRED = "handoff_required"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class IntegrationFlowEvent:
    """Content-free progress event for one bounded lifecycle stage."""

    stage: str
    status: str
    occurred_at: str
    code: str | None = None


@dataclass(frozen=True)
class IntegrationFlowRecord:
    """Private durable flow record with a public content-free projection."""

    id: str
    plan_id: str
    status: IntegrationFlowStatus
    source: IntegrationFlowSource
    package_id: str
    package_version: str
    manifest_sha256: str
    target_id: str
    scope: InstallationScope
    workspace: str | None
    request: Mapping[str, Any]
    receipt_id: str | None
    verification_status: str
    rollback_available: bool
    error_code: str | None
    created_at: str
    updated_at: str
    events: tuple[IntegrationFlowEvent, ...]


@dataclass(frozen=True)
class _ResolvedPreview:
    """Internal exact preview plus its public application projection."""

    package: IntegrationPackage
    target: ExtensionTargetDescriptor
    root: Path
    executable: bool
    execution_owner: str
    native_plan_id: str | None
    configuration_diff: tuple[str, ...]
    restart_required: bool
    handoff_reason: str | None = None


_SKILL_TARGETS = {
    CODEX_SKILL_TARGET_ID: ExtensionTargetDescriptor(
        id=CODEX_SKILL_TARGET_ID,
        revision="1",
        component_types=(IntegrationComponentType.SKILL,),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        capabilities=("install", "verify", "rollback", "skill.discovery"),
        trust_evidence=(
            IntegrationTrustEvidence(
                id="codex-skill-documented-surface",
                kind=IntegrationTrustKind.SOURCE,
                status=IntegrationTrustStatus.VERIFIED,
                authority="agentskills-open-standard",
                revision="2026-07-19",
            ),
        ),
    ),
    CLAUDE_SKILL_TARGET_ID: ExtensionTargetDescriptor(
        id=CLAUDE_SKILL_TARGET_ID,
        revision="1",
        component_types=(IntegrationComponentType.SKILL,),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        capabilities=("install", "verify", "rollback", "skill.discovery"),
        trust_evidence=(
            IntegrationTrustEvidence(
                id="claude-skill-documented-surface",
                kind=IntegrationTrustKind.SOURCE,
                status=IntegrationTrustStatus.VERIFIED,
                authority="agentskills-open-standard",
                revision="2026-07-19",
            ),
        ),
    ),
    GEMINI_SKILL_TARGET_ID: ExtensionTargetDescriptor(
        id=GEMINI_SKILL_TARGET_ID,
        revision="1",
        component_types=(IntegrationComponentType.SKILL,),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        capabilities=(
            "install",
            "provider_consent",
            "rollback",
            "skill.discovery",
            "verify",
        ),
        trust_evidence=(
            IntegrationTrustEvidence(
                id="gemini-skill-documented-surface",
                kind=IntegrationTrustKind.SOURCE,
                status=IntegrationTrustStatus.VERIFIED,
                authority="agentskills-open-standard",
                revision="2026-07-19",
            ),
        ),
    ),
}

HARNESS_PACKAGE_TARGET = ExtensionTargetDescriptor(
    id="harness-adapter-package",
    revision="1",
    component_types=(IntegrationComponentType.HARNESS_ADAPTER,),
    scopes=(InstallationScope.MANAGED_HOME,),
    capabilities=("package_handoff", "preview", "sdk_conformance_required"),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="harness-adapter-sdk-surface",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="gpt2giga-harness-sdk",
            revision="1",
        ),
    ),
)

BUILTIN_FLOW_TARGETS = tuple(
    sorted(
        (
            CODEX_MCP_TARGET_DESCRIPTOR,
            CLAUDE_MCP_TARGET_DESCRIPTOR,
            GEMINI_MCP_TARGET_DESCRIPTOR,
            CODEX_PLUGIN_TARGET_DESCRIPTOR,
            CLAUDE_PLUGIN_TARGET_DESCRIPTOR,
            GEMINI_EXTENSION_TARGET_DESCRIPTOR,
            *_SKILL_TARGETS.values(),
            HARNESS_PACKAGE_TARGET,
        ),
        key=lambda item: item.id,
    )
)


class IntegrationFlowService:
    """Coordinate exact previews and reversible application-owned operations."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        skill_capability_provider: Callable[[str], SkillCapabilitySnapshot]
        | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "integrations"
        self.path = self.root / "flows.json"
        self.lock_path = self.root / ".flows.json.lock"
        self.catalog = IntegrationCatalogStore(self.data_dir)
        self._skill_capability_provider = (
            skill_capability_provider or probe_skill_target
        )
        self._now = now or (lambda: datetime.now(timezone.utc))

    def inventory(self) -> dict[str, Any]:
        """Return bounded sources, targets, catalog entries, and recent flows."""
        self._ensure_catalog_seeded()
        entries = tuple(self.catalog.list())
        return {
            "schema_version": INTEGRATION_FLOW_SCHEMA_VERSION,
            "sources": [
                {
                    "id": item.value,
                    "network_required": item
                    in {IntegrationFlowSource.MARKETPLACE, IntegrationFlowSource.GIT},
                    "immutable_input_required": item
                    not in {
                        IntegrationFlowSource.CATALOG,
                        IntegrationFlowSource.RAW_DESCRIPTOR,
                    },
                }
                for item in IntegrationFlowSource
            ],
            "targets": [
                {
                    **extension_target_descriptor_to_dict(item),
                    "execution_owner": _execution_owner(item.id),
                }
                for item in BUILTIN_FLOW_TARGETS
            ],
            "catalog": [_catalog_entry_to_dict(item) for item in entries[:200]],
            "flows": [integration_flow_record_to_dict(item) for item in self.list()],
            "content_free": True,
        }

    def list(self) -> tuple[IntegrationFlowRecord, ...]:
        """Return recent flows in reverse update order."""
        records = self._read_records()
        return tuple(
            sorted(records.values(), key=lambda item: item.updated_at, reverse=True)
        )[:MAX_INTEGRATION_FLOWS]

    def get(self, flow_id: str) -> IntegrationFlowRecord:
        """Return one exact durable flow."""
        _validate_flow_id(flow_id)
        record = self._read_records().get(flow_id)
        if record is None:
            raise IntegrationFlowNotFoundError(flow_id)
        return record

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve one immutable package and persist an exact approval preview."""
        request = _normalize_request(payload)
        resolved = self._resolve_preview(request)
        plan = _public_plan(request, resolved)
        timestamp = self._timestamp()
        flow_id = f"flow_{uuid4().hex}"
        record = IntegrationFlowRecord(
            id=flow_id,
            plan_id=plan["plan_id"],
            status=IntegrationFlowStatus.AWAITING_APPROVAL,
            source=IntegrationFlowSource(request["source"]),
            package_id=resolved.package.id,
            package_version=resolved.package.version,
            manifest_sha256=integration_package_semantic_hash(resolved.package),
            target_id=resolved.target.id,
            scope=InstallationScope(request["scope"]),
            workspace=request.get("workspace"),
            request=request,
            receipt_id=None,
            verification_status="not_started",
            rollback_available=False,
            error_code=None,
            created_at=timestamp,
            updated_at=timestamp,
            events=(
                IntegrationFlowEvent(
                    stage="preview",
                    status="completed",
                    occurred_at=timestamp,
                ),
            ),
        )
        self._put(record)
        return {"flow": integration_flow_record_to_dict(record), "plan": plan}

    def apply(
        self,
        flow_id: str,
        *,
        plan_id: str,
        authority: str,
        allow_network: bool = False,
        allow_user_home: bool = False,
        native_consent_acknowledged: bool = False,
    ) -> dict[str, Any]:
        """Apply one exact preview or return its explicit target-owned handoff."""
        record = self.get(flow_id)
        _validate_plan_id(plan_id)
        _validate_identity(authority, field_name="approval authority")
        if record.plan_id != plan_id:
            raise IntegrationFlowConflictError("approval does not match the preview")
        if record.status is not IntegrationFlowStatus.AWAITING_APPROVAL:
            if record.status in {
                IntegrationFlowStatus.VERIFIED,
                IntegrationFlowStatus.HANDOFF_REQUIRED,
            }:
                return {"flow": integration_flow_record_to_dict(record)}
            raise IntegrationFlowConflictError("flow cannot be applied in its state")
        resolved = self._resolve_preview(record.request)
        current_plan = _public_plan(record.request, resolved)
        if current_plan["plan_id"] != plan_id:
            raise IntegrationFlowConflictError("integration preview is stale")
        if current_plan["permissions"]["network"] and not allow_network:
            raise IntegrationFlowConflictError("network access requires approval")
        if record.scope is InstallationScope.USER_HOME and not allow_user_home:
            raise IntegrationFlowConflictError("user-home access requires approval")
        if (
            current_plan["permissions"]["native_consent"]
            and not native_consent_acknowledged
        ):
            raise IntegrationFlowConflictError(
                "native consent requires acknowledgement"
            )
        applying = self._transition(record, IntegrationFlowStatus.APPLYING, "apply")
        try:
            if not resolved.executable:
                completed = self._transition(
                    applying,
                    IntegrationFlowStatus.HANDOFF_REQUIRED,
                    "handoff",
                    verification_status="provider_owned",
                )
                return {
                    "flow": integration_flow_record_to_dict(completed),
                    "handoff": {
                        "owner": resolved.execution_owner,
                        "reason": resolved.handoff_reason,
                        "mutation_performed": False,
                    },
                }
            receipt_id, verification_status = self._apply_skill(
                record.request,
                resolved,
                authority=authority,
                allow_user_home=allow_user_home,
            )
            verified = self._transition(
                applying,
                IntegrationFlowStatus.VERIFIED,
                "verify",
                receipt_id=receipt_id,
                verification_status=verification_status,
                rollback_available=True,
            )
            return {"flow": integration_flow_record_to_dict(verified)}
        except Exception as exc:
            self._transition(
                applying,
                IntegrationFlowStatus.FAILED,
                "failure",
                error_code=type(exc).__name__,
                verification_status="failed",
            )
            raise IntegrationFlowError(
                "integration apply failed; details were omitted"
            ) from exc

    def rollback(self, flow_id: str) -> dict[str, Any]:
        """Roll back one verified application-owned transaction."""
        record = self.get(flow_id)
        if (
            record.status is not IntegrationFlowStatus.VERIFIED
            or not record.rollback_available
            or record.receipt_id is None
        ):
            raise IntegrationFlowConflictError("flow has no reversible transaction")
        try:
            resolved = self._resolve_preview(record.request, existing=True)
            if resolved.target.id not in _SKILL_TARGETS:
                raise IntegrationFlowConflictError(
                    "rollback remains owned by the selected native target"
                )
            installer = self._skill_installer(record.request, resolved.root)
            installer.rollback(record.receipt_id)
            updated = self._transition(
                record,
                IntegrationFlowStatus.ROLLED_BACK,
                "rollback",
                verification_status="rolled_back",
                rollback_available=False,
            )
            return {"flow": integration_flow_record_to_dict(updated)}
        except IntegrationFlowConflictError:
            raise
        except Exception as exc:
            self._transition(
                record,
                IntegrationFlowStatus.FAILED,
                "rollback_failure",
                error_code=type(exc).__name__,
                verification_status="rollback_failed",
            )
            raise IntegrationFlowError(
                "integration rollback failed; details were omitted"
            ) from exc

    def _resolve_preview(
        self,
        request: Mapping[str, Any],
        *,
        existing: bool = False,
    ) -> _ResolvedPreview:
        source = IntegrationFlowSource(request["source"])
        target = _target(str(request["target_id"]))
        scope = InstallationScope(request["scope"])
        if scope not in target.scopes:
            raise ValueError("selected target does not support the requested scope")
        root = self._target_root(request, target, create=not existing)
        package = self._resolve_package(request, source, target, scope)
        _validate_target_compatibility(package, target, scope)
        if target.id in _SKILL_TARGETS:
            entry = self._catalog_entry_for_package(package)
            capability = self._skill_capability_provider(target.id)
            install_request, generated = build_builtin_skill_installation_request(
                entry,
                capability,
                scope=scope,
                root=root,
            )
            installer = self._skill_installer(request, root)
            native = installer.preview(install_request)
            return _ResolvedPreview(
                package=package,
                target=target,
                root=root,
                executable=True,
                execution_owner="workbench_transactional_installer",
                native_plan_id=native.plan_id,
                configuration_diff=tuple(
                    f"{'update' if item.current_sha256 else 'create'}:{item.relative_path}"
                    for item in native.mutations
                ),
                restart_required=generated.restart_required,
            )
        return _ResolvedPreview(
            package=package,
            target=target,
            root=root,
            executable=False,
            execution_owner=_execution_owner(target.id),
            native_plan_id=None,
            configuration_diff=_configuration_diff(request.get("configuration", {})),
            restart_required=True,
            handoff_reason=_handoff_reason(target.id),
        )

    def _resolve_package(
        self,
        request: Mapping[str, Any],
        source: IntegrationFlowSource,
        target: ExtensionTargetDescriptor,
        scope: InstallationScope,
    ) -> IntegrationPackage:
        if source is IntegrationFlowSource.CATALOG:
            self._ensure_catalog_seeded()
            catalog_id = str(request.get("catalog_id") or "")
            entry = self.catalog.get(catalog_id) if catalog_id else None
            if entry is None or entry.package is None:
                raise ValueError("catalog selection requires an exact package entry")
            return entry.package
        if source is IntegrationFlowSource.RAW_DESCRIPTOR:
            return _raw_mcp_package(request, target, scope)
        manifest = request.get("manifest")
        if not isinstance(manifest, Mapping):
            raise ValueError("selected source requires an exact package manifest")
        package = integration_package_from_dict(manifest)
        expected = {
            IntegrationFlowSource.MARKETPLACE: IntegrationSourceType.PROVIDER_MARKETPLACE,
            IntegrationFlowSource.GIT: IntegrationSourceType.GIT,
            IntegrationFlowSource.LOCAL: IntegrationSourceType.LOCAL,
            IntegrationFlowSource.PACKAGE: IntegrationSourceType.PACKAGE,
        }[source]
        if package.source_type is not expected:
            raise ValueError("package source_type does not match the selected source")
        return package

    def _catalog_entry_for_package(self, package: IntegrationPackage) -> CatalogEntry:
        self._ensure_catalog_seeded()
        entry = next(
            (
                item
                for item in self.catalog.list()
                if item.source_id == BUILTIN_SKILL_SOURCE_ID
                and item.package_id == package.id
                and item.version == package.version
            ),
            None,
        )
        if entry is None or entry.package != package:
            raise ValueError("portable skill execution requires a shipped catalog pin")
        return entry

    def _apply_skill(
        self,
        request: Mapping[str, Any],
        resolved: _ResolvedPreview,
        *,
        authority: str,
        allow_user_home: bool,
    ) -> tuple[str, str]:
        entry = self._catalog_entry_for_package(resolved.package)
        capability = self._skill_capability_provider(resolved.target.id)
        install_request, generated = build_builtin_skill_installation_request(
            entry,
            capability,
            scope=InstallationScope(request["scope"]),
            root=resolved.root,
        )
        installer = self._skill_installer(request, resolved.root)
        plan = installer.preview(install_request)
        if plan.plan_id != resolved.native_plan_id:
            raise InstallationConflictError("target preview changed before apply")
        result = installer.apply(
            install_request,
            plan,
            InstallationApproval(
                plan_id=plan.plan_id,
                authority=authority,
                allow_user_home=allow_user_home,
            ),
            verifier=generated_skill_verifier(generated),
        )
        discovery = discover_generated_skill(generated, resolved.root)
        if discovery.status.value != "discovered":
            raise IntegrationFlowError("skill discovery did not verify")
        return result.transaction_id, discovery.status.value

    def _skill_installer(
        self,
        request: Mapping[str, Any],
        root: Path,
    ) -> TransactionalIntegrationInstaller:
        scope = InstallationScope(request["scope"])
        return TransactionalIntegrationInstaller(
            self.data_dir,
            project_roots=(root,) if scope is InstallationScope.PROJECT else (),
        )

    def _target_root(
        self,
        request: Mapping[str, Any],
        target: ExtensionTargetDescriptor,
        *,
        create: bool,
    ) -> Path:
        scope = InstallationScope(request["scope"])
        if scope is InstallationScope.USER_HOME:
            raise ValueError(
                "user-home flows require an explicitly configured exact root"
            )
        if scope is InstallationScope.PROJECT:
            workspace = request.get("workspace")
            if not isinstance(workspace, str) or not workspace.strip():
                raise ValueError("project scope requires an explicit workspace")
            root = Path(workspace).expanduser().resolve()
            if not root.is_dir() or root.is_symlink():
                raise ValueError("project workspace must be an existing safe directory")
            return root
        package_hint = str(
            request.get("catalog_id") or request.get("package_id") or "candidate"
        )
        package_key = hashlib.sha256(package_hint.encode("utf-8")).hexdigest()[:24]
        root = self.data_dir / "native" / target.id / "homes" / package_key
        if create:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
        return root

    def _transition(
        self,
        record: IntegrationFlowRecord,
        status: IntegrationFlowStatus,
        stage: str,
        *,
        receipt_id: str | None = None,
        verification_status: str | None = None,
        rollback_available: bool | None = None,
        error_code: str | None = None,
    ) -> IntegrationFlowRecord:
        timestamp = self._timestamp()
        updated = replace(
            record,
            status=status,
            receipt_id=receipt_id if receipt_id is not None else record.receipt_id,
            verification_status=(
                verification_status
                if verification_status is not None
                else record.verification_status
            ),
            rollback_available=(
                rollback_available
                if rollback_available is not None
                else record.rollback_available
            ),
            error_code=error_code,
            updated_at=timestamp,
            events=(
                *record.events[-(MAX_FLOW_EVENTS - 1) :],
                IntegrationFlowEvent(
                    stage=stage,
                    status=status.value,
                    occurred_at=timestamp,
                    code=error_code,
                ),
            ),
        )
        self._put(updated)
        return updated

    def _timestamp(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _ensure_catalog_seeded(self) -> None:
        import_builtin_skills(self.catalog)

    def _put(self, record: IntegrationFlowRecord) -> None:
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            records = self._read_records_unlocked()
            records[record.id] = record
            if len(records) > MAX_INTEGRATION_FLOWS:
                oldest = sorted(records.values(), key=lambda item: item.updated_at)
                records = {item.id: item for item in oldest[-MAX_INTEGRATION_FLOWS:]}
            self._write_records_unlocked(records)

    def _read_records(self) -> dict[str, IntegrationFlowRecord]:
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            return self._read_records_unlocked()

    def _read_records_unlocked(self) -> dict[str, IntegrationFlowRecord]:
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or not self.path.is_file():
            raise IntegrationFlowError("integration flow state is unsafe")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise IntegrationFlowError("integration flow state is unreadable") from exc
        if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
            raise IntegrationFlowError("integration flow state schema is unsupported")
        raw_records = payload.get("flows")
        if (
            not isinstance(raw_records, list)
            or len(raw_records) > MAX_INTEGRATION_FLOWS
        ):
            raise IntegrationFlowError("integration flow state is invalid")
        records = tuple(_record_from_dict(item) for item in raw_records)
        if len({item.id for item in records}) != len(records):
            raise IntegrationFlowError("integration flow state has duplicate ids")
        return {item.id: item for item in records}

    def _write_records_unlocked(
        self, records: Mapping[str, IntegrationFlowRecord]
    ) -> None:
        payload = {
            "schema_version": INTEGRATION_FLOW_SCHEMA_VERSION,
            "flows": [_private_record_to_dict(records[key]) for key in sorted(records)],
        }
        self._atomic_private_json(payload)

    def _atomic_private_json(self, payload: Mapping[str, Any]) -> None:
        self._ensure_root()
        fd, raw_path = tempfile.mkstemp(prefix=".flows-", dir=self.root)
        temp_path = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _ensure_root(self) -> None:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise IntegrationFlowError("integration flow root is unsafe")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)


def integration_flow_record_to_dict(record: IntegrationFlowRecord) -> dict[str, Any]:
    """Return the bounded public lifecycle projection."""
    return {
        "id": record.id,
        "plan_id": record.plan_id,
        "status": record.status.value,
        "source": record.source.value,
        "package_id": record.package_id,
        "package_version": record.package_version,
        "manifest_sha256": record.manifest_sha256,
        "target_id": record.target_id,
        "scope": record.scope.value,
        "verification_status": record.verification_status,
        "rollback_available": record.rollback_available,
        "error_code": record.error_code,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "events": [asdict(item) for item in record.events],
        "content_free": True,
    }


def _public_plan(
    request: Mapping[str, Any], resolved: _ResolvedPreview
) -> dict[str, Any]:
    assessment = assess_integration_package(resolved.package)
    requirements = tuple(resolved.package.requirements)
    network_required = any(
        item.type is IntegrationRequirementType.NETWORK for item in requirements
    ) or IntegrationFlowSource(request["source"]) in {
        IntegrationFlowSource.GIT,
        IntegrationFlowSource.MARKETPLACE,
    }
    native_consent = resolved.target.id in {
        CLAUDE_MCP_TARGET_DESCRIPTOR.id,
        GEMINI_MCP_TARGET_DESCRIPTOR.id,
        CODEX_PLUGIN_TARGET_DESCRIPTOR.id,
        CLAUDE_PLUGIN_TARGET_DESCRIPTOR.id,
        GEMINI_EXTENSION_TARGET_DESCRIPTOR.id,
    }
    semantic = {
        "schema_version": INTEGRATION_FLOW_SCHEMA_VERSION,
        "source": request["source"],
        "catalog_id": request.get("catalog_id"),
        "manifest_sha256": integration_package_semantic_hash(resolved.package),
        "target_id": resolved.target.id,
        "target_revision": resolved.target.revision,
        "scope": request["scope"],
        "workspace": request.get("workspace"),
        "configuration_sha256": _json_hash(request.get("configuration", {})),
        "native_plan_id": resolved.native_plan_id,
    }
    plan_id = f"plan_{_json_hash(semantic)}"
    return {
        "plan_id": plan_id,
        "package": {
            "id": resolved.package.id,
            "version": resolved.package.version,
            "publisher": resolved.package.publisher,
            "license": resolved.package.license,
            "source": resolved.package.source,
            "source_type": resolved.package.source_type.value,
            "immutable_ref": resolved.package.immutable_ref,
            "checksum": resolved.package.checksum,
            "manifest_sha256": integration_package_semantic_hash(resolved.package),
        },
        "target": {
            "id": resolved.target.id,
            "revision": resolved.target.revision,
            "scope": request["scope"],
            "execution_owner": resolved.execution_owner,
            "executable": resolved.executable,
        },
        "risk": {
            "decision": assessment.decision.value,
            "install_authorized": assessment.install_authorized,
            "diagnostics": [
                {
                    "code": item.code,
                    "subject_id": item.subject_id,
                    "classification": item.classification.value,
                }
                for item in assessment.diagnostics
            ],
        },
        "permissions": {
            "network": network_required,
            "native_consent": native_consent,
            "user_home": request["scope"] == InstallationScope.USER_HOME.value,
            "requirements": [_requirement_to_dict(item) for item in requirements],
        },
        "configuration": {
            "diff": list(resolved.configuration_diff),
            "restart_required": resolved.restart_required,
            "fields": sorted(request.get("configuration", {})),
        },
        "verification_steps": list(resolved.package.verification_steps),
        "rollback_steps": list(resolved.package.rollback_steps),
        "handoff_reason": resolved.handoff_reason,
        "approval_required": True,
        "content_free": True,
    }


def _normalize_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("integration flow request must be an object")
    allowed = {
        "source",
        "catalog_id",
        "manifest",
        "target_id",
        "scope",
        "workspace",
        "package_id",
        "configuration",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError("integration flow request contains unknown fields")
    source = IntegrationFlowSource(str(payload.get("source") or ""))
    target_id = str(payload.get("target_id") or "")
    _target(target_id)
    scope = InstallationScope(str(payload.get("scope") or ""))
    catalog_id = payload.get("catalog_id")
    if catalog_id is not None:
        _validate_identity(str(catalog_id), field_name="catalog id")
    package_id = payload.get("package_id")
    if package_id is not None:
        _validate_identity(str(package_id), field_name="package id")
    workspace = payload.get("workspace")
    if workspace is not None and (
        not isinstance(workspace, str) or not workspace.strip()
    ):
        raise ValueError("workspace must be a non-empty path")
    configuration = payload.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ValueError("configuration must be an object")
    _validate_configuration(configuration)
    manifest = payload.get("manifest")
    if manifest is not None:
        if not isinstance(manifest, Mapping):
            raise ValueError("manifest must be an object")
        manifest = integration_package_to_dict(integration_package_from_dict(manifest))
    return {
        "source": source.value,
        "catalog_id": str(catalog_id) if catalog_id is not None else None,
        "manifest": manifest,
        "target_id": target_id,
        "scope": scope.value,
        "workspace": str(Path(workspace).expanduser().resolve()) if workspace else None,
        "package_id": str(package_id) if package_id is not None else None,
        "configuration": _json_value(configuration),
    }


def _raw_mcp_package(
    request: Mapping[str, Any],
    target: ExtensionTargetDescriptor,
    scope: InstallationScope,
) -> IntegrationPackage:
    if IntegrationComponentType.MCP not in target.component_types:
        raise ValueError("raw descriptors are supported only by MCP targets")
    package_id = str(request.get("package_id") or "")
    _validate_identity(package_id, field_name="raw descriptor package id")
    configuration = request.get("configuration")
    if not isinstance(configuration, Mapping):
        raise ValueError("raw descriptor configuration is required")
    transport = str(configuration.get("transport") or "")
    if transport not in {"stdio", "http", "sse", "streamable_http"}:
        raise ValueError("raw MCP transport is unsupported")
    if transport == "stdio":
        command = configuration.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("raw stdio MCP descriptor requires a command")
    else:
        url = configuration.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("raw network MCP descriptor requires an HTTPS URL")
    canonical = _json_value(configuration)
    descriptor_hash = _json_hash(canonical)
    requirements: list[IntegrationRequirement] = []
    if transport == "stdio":
        requirements.append(
            IntegrationRequirement(
                id="mcp-command",
                type=IntegrationRequirementType.COMMAND,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Start the reviewed MCP server command.",
                argv=(str(configuration["command"]),),
                environment=tuple(
                    str(item) for item in configuration.get("env_vars", ())
                ),
            )
        )
    else:
        url = str(configuration["url"])
        origin = "/".join(url.split("/", 3)[:3])
        requirements.append(
            IntegrationRequirement(
                id="mcp-network",
                type=IntegrationRequirementType.NETWORK,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Connect to the reviewed MCP server origin.",
                locator=origin,
            )
        )
    for index, env_name in enumerate(configuration.get("env_vars", ())):
        requirements.append(
            IntegrationRequirement(
                id=f"mcp-secret-{index + 1}",
                type=IntegrationRequirementType.SECRET,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Resolve a named environment reference at target runtime.",
                secret_owner="environment",
            )
        )
    return IntegrationPackage(
        id=package_id,
        version=f"raw-{descriptor_hash[:12]}",
        publisher="local-operator",
        license="NOASSERTION",
        source_type=IntegrationSourceType.RAW_MCP,
        source=f"raw-mcp://{package_id}",
        immutable_ref=f"descriptor:{descriptor_hash}",
        checksum=f"sha256:{descriptor_hash}",
        components=(
            IntegrationComponent(
                id=f"{package_id}-mcp",
                type=IntegrationComponentType.MCP,
                portable=True,
            ),
        ),
        requirements=tuple(requirements),
        overlays=(
            IntegrationTargetOverlay(
                target_id=target.id,
                component_ids=(f"{package_id}-mcp",),
                requirement_ids=tuple(item.id for item in requirements),
            ),
        ),
        compatibility=(IntegrationCompatibility(target_id=target.id),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("native-discovery",),
        rollback_steps=("restore-target-snapshot",),
    )


def _validate_target_compatibility(
    package: IntegrationPackage,
    target: ExtensionTargetDescriptor,
    scope: InstallationScope,
) -> None:
    if scope not in package.scopes:
        raise ValueError("package does not support the selected scope")
    if not any(item.target_id == target.id for item in package.compatibility):
        raise ValueError("package is not compatible with the selected target")
    component_types = {item.type for item in package.components}
    if not component_types & set(target.component_types):
        raise ValueError("package has no component supported by the selected target")
    assessment = assess_integration_package(package)
    if assessment.decision is IntegrationTrustDecision.BLOCKED:
        raise ValueError("package trust assessment is blocked")


def _catalog_entry_to_dict(entry: CatalogEntry) -> dict[str, Any]:
    package = entry.package
    federated = entry.federated
    return {
        "catalog_id": entry.catalog_id,
        "source_id": entry.source_id,
        "source_type": entry.source_type.value,
        "package_id": entry.package_id,
        "version": entry.version,
        "immutable_ref": entry.immutable_ref,
        "content_hash": entry.content_hash,
        "status": entry.status.value,
        "pinned": entry.pinned,
        "source_present": entry.source_present,
        "install_authorized": False,
        "trust_decision": entry.trust_decision.value,
        "component_types": (
            sorted({item.type.value for item in package.components})
            if package
            else ([federated.component] if federated is not None else [])
        ),
        "target_ids": (
            sorted(item.target_id for item in package.compatibility) if package else []
        ),
        "scopes": [item.value for item in package.scopes] if package else [],
        "discovery": (
            {
                "upstream_id": federated.upstream_id,
                "canonical_package_id": federated.canonical_package_id,
                "name": federated.name,
                "component": federated.component,
                "canonical_origin": federated.canonical_origin,
                "detail_url": federated.detail_url,
                "artifact_url": federated.artifact_url,
                "curated": federated.curated,
                "popularity": federated.popularity,
                "upstream_audit": federated.upstream_audit,
                "artifact_resolved": federated.artifact_resolved,
                "source_present": federated.source_present,
                "install_authorized": False,
            }
            if federated is not None
            else None
        ),
    }


def _requirement_to_dict(item: IntegrationRequirement) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type.value,
        "classification": item.classification.value,
        "reason": item.reason,
        "argv": list(item.argv),
        "locator": item.locator,
        "checksum": item.checksum,
        "secret_owner": item.secret_owner,
        "environment": list(item.environment),
    }


def _configuration_diff(configuration: object) -> tuple[str, ...]:
    if not isinstance(configuration, Mapping):
        return ()
    return tuple(f"set:{key}" for key in sorted(configuration))


def _execution_owner(target_id: str) -> str:
    if target_id in _SKILL_TARGETS:
        return "workbench_transactional_installer"
    if target_id == HARNESS_PACKAGE_TARGET.id:
        return "python_package_manager_and_adapter_sdk"
    return "provider_native_target_driver"


def _handoff_reason(target_id: str) -> str:
    if target_id == HARNESS_PACKAGE_TARGET.id:
        return (
            "Package installation and SDK conformance remain explicit client handoffs."
        )
    return (
        "The exact provider-native target driver owns mutation; this application "
        "flow retains the approved preview and handoff without bypassing consent."
    )


def _target(target_id: str) -> ExtensionTargetDescriptor:
    target = next((item for item in BUILTIN_FLOW_TARGETS if item.id == target_id), None)
    if target is None:
        raise ValueError("unknown integration target")
    return target


def _validate_configuration(configuration: Mapping[str, Any]) -> None:
    if len(configuration) > MAX_CONFIGURATION_FIELDS:
        raise ValueError("integration configuration has too many fields")
    for key, value in configuration.items():
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ValueError("integration configuration field is invalid")
        if _SENSITIVE_FIELD_RE.search(key) and not key.endswith("_env_var"):
            raise ValueError(
                "integration configuration accepts references, not secrets"
            )
        _json_value(value)


def _json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("integration payload nesting is too deep")
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("integration payload text is too long")
        return value
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("integration payload object is too large")
        return {
            str(key): _json_value(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 256:
            raise ValueError("integration payload list is too large")
        return [_json_value(item, depth=depth + 1) for item in value]
    raise ValueError("integration payload must contain JSON values only")


def _private_record_to_dict(record: IntegrationFlowRecord) -> dict[str, Any]:
    return {
        **integration_flow_record_to_dict(record),
        "workspace": record.workspace,
        "request": record.request,
        "receipt_id": record.receipt_id,
    }


def _record_from_dict(payload: object) -> IntegrationFlowRecord:
    if not isinstance(payload, Mapping):
        raise IntegrationFlowError("integration flow record is invalid")
    try:
        record = IntegrationFlowRecord(
            id=str(payload["id"]),
            plan_id=str(payload["plan_id"]),
            status=IntegrationFlowStatus(str(payload["status"])),
            source=IntegrationFlowSource(str(payload["source"])),
            package_id=str(payload["package_id"]),
            package_version=str(payload["package_version"]),
            manifest_sha256=str(payload["manifest_sha256"]),
            target_id=str(payload["target_id"]),
            scope=InstallationScope(str(payload["scope"])),
            workspace=(str(payload["workspace"]) if payload.get("workspace") else None),
            request=_normalize_request(payload["request"]),
            receipt_id=(
                str(payload["receipt_id"]) if payload.get("receipt_id") else None
            ),
            verification_status=str(payload["verification_status"]),
            rollback_available=bool(payload["rollback_available"]),
            error_code=(
                str(payload["error_code"]) if payload.get("error_code") else None
            ),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            events=tuple(
                IntegrationFlowEvent(
                    stage=str(item["stage"]),
                    status=str(item["status"]),
                    occurred_at=str(item["occurred_at"]),
                    code=str(item["code"]) if item.get("code") else None,
                )
                for item in payload["events"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrationFlowError("integration flow record is invalid") from exc
    _validate_flow_id(record.id)
    _validate_plan_id(record.plan_id)
    return record


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_flow_id(value: str) -> None:
    if _FLOW_ID_RE.fullmatch(value) is None:
        raise ValueError("integration flow id is invalid")


def _validate_plan_id(value: str) -> None:
    if _PLAN_ID_RE.fullmatch(value) is None:
        raise ValueError("integration plan id is invalid")


def _validate_identity(value: str, *, field_name: str) -> None:
    if _IDENTITY_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")


__all__ = [
    "BUILTIN_FLOW_TARGETS",
    "IntegrationFlowConflictError",
    "IntegrationFlowError",
    "IntegrationFlowNotFoundError",
    "IntegrationFlowRecord",
    "IntegrationFlowService",
    "IntegrationFlowSource",
    "IntegrationFlowStatus",
    "integration_flow_record_to_dict",
]
