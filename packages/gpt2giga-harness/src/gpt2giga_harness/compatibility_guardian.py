"""Deterministic compatibility fixtures for native and extension contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from gpt2giga_harness.adapter_sdk import (
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    ADAPTER_SDK_API_VERSION,
)
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.federated_catalog import (
    FEDERATED_CATALOG_CONTRACT_VERSION,
    NEURALDEEP_ORIGIN,
    NEURALDEEP_SOURCE_ID,
    SKILLS_SH_ORIGIN,
    SKILLS_SH_SOURCE_ID,
    NeuralDeepFederatedCatalogSource,
    SkillsShFederatedCatalogSource,
)
from gpt2giga_harness.integration_catalog import (
    CATALOG_SCHEMA_VERSION,
    OFFICIAL_MCP_REGISTRY_API_VERSION,
    OFFICIAL_MCP_REGISTRY_BASE_URL,
    OFFICIAL_MCP_REGISTRY_SOURCE_ID,
)
from gpt2giga_harness.integration_packages import (
    EXTENSION_TARGET_SCHEMA_VERSION,
    INTEGRATION_PACKAGE_SCHEMA_VERSION,
)
from gpt2giga_harness.integration_sdk import INTEGRATION_SDK_API_VERSION
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.structured import (
    DurableStructuredAdmissionError,
    admitted_durable_structured_capabilities,
)

COMPATIBILITY_GUARDIAN_SCHEMA_VERSION = 1
COMPATIBILITY_FIXTURE_VERSION = "n7-05-v1"

_PASSED = "passed"
_BLOCKED = "blocked"
_CATEGORIES = ("adapter", "provider", "extension", "environment", "model")
_FAILURE_TAXONOMY = {
    "adapter": "native_cli_or_normalized_schema_drift",
    "provider": "provider_protocol_or_driver_drift",
    "extension": "sdk_schema_or_marketplace_contract_drift",
    "environment": "executable_discovery_or_probe_failure",
    "model": "truthful_execution_missed_fixture_contract",
}
_EXPECTED_SCHEMA_CONTRACTS = {
    "adapter_manifest": 1,
    "adapter_sdk": 1,
    "catalog": 1,
    "extension_target": 1,
    "federated_catalog": 1,
    "integration_package": 1,
    "integration_sdk": 1,
}
_EXPECTED_MARKETPLACE_CONTRACTS = {
    "official_mcp_api": "v0.1",
    "official_mcp_origin": "https://registry.modelcontextprotocol.io",
    "official_mcp_source": "official-mcp-registry",
    "skills_origin": "https://skills.sh",
    "skills_source": "skills-sh",
    "neuraldeep_origin": "https://neuraldeep.ru",
    "neuraldeep_source": "neuraldeep",
    "descriptors_read_only": True,
}
_EXPECTED_CLI_CONTRACTS: dict[str, dict[str, Any]] = {
    "codex-cli": {
        "minimum": "0.144.0",
        "maximum_exclusive": "0.145.0",
        "event_schema": "codex-exec-jsonl-v1",
        "history_schema": "codex-session-jsonl-v1",
        "native_event_schema": "raw-terminal-v1",
        "required_capabilities": ("--json", "--sandbox", "--ephemeral", "app-server"),
        "structured_protocol": "codex-app-server-json-rpc-v2",
        "structured_protocol_version": "2",
    },
    "claude-code": {
        "minimum": "2.1.0",
        "maximum_exclusive": "2.2.0",
        "event_schema": "claude-stream-json-v1",
        "history_schema": "claude-project-jsonl-v1",
        "native_event_schema": "raw-terminal-v1",
        "required_capabilities": (
            "--output-format",
            "stream-json",
            "--permission-mode",
            "--no-session-persistence",
        ),
        "structured_protocol": None,
        "structured_protocol_version": None,
    },
    "gemini-cli": {
        "minimum": "0.46.0",
        "maximum_exclusive": "0.47.0",
        "event_schema": "gemini-stream-json-v1",
        "history_schema": "gemini-checkpoint-jsonl-v1",
        "native_event_schema": "raw-terminal-v1",
        "required_capabilities": (
            "--output-format",
            "stream-json",
            "--approval-mode",
            "--skip-trust",
            "--acp",
            "--experimental-acp",
        ),
        "structured_protocol": "agent-client-protocol",
        "structured_protocol_version": "1",
    },
}


@dataclass(frozen=True)
class CompatibilityFixtureResult:
    """One content-free compatibility fixture result."""

    fixture_id: str
    category: str
    status: str
    code: str
    expected: str
    observed: str

    def __post_init__(self) -> None:
        if self.category not in _CATEGORIES:
            raise ValueError("compatibility fixture category is invalid")
        if self.status not in {_PASSED, _BLOCKED}:
            raise ValueError("compatibility fixture status is invalid")

    def to_dict(self) -> dict[str, Any]:
        """Serialize one bounded fixture with deterministic evidence."""
        payload = {
            "id": self.fixture_id,
            "category": self.category,
            "status": self.status,
            "code": self.code,
            "expected": self.expected,
            "observed": self.observed,
        }
        return {**payload, "evidence_hash": _hash(payload)}


def run_compatibility_guardian(
    registry: HarnessRegistry,
    *,
    harness_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run offline contract fixtures without starting providers or integrations."""
    selected = (
        tuple(sorted(dict.fromkeys(harness_ids)))
        if harness_ids is not None
        else tuple(sorted(registry.ids()))
    )
    fixtures = [*_static_contract_fixtures()]
    if registry.discovery_errors:
        fixtures.append(
            _fixture(
                "registry.discovery",
                "environment",
                _BLOCKED,
                "entry_point_discovery_failed",
                "no_errors",
                f"error_count:{len(registry.discovery_errors)}",
            )
        )
    else:
        fixtures.append(
            _fixture(
                "registry.discovery",
                "environment",
                _PASSED,
                "entry_point_discovery_accepted",
                "no_errors",
                "no_errors",
            )
        )
    for harness_id in selected:
        try:
            harness = registry.get(harness_id)
        except KeyError:
            fixtures.append(
                _fixture(
                    f"adapter.{harness_id}",
                    "environment",
                    _BLOCKED,
                    "adapter_not_registered",
                    "registered",
                    "missing",
                )
            )
            continue
        fixtures.extend(compatibility_fixtures_for_harness(harness))
    serialized = [item.to_dict() for item in fixtures]
    blocked = sum(item["status"] == _BLOCKED for item in serialized)
    summary = {
        "passed": len(serialized) - blocked,
        "blocked": blocked,
        "categories": {
            category: {
                "passed": sum(
                    item["category"] == category and item["status"] == _PASSED
                    for item in serialized
                ),
                "blocked": sum(
                    item["category"] == category and item["status"] == _BLOCKED
                    for item in serialized
                ),
            }
            for category in _CATEGORIES
        },
    }
    payload = {
        "schema_version": COMPATIBILITY_GUARDIAN_SCHEMA_VERSION,
        "fixture_version": COMPATIBILITY_FIXTURE_VERSION,
        "status": "blocked" if blocked else "ready",
        "ok": blocked == 0,
        "block_execution": blocked > 0,
        "summary": summary,
        "failure_taxonomy": dict(_FAILURE_TAXONOMY),
        "fixtures": serialized,
    }
    return {**payload, "snapshot_hash": _hash(payload)}


