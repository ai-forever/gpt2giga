"""Internal Adapter/Integration SDK preview contracts and conformance kit."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
from pathlib import Path
import stat
from typing import Any, Mapping

from gpt2giga_harness.adapter_sdk import (
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    ADAPTER_SDK_API_VERSION,
)
from gpt2giga_harness.integration_packages import (
    EXTENSION_TARGET_SCHEMA_VERSION,
    INTEGRATION_PACKAGE_SCHEMA_VERSION,
    ExtensionTargetDescriptor,
    IntegrationPackage,
    assess_integration_package,
    extension_target_descriptor_from_dict,
    integration_package_from_dict,
    integration_package_semantic_hash,
)


INTEGRATION_SDK_API_VERSION = 1
INTEGRATION_SDK_RESOURCE_PACKAGE = "gpt2giga_harness.integration_sdk_preview"
MAX_SDK_DOCUMENT_BYTES = 1_048_576


@dataclass(frozen=True)
class IntegrationSdkPolicy:
    """Machine-readable compatibility and deprecation policy for preview v1."""

    sdk_api_version: int = INTEGRATION_SDK_API_VERSION
    adapter_sdk_api_version: int = ADAPTER_SDK_API_VERSION
    adapter_manifest_schema_version: int = ADAPTER_MANIFEST_SCHEMA_VERSION
    package_schema_version: int = INTEGRATION_PACKAGE_SCHEMA_VERSION
    target_schema_version: int = EXTENSION_TARGET_SCHEMA_VERSION
    stability: str = "internal_preview"
    unknown_fields: str = "reject"
    future_versions: str = "reject"
    minimum_deprecation_releases: int = 2
    minimum_deprecation_days: int = 30
    public_marketplace_release: bool = False


@dataclass(frozen=True)
class IntegrationConformanceResult:
    """One bounded Integration SDK conformance result."""

    claim: str
    status: str
    detail: str


@dataclass(frozen=True)
class IntegrationConformanceReport:
    """Content-free conformance report for one immutable package manifest."""

    package_id: str
    package_version: str
    manifest_hash: str
    ok: bool
    target_ids: tuple[str, ...]
    results: tuple[IntegrationConformanceResult, ...]


def integration_sdk_policy_to_dict(
    policy: IntegrationSdkPolicy | None = None,
) -> dict[str, Any]:
    """Project the current preview compatibility and deprecation policy."""
    value = policy or IntegrationSdkPolicy()
    return {
        "sdk_api_version": value.sdk_api_version,
        "adapter_sdk_api_version": value.adapter_sdk_api_version,
        "adapter_manifest_schema_version": value.adapter_manifest_schema_version,
        "package_schema_version": value.package_schema_version,
        "target_schema_version": value.target_schema_version,
        "stability": value.stability,
        "unknown_fields": value.unknown_fields,
        "future_versions": value.future_versions,
        "deprecation": {
            "minimum_releases": value.minimum_deprecation_releases,
            "minimum_days": value.minimum_deprecation_days,
        },
        "public_marketplace_release": value.public_marketplace_release,
    }


def load_integration_package_document(path: str | Path) -> IntegrationPackage:
    """Load one bounded, strict, duplicate-key-free package document."""
    return integration_package_from_dict(_load_json_document(path))


def load_extension_target_document(path: str | Path) -> ExtensionTargetDescriptor:
    """Load one bounded, strict, duplicate-key-free target descriptor."""
    return extension_target_descriptor_from_dict(_load_json_document(path))


def load_integration_sdk_resource(relative_path: str) -> str:
    """Read one packaged preview document without accepting path traversal."""
    normalized = Path(relative_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("SDK resource path is invalid")
    try:
        resource = resources.files(INTEGRATION_SDK_RESOURCE_PACKAGE).joinpath(
            normalized.as_posix()
        )
        payload = resource.read_text(encoding="utf-8")
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        raise ValueError("SDK resource could not be loaded") from exc
    if len(payload.encode("utf-8")) > MAX_SDK_DOCUMENT_BYTES:
        raise ValueError("SDK resource is too large")
    return payload


def run_integration_conformance(
    package: IntegrationPackage,
    *,
    target_descriptors: tuple[ExtensionTargetDescriptor, ...] = (),
) -> IntegrationConformanceReport:
    """Validate schema, non-authority, and exact target compatibility offline."""
    manifest_hash = integration_package_semantic_hash(package)
    assessment = assess_integration_package(package)
    target_ids = tuple(item.target_id for item in package.compatibility)
    results = [
        IntegrationConformanceResult(
            claim="manifest.schema",
            status="passed",
            detail="strict IntegrationPackage schema v1 accepted",
        ),
        IntegrationConformanceResult(
            claim="manifest.immutable",
            status="passed",
            detail="immutable reference and sha256 pin accepted",
        ),
        IntegrationConformanceResult(
            claim="trust.non_authority",
            status="passed" if not assessment.install_authorized else "failed",
            detail=(
                "trust projection does not authorize installation"
                if not assessment.install_authorized
                else "trust projection unexpectedly authorizes installation"
            ),
        ),
    ]
    compatibility_issue = _target_compatibility_issue(package, target_descriptors)
    results.append(
        IntegrationConformanceResult(
            claim="target.compatibility",
            status="failed" if compatibility_issue else "passed",
            detail=compatibility_issue or "declared target compatibility is exact",
        )
    )
    normalized_results = tuple(results)
    return IntegrationConformanceReport(
        package_id=package.id,
        package_version=package.version,
        manifest_hash=manifest_hash,
        ok=all(item.status == "passed" for item in normalized_results),
        target_ids=target_ids,
        results=normalized_results,
    )


def integration_conformance_report_to_dict(
    report: IntegrationConformanceReport,
) -> dict[str, Any]:
    """Serialize a bounded report suitable for CI and the product CLI."""
    return {
        "sdk_api_version": INTEGRATION_SDK_API_VERSION,
        "package_schema_version": INTEGRATION_PACKAGE_SCHEMA_VERSION,
        "target_schema_version": EXTENSION_TARGET_SCHEMA_VERSION,
        "package_id": report.package_id,
        "package_version": report.package_version,
        "manifest_hash": report.manifest_hash,
        "ok": report.ok,
        "target_ids": list(report.target_ids),
        "results": [
            {
                "claim": item.claim,
                "status": item.status,
                "detail": item.detail,
            }
            for item in report.results
        ],
        "install_authorized": False,
        "public_marketplace_release": False,
    }


def _target_compatibility_issue(
    package: IntegrationPackage,
    descriptors: tuple[ExtensionTargetDescriptor, ...],
) -> str | None:
    descriptor_ids = [item.id for item in descriptors]
    if len(set(descriptor_ids)) != len(descriptor_ids):
        return "target descriptors contain duplicate ids"
    expected = {item.target_id: item for item in package.compatibility}
    provided = {item.id: item for item in descriptors}
    if set(expected) != set(provided):
        return "target descriptors do not exactly match manifest compatibility"
    overlays = {item.target_id: item for item in package.overlays}
    components = {item.id: item for item in package.components}
    portable_ids = {item.id for item in package.components if item.portable}
    for target_id, compatibility in sorted(expected.items()):
        descriptor = provided[target_id]
        overlay = overlays.get(target_id)
        projected_ids = portable_ids | (
            set(overlay.component_ids) if overlay is not None else set()
        )
        projected_types = {
            components[item_id].type
            for item_id in projected_ids
            if item_id in components
        }
        if not projected_types <= set(descriptor.component_types):
            return f"target {target_id} does not support projected component types"
        if not set(package.scopes) <= set(descriptor.scopes):
            return f"target {target_id} does not support declared package scopes"
        if not set(compatibility.required_capabilities) <= set(descriptor.capabilities):
            return f"target {target_id} is missing required capabilities"
        version_issue = _target_version_issue(
            descriptor.revision,
            minimum=compatibility.minimum_version,
            maximum_exclusive=compatibility.maximum_version_exclusive,
        )
        if version_issue is not None:
            return f"target {target_id} {version_issue}"
    return None


def _target_version_issue(
    revision: str,
    *,
    minimum: str | None,
    maximum_exclusive: str | None,
) -> str | None:
    if minimum is None and maximum_exclusive is None:
        return None
    revision_key = _numeric_version_key(revision)
    minimum_key = _numeric_version_key(minimum) if minimum is not None else None
    maximum_key = (
        _numeric_version_key(maximum_exclusive)
        if maximum_exclusive is not None
        else None
    )
    if revision_key is None or (minimum is not None and minimum_key is None):
        return "version constraints cannot be evaluated"
    if maximum_exclusive is not None and maximum_key is None:
        return "version constraints cannot be evaluated"
    if minimum_key is not None and revision_key < minimum_key:
        return "revision is below the declared minimum"
    if maximum_key is not None and revision_key >= maximum_key:
        return "revision is outside the declared maximum"
    return None


def _numeric_version_key(value: str) -> tuple[int, int, int, int] | None:
    parts = value.split(".")
    if not 1 <= len(parts) <= 4 or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in (*parts, *("0",) * (4 - len(parts))))


def _load_json_document(path: str | Path) -> Mapping[str, Any]:
    candidate = Path(path)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise ValueError("SDK document could not be loaded") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("SDK document must be a regular non-symlink file")
    if metadata.st_size > MAX_SDK_DOCUMENT_BYTES:
        raise ValueError("SDK document is too large")
    try:
        payload = json.loads(
            candidate.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("SDK document must be valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("SDK document must be a JSON object")
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("SDK document contains duplicate keys")
        result[key] = value
    return result


__all__ = [
    "INTEGRATION_SDK_API_VERSION",
    "INTEGRATION_SDK_RESOURCE_PACKAGE",
    "IntegrationConformanceReport",
    "IntegrationConformanceResult",
    "IntegrationSdkPolicy",
    "integration_conformance_report_to_dict",
    "integration_sdk_policy_to_dict",
    "load_extension_target_document",
    "load_integration_package_document",
    "load_integration_sdk_resource",
    "run_integration_conformance",
]
