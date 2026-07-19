"""Provider-neutral integration package and target discovery contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
from importlib.metadata import entry_points
import json
import re
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from gpt2giga_harness.registries import (
    EntryPointFamily,
    RegistrationOutcome,
    RegistryCollisionError,
    VersionedRegistryKernel,
)
from gpt2giga_harness.types import redact_secrets


INTEGRATION_PACKAGE_SCHEMA_VERSION = 1
EXTENSION_TARGET_SCHEMA_VERSION = 1
NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP = "agent_workbench.extension_targets.v1"
EXTENSION_TARGET_ENTRY_POINTS = EntryPointFamily(
    registry_id="extension_target",
    api_version=1,
    primary_group=NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP,
)
MAX_TARGET_DISCOVERY_ERRORS = 20
MAX_TARGET_DISCOVERY_ERROR_CHARS = 400
MAX_TRUST_DIAGNOSTICS = 100
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")
_CHECKSUM_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")


class IntegrationComponentType(str, Enum):
    """Component families carried by one integration package."""

    MCP = "mcp"
    SKILL = "skill"
    PLUGIN = "plugin"
    EXTENSION = "extension"
    HARNESS_ADAPTER = "harness_adapter"


class IntegrationSourceType(str, Enum):
    """Reviewed source families from which immutable packages may be resolved."""

    CURATED_CATALOG = "curated_catalog"
    PROVIDER_MARKETPLACE = "provider_marketplace"
    GIT = "git"
    LOCAL = "local"
    PACKAGE = "package"
    RAW_MCP = "raw_mcp"


class InstallationScope(str, Enum):
    """Mutation scopes supported by an integration package or target."""

    MANAGED_HOME = "managed_home"
    PROJECT = "project"
    USER_HOME = "user_home"


class IntegrationRequirementType(str, Enum):
    """Security-relevant effect declared by an integration manifest."""

    PERMISSION = "permission"
    SECRET = "secret"
    COMMAND = "command"
    HOOK = "hook"
    BINARY = "binary"
    PACKAGE = "package"
    FILE = "file"
    NETWORK = "network"


class IntegrationPolicyClass(str, Enum):
    """Fail-closed policy classification for a declared package effect."""

    REVIEW_REQUIRED = "review_required"
    EXPLICIT_APPROVAL = "explicit_approval"
    PROVIDER_HANDOFF = "provider_handoff"
    FORBIDDEN = "forbidden"


class IntegrationTrustKind(str, Enum):
    """Supply-chain evidence classes retained without raw reports."""

    SOURCE = "source"
    PUBLISHER = "publisher"
    LICENSE = "license"
    SIGNATURE = "signature"
    SCAN = "scan"


class IntegrationTrustStatus(str, Enum):
    """Truthful status of one trust claim."""

    VERIFIED = "verified"
    DELEGATED = "delegated"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"


class IntegrationUpdatePolicy(str, Enum):
    """How a newer immutable package may be selected."""

    PINNED = "pinned"
    MANUAL_REVIEW = "manual_review"
    TRACK_CHANNEL_WITH_REVIEW = "track_channel_with_review"


class IntegrationTrustDecision(str, Enum):
    """Highest policy gate required before any installation work."""

    REVIEW_REQUIRED = "review_required"
    EXPLICIT_APPROVAL = "explicit_approval"
    PROVIDER_HANDOFF = "provider_handoff"
    BLOCKED = "blocked"


@dataclass(frozen=True, order=True)
class IntegrationComponent:
    """One portable or target-specific component in a package."""

    id: str
    type: IntegrationComponentType
    portable: bool

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="component id")
        if not isinstance(self.type, IntegrationComponentType):
            raise ValueError("component type is invalid")
        if not isinstance(self.portable, bool):
            raise ValueError("component portable must be a boolean")


@dataclass(frozen=True, order=True)
class IntegrationRequirement:
    """Content-free declaration of one privileged package requirement."""

    id: str
    type: IntegrationRequirementType
    classification: IntegrationPolicyClass
    reason: str
    argv: tuple[str, ...] = ()
    locator: str | None = None
    checksum: str | None = None
    secret_owner: str | None = None
    environment: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="requirement id")
        if not isinstance(self.type, IntegrationRequirementType):
            raise ValueError("requirement type is invalid")
        if not isinstance(self.classification, IntegrationPolicyClass):
            raise ValueError("requirement classification is invalid")
        _validate_text(self.reason, field_name="requirement reason")
        object.__setattr__(self, "argv", _normalize_argv(self.argv))
        object.__setattr__(
            self,
            "environment",
            _normalize_environment_names(self.environment),
        )
        if self.locator is not None:
            _validate_text(self.locator, field_name="requirement locator")
        if self.checksum is not None:
            _validate_checksum(self.checksum, field_name="requirement checksum")
        if self.secret_owner is not None:
            _validate_identity(self.secret_owner, field_name="secret owner")
        self._validate_shape()

    def _validate_shape(self) -> None:
        command_types = {
            IntegrationRequirementType.COMMAND,
            IntegrationRequirementType.HOOK,
        }
        artifact_types = {
            IntegrationRequirementType.BINARY,
            IntegrationRequirementType.PACKAGE,
            IntegrationRequirementType.FILE,
        }
        if self.type in command_types:
            if not self.argv or self.locator is not None or self.checksum is not None:
                raise ValueError("command and hook requirements use explicit argv only")
            if self.secret_owner is not None:
                raise ValueError("commands and hooks cannot own secrets")
            return
        if self.type in artifact_types:
            if self.locator is None or self.checksum is None:
                raise ValueError("artifact requirements require locator and checksum")
            if self.argv or self.secret_owner is not None or self.environment:
                raise ValueError("artifact requirement fields are invalid")
            return
        if self.type is IntegrationRequirementType.NETWORK:
            if self.locator is None:
                raise ValueError("network requirements require an HTTPS origin")
            object.__setattr__(self, "locator", _canonical_https_origin(self.locator))
            if self.argv or self.checksum is not None or self.secret_owner is not None:
                raise ValueError("network requirement fields are invalid")
            return
        if self.type is IntegrationRequirementType.SECRET:
            if self.secret_owner is None:
                raise ValueError("secret requirements require a backend owner")
            if self.argv or self.locator is not None or self.checksum is not None:
                raise ValueError("secret requirements cannot retain values or commands")
            if self.environment:
                raise ValueError("secret requirements declare ownership, not values")
            return
        if self.type is IntegrationRequirementType.PERMISSION:
            if (
                self.argv
                or self.locator is not None
                or self.checksum is not None
                or self.secret_owner is not None
                or self.environment
            ):
                raise ValueError("permission requirement fields are invalid")


@dataclass(frozen=True, order=True)
class IntegrationCompatibility:
    """Version and capability constraint for one extension target."""

    target_id: str
    minimum_version: str | None = None
    maximum_version_exclusive: str | None = None
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.target_id, field_name="compatibility target id")
        for field_name in ("minimum_version", "maximum_version_exclusive"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_identity(value, field_name=f"compatibility {field_name}")
        object.__setattr__(
            self,
            "required_capabilities",
            _normalize_identities(
                self.required_capabilities,
                field_name="required capability",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True, order=True)
class IntegrationTargetOverlay:
    """Target-specific projection that never erases the portable core."""

    target_id: str
    component_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.target_id, field_name="overlay target id")
        object.__setattr__(
            self,
            "component_ids",
            _normalize_identities(
                self.component_ids,
                field_name="overlay component id",
            ),
        )
        object.__setattr__(
            self,
            "requirement_ids",
            _normalize_identities(
                self.requirement_ids,
                field_name="overlay requirement id",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True, order=True)
class IntegrationTrustEvidence:
    """Bounded trust result without raw scanner, signature, or publisher data."""

    id: str
    kind: IntegrationTrustKind
    status: IntegrationTrustStatus
    authority: str
    revision: str

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="trust evidence id")
        if not isinstance(self.kind, IntegrationTrustKind):
            raise ValueError("trust evidence kind is invalid")
        if not isinstance(self.status, IntegrationTrustStatus):
            raise ValueError("trust evidence status is invalid")
        _validate_identity(self.authority, field_name="trust evidence authority")
        _validate_identity(self.revision, field_name="trust evidence revision")


@dataclass(frozen=True)
class IntegrationPackage:
    """Strict immutable manifest for a provider-neutral integration package."""

    id: str
    version: str
    publisher: str
    license: str
    source_type: IntegrationSourceType
    source: str
    immutable_ref: str
    checksum: str
    components: tuple[IntegrationComponent, ...]
    requirements: tuple[IntegrationRequirement, ...]
    overlays: tuple[IntegrationTargetOverlay, ...]
    compatibility: tuple[IntegrationCompatibility, ...]
    scopes: tuple[InstallationScope, ...]
    update_policy: IntegrationUpdatePolicy
    verification_steps: tuple[str, ...]
    rollback_steps: tuple[str, ...]
    trust_evidence: tuple[IntegrationTrustEvidence, ...] = ()
    schema_version: int = INTEGRATION_PACKAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != INTEGRATION_PACKAGE_SCHEMA_VERSION:
            raise ValueError("unsupported integration package schema_version")
        _validate_identity(self.id, field_name="integration id")
        _validate_identity(self.version, field_name="integration version")
        _validate_identity(self.publisher, field_name="integration publisher")
        _validate_identity(self.license, field_name="integration license")
        if not isinstance(self.source_type, IntegrationSourceType):
            raise ValueError("integration source_type is invalid")
        _validate_text(self.source, field_name="integration source")
        _validate_identity(self.immutable_ref, field_name="integration immutable_ref")
        _validate_checksum(self.checksum, field_name="integration checksum")
        object.__setattr__(
            self,
            "components",
            _normalize_records(
                self.components,
                expected_type=IntegrationComponent,
                field_name="integration component",
            ),
        )
        object.__setattr__(
            self,
            "requirements",
            _normalize_records(
                self.requirements,
                expected_type=IntegrationRequirement,
                field_name="integration requirement",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "overlays",
            _normalize_records(
                self.overlays,
                expected_type=IntegrationTargetOverlay,
                field_name="integration overlay",
                id_attribute="target_id",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "compatibility",
            _normalize_records(
                self.compatibility,
                expected_type=IntegrationCompatibility,
                field_name="integration compatibility",
                id_attribute="target_id",
                allow_empty=True,
            ),
        )
        object.__setattr__(self, "scopes", _normalize_scopes(self.scopes))
        if not isinstance(self.update_policy, IntegrationUpdatePolicy):
            raise ValueError("integration update_policy is invalid")
        object.__setattr__(
            self,
            "verification_steps",
            _normalize_identities(
                self.verification_steps,
                field_name="verification step",
            ),
        )
        object.__setattr__(
            self,
            "rollback_steps",
            _normalize_identities(self.rollback_steps, field_name="rollback step"),
        )
        object.__setattr__(
            self,
            "trust_evidence",
            _normalize_records(
                self.trust_evidence,
                expected_type=IntegrationTrustEvidence,
                field_name="trust evidence",
                allow_empty=True,
            ),
        )
        self._validate_references()

    def _validate_references(self) -> None:
        component_ids = {item.id for item in self.components}
        requirement_ids = {item.id for item in self.requirements}
        target_ids = {item.target_id for item in self.compatibility}
        for overlay in self.overlays:
            if overlay.target_id not in target_ids:
                raise ValueError("overlay target requires a compatibility contract")
            if not set(overlay.component_ids) <= component_ids:
                raise ValueError("overlay references an unknown component")
            if not set(overlay.requirement_ids) <= requirement_ids:
                raise ValueError("overlay references an unknown requirement")
        target_specific = {item.id for item in self.components if not item.portable}
        projected = {
            component_id
            for overlay in self.overlays
            for component_id in overlay.component_ids
        }
        if not target_specific <= projected:
            raise ValueError("target-specific components require a target overlay")


@dataclass(frozen=True, order=True)
class IntegrationTrustDiagnostic:
    """Content-free policy result bound only to a stable manifest subject."""

    code: str
    subject_id: str
    classification: IntegrationTrustDecision


@dataclass(frozen=True)
class IntegrationTrustAssessment:
    """Bounded trust preview which never authorizes installation."""

    package_id: str
    package_version: str
    manifest_hash: str
    decision: IntegrationTrustDecision
    install_authorized: bool
    diagnostics: tuple[IntegrationTrustDiagnostic, ...]


@dataclass(frozen=True)
class ExtensionTargetDescriptor:
    """Versioned capability declaration for one extension installation target."""

    id: str
    revision: str
    component_types: tuple[IntegrationComponentType, ...]
    scopes: tuple[InstallationScope, ...]
    capabilities: tuple[str, ...]
    trust_evidence: tuple[IntegrationTrustEvidence, ...]
    schema_version: int = EXTENSION_TARGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXTENSION_TARGET_SCHEMA_VERSION:
            raise ValueError("unsupported extension target schema_version")
        _validate_identity(self.id, field_name="extension target id")
        _validate_identity(self.revision, field_name="extension target revision")
        types = tuple(sorted(set(self.component_types), key=lambda item: item.value))
        if not types or any(
            not isinstance(item, IntegrationComponentType) for item in types
        ):
            raise ValueError("extension target component_types are invalid")
        object.__setattr__(self, "component_types", types)
        object.__setattr__(self, "scopes", _normalize_scopes(self.scopes))
        object.__setattr__(
            self,
            "capabilities",
            _normalize_identities(self.capabilities, field_name="target capability"),
        )
        object.__setattr__(
            self,
            "trust_evidence",
            _normalize_records(
                self.trust_evidence,
                expected_type=IntegrationTrustEvidence,
                field_name="target trust evidence",
            ),
        )


@runtime_checkable
class ExtensionTargetDriver(Protocol):
    """Provider-neutral lifecycle surface implemented by target adapters."""

    descriptor: ExtensionTargetDescriptor

    def probe_target(self) -> object: ...

    def discover_installed(self) -> object: ...

    def preview_install(self) -> object: ...

    def install(self) -> object: ...

    def verify(self) -> object: ...

    def enable(self) -> object: ...

    def disable(self) -> object: ...

    def preview_update(self) -> object: ...

    def update(self) -> object: ...

    def preview_uninstall(self) -> object: ...

    def uninstall(self) -> object: ...

    def rollback(self) -> object: ...


@dataclass(frozen=True)
class ExtensionTargetPlugin:
    """Discoverable descriptor and lazy driver factory."""

    descriptor: ExtensionTargetDescriptor
    factory: Callable[[], ExtensionTargetDriver]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ExtensionTargetDescriptor):
            raise ValueError("extension target descriptor is invalid")
        if not callable(self.factory):
            raise ValueError("extension target factory must be callable")


class ExtensionTargetRegistry:
    """Discover extension targets through the neutral v1 registry family."""

    def __init__(self) -> None:
        self._kernel = VersionedRegistryKernel[ExtensionTargetPlugin](
            EXTENSION_TARGET_ENTRY_POINTS
        )
        self.discovery_errors: list[str] = []

    def register(self, plugin: ExtensionTargetPlugin) -> RegistrationOutcome:
        """Register one runtime extension target."""
        return self._register(
            plugin,
            identity=_plugin_identity(plugin),
            source=f"runtime:{plugin.descriptor.id}",
        )

    def _register(
        self,
        plugin: ExtensionTargetPlugin,
        *,
        identity: str,
        source: str,
        allow_equivalent_duplicate: bool = False,
    ) -> RegistrationOutcome:
        if not isinstance(plugin, ExtensionTargetPlugin):
            raise TypeError("extension target entry point must return a plugin")
        return self._kernel.register(
            item_id=plugin.descriptor.id,
            item=plugin,
            identity=identity,
            source=source,
            allow_equivalent_duplicate=allow_equivalent_duplicate,
        )

    def list(self) -> tuple[ExtensionTargetDescriptor, ...]:
        """Return target declarations in deterministic order."""
        return tuple(
            item.descriptor
            for item in sorted(
                self._kernel.values(),
                key=lambda plugin: plugin.descriptor.id,
            )
        )

    def create_driver(self, target_id: str) -> ExtensionTargetDriver:
        """Create one driver and reject a mismatched or incomplete factory result."""
        plugin = self._kernel.get(target_id)
        if plugin is None:
            raise KeyError(target_id)
        driver = plugin.factory()
        if not isinstance(driver, ExtensionTargetDriver):
            raise TypeError("extension target factory returned an invalid driver")
        if driver.descriptor != plugin.descriptor:
            raise ValueError(
                "extension target driver descriptor does not match registry"
            )
        return driver

    def load_entry_points(self) -> None:
        """Load third-party target plugins with bounded redaction-safe failures."""
        try:
            all_entry_points = entry_points()
        except Exception as exc:  # pragma: no cover - defensive importlib path
            self._record_discovery_error(
                "Extension target discovery failed: "
                f"{type(exc).__name__} (details omitted)."
            )
            return
        selected = sorted(
            _select_entry_points(
                all_entry_points,
                EXTENSION_TARGET_ENTRY_POINTS.primary_group,
            ),
            key=_entry_point_sort_key,
        )
        for entry_point in selected:
            entry_name = str(getattr(entry_point, "name", "<unnamed>"))
            source = (
                f"entry-point:{EXTENSION_TARGET_ENTRY_POINTS.primary_group}:"
                f"{entry_name}"
            )
            try:
                loaded = entry_point.load()
                plugin = _load_target_plugin(loaded)
                self._register(
                    plugin,
                    identity=_entry_point_identity(entry_point, loaded, plugin),
                    source=source,
                    allow_equivalent_duplicate=True,
                )
            except RegistryCollisionError as exc:
                self._record_discovery_error(
                    "Extension target id collision for "
                    f"{exc.item_id!r}: keeping {exc.existing_source}; "
                    f"rejected {exc.incoming_source}."
                )
            except Exception as exc:  # pragma: no cover - plugin failure path
                self._record_discovery_error(
                    f"{source}: {type(exc).__name__} (details omitted)."
                )

    def _record_discovery_error(self, message: str) -> None:
        if len(self.discovery_errors) >= MAX_TARGET_DISCOVERY_ERRORS:
            return
        safe_message = str(redact_secrets(message))
        self.discovery_errors.append(safe_message[:MAX_TARGET_DISCOVERY_ERROR_CHARS])


def integration_package_to_dict(package: IntegrationPackage) -> dict[str, Any]:
    """Serialize one manifest into its strict forward-only v1 shape."""
    return {
        "schema_version": package.schema_version,
        "id": package.id,
        "version": package.version,
        "publisher": package.publisher,
        "license": package.license,
        "source_type": package.source_type.value,
        "source": package.source,
        "immutable_ref": package.immutable_ref,
        "checksum": package.checksum,
        "components": [_component_to_dict(item) for item in package.components],
        "requirements": [_requirement_to_dict(item) for item in package.requirements],
        "overlays": [_overlay_to_dict(item) for item in package.overlays],
        "compatibility": [
            _compatibility_to_dict(item) for item in package.compatibility
        ],
        "scopes": [item.value for item in package.scopes],
        "update_policy": package.update_policy.value,
        "verification_steps": list(package.verification_steps),
        "rollback_steps": list(package.rollback_steps),
        "trust_evidence": [
            _trust_evidence_to_dict(item) for item in package.trust_evidence
        ],
    }


def integration_package_from_dict(data: Mapping[str, Any]) -> IntegrationPackage:
    """Parse a manifest without accepting unknown or future fields."""
    mapping = _strict_mapping(
        data,
        allowed={
            "schema_version",
            "id",
            "version",
            "publisher",
            "license",
            "source_type",
            "source",
            "immutable_ref",
            "checksum",
            "components",
            "requirements",
            "overlays",
            "compatibility",
            "scopes",
            "update_policy",
            "verification_steps",
            "rollback_steps",
            "trust_evidence",
        },
        field_name="integration package",
    )
    if mapping.get("schema_version") != INTEGRATION_PACKAGE_SCHEMA_VERSION:
        raise ValueError("unsupported integration package schema_version")
    return IntegrationPackage(
        id=_required_text(mapping.get("id"), field_name="integration id"),
        version=_required_text(
            mapping.get("version"), field_name="integration version"
        ),
        publisher=_required_text(
            mapping.get("publisher"), field_name="integration publisher"
        ),
        license=_required_text(
            mapping.get("license"), field_name="integration license"
        ),
        source_type=_enum_value(
            IntegrationSourceType,
            mapping.get("source_type"),
            field_name="integration source_type",
        ),
        source=_required_text(mapping.get("source"), field_name="integration source"),
        immutable_ref=_required_text(
            mapping.get("immutable_ref"), field_name="integration immutable_ref"
        ),
        checksum=_required_text(
            mapping.get("checksum"), field_name="integration checksum"
        ),
        components=tuple(
            _component_from_dict(item)
            for item in _required_list(mapping.get("components"), "components")
        ),
        requirements=tuple(
            _requirement_from_dict(item)
            for item in _required_list(mapping.get("requirements"), "requirements")
        ),
        overlays=tuple(
            _overlay_from_dict(item)
            for item in _required_list(mapping.get("overlays"), "overlays")
        ),
        compatibility=tuple(
            _compatibility_from_dict(item)
            for item in _required_list(mapping.get("compatibility"), "compatibility")
        ),
        scopes=tuple(
            _enum_value(InstallationScope, item, field_name="installation scope")
            for item in _required_list(mapping.get("scopes"), "scopes")
        ),
        update_policy=_enum_value(
            IntegrationUpdatePolicy,
            mapping.get("update_policy"),
            field_name="integration update_policy",
        ),
        verification_steps=tuple(
            _required_text(item, field_name="verification step")
            for item in _required_list(
                mapping.get("verification_steps"), "verification_steps"
            )
        ),
        rollback_steps=tuple(
            _required_text(item, field_name="rollback step")
            for item in _required_list(mapping.get("rollback_steps"), "rollback_steps")
        ),
        trust_evidence=tuple(
            _trust_evidence_from_dict(item)
            for item in _required_list(mapping.get("trust_evidence"), "trust_evidence")
        ),
    )


def integration_package_semantic_hash(package: IntegrationPackage) -> str:
    """Return the deterministic hash used to bind previews and approvals."""
    payload = integration_package_to_dict(package)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def assess_integration_package(
    package: IntegrationPackage,
) -> IntegrationTrustAssessment:
    """Return bounded policy gates without granting installation authority."""
    diagnostics: list[IntegrationTrustDiagnostic] = []
    for requirement in package.requirements:
        decision = _policy_decision(requirement.classification)
        diagnostics.append(
            IntegrationTrustDiagnostic(
                code=f"requirement.{requirement.type.value}.{decision.value}",
                subject_id=requirement.id,
                classification=decision,
            )
        )
    for kind in IntegrationTrustKind:
        evidence_items = tuple(
            item for item in package.trust_evidence if item.kind is kind
        )
        if not evidence_items:
            diagnostics.append(
                IntegrationTrustDiagnostic(
                    code=f"trust.{kind.value}.missing",
                    subject_id=package.id,
                    classification=IntegrationTrustDecision.REVIEW_REQUIRED,
                )
            )
            continue
        for evidence in evidence_items:
            if evidence.status is IntegrationTrustStatus.VERIFIED:
                continue
            decision = (
                IntegrationTrustDecision.BLOCKED
                if evidence.status is IntegrationTrustStatus.BLOCKED
                else IntegrationTrustDecision.REVIEW_REQUIRED
            )
            diagnostics.append(
                IntegrationTrustDiagnostic(
                    code=f"trust.{kind.value}.{evidence.status.value}",
                    subject_id=evidence.id,
                    classification=decision,
                )
            )
    if InstallationScope.USER_HOME in package.scopes:
        diagnostics.append(
            IntegrationTrustDiagnostic(
                code="scope.user_home.explicit_approval",
                subject_id=package.id,
                classification=IntegrationTrustDecision.EXPLICIT_APPROVAL,
            )
        )
    if not diagnostics:
        diagnostics.append(
            IntegrationTrustDiagnostic(
                code="manifest.review_required",
                subject_id=package.id,
                classification=IntegrationTrustDecision.REVIEW_REQUIRED,
            )
        )
    normalized = tuple(
        sorted(
            diagnostics,
            key=lambda item: (item.classification.value, item.code, item.subject_id),
        )[:MAX_TRUST_DIAGNOSTICS]
    )
    decision = max(
        (item.classification for item in normalized),
        key=_decision_rank,
    )
    return IntegrationTrustAssessment(
        package_id=package.id,
        package_version=package.version,
        manifest_hash=integration_package_semantic_hash(package),
        decision=decision,
        install_authorized=False,
        diagnostics=normalized,
    )


def integration_trust_assessment_to_dict(
    assessment: IntegrationTrustAssessment,
) -> dict[str, Any]:
    """Project only stable content-free trust diagnostics."""
    return {
        "package_id": assessment.package_id,
        "package_version": assessment.package_version,
        "manifest_hash": assessment.manifest_hash,
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
    }


def extension_target_descriptor_to_dict(
    descriptor: ExtensionTargetDescriptor,
) -> dict[str, Any]:
    """Serialize target capability evidence without loading its driver."""
    return {
        "schema_version": descriptor.schema_version,
        "id": descriptor.id,
        "revision": descriptor.revision,
        "component_types": [item.value for item in descriptor.component_types],
        "scopes": [item.value for item in descriptor.scopes],
        "capabilities": list(descriptor.capabilities),
        "trust_evidence": [
            _trust_evidence_to_dict(item) for item in descriptor.trust_evidence
        ],
    }


def _component_to_dict(item: IntegrationComponent) -> dict[str, Any]:
    return {"id": item.id, "type": item.type.value, "portable": item.portable}


def _component_from_dict(value: Any) -> IntegrationComponent:
    mapping = _strict_mapping(
        value,
        allowed={"id", "type", "portable"},
        field_name="integration component",
    )
    portable = mapping.get("portable")
    if not isinstance(portable, bool):
        raise ValueError("component portable must be a boolean")
    return IntegrationComponent(
        id=_required_text(mapping.get("id"), field_name="component id"),
        type=_enum_value(
            IntegrationComponentType,
            mapping.get("type"),
            field_name="component type",
        ),
        portable=portable,
    )


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


def _requirement_from_dict(value: Any) -> IntegrationRequirement:
    mapping = _strict_mapping(
        value,
        allowed={
            "id",
            "type",
            "classification",
            "reason",
            "argv",
            "locator",
            "checksum",
            "secret_owner",
            "environment",
        },
        field_name="integration requirement",
    )
    return IntegrationRequirement(
        id=_required_text(mapping.get("id"), field_name="requirement id"),
        type=_enum_value(
            IntegrationRequirementType,
            mapping.get("type"),
            field_name="requirement type",
        ),
        classification=_enum_value(
            IntegrationPolicyClass,
            mapping.get("classification"),
            field_name="requirement classification",
        ),
        reason=_required_text(mapping.get("reason"), field_name="requirement reason"),
        argv=tuple(
            _required_text(item, field_name="requirement argv")
            for item in _required_list(mapping.get("argv"), "requirement argv")
        ),
        locator=_optional_text(
            mapping.get("locator"), field_name="requirement locator"
        ),
        checksum=_optional_text(
            mapping.get("checksum"), field_name="requirement checksum"
        ),
        secret_owner=_optional_text(
            mapping.get("secret_owner"), field_name="secret owner"
        ),
        environment=tuple(
            _required_text(item, field_name="environment name")
            for item in _required_list(
                mapping.get("environment"), "requirement environment"
            )
        ),
    )


def _overlay_to_dict(item: IntegrationTargetOverlay) -> dict[str, Any]:
    return {
        "target_id": item.target_id,
        "component_ids": list(item.component_ids),
        "requirement_ids": list(item.requirement_ids),
    }


def _overlay_from_dict(value: Any) -> IntegrationTargetOverlay:
    mapping = _strict_mapping(
        value,
        allowed={"target_id", "component_ids", "requirement_ids"},
        field_name="integration overlay",
    )
    return IntegrationTargetOverlay(
        target_id=_required_text(mapping.get("target_id"), field_name="target id"),
        component_ids=tuple(
            _required_text(item, field_name="overlay component id")
            for item in _required_list(
                mapping.get("component_ids"), "overlay component_ids"
            )
        ),
        requirement_ids=tuple(
            _required_text(item, field_name="overlay requirement id")
            for item in _required_list(
                mapping.get("requirement_ids"), "overlay requirement_ids"
            )
        ),
    )


def _compatibility_to_dict(item: IntegrationCompatibility) -> dict[str, Any]:
    return {
        "target_id": item.target_id,
        "minimum_version": item.minimum_version,
        "maximum_version_exclusive": item.maximum_version_exclusive,
        "required_capabilities": list(item.required_capabilities),
    }


def _compatibility_from_dict(value: Any) -> IntegrationCompatibility:
    mapping = _strict_mapping(
        value,
        allowed={
            "target_id",
            "minimum_version",
            "maximum_version_exclusive",
            "required_capabilities",
        },
        field_name="integration compatibility",
    )
    return IntegrationCompatibility(
        target_id=_required_text(mapping.get("target_id"), field_name="target id"),
        minimum_version=_optional_text(
            mapping.get("minimum_version"), field_name="minimum version"
        ),
        maximum_version_exclusive=_optional_text(
            mapping.get("maximum_version_exclusive"),
            field_name="maximum version exclusive",
        ),
        required_capabilities=tuple(
            _required_text(item, field_name="required capability")
            for item in _required_list(
                mapping.get("required_capabilities"), "required_capabilities"
            )
        ),
    )


def _trust_evidence_to_dict(item: IntegrationTrustEvidence) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind.value,
        "status": item.status.value,
        "authority": item.authority,
        "revision": item.revision,
    }


def _trust_evidence_from_dict(value: Any) -> IntegrationTrustEvidence:
    mapping = _strict_mapping(
        value,
        allowed={"id", "kind", "status", "authority", "revision"},
        field_name="trust evidence",
    )
    return IntegrationTrustEvidence(
        id=_required_text(mapping.get("id"), field_name="trust evidence id"),
        kind=_enum_value(
            IntegrationTrustKind,
            mapping.get("kind"),
            field_name="trust evidence kind",
        ),
        status=_enum_value(
            IntegrationTrustStatus,
            mapping.get("status"),
            field_name="trust evidence status",
        ),
        authority=_required_text(
            mapping.get("authority"), field_name="trust evidence authority"
        ),
        revision=_required_text(
            mapping.get("revision"), field_name="trust evidence revision"
        ),
    )


def _policy_decision(value: IntegrationPolicyClass) -> IntegrationTrustDecision:
    return {
        IntegrationPolicyClass.REVIEW_REQUIRED: IntegrationTrustDecision.REVIEW_REQUIRED,
        IntegrationPolicyClass.EXPLICIT_APPROVAL: IntegrationTrustDecision.EXPLICIT_APPROVAL,
        IntegrationPolicyClass.PROVIDER_HANDOFF: IntegrationTrustDecision.PROVIDER_HANDOFF,
        IntegrationPolicyClass.FORBIDDEN: IntegrationTrustDecision.BLOCKED,
    }[value]


def _decision_rank(value: IntegrationTrustDecision) -> int:
    return {
        IntegrationTrustDecision.REVIEW_REQUIRED: 0,
        IntegrationTrustDecision.EXPLICIT_APPROVAL: 1,
        IntegrationTrustDecision.PROVIDER_HANDOFF: 2,
        IntegrationTrustDecision.BLOCKED: 3,
    }[value]


def _plugin_identity(plugin: ExtensionTargetPlugin) -> str:
    payload = extension_target_descriptor_to_dict(plugin.descriptor)
    payload["factory"] = _implementation_identity(plugin.factory)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_target_plugin(loaded: Any) -> ExtensionTargetPlugin:
    value = loaded() if callable(loaded) else loaded
    if not isinstance(value, ExtensionTargetPlugin):
        raise TypeError("extension target entry point did not create a plugin")
    return value


def _entry_point_identity(
    entry_point: Any,
    loaded: Any,
    plugin: ExtensionTargetPlugin,
) -> str:
    value = getattr(entry_point, "value", None)
    if isinstance(value, str) and value.strip():
        return hashlib.sha256(
            f"{value.strip()}:{_plugin_identity(plugin)}".encode("utf-8")
        ).hexdigest()
    return hashlib.sha256(
        f"{_implementation_identity(loaded)}:{_plugin_identity(plugin)}".encode("utf-8")
    ).hexdigest()


def _implementation_identity(value: Any) -> str:
    module = getattr(value, "__module__", type(value).__module__)
    qualname = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{module}:{qualname}"


def _select_entry_points(all_entry_points: Any, group: str):
    if hasattr(all_entry_points, "select"):
        return all_entry_points.select(group=group)
    return all_entry_points.get(group, ())


def _entry_point_sort_key(entry_point: Any) -> tuple[str, str]:
    return (
        str(getattr(entry_point, "name", "")),
        str(getattr(entry_point, "value", "")),
    )


def _strict_mapping(
    value: Any,
    *,
    allowed: set[str],
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{field_name} contains unknown fields: {sorted(unknown)!r}")
    return value


def _required_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    _validate_text(value, field_name=field_name)
    return value


def _optional_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name)


def _enum_value(enum_type: type[Enum], value: Any, *, field_name: str):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _validate_identity(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")


def _validate_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{field_name} contains control characters")
    if len(value) > 2048:
        raise ValueError(f"{field_name} is too long")
    if redact_secrets(value) != value:
        raise ValueError(f"{field_name} contains secret material")


def _validate_checksum(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or _CHECKSUM_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a sha256 digest")


def _normalize_argv(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(values)
    for value in normalized:
        _validate_text(value, field_name="requirement argv")
    return normalized


def _normalize_environment_names(values: Iterable[str]) -> tuple[str, ...]:
    raw_values = tuple(values)
    if any(not isinstance(value, str) for value in raw_values):
        raise ValueError("requirement environment name is invalid")
    normalized = tuple(sorted(set(raw_values)))
    if any(_ENV_NAME_RE.fullmatch(value) is None for value in normalized):
        raise ValueError("requirement environment name is invalid")
    return normalized


def _normalize_identities(
    values: Iterable[str],
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if not normalized and not allow_empty:
        raise ValueError(f"{field_name} is required")
    for value in normalized:
        _validate_identity(value, field_name=field_name)
    return normalized


def _normalize_records(
    values: Iterable[Any],
    *,
    expected_type: type[Any],
    field_name: str,
    id_attribute: str = "id",
    allow_empty: bool = False,
) -> tuple[Any, ...]:
    normalized = tuple(values)
    if not normalized and not allow_empty:
        raise ValueError(f"{field_name} is required")
    if any(not isinstance(item, expected_type) for item in normalized):
        raise ValueError(f"{field_name} is invalid")
    normalized = tuple(sorted(normalized, key=lambda item: getattr(item, id_attribute)))
    ids = [getattr(item, id_attribute) for item in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{field_name} contains duplicate ids")
    return normalized


def _normalize_scopes(
    values: Iterable[InstallationScope],
) -> tuple[InstallationScope, ...]:
    raw_values = tuple(values)
    if not raw_values or any(
        not isinstance(item, InstallationScope) for item in raw_values
    ):
        raise ValueError("installation scopes are invalid")
    normalized = tuple(sorted(set(raw_values), key=lambda item: item.value))
    return normalized


def _canonical_https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("network requirement must be an HTTPS origin")
    return urlunsplit(("https", parsed.netloc.lower(), "", "", ""))


__all__ = [
    "EXTENSION_TARGET_ENTRY_POINTS",
    "EXTENSION_TARGET_SCHEMA_VERSION",
    "ExtensionTargetDescriptor",
    "ExtensionTargetDriver",
    "ExtensionTargetPlugin",
    "ExtensionTargetRegistry",
    "INTEGRATION_PACKAGE_SCHEMA_VERSION",
    "InstallationScope",
    "IntegrationCompatibility",
    "IntegrationComponent",
    "IntegrationComponentType",
    "IntegrationPackage",
    "IntegrationPolicyClass",
    "IntegrationRequirement",
    "IntegrationRequirementType",
    "IntegrationSourceType",
    "IntegrationTargetOverlay",
    "IntegrationTrustAssessment",
    "IntegrationTrustDecision",
    "IntegrationTrustDiagnostic",
    "IntegrationTrustEvidence",
    "IntegrationTrustKind",
    "IntegrationTrustStatus",
    "IntegrationUpdatePolicy",
    "NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP",
    "assess_integration_package",
    "extension_target_descriptor_to_dict",
    "integration_package_from_dict",
    "integration_package_semantic_hash",
    "integration_package_to_dict",
    "integration_trust_assessment_to_dict",
]