def compatibility_fixtures_for_harness(
    harness: Any,
) -> tuple[CompatibilityFixtureResult, ...]:
    """Evaluate one adapter without executing its provider."""
    harness_id = str(harness.spec().id)
    expected = _EXPECTED_CLI_CONTRACTS.get(harness_id)
    probe = getattr(harness, "capability_probe", None)
    if expected is None:
        return ()
    if not callable(probe):
        return (
            _fixture(
                f"adapter.{harness_id}",
                "adapter",
                _BLOCKED,
                "capability_probe_missing",
                "bounded_probe",
                "missing",
            ),
        )
    try:
        snapshot = probe()
    except Exception:
        return (
            _fixture(
                f"adapter.{harness_id}",
                "environment",
                _BLOCKED,
                "capability_probe_failed",
                "supported",
                "error",
            ),
        )
    if not isinstance(snapshot, CliCapabilitySnapshot):
        return (
            _fixture(
                f"adapter.{harness_id}",
                "adapter",
                _BLOCKED,
                "capability_snapshot_invalid",
                "schema_v1",
                "invalid",
            ),
        )
    cli_fixture = _cli_fixture(harness_id, snapshot, expected)
    if cli_fixture.status == _BLOCKED:
        return (cli_fixture, _provider_fixture_blocked(harness_id, expected))
    return (cli_fixture, _provider_fixture(harness, harness_id, expected))


