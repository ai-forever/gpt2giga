"""Capability-based durable admission for structured native drivers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol, runtime_checkable

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.structured_sessions import (
    AdapterCapabilitySnapshot,
    capability_snapshot_to_dict,
)
from gpt2giga_harness.types import HarnessContext, HarnessRequest, HarnessResult

DURABLE_STRUCTURED_ADMISSION_SCHEMA_VERSION = 1
DURABLE_STRUCTURED_ADMISSION_FIELD = "_durable_structured_admission"


class DurableStructuredAdmissionError(ValueError):
    """Raised when a requested durable structured transport is not proven."""


@runtime_checkable
class DurableStructuredHarness(Protocol):
    """Optional adapter contract for worker-owned structured execution."""

    def durable_structured_capabilities(self) -> AdapterCapabilitySnapshot:
        """Return reviewed, content-free admission capabilities."""

    def run_durable_structured(
        self, request: HarnessRequest, context: HarnessContext
    ) -> HarnessResult:
        """Run one worker-owned turn through the structured driver."""


@dataclass(frozen=True)
class DurableStructuredAdmission:
    """Immutable content-free decision persisted with a durable payload."""

    harness_id: str
    capability_snapshot: AdapterCapabilitySnapshot
    retry_class: str
    schema_version: int = DURABLE_STRUCTURED_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DURABLE_STRUCTURED_ADMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported durable structured admission schema")
        if self.harness_id != self.capability_snapshot.adapter_id:
            raise ValueError("admission harness and capability identities differ")
        if self.retry_class not in {
            "structured_recoverable",
            "structured_ambiguous",
        }:
            raise ValueError("unsupported durable structured retry class")

    def to_dict(self) -> dict[str, Any]:
        """Serialize one admission with a deterministic integrity hash."""
        payload = {
            "schema_version": self.schema_version,
            "harness_id": self.harness_id,
            "transport": ExecutionTransport.NATIVE_STRUCTURED.value,
            "retry_class": self.retry_class,
            "capability_snapshot": capability_snapshot_to_dict(
                self.capability_snapshot
            ),
        }
        return {**payload, "admission_hash": _hash(payload)}


def requested_execution_transport(
    payload: Mapping[str, Any],
) -> ExecutionTransport | None:
    """Parse an optional canonical transport without inferring legacy native mode."""
    value = payload.get("execution_transport")
    if value is None or not str(value).strip():
        return None
    try:
        return ExecutionTransport(str(value).strip().lower())
    except ValueError as exc:
        raise DurableStructuredAdmissionError(
            "execution_transport must be native_structured, native_terminal, or one_shot"
        ) from exc


def prepare_durable_structured_admission(
    harness: Any, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate and freeze an explicitly requested structured-native transport."""
    transport = requested_execution_transport(payload)
    if transport is None:
        return dict(payload)
    if transport is not ExecutionTransport.NATIVE_STRUCTURED:
        if transport is ExecutionTransport.NATIVE_TERMINAL:
            raise DurableStructuredAdmissionError(
                "native_terminal remains synchronous and is not durable-admitted"
            )
        return dict(payload)
    if not isinstance(harness, DurableStructuredHarness):
        raise DurableStructuredAdmissionError(
            "selected harness has no proven durable native_structured driver"
        )
    capabilities = harness.durable_structured_capabilities()
    _validate_capabilities(capabilities)
    retry_class = (
        "structured_recoverable"
        if capabilities.durable_approval and capabilities.recovery_after_process_loss
        else "structured_ambiguous"
    )
    admission = DurableStructuredAdmission(
        harness_id=capabilities.adapter_id,
        capability_snapshot=capabilities,
        retry_class=retry_class,
    )
    prepared = dict(payload)
    prepared[DURABLE_STRUCTURED_ADMISSION_FIELD] = admission.to_dict()
    return prepared


def structured_admission(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return and minimally verify the frozen structured admission record."""
    value = payload.get(DURABLE_STRUCTURED_ADMISSION_FIELD)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DurableStructuredAdmissionError("structured admission must be an object")
    payload_without_hash = {key: value[key] for key in value if key != "admission_hash"}
    if value.get("admission_hash") != _hash(payload_without_hash):
        raise DurableStructuredAdmissionError("structured admission hash mismatch")
    if value.get("transport") != ExecutionTransport.NATIVE_STRUCTURED.value:
        raise DurableStructuredAdmissionError("structured admission transport changed")
    return value


def _validate_capabilities(capabilities: AdapterCapabilitySnapshot) -> None:
    if not isinstance(capabilities, AdapterCapabilitySnapshot):
        raise DurableStructuredAdmissionError(
            "structured capability probe returned an invalid snapshot"
        )
    required = {
        "structured_events": capabilities.structured_events,
        "interrupt": capabilities.interrupt,
        "resume": capabilities.resume,
        "recovery_after_process_loss": capabilities.recovery_after_process_loss,
    }
    missing = sorted(name for name, supported in required.items() if not supported)
    if missing:
        raise DurableStructuredAdmissionError(
            "structured driver is not durable-admissible: missing " + ", ".join(missing)
        )
    if not (capabilities.live_approvals or capabilities.durable_approval):
        raise DurableStructuredAdmissionError(
            "structured driver has no proven approval bridge"
        )


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
