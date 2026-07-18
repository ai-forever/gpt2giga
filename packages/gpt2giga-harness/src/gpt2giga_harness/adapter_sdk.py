"""Versioned SDK foundations for out-of-tree Harness adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from importlib import metadata, resources
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Protocol

from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.plugins import validate_harness_spec
from gpt2giga_harness.types import (
    Availability,
    AvailabilityStatus,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
)


ADAPTER_SDK_API_VERSION = 1
ADAPTER_MANIFEST_SCHEMA_VERSION = 1
ADAPTER_ENTRY_POINT_GROUP = "agent_workbench.harness_adapters.v1"
CONFORMANCE_ENTRY_POINT_GROUP = "agent_workbench.adapter_conformance.v1"
_ADAPTER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DISTRIBUTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9._+-]*)?$")
_ENTRY_POINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


class AdapterConformanceCategory(str, Enum):
    """Stable top-level conformance categories for adapter SDK v1."""

    EXECUTION = "execution"
    SESSIONS = "sessions"
    APPROVALS = "approvals"
    ATTACHMENTS = "attachments"
    INTEGRATIONS = "integrations"
    RECOVERY = "recovery"
    HISTORY = "history"
    TELEMETRY = "telemetry"
    PACKAGING = "packaging"


class AdapterConformanceClaim(str, Enum):
    """Behavioral claims understood by the adapter SDK v1 kit."""

    EXECUTION_RUN = "execution.run"
    SESSIONS_LIFECYCLE = "sessions.lifecycle"
    APPROVALS_ROUND_TRIP = "approvals.round_trip"
    ATTACHMENTS_INPUT = "attachments.input"
    INTEGRATIONS_CONFIGURATION = "integrations.configuration"
    RECOVERY_PROCESS_LOSS = "recovery.process_loss"
    HISTORY_DISCOVERY = "history.discovery"
    TELEMETRY_CONTENT_FREE = "telemetry.content_free"
    PACKAGING_ENTRY_POINT = "packaging.entry_point"


_CLAIM_CATEGORIES = {
    AdapterConformanceClaim.EXECUTION_RUN: AdapterConformanceCategory.EXECUTION,
    AdapterConformanceClaim.SESSIONS_LIFECYCLE: AdapterConformanceCategory.SESSIONS,
    AdapterConformanceClaim.APPROVALS_ROUND_TRIP: AdapterConformanceCategory.APPROVALS,
    AdapterConformanceClaim.ATTACHMENTS_INPUT: AdapterConformanceCategory.ATTACHMENTS,
    AdapterConformanceClaim.INTEGRATIONS_CONFIGURATION: (
        AdapterConformanceCategory.INTEGRATIONS
    ),
    AdapterConformanceClaim.RECOVERY_PROCESS_LOSS: AdapterConformanceCategory.RECOVERY,
    AdapterConformanceClaim.HISTORY_DISCOVERY: AdapterConformanceCategory.HISTORY,
    AdapterConformanceClaim.TELEMETRY_CONTENT_FREE: AdapterConformanceCategory.TELEMETRY,
    AdapterConformanceClaim.PACKAGING_ENTRY_POINT: AdapterConformanceCategory.PACKAGING,
}


@dataclass(frozen=True)
class AdapterManifest:
    """Content-free, versioned declaration for one out-of-tree adapter."""

    adapter_id: str
    adapter_version: str
    distribution: str
    entry_point: str
    claims: tuple[AdapterConformanceClaim, ...] = field(default_factory=tuple)
    schema_version: int = ADAPTER_MANIFEST_SCHEMA_VERSION
    sdk_api_version: int = ADAPTER_SDK_API_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ADAPTER_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported adapter manifest schema_version")
        if self.sdk_api_version != ADAPTER_SDK_API_VERSION:
            raise ValueError("unsupported adapter SDK api version")
        if _ADAPTER_ID_RE.fullmatch(self.adapter_id) is None:
            raise ValueError("adapter_id must be a lowercase stable identifier")
        if _VERSION_RE.fullmatch(self.adapter_version) is None:
            raise ValueError("adapter_version must be a stable dotted version")
        if _DISTRIBUTION_RE.fullmatch(self.distribution) is None:
            raise ValueError("distribution must be a valid package name")
        if _ENTRY_POINT_RE.fullmatch(self.entry_point) is None:
            raise ValueError("entry_point must use module.path:attribute syntax")
        normalized_claims = tuple(
            claim
            if isinstance(claim, AdapterConformanceClaim)
            else AdapterConformanceClaim(str(claim))
            for claim in self.claims
        )
        if len(set(normalized_claims)) != len(normalized_claims):
            raise ValueError("adapter manifest claims must be unique")
        object.__setattr__(
            self,
            "claims",
            tuple(sorted(normalized_claims, key=lambda claim: claim.value)),
        )

    def supports(self, claim: AdapterConformanceClaim | str) -> bool:
        """Return whether the manifest explicitly declares one claim."""
        try:
            normalized = (
                claim
                if isinstance(claim, AdapterConformanceClaim)
                else AdapterConformanceClaim(str(claim))
            )
        except ValueError:
            return False
        return normalized in self.claims


@dataclass(frozen=True)
class FakeProviderCall:
    """Content-bounded evidence for one fake provider request."""

    prompt: str
    workspace: str | None
    attachment_count: int


class AdapterExecutionProtocol(Protocol):
    """Minimal provider-neutral execution port used by SDK v1 scaffolds."""

    def availability(self) -> Availability:
        """Return current execution availability."""

    def run(self, request: HarnessRequest) -> HarnessResult:
        """Execute one normalized request."""


class FakeProviderProtocol(AdapterExecutionProtocol):
    """Deterministic provider fixture used by out-of-tree conformance tests."""

    def __init__(
        self,
        *,
        expected_prompt: str = "adapter conformance ping",
        response: str = "adapter conformance pong",
    ) -> None:
        self.expected_prompt = expected_prompt
        self.response = response
        self.calls: list[FakeProviderCall] = []

    def availability(self) -> Availability:
        """Report hermetic availability without provider or network access."""
        return Availability.available("fake provider protocol")

    def run(self, request: HarnessRequest) -> HarnessResult:
        """Return the scripted response and retain bounded call evidence."""
        if request.prompt != self.expected_prompt:
            return HarnessResult(
                ok=False,
                text="",
                error="unexpected conformance prompt",
            )
        self.calls.append(
            FakeProviderCall(
                prompt=request.prompt,
                workspace=request.workspace,
                attachment_count=len(request.attachments),
            )
        )
        return HarnessResult(
            ok=True,
            text=self.response,
            raw={"fixture": "fake-provider-v1"},
        )


@dataclass(frozen=True)
class AdapterConformanceProbeContext:
    """Inputs supplied to one explicit behavioral conformance probe."""

    manifest: AdapterManifest
    harness: BaseHarness
    fake_provider: FakeProviderProtocol


AdapterConformanceProbe = Callable[[AdapterConformanceProbeContext], None]


@dataclass(frozen=True)
class AdapterConformanceSubject:
    """Hermetic adapter instance and opt-in probes evaluated by the kit."""

    manifest: AdapterManifest
    harness: BaseHarness
    fake_provider: FakeProviderProtocol
    probes: Mapping[AdapterConformanceClaim, AdapterConformanceProbe] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class AdapterConformanceResult:
    """Result for one known v1 conformance claim."""

    claim: AdapterConformanceClaim
    category: AdapterConformanceCategory
    status: str
    detail: str


@dataclass(frozen=True)
class AdapterConformanceReport:
    """Complete v1 report including explicitly unsupported claims."""

    adapter_id: str
    adapter_version: str
    ok: bool
    issues: tuple[str, ...]
    results: tuple[AdapterConformanceResult, ...]


def adapter_manifest_to_dict(manifest: AdapterManifest) -> dict[str, Any]:
    """Serialize one adapter manifest deterministically."""
    return {
        "schema_version": manifest.schema_version,
        "sdk_api_version": manifest.sdk_api_version,
        "adapter_id": manifest.adapter_id,
        "adapter_version": manifest.adapter_version,
        "distribution": manifest.distribution,
        "entry_point": manifest.entry_point,
        "claims": [claim.value for claim in manifest.claims],
    }


def adapter_manifest_from_dict(data: Mapping[str, Any]) -> AdapterManifest:
    """Strictly parse one adapter manifest without inferring missing claims."""
    if not isinstance(data, Mapping):
        raise ValueError("adapter manifest must be an object")
    allowed = {
        "schema_version",
        "sdk_api_version",
        "adapter_id",
        "adapter_version",
        "distribution",
        "entry_point",
        "claims",
    }
    unknown = set(data) - allowed
    missing = allowed - set(data)
    if unknown:
        raise ValueError(f"adapter manifest has unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"adapter manifest is missing fields: {sorted(missing)}")
    schema_version = _strict_int(data["schema_version"], "schema_version")
    sdk_api_version = _strict_int(data["sdk_api_version"], "sdk_api_version")
    raw_claims = data["claims"]
    if not isinstance(raw_claims, list) or any(
        not isinstance(claim, str) for claim in raw_claims
    ):
        raise ValueError("adapter manifest claims must be a list of strings")
    try:
        claims = tuple(AdapterConformanceClaim(claim) for claim in raw_claims)
    except ValueError as exc:
        raise ValueError(
            "adapter manifest contains an unknown conformance claim"
        ) from exc
    return AdapterManifest(
        schema_version=schema_version,
        sdk_api_version=sdk_api_version,
        adapter_id=_strict_text(data["adapter_id"], "adapter_id"),
        adapter_version=_strict_text(data["adapter_version"], "adapter_version"),
        distribution=_strict_text(data["distribution"], "distribution"),
        entry_point=_strict_text(data["entry_point"], "entry_point"),
        claims=claims,
    )


def load_adapter_manifest(path: str | Path) -> AdapterManifest:
    """Load a strict adapter manifest from a UTF-8 JSON file."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("adapter manifest could not be loaded") from exc
    return adapter_manifest_from_dict(payload)