def compatibility_readiness_check(harness: Any) -> dict[str, Any] | None:
    """Project a selected adapter guardian result into execution readiness."""
    probe = getattr(harness, "capability_probe", None)
    if not callable(probe):
        return None
    try:
        snapshot = probe()
    except Exception:
        snapshot = None
    if snapshot is not None and not isinstance(snapshot, CliCapabilitySnapshot):
        # Legacy/out-of-tree harness doubles may expose a private probe shape.
        # Only the public native CLI snapshot contract is admission-authoritative.
        return None
    fixtures = compatibility_fixtures_for_harness(harness)
    if not fixtures:
        return None
    serialized = [item.to_dict() for item in fixtures]
    blocked = [item for item in serialized if item["status"] == _BLOCKED]
    evidence_payload = {
        "schema_version": COMPATIBILITY_GUARDIAN_SCHEMA_VERSION,
        "fixture_version": COMPATIBILITY_FIXTURE_VERSION,
        "fixtures": serialized,
    }
    if blocked:
        return {
            "id": "compatibility-guardian",
            "status": "blocked",
            "summary": "Selected adapter is outside the reviewed compatibility contract.",
            "required": True,
            "remediation": [
                {
                    "message": "Review the detected compatibility drift before execution.",
                    "command": "giga compatibility check --json",
                }
            ],
            "evidence": {
                "fixture_version": COMPATIBILITY_FIXTURE_VERSION,
                "blocked_categories": sorted(
                    {str(item["category"]) for item in blocked}
                ),
                "reason_codes": sorted({str(item["code"]) for item in blocked}),
                "snapshot_hash": _hash(evidence_payload),
            },
        }
    return {
        "id": "compatibility-guardian",
        "status": "ready",
        "summary": "Selected adapter matches the reviewed compatibility contract.",
        "required": True,
        "evidence": {
            "fixture_version": COMPATIBILITY_FIXTURE_VERSION,
            "snapshot_hash": _hash(evidence_payload),
        },
    }


def _cli_fixture(
    harness_id: str,
    snapshot: CliCapabilitySnapshot,
    expected: Mapping[str, Any],
) -> CompatibilityFixtureResult:
    if snapshot.status in {"missing", "error"}:
        return _fixture(
            f"adapter.{harness_id}",
            "environment",
            _BLOCKED,
            f"cli_{snapshot.status}",
            "supported",
            snapshot.status,
        )
    mismatches = []
    for field in ("event_schema", "history_schema", "native_event_schema"):
        if getattr(snapshot, field) != expected[field]:
            mismatches.append(field)
    if snapshot.minimum_version != expected["minimum"]:
        mismatches.append("minimum_version")
    if snapshot.maximum_version_exclusive != expected["maximum_exclusive"]:
        mismatches.append("maximum_version")
    if snapshot.version_window_status != "in_window":
        mismatches.append("version_window")
    missing = [
        capability
        for capability in expected["required_capabilities"]
        if not snapshot.capabilities.get(capability, False)
    ]
    if snapshot.status != "supported" or mismatches or missing:
        observed = ",".join(
            (
                f"status:{snapshot.status}",
                f"version:{snapshot.parsed_version or 'unparsed'}",
                f"drift:{'+'.join(sorted(mismatches)) or 'none'}",
                f"missing:{'+'.join(sorted(missing)) or 'none'}",
            )
        )
        return _fixture(
            f"adapter.{harness_id}",
            "adapter",
            _BLOCKED,
            "native_cli_contract_drift",
            (
                f"version:{expected['minimum']}.."
                f"{expected['maximum_exclusive']};schemas:v1"
            ),
            observed,
        )
    return _fixture(
        f"adapter.{harness_id}",
        "adapter",
        _PASSED,
        "native_cli_contract_accepted",
        (f"version:{expected['minimum']}..{expected['maximum_exclusive']};schemas:v1"),
        f"version:{snapshot.parsed_version};schemas:v1",
    )


def _provider_fixture(
    harness: Any,
    harness_id: str,
    expected: Mapping[str, Any],
) -> CompatibilityFixtureResult:
    protocol = expected["structured_protocol"]
    version = expected["structured_protocol_version"]
    if protocol is None:
        return _fixture(
            f"provider.{harness_id}",
            "provider",
            _PASSED,
            "provider_boundary_accepted",
            "native_handoff_or_one_shot",
            "native_handoff_or_one_shot",
        )
    try:
        capabilities = admitted_durable_structured_capabilities(harness)
    except (DurableStructuredAdmissionError, TypeError, ValueError):
        return _fixture(
            f"provider.{harness_id}",
            "provider",
            _BLOCKED,
            "structured_protocol_unavailable",
            f"{protocol}@{version}",
            "unavailable",
        )
    if (
        capabilities.protocol != protocol
        or capabilities.protocol_version != version
        or capabilities.adapter_id != harness_id
    ):
        return _fixture(
            f"provider.{harness_id}",
            "provider",
            _BLOCKED,
            "structured_protocol_drift",
            f"{protocol}@{version}",
            f"{capabilities.protocol}@{capabilities.protocol_version}",
        )
    return _fixture(
        f"provider.{harness_id}",
        "provider",
        _PASSED,
        "structured_protocol_accepted",
        f"{protocol}@{version}",
        f"{capabilities.protocol}@{capabilities.protocol_version}",
    )


