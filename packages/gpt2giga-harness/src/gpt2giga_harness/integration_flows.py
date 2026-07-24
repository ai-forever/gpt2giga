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
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from gpt2giga_harness.builtin_skills import (
    BUILTIN_SKILL_SOURCE_ID,
    get_builtin_skill_bundle,
    import_builtin_skills,
)
from gpt2giga_harness.claude_mcp_target import (
    CLAUDE_MCP_TARGET_DESCRIPTOR,
    CLAUDE_MCP_TARGET_ID,
    ClaudeMCPRequest,
    ClaudeMCPTargetDriver,
)
from gpt2giga_harness.claude_plugin_target import (
    CLAUDE_PLUGIN_TARGET_DESCRIPTOR,
    CLAUDE_PLUGIN_TARGET_ID,
    ClaudePluginApproval,
    ClaudePluginRequest,
    ClaudePluginSource,
    ClaudePluginSourceKind,
    ClaudePluginTargetDriver,
)
from gpt2giga_harness.codex_mcp_target import (
    CODEX_MCP_TARGET_DESCRIPTOR,
    CODEX_MCP_TARGET_ID,
    CodexMCPRequest,
    CodexMCPTargetDriver,
)
from gpt2giga_harness.external_mcp import (
    HARNESS_MANAGED_MCP_TARGET_ID,
    ExternalMCPDescriptor,
    ExternalMCPToolPolicy,
    external_mcp_selection_from_dict,
    external_mcp_server_spec,
    normalize_external_mcp_candidate,
    project_external_mcp_target,
)
from gpt2giga_harness.external_skills import ExternalSkillStore, parse_external_skill
from gpt2giga_harness.codex_plugin_target import (
    CODEX_PLUGIN_TARGET_DESCRIPTOR,
    CODEX_PLUGIN_TARGET_ID,
    CodexPluginApproval,
    CodexPluginRequest,
    CodexPluginSource,
    CodexPluginSourceKind,
    CodexPluginTargetDriver,
)
from gpt2giga_harness.gemini_extension_target import (
    GEMINI_EXTENSION_TARGET_DESCRIPTOR,
    GEMINI_EXTENSION_TARGET_ID,
    GeminiExtensionApproval,
    GeminiExtensionHandoff,
    GeminiExtensionRequest,
    GeminiExtensionSource,
    GeminiExtensionSourceKind,
    GeminiExtensionTargetDriver,
)
from gpt2giga_harness.gemini_mcp_target import (
    GEMINI_MCP_TARGET_DESCRIPTOR,
    GEMINI_MCP_TARGET_ID,
    GeminiMCPRequest,
    GeminiMCPTargetDriver,
)
from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    CatalogSourceType,
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
from gpt2giga_harness.managed_mcp_inventory import ManagedMCPInventoryStore
from gpt2giga_harness.mcp_authoring import (
    MCPAuthoringTransport,
    mcp_authoring_configuration_from_dict,
    resolve_mcp_authoring_cwd,
)
from gpt2giga_harness.mcp import MCPTransport
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
    SkillCapabilitySnapshot,
    build_skill_installation_request,
    discover_generated_skill,
    generate_skill_package,
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
    source_provenance: Mapping[str, Any] | None = None


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
    configuration_preview: Mapping[str, Any] | None = None
    source_provenance: Mapping[str, Any] | None = None


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