def load_packaged_adapter_manifest(package: str) -> AdapterManifest:
    """Load ``adapter_manifest.json`` from an installed adapter package."""
    try:
        resource = resources.files(package).joinpath("adapter_manifest.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (ImportError, ModuleNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("packaged adapter manifest could not be loaded") from exc
    return adapter_manifest_from_dict(payload)


def adapter_conformance_report_to_dict(
    report: AdapterConformanceReport,
) -> dict[str, Any]:
    """Serialize one bounded conformance report for CLI and CI."""
    return {
        "sdk_api_version": ADAPTER_SDK_API_VERSION,
        "adapter_id": report.adapter_id,
        "adapter_version": report.adapter_version,
        "ok": report.ok,
        "issues": list(report.issues),
        "categories": [category.value for category in AdapterConformanceCategory],
        "results": [
            {
                "claim": result.claim.value,
                "category": result.category.value,
                "status": result.status,
                "detail": result.detail,
            }
            for result in report.results
        ],
    }


def run_adapter_conformance(
    subject: AdapterConformanceSubject,
) -> AdapterConformanceReport:
    """Run only explicitly declared claims against a hermetic subject."""
    manifest = subject.manifest
    issues = _subject_issues(subject)
    context = AdapterConformanceProbeContext(
        manifest=manifest,
        harness=subject.harness,
        fake_provider=subject.fake_provider,
    )
    builtins: dict[AdapterConformanceClaim, AdapterConformanceProbe] = {
        AdapterConformanceClaim.EXECUTION_RUN: _probe_execution,
        AdapterConformanceClaim.PACKAGING_ENTRY_POINT: _probe_packaging,
    }
    results: list[AdapterConformanceResult] = []
    for claim in AdapterConformanceClaim:
        category = _CLAIM_CATEGORIES[claim]
        if not manifest.supports(claim):
            results.append(
                AdapterConformanceResult(
                    claim=claim,
                    category=category,
                    status="unsupported",
                    detail="claim not declared by adapter manifest",
                )
            )
            continue
        probe = subject.probes.get(claim) or builtins.get(claim)
        if probe is None:
            results.append(
                AdapterConformanceResult(
                    claim=claim,
                    category=category,
                    status="failed",
                    detail="declared claim has no conformance probe",
                )
            )
            continue
        try:
            probe(context)
        except Exception as exc:
            results.append(
                AdapterConformanceResult(
                    claim=claim,
                    category=category,
                    status="failed",
                    detail=f"{type(exc).__name__}: conformance probe failed",
                )
            )
        else:
            results.append(
                AdapterConformanceResult(
                    claim=claim,
                    category=category,
                    status="passed",
                    detail="declared claim passed",
                )
            )
    ok = not issues and all(result.status != "failed" for result in results)
    return AdapterConformanceReport(
        adapter_id=manifest.adapter_id,
        adapter_version=manifest.adapter_version,
        ok=ok,
        issues=tuple(issues),
        results=tuple(results),
    )


def load_installed_conformance_subject(adapter_id: str) -> AdapterConformanceSubject:
    """Load one adapter-owned hermetic subject from the v1 entry-point group."""
    if _ADAPTER_ID_RE.fullmatch(adapter_id) is None:
        raise ValueError("adapter_id must be a lowercase stable identifier")
    matches = sorted(
        _select_entry_points(CONFORMANCE_ENTRY_POINT_GROUP, adapter_id),
        key=lambda entry_point: str(getattr(entry_point, "value", "")),
    )
    if not matches:
        raise ValueError("adapter conformance entry point is not installed")
    if len(matches) != 1:
        raise ValueError("adapter conformance entry point is ambiguous")
    try:
        factory = matches[0].load()
        subject = factory()
    except Exception as exc:
        raise ValueError("adapter conformance subject could not be loaded") from exc
    if not isinstance(subject, AdapterConformanceSubject):
        raise ValueError("conformance entry point returned an invalid subject")
    if subject.manifest.adapter_id != adapter_id:
        raise ValueError("conformance subject adapter_id does not match entry point")
    return subject


def _subject_issues(subject: AdapterConformanceSubject) -> list[str]:
    issues: list[str] = []
    spec = subject.harness.spec()
    report = validate_harness_spec(spec)
    if spec.id != subject.manifest.adapter_id:
        issues.append("harness spec id does not match adapter manifest")
    if not report.ok:
        issues.append("harness spec validation failed")
    unknown_probes = set(subject.probes) - set(AdapterConformanceClaim)
    if unknown_probes:
        issues.append("conformance subject contains unknown probes")
    return issues


def _probe_execution(context: AdapterConformanceProbeContext) -> None:
    availability = context.harness.availability()
    if availability.status is not AvailabilityStatus.AVAILABLE:
        raise AssertionError("fake provider harness is unavailable")
    result = context.harness.run(
        HarnessRequest(prompt=context.fake_provider.expected_prompt),
        HarnessContext(
            proxy_url="http://127.0.0.1:9",
            timeout_seconds=1.0,
        ),
    )
    if not isinstance(result, HarnessResult) or not result.ok:
        raise AssertionError("adapter did not return a successful HarnessResult")
    if result.text != context.fake_provider.response:
        raise AssertionError("adapter did not preserve the fake provider response")
    if len(context.fake_provider.calls) != 1:
        raise AssertionError(
            "adapter did not execute exactly one fake provider request"
        )


def _probe_packaging(context: AdapterConformanceProbeContext) -> None:
    try:
        distribution = metadata.distribution(context.manifest.distribution)
    except metadata.PackageNotFoundError as exc:
        raise AssertionError("adapter distribution is not installed") from exc
    matches = [
        entry_point
        for entry_point in distribution.entry_points
        if entry_point.group == ADAPTER_ENTRY_POINT_GROUP
        and entry_point.name == context.manifest.adapter_id
    ]
    if len(matches) != 1:
        raise AssertionError("adapter distribution must expose one v1 entry point")
    if matches[0].value != context.manifest.entry_point:
        raise AssertionError("installed adapter entry point differs from manifest")


def _select_entry_points(group: str, name: str):
    points = metadata.entry_points()
    if hasattr(points, "select"):
        return tuple(points.select(group=group, name=name))
    return tuple(
        entry_point for entry_point in points.get(group, ()) if entry_point.name == name
    )


def _strict_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"adapter manifest {field_name} must be an integer")
    return value


def _strict_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"adapter manifest {field_name} must be non-empty text")
    return value


__all__ = [
    "ADAPTER_ENTRY_POINT_GROUP",
    "ADAPTER_MANIFEST_SCHEMA_VERSION",
    "ADAPTER_SDK_API_VERSION",
    "CONFORMANCE_ENTRY_POINT_GROUP",
    "AdapterConformanceCategory",
    "AdapterConformanceClaim",
    "AdapterConformanceProbe",
    "AdapterConformanceProbeContext",
    "AdapterConformanceReport",
    "AdapterConformanceResult",
    "AdapterConformanceSubject",
    "AdapterExecutionProtocol",
    "AdapterManifest",
    "FakeProviderCall",
    "FakeProviderProtocol",
    "adapter_conformance_report_to_dict",
    "adapter_manifest_from_dict",
    "adapter_manifest_to_dict",
    "load_adapter_manifest",
    "load_installed_conformance_subject",
    "load_packaged_adapter_manifest",
    "run_adapter_conformance",
]