def _provider_fixture_blocked(
    harness_id: str,
    expected: Mapping[str, Any],
) -> CompatibilityFixtureResult:
    expected_protocol = expected["structured_protocol"]
    return _fixture(
        f"provider.{harness_id}",
        "provider",
        _BLOCKED,
        "adapter_contract_unavailable",
        (
            "native_handoff_or_one_shot"
            if expected_protocol is None
            else f"{expected_protocol}@{expected['structured_protocol_version']}"
        ),
        "not_evaluated",
    )


def _static_contract_fixtures() -> tuple[CompatibilityFixtureResult, ...]:
    observed_schemas = {
        "adapter_manifest": ADAPTER_MANIFEST_SCHEMA_VERSION,
        "adapter_sdk": ADAPTER_SDK_API_VERSION,
        "catalog": CATALOG_SCHEMA_VERSION,
        "extension_target": EXTENSION_TARGET_SCHEMA_VERSION,
        "federated_catalog": FEDERATED_CATALOG_CONTRACT_VERSION,
        "integration_package": INTEGRATION_PACKAGE_SCHEMA_VERSION,
        "integration_sdk": INTEGRATION_SDK_API_VERSION,
    }
    schema_status = (
        _PASSED if observed_schemas == _EXPECTED_SCHEMA_CONTRACTS else _BLOCKED
    )
    marketplace = {
        "official_mcp_api": OFFICIAL_MCP_REGISTRY_API_VERSION,
        "official_mcp_origin": OFFICIAL_MCP_REGISTRY_BASE_URL,
        "official_mcp_source": OFFICIAL_MCP_REGISTRY_SOURCE_ID,
        "skills_origin": SKILLS_SH_ORIGIN,
        "skills_source": SKILLS_SH_SOURCE_ID,
        "neuraldeep_origin": NEURALDEEP_ORIGIN,
        "neuraldeep_source": NEURALDEEP_SOURCE_ID,
    }
    descriptor_contracts_match = (
        SkillsShFederatedCatalogSource.descriptor.source_id == SKILLS_SH_SOURCE_ID
        and SkillsShFederatedCatalogSource.descriptor.canonical_origin
        == SKILLS_SH_ORIGIN
        and SkillsShFederatedCatalogSource.descriptor.install_authorized is False
        and NeuralDeepFederatedCatalogSource.descriptor.source_id
        == NEURALDEEP_SOURCE_ID
        and NeuralDeepFederatedCatalogSource.descriptor.canonical_origin
        == NEURALDEEP_ORIGIN
        and NeuralDeepFederatedCatalogSource.descriptor.install_authorized is False
    )
    marketplace["descriptors_read_only"] = descriptor_contracts_match
    marketplace_status = (
        _PASSED if marketplace == _EXPECTED_MARKETPLACE_CONTRACTS else _BLOCKED
    )
    return (
        _fixture(
            "extension.sdk-schema",
            "extension",
            schema_status,
            (
                "sdk_schema_contracts_accepted"
                if schema_status == _PASSED
                else "sdk_schema_contract_drift"
            ),
            _compact_mapping(_EXPECTED_SCHEMA_CONTRACTS),
            _compact_mapping(observed_schemas),
        ),
        _fixture(
            "extension.marketplace",
            "extension",
            marketplace_status,
            (
                "marketplace_contracts_accepted"
                if marketplace_status == _PASSED
                else "marketplace_contract_drift"
            ),
            _hash(_EXPECTED_MARKETPLACE_CONTRACTS),
            _hash(marketplace),
        ),
    )


def _fixture(
    fixture_id: str,
    category: str,
    status: str,
    code: str,
    expected: str,
    observed: str,
) -> CompatibilityFixtureResult:
    return CompatibilityFixtureResult(
        fixture_id=fixture_id,
        category=category,
        status=status,
        code=code,
        expected=expected,
        observed=observed,
    )


def _compact_mapping(value: Mapping[str, Any]) -> str:
    return ",".join(f"{key}:{value[key]}" for key in sorted(value))


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "COMPATIBILITY_FIXTURE_VERSION",
    "COMPATIBILITY_GUARDIAN_SCHEMA_VERSION",
    "CompatibilityFixtureResult",
    "compatibility_fixtures_for_harness",
    "compatibility_readiness_check",
    "run_compatibility_guardian",
]