_PLUGIN_TARGET_IDS = {
    CODEX_PLUGIN_TARGET_ID,
    CLAUDE_PLUGIN_TARGET_ID,
    GEMINI_EXTENSION_TARGET_ID,
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

HARNESS_MANAGED_MCP_TARGET = ExtensionTargetDescriptor(
    id=HARNESS_MANAGED_MCP_TARGET_ID,
    revision="1",
    component_types=(IntegrationComponentType.MCP,),
    scopes=(InstallationScope.MANAGED_HOME,),
    capabilities=("install", "verify", "rollback", "managed-mcp.inventory"),
    trust_evidence=(
        IntegrationTrustEvidence(
            id="harness-managed-mcp-inventory",
            kind=IntegrationTrustKind.SOURCE,
            status=IntegrationTrustStatus.VERIFIED,
            authority="gpt2giga-harness",
            revision="1",
        ),
    ),
)

_MCP_TARGET_IDS = {
    CODEX_MCP_TARGET_ID,
    CLAUDE_MCP_TARGET_ID,
    GEMINI_MCP_TARGET_ID,
    HARNESS_MANAGED_MCP_TARGET_ID,
}

BUILTIN_FLOW_TARGETS = tuple(
    sorted(
        (
            CODEX_MCP_TARGET_DESCRIPTOR,
            CLAUDE_MCP_TARGET_DESCRIPTOR,
            GEMINI_MCP_TARGET_DESCRIPTOR,
            CODEX_PLUGIN_TARGET_DESCRIPTOR,
            CLAUDE_PLUGIN_TARGET_DESCRIPTOR,
            GEMINI_EXTENSION_TARGET_DESCRIPTOR,
            HARNESS_MANAGED_MCP_TARGET,
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
        mcp_driver_provider: Callable[[str], Any] | None = None,
        plugin_driver_provider: Callable[[str, Path, InstallationScope], Any]
        | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "integrations"
        self.path = self.root / "flows.json"
        self.lock_path = self.root / ".flows.json.lock"
        self.catalog = IntegrationCatalogStore(self.data_dir)
        self._external_skill_store = ExternalSkillStore(
            self.data_dir / "integrations" / "external-skills"
        )
        self._skill_capability_provider = (
            skill_capability_provider or probe_skill_target
        )
        self._mcp_driver_provider = mcp_driver_provider or self._default_mcp_driver
        self._plugin_driver_provider = plugin_driver_provider
        self._managed_mcp_inventory = ManagedMCPInventoryStore(self.data_dir)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def inventory(self) -> dict[str, Any]:
        """Return bounded sources, targets, catalog entries, and recent flows."""
        self._ensure_catalog_seeded()
        snapshot = self.catalog.snapshot()
        entries = tuple(snapshot.entries)
        now = self._now().astimezone(timezone.utc)
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
            "catalog_sources": [
                _catalog_source_to_dict(item, now=now) for item in snapshot.sources
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
            source_provenance=resolved.source_provenance,
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

    def probe(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve one immutable package without persisting an approval flow."""
        request = _normalize_request(payload)
        resolved = self._resolve_preview(request)
        return {"plan": _public_plan(request, resolved)}

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
            if resolved.target.id in _SKILL_TARGETS:
                receipt_id, verification_status = self._apply_skill(
                    record.request,
                    resolved,
                    authority=authority,
                    allow_user_home=allow_user_home,
                )
            elif resolved.target.id in _MCP_TARGET_IDS:
                receipt_id, verification_status = self._apply_mcp(
                    record.request,
                    resolved,
                    authority=authority,
                    allow_user_home=allow_user_home,
                )
            else:
                receipt_id, verification_status = self._apply_plugin(
                    record.request,
                    resolved,
                    authority=authority,
                    allow_network=allow_network,
                    allow_user_home=allow_user_home,
                    native_consent_acknowledged=native_consent_acknowledged,
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
            if resolved.target.id in _MCP_TARGET_IDS:
                self._rollback_mcp(record, resolved)
            elif resolved.target.id in _SKILL_TARGETS:
                installer = self._skill_installer(record.request, resolved.root)
                installer.rollback(record.receipt_id)
            elif resolved.target.id in _PLUGIN_TARGET_IDS:
                scope = InstallationScope(record.request["scope"])
                native_request = self._plugin_request(
                    record.request,
                    resolved.package,
                    resolved.target.id,
                    resolved.root,
                    scope,
                )
                self._plugin_driver(resolved.target.id, resolved.root, scope).rollback(
                    native_request
                )
            else:
                raise IntegrationFlowConflictError(
                    "rollback remains owned by the selected native target"
                )
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

    def uninstall_owned(
        self,
        flow_id: str,
        *,
        receipt_id: str,
        authority: str,
        allow_user_home: bool = False,
    ) -> dict[str, Any]:
        """Remove only material owned by one exact verified installation."""
        record = self.get(flow_id)
        _validate_identity(authority, field_name="approval authority")
        if (
            record.status is not IntegrationFlowStatus.VERIFIED
            or record.receipt_id is None
            or record.receipt_id != receipt_id
        ):
            raise IntegrationFlowConflictError(
                "uninstall requires the exact verified installation receipt"
            )
        target = _target(record.target_id)
        root = self._target_root(record.request, target, create=False)
        package = self._resolve_package(
            record.request,
            record.source,
            target,
            record.scope,
        )
        try:
            if target.id in _SKILL_TARGETS:
                result = self._skill_installer(record.request, root).rollback(
                    receipt_id
                )
                outcome = result.status
            elif target.id == HARNESS_MANAGED_MCP_TARGET_ID:
                result = self._managed_mcp_inventory.rollback(receipt_id)
                outcome = result.status
            elif target.id in _MCP_TARGET_IDS:
                driver = self._mcp_driver_provider(target.id)
                plan = driver.preview_uninstall(receipt_id)
                result = driver.uninstall(
                    plan,
                    InstallationApproval(
                        plan_id=plan.plan_id,
                        authority=authority,
                        allow_user_home=allow_user_home,
                    ),
                )
                outcome = result.status
            elif target.id in _PLUGIN_TARGET_IDS:
                driver = self._plugin_driver(target.id, root, record.scope)
                native_request = self._plugin_request(
                    record.request,
                    package,
                    target.id,
                    root,
                    record.scope,
                )
                plan = driver.preview_uninstall(native_request)
                if target.id == CODEX_PLUGIN_TARGET_ID:
                    approval = CodexPluginApproval(
                        plan_id=plan.plan_id,
                        authority=authority,
                        native_consent_acknowledged=True,
                        allow_user_home=allow_user_home,
                    )
                elif target.id == CLAUDE_PLUGIN_TARGET_ID:
                    approval = ClaudePluginApproval(
                        plan_id=plan.plan_id,
                        authority=authority,
                        native_consent_acknowledged=True,
                        allow_user_home=allow_user_home,
                    )
                else:
                    approval = GeminiExtensionApproval(
                        plan_id=plan.plan_id,
                        authority=authority,
                        native_consent_acknowledged=True,
                        source_trust_acknowledged=True,
                        allow_user_home=allow_user_home,
                    )
                result = driver.uninstall(native_request, plan, approval)
                outcome = result.status
            else:
                raise IntegrationFlowConflictError(
                    "selected target has no application-owned uninstall surface"
                )
            return {
                "flow_id": record.id,
                "receipt_id": receipt_id,
                "status": str(outcome),
                "installer_owned_only": True,
                "content_free": True,
            }
        except IntegrationFlowConflictError:
            raise
        except Exception as exc:
            raise IntegrationFlowError(
                "integration uninstall failed; details were omitted"
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
        source_provenance = self._source_provenance(request)
        _validate_target_compatibility(package, target, scope)
        if target.id in _SKILL_TARGETS:
            skill = self._portable_skill_for_package(package)
            capability = self._skill_capability_provider(target.id)
            generated = generate_skill_package(skill, capability)
            install_request = build_skill_installation_request(
                package,
                skill,
                generated,
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
                source_provenance=source_provenance,
            )
        if (
            target.id in _MCP_TARGET_IDS
            and source is IntegrationFlowSource.CATALOG
            and self.catalog.get(str(request.get("catalog_id") or "")) is not None
            and self.catalog.get(str(request.get("catalog_id") or "")).mcp_response
            is not None
        ):
            descriptor = self._external_mcp_descriptor(request)
            target_preview = project_external_mcp_target(descriptor, target.id)
            if not target_preview.supported:
                raise ValueError(
                    "external MCP target is incompatible: "
                    f"{target_preview.error_code or 'unknown'}"
                )
            if target.id == HARNESS_MANAGED_MCP_TARGET_ID:
                native = self._managed_mcp_inventory.preview(descriptor)
                configuration_diff = (
                    ("create:managed-mcp-inventory",) if native.changed else ()
                )
                native_plan_id = native.plan_id
                execution_owner = "harness_managed_mcp_inventory"
                restart_required = False
            else:
                driver = self._mcp_driver_provider(target.id)
                native_request = self._mcp_request(descriptor, target.id, root, scope)
                native = driver.preview_install(native_request)
                configuration_diff = tuple(
                    f"{'update' if item.current_sha256 else 'create'}:{item.relative_path}"
                    for item in native.installation.mutations
                )
                native_plan_id = native.plan_id
                execution_owner = "provider_native_target_driver"
                restart_required = True
            return _ResolvedPreview(
                package=descriptor.to_integration_package(),
                target=target,
                root=root,
                executable=True,
                execution_owner=execution_owner,
                native_plan_id=native_plan_id,
                configuration_diff=configuration_diff,
                restart_required=restart_required,
                source_provenance=source_provenance,
            )
        if (
            target.id in _MCP_TARGET_IDS
            and source is IntegrationFlowSource.RAW_DESCRIPTOR
        ):
            descriptor = self._raw_mcp_descriptor(request, root)
            target_preview = project_external_mcp_target(descriptor, target.id)
            if not target_preview.supported:
                raise ValueError(
                    "raw MCP target is incompatible: "
                    f"{target_preview.error_code or 'unknown'}"
                )
            if target.id == HARNESS_MANAGED_MCP_TARGET_ID:
                native = self._managed_mcp_inventory.preview(descriptor)
                configuration_diff = (
                    ("create:managed-mcp-inventory",) if native.changed else ()
                )
                native_plan_id = native.plan_id
                execution_owner = "harness_managed_mcp_inventory"
                restart_required = False
            else:
                driver = self._mcp_driver_provider(target.id)
                native = driver.preview_install(
                    self._raw_mcp_request(request, package, target.id, root, scope)
                )
                configuration_diff = tuple(
                    f"{'update' if item.current_sha256 else 'create'}:{item.relative_path}"
                    for item in native.installation.mutations
                )
                native_plan_id = native.plan_id
                execution_owner = "provider_native_target_driver"
                restart_required = True
            return _ResolvedPreview(
                package=package,
                target=target,
                root=root,
                executable=True,
                execution_owner=execution_owner,
                native_plan_id=native_plan_id,
                configuration_diff=configuration_diff,
                restart_required=restart_required,
                configuration_preview={
                    "transport": descriptor.transport.value,
                    "target": dict(target_preview.configuration),
                    "secret_references": list(target_preview.secret_references),
                },
                source_provenance=source_provenance,
            )
        if target.id in _PLUGIN_TARGET_IDS:
            driver = self._plugin_driver(target.id, root, scope)
            native_request = self._plugin_request(
                request, package, target.id, root, scope
            )
            native = driver.preview_install(native_request)
            return _ResolvedPreview(
                package=package,
                target=target,
                root=root,
                executable=True,
                execution_owner="provider_native_target_driver",
                native_plan_id=native.plan_id,
                configuration_diff=tuple(
                    f"native-command:{item}"
                    for item in getattr(native, "command_ids", ())
                ),
                restart_required=bool(getattr(native, "restart_required", True)),
                source_provenance=source_provenance,
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
            source_provenance=source_provenance,
        )

    def _source_provenance(
        self, request: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        if request.get("source") != IntegrationFlowSource.CATALOG.value:
            return None
        catalog_id = str(request.get("catalog_id") or "")
        entry = self.catalog.get(catalog_id) if catalog_id else None
        if entry is None or entry.federated is None:
            return None
        metadata = entry.federated
        return {
            "canonical_source": entry.source_id,
            "upstream_id": metadata.upstream_id,
            "canonical_origin": metadata.canonical_origin,
            "repository_url": metadata.artifact_url,
            "artifact_url": metadata.artifact_url,
            "immutable_ref": metadata.immutable_ref or entry.immutable_ref,
            "content_hash": metadata.content_hash or entry.content_hash,
            "relative_path": metadata.relative_path,
            "discovery_location": metadata.discovery_location
            or f"{entry.source_id}/{metadata.upstream_id}",
            "observed_at": metadata.observed_at or entry.last_seen_at,
        }

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
            if entry is None:
                raise ValueError("catalog selection requires an exact package entry")
            if entry.package is not None:
                return entry.package
            if entry.mcp_response is not None:
                descriptor = self._external_mcp_descriptor(request)
                preview = project_external_mcp_target(descriptor, target.id)
                if not preview.supported:
                    raise ValueError(
                        "external MCP target is incompatible: "
                        f"{preview.error_code or 'unknown'}"
                    )
                return descriptor.to_integration_package()
            raise ValueError("catalog selection requires an exact package entry")
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
                if item.package_id == package.id and item.version == package.version
            ),
            None,
        )
        if entry is None or entry.package != package:
            raise ValueError("portable skill execution requires an exact catalog pin")
        return entry

    def _portable_skill_for_package(self, package: IntegrationPackage):
        entry = self._catalog_entry_for_package(package)
        if entry.source_id == BUILTIN_SKILL_SOURCE_ID:
            return get_builtin_skill_bundle(package.id).skill
        digest = package.checksum.removeprefix("sha256:")
        try:
            artifact = self._external_skill_store.resolve(digest)
            return parse_external_skill(artifact)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "external Skill artifact is unavailable or drifted"
            ) from exc

    def _apply_skill(
        self,
        request: Mapping[str, Any],
        resolved: _ResolvedPreview,
        *,
        authority: str,
        allow_user_home: bool,
    ) -> tuple[str, str]:
        skill = self._portable_skill_for_package(resolved.package)
        capability = self._skill_capability_provider(resolved.target.id)
        generated = generate_skill_package(skill, capability)
        install_request = build_skill_installation_request(
            resolved.package,
            skill,
            generated,
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

    def _apply_mcp(
        self,
        request: Mapping[str, Any],
        resolved: _ResolvedPreview,
        *,
        authority: str,
        allow_user_home: bool,
    ) -> tuple[str, str]:
        if (
            IntegrationFlowSource(request["source"])
            is IntegrationFlowSource.RAW_DESCRIPTOR
        ):
            if resolved.target.id == HARNESS_MANAGED_MCP_TARGET_ID:
                descriptor = self._raw_mcp_descriptor(request, resolved.root)
                plan = self._managed_mcp_inventory.preview(descriptor)
                if plan.plan_id != resolved.native_plan_id:
                    raise InstallationConflictError(
                        "target preview changed before apply"
                    )
                result = self._managed_mcp_inventory.apply(
                    descriptor, plan, authority=authority
                )
                verified = self._managed_mcp_inventory.verify(result.transaction_id)
                return verified.transaction_id, "inventory_verified"
            driver = self._mcp_driver_provider(resolved.target.id)
            native_request = self._raw_mcp_request(
                request,
                resolved.package,
                resolved.target.id,
                resolved.root,
                InstallationScope(request["scope"]),
            )
            plan = driver.preview_install(native_request)
            if plan.plan_id != resolved.native_plan_id:
                raise InstallationConflictError("target preview changed before apply")
            result = driver.install(
                native_request,
                plan,
                InstallationApproval(
                    plan_id=plan.plan_id,
                    authority=authority,
                    allow_user_home=allow_user_home,
                ),
            )
            health = driver.verify(result.transaction_id)
            if getattr(health, "status", None) != "healthy":
                raise IntegrationFlowError("native MCP discovery did not verify")
            return result.transaction_id, "native_verified"
        descriptor = self._external_mcp_descriptor(request)
        if resolved.target.id == HARNESS_MANAGED_MCP_TARGET_ID:
            plan = self._managed_mcp_inventory.preview(descriptor)
            if plan.plan_id != resolved.native_plan_id:
                raise InstallationConflictError("target preview changed before apply")
            result = self._managed_mcp_inventory.apply(
                descriptor, plan, authority=authority
            )
            verified = self._managed_mcp_inventory.verify(result.transaction_id)
            return verified.transaction_id, "inventory_verified"
        driver = self._mcp_driver_provider(resolved.target.id)
        native_request = self._mcp_request(
            descriptor,
            resolved.target.id,
            resolved.root,
            InstallationScope(request["scope"]),
        )
        plan = driver.preview_install(native_request)
        if plan.plan_id != resolved.native_plan_id:
            raise InstallationConflictError("target preview changed before apply")
        result = driver.install(
            native_request,
            plan,
            InstallationApproval(
                plan_id=plan.plan_id,
                authority=authority,
                allow_user_home=allow_user_home,
            ),
        )
        health = driver.verify(result.transaction_id)
        if getattr(health, "status", None) != "healthy":
            raise IntegrationFlowError("native MCP discovery did not verify")
        return result.transaction_id, "native_verified"

    def _rollback_mcp(
        self, record: IntegrationFlowRecord, resolved: _ResolvedPreview
    ) -> None:
        if record.receipt_id is None:
            raise IntegrationFlowConflictError("MCP flow receipt is missing")
        if resolved.target.id == HARNESS_MANAGED_MCP_TARGET_ID:
            self._managed_mcp_inventory.rollback(record.receipt_id)
            return
        self._mcp_driver_provider(resolved.target.id).rollback(record.receipt_id)

    def _apply_plugin(
        self,
        request: Mapping[str, Any],
        resolved: _ResolvedPreview,
        *,
        authority: str,
        allow_network: bool,
        allow_user_home: bool,
        native_consent_acknowledged: bool,
    ) -> tuple[str, str]:
        scope = InstallationScope(request["scope"])
        driver = self._plugin_driver(resolved.target.id, resolved.root, scope)
        native_request = self._plugin_request(
            request, resolved.package, resolved.target.id, resolved.root, scope
        )
        plan = driver.preview_install(native_request)
        if plan.plan_id != resolved.native_plan_id:
            raise InstallationConflictError("target preview changed before apply")
        if resolved.target.id == CODEX_PLUGIN_TARGET_ID:
            driver.install(
                native_request,
                plan,
                CodexPluginApproval(
                    plan_id=plan.plan_id,
                    authority=authority,
                    native_consent_acknowledged=native_consent_acknowledged,
                    allow_network=allow_network,
                    allow_user_home=allow_user_home,
                ),
            )
        elif resolved.target.id == CLAUDE_PLUGIN_TARGET_ID:
            driver.install(
                native_request,
                plan,
                ClaudePluginApproval(
                    plan_id=plan.plan_id,
                    authority=authority,
                    native_consent_acknowledged=native_consent_acknowledged,
                    allow_network=allow_network,
                    allow_user_home=allow_user_home,
                ),
            )
        else:
            result = driver.install(
                native_request,
                plan,
                GeminiExtensionApproval(
                    plan_id=plan.plan_id,
                    authority=authority,
                    native_consent_acknowledged=native_consent_acknowledged,
                    source_trust_acknowledged=native_consent_acknowledged,
                    allow_network=allow_network,
                    allow_user_home=allow_user_home,
                ),
            )
            if isinstance(result, GeminiExtensionHandoff):
                raise IntegrationFlowError("Gemini gallery requires provider handoff")
        health = driver.verify(native_request)
        if getattr(health, "status", None) != "healthy":
            raise IntegrationFlowError("native Plugin discovery did not verify")
        return str(resolved.native_plan_id), "native_verified"

    def _external_mcp_descriptor(
        self, request: Mapping[str, Any]
    ) -> ExternalMCPDescriptor:
        if (
            IntegrationFlowSource(request["source"])
            is not IntegrationFlowSource.CATALOG
        ):
            raise ValueError("managed external MCP execution requires a catalog pin")
        catalog_id = str(request.get("catalog_id") or "")
        entry = self.catalog.get(catalog_id) if catalog_id else None
        if entry is None or entry.mcp_response is None:
            raise ValueError("external MCP execution requires an official Registry pin")
        configuration = request.get("configuration")
        if not isinstance(configuration, Mapping):
            raise ValueError("external MCP configuration is invalid")
        selection = external_mcp_selection_from_dict(configuration.get("selection"))
        discovery = None
        discovery_id = configuration.get("discovery_catalog_id")
        if discovery_id is not None:
            discovery = self.catalog.get(str(discovery_id))
            if discovery is None:
                raise ValueError("external MCP discovery entry was not found")
        return normalize_external_mcp_candidate(
            entry,
            selection,
            discovery_entry=discovery,
        )

    def _mcp_request(
        self,
        descriptor: ExternalMCPDescriptor,
        target_id: str,
        root: Path,
        scope: InstallationScope,
    ) -> CodexMCPRequest | ClaudeMCPRequest | GeminiMCPRequest:
        package = descriptor.to_integration_package()
        spec = external_mcp_server_spec(descriptor, target_id)
        if target_id == CODEX_MCP_TARGET_ID:
            return CodexMCPRequest(package=package, scope=scope, root=root, server=spec)
        if target_id == CLAUDE_MCP_TARGET_ID:
            return ClaudeMCPRequest(
                package=package, scope=scope, root=root, server=spec
            )
        if target_id == GEMINI_MCP_TARGET_ID:
            return GeminiMCPRequest(
                package=package, scope=scope, root=root, server=spec
            )
        raise ValueError("external MCP native target is unsupported")

    def _raw_mcp_request(
        self,
        request: Mapping[str, Any],
        package: IntegrationPackage,
        target_id: str,
        root: Path,
        scope: InstallationScope,
    ) -> CodexMCPRequest | ClaudeMCPRequest | GeminiMCPRequest:
        descriptor = self._raw_mcp_descriptor(request, root)
        spec = external_mcp_server_spec(descriptor, target_id)
        if target_id == CODEX_MCP_TARGET_ID:
            return CodexMCPRequest(package=package, scope=scope, root=root, server=spec)
        if target_id == CLAUDE_MCP_TARGET_ID:
            return ClaudeMCPRequest(
                package=package, scope=scope, root=root, server=spec
            )
        if target_id == GEMINI_MCP_TARGET_ID:
            return GeminiMCPRequest(
                package=package, scope=scope, root=root, server=spec
            )
        raise ValueError("raw MCP native target is unsupported")

    def _raw_mcp_descriptor(
        self,
        request: Mapping[str, Any],
        root: Path,
    ) -> ExternalMCPDescriptor:
        configuration = request.get("configuration")
        if not isinstance(configuration, Mapping):
            raise ValueError("raw MCP configuration is invalid")
        target_id = str(request.get("target_id") or "")
        authored = mcp_authoring_configuration_from_dict(
            configuration,
            target_id=target_id,
        )
        package_id = str(request.get("package_id") or "")
        transport = (
            MCPTransport.STDIO
            if authored.transport is MCPAuthoringTransport.STDIO
            else MCPTransport.SSE
            if authored.transport is MCPAuthoringTransport.SSE
            else MCPTransport.STREAMABLE_HTTP
        )
        cwd = resolve_mcp_authoring_cwd(root, authored.cwd)
        content_hash = hashlib.sha256(
            json.dumps(
                {
                    "id": package_id,
                    "configuration": authored.to_dict(),
                    "cwd": cwd,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        network_origins = ()
        if authored.url is not None:
            parsed = urlsplit(authored.url)
            network_origins = (urlunsplit((parsed.scheme, parsed.netloc, "", "", "")),)
        return ExternalMCPDescriptor(
            id=package_id,
            official_name=package_id,
            version="0.0.0",
            title=package_id,
            description="Operator-reviewed MCP server",
            catalog_id=f"raw:{package_id}",
            immutable_ref=f"sha256:{content_hash}",
            content_hash=content_hash,
            transport=transport,
            command=authored.executable,
            args=authored.argv,
            cwd=cwd,
            url=authored.url,
            environment=authored.environment,
            headers=authored.headers,
            artifact=None,
            network_origins=network_origins,
            timeout_seconds=10,
            tool_policy=ExternalMCPToolPolicy(),
        )

    def _plugin_request(
        self,
        request: Mapping[str, Any],
        package: IntegrationPackage,
        target_id: str,
        root: Path,
        scope: InstallationScope,
    ) -> CodexPluginRequest | ClaudePluginRequest | GeminiExtensionRequest:
        configuration = request.get("configuration")
        if not isinstance(configuration, Mapping):
            raise ValueError("Plugin configuration is invalid")
        name = _plugin_name(package, configuration.get("plugin_name"))
        sparse_value = configuration.get("sparse", ())
        if not isinstance(sparse_value, (list, tuple)):
            raise ValueError("Plugin sparse paths must be a list")
        sparse = tuple(str(item) for item in sparse_value)
        is_local = package.source_type is IntegrationSourceType.LOCAL
        if target_id == CODEX_PLUGIN_TARGET_ID:
            source = CodexPluginSource(
                marketplace_name=name,
                kind=(
                    CodexPluginSourceKind.LOCAL
                    if is_local
                    else CodexPluginSourceKind.GIT
                ),
                location=package.source,
                ref=None if is_local else package.immutable_ref,
                sparse=() if is_local else sparse,
            )
            return CodexPluginRequest(package, scope, root, source, name)
        if target_id == CLAUDE_PLUGIN_TARGET_ID:
            source = ClaudePluginSource(
                marketplace_name=name,
                kind=(
                    ClaudePluginSourceKind.LOCAL
                    if is_local
                    else ClaudePluginSourceKind.GIT
                ),
                location=package.source,
                ref=None if is_local else package.immutable_ref,
                sparse=() if is_local else sparse,
            )
            return ClaudePluginRequest(package, scope, root, source, name)
        if target_id == GEMINI_EXTENSION_TARGET_ID:
            source = GeminiExtensionSource(
                kind=(
                    GeminiExtensionSourceKind.LOCAL
                    if is_local
                    else GeminiExtensionSourceKind.GALLERY
                    if package.source_type is IntegrationSourceType.PROVIDER_MARKETPLACE
                    else GeminiExtensionSourceKind.GIT
                ),
                location=package.source,
                ref=(
                    package.immutable_ref
                    if package.source_type is IntegrationSourceType.GIT
                    else None
                ),
            )
            return GeminiExtensionRequest(package, scope, root, source, name)
        raise ValueError("Plugin native target is unsupported")

    def _plugin_driver(
        self, target_id: str, root: Path, scope: InstallationScope
    ) -> Any:
        if self._plugin_driver_provider is not None:
            return self._plugin_driver_provider(target_id, root, scope)
        managed_roots = (root,) if scope is InstallationScope.MANAGED_HOME else ()
        project_roots = (root,) if scope is InstallationScope.PROJECT else ()
        if target_id == CODEX_PLUGIN_TARGET_ID:
            return CodexPluginTargetDriver(
                self.data_dir,
                managed_roots=managed_roots,
                source_roots=project_roots,
            )
        if target_id == CLAUDE_PLUGIN_TARGET_ID:
            return ClaudePluginTargetDriver(
                self.data_dir,
                managed_roots=managed_roots,
                project_roots=project_roots,
                source_roots=project_roots,
            )
        if target_id == GEMINI_EXTENSION_TARGET_ID:
            return GeminiExtensionTargetDriver(
                self.data_dir,
                managed_roots=managed_roots,
                project_roots=project_roots,
                source_roots=project_roots,
            )
        raise ValueError("Plugin native target is unsupported")

    def _default_mcp_driver(self, target_id: str) -> Any:
        if target_id == CODEX_MCP_TARGET_ID:
            return CodexMCPTargetDriver(self.data_dir)
        if target_id == CLAUDE_MCP_TARGET_ID:
            return ClaudeMCPTargetDriver(self.data_dir)
        if target_id == GEMINI_MCP_TARGET_ID:
            return GeminiMCPTargetDriver(self.data_dir)
        raise ValueError("external MCP native target is unsupported")

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
        "source_provenance": (
            dict(record.source_provenance)
            if record.source_provenance is not None
            else None
        ),
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
        CODEX_MCP_TARGET_DESCRIPTOR.id,
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
        "source_provenance": resolved.source_provenance,
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
            "source_provenance": (
                dict(resolved.source_provenance)
                if resolved.source_provenance is not None
                else None
            ),
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
            "preview": dict(resolved.configuration_preview or {}),
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
    if source is IntegrationFlowSource.RAW_DESCRIPTOR:
        configuration = mcp_authoring_configuration_from_dict(
            configuration,
            target_id=target_id,
        ).to_dict()
    else:
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
    authored = mcp_authoring_configuration_from_dict(
        configuration,
        target_id=target.id,
    )
    canonical = authored.to_dict()
    descriptor_hash = _json_hash(canonical)
    requirements: list[IntegrationRequirement] = []
    if authored.transport is MCPAuthoringTransport.STDIO:
        requirements.append(
            IntegrationRequirement(
                id="mcp-command",
                type=IntegrationRequirementType.COMMAND,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Start the reviewed MCP server command.",
                argv=(str(authored.executable), *authored.argv),
                environment=tuple(authored.environment),
            )
        )
    else:
        parsed_url = urlsplit(str(authored.url))
        origin = urlunsplit((parsed_url.scheme, parsed_url.netloc, "", "", ""))
        requirements.append(
            IntegrationRequirement(
                id="mcp-network",
                type=IntegrationRequirementType.NETWORK,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Connect to the reviewed MCP server origin.",
                locator=origin,
            )
        )
    secret_names = sorted(set(authored.environment) | set(authored.headers))
    for index, _name in enumerate(secret_names):
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


def _plugin_name(package: IntegrationPackage, configured: Any) -> str:
    raw = str(configured or "")
    if not raw:
        component = next(
            (
                item
                for item in package.components
                if item.type
                in {IntegrationComponentType.PLUGIN, IntegrationComponentType.EXTENSION}
            ),
            None,
        )
        raw = component.id if component is not None else package.id
    normalized = re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")
    if not normalized:
        raise ValueError("Plugin name is invalid")
    return normalized[:64].rstrip("-")


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
            else (
                [federated.component]
                if federated is not None
                else (
                    [IntegrationComponentType.MCP.value] if entry.mcp_response else []
                )
            )
        ),
        "target_ids": (
            sorted(item.target_id for item in package.compatibility)
            if package
            else (sorted(_MCP_TARGET_IDS) if entry.mcp_response else [])
        ),
        "scopes": (
            [item.value for item in package.scopes]
            if package
            else ([InstallationScope.MANAGED_HOME.value] if entry.mcp_response else [])
        ),
        "discovery": (
            {
                "upstream_id": federated.upstream_id,
                "canonical_package_id": federated.canonical_package_id,
                "name": federated.name,
                "component": federated.component,
                "canonical_origin": federated.canonical_origin,
                "detail_url": federated.detail_url,
                "artifact_url": federated.artifact_url,
                "repository_url": federated.artifact_url,
                "observed_at": federated.observed_at,
                "discovery_location": federated.discovery_location,
                "immutable_ref": federated.immutable_ref,
                "content_hash": federated.content_hash,
                "relative_path": federated.relative_path,
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


def _catalog_source_to_dict(item: Any, *, now: datetime) -> dict[str, Any]:
    last_success = (
        datetime.fromisoformat(item.last_success_at.replace("Z", "+00:00"))
        if item.last_success_at is not None
        else None
    )
    freshness = (
        datetime.fromisoformat(item.freshness_expires_at.replace("Z", "+00:00"))
        if item.freshness_expires_at is not None
        else None
    )
    stale = item.last_success_at is not None and (
        not item.last_attempt_succeeded
        or (
            item.source_type is CatalogSourceType.FEDERATED_CATALOG
            and (freshness is None or freshness <= now)
        )
    )
    return {
        "id": item.source_id,
        "status": (
            "unavailable"
            if item.last_success_at is None and not item.last_attempt_succeeded
            else "stale"
            if stale
            else "ready"
        ),
        "last_sync_at": item.last_success_at,
        "last_attempt_at": item.last_attempt_at,
        "cache_age_seconds": (
            max(0, int((now - last_success).total_seconds()))
            if last_success is not None
            else None
        ),
        "last_good": item.last_success_at is not None,
        "stale": stale,
        "reason_code": item.errors[-1].code if item.errors else None,
        "next_retry_at": item.next_retry_at,
        "entry_count": item.entry_count,
        "content_free": True,
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
    if target_id == HARNESS_MANAGED_MCP_TARGET_ID:
        return "harness_managed_mcp_inventory"
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
        source_provenance = payload.get("source_provenance")
        if source_provenance is not None and not isinstance(source_provenance, Mapping):
            raise TypeError("source provenance must be an object")
        record = IntegrationFlowRecord(
            id=str(payload["id"]),
            plan_id=str(payload["plan_id"]),
            status=IntegrationFlowStatus(str(payload["status"])),
            source=IntegrationFlowSource(str(payload["source"])),
            package_id=str(payload["package_id"]),
            package_version=str(payload["package_version"]),
            manifest_sha256=str(payload["manifest_sha256"]),
            source_provenance=(
                _json_value(source_provenance)
                if source_provenance is not None
                else None
            ),
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
