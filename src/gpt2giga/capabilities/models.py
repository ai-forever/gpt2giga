"""Model-aware capability contracts for route admission."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReasonId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
EvidenceId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$"),
]
MachineId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
]
Revision = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class CapabilityState(str, Enum):
    """Truth state for one capability at one resolution layer."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CapabilityKey(str, Enum):
    """Complete model-level semantic vocabulary for the 0.3 release."""

    TEXT_INPUT = "text_input"
    STREAMING = "streaming"
    FUNCTION_TOOLS = "function_tools"
    HOSTED_WEB_SEARCH = "hosted_web_search"
    HOSTED_URL_EXTRACTION = "hosted_url_extraction"
    HOSTED_CODE_INTERPRETER = "hosted_code_interpreter"
    HOSTED_IMAGE_GENERATION = "hosted_image_generation"
    HOSTED_3D_GENERATION = "hosted_3d_generation"
    PARALLEL_TOOL_CALLS = "parallel_tool_calls"
    JSON_SCHEMA_OUTPUT = "json_schema_output"
    REASONING_CONTROLS = "reasoning_controls"
    REASONING_SUMMARY = "reasoning_summary"
    PREVIOUS_RESPONSE_STATE = "previous_response_state"
    CONVERSATION_STATE = "conversation_state"
    FILE_INPUT = "file_input"
    IMAGE_INPUT = "image_input"
    USAGE_TOKENS = "usage_tokens"
    CANCELLATION = "cancellation"
    DISCONNECT = "disconnect"


class CapabilitySource(str, Enum):
    """Reviewed source that produced one capability decision."""

    PROVIDER_METADATA = "provider_metadata"
    EXACT_MODEL_OVERLAY = "exact_model_overlay"
    FAMILY_OVERLAY = "family_overlay"
    HERMETIC_PROBE = "hermetic_probe"
    PROVIDER_INVARIANT = "provider_invariant"
    PUBLIC_PROTOCOL = "public_protocol"
    PROVIDER_ADAPTER = "provider_adapter"
    API_MODE = "api_mode"
    ROUTE_POLICY = "route_policy"
    EFFECTIVE_INTERSECTION = "effective_intersection"
    UNRESOLVED = "unresolved"


class CapabilityScope(str, Enum):
    """One input dimension of effective route capability resolution."""

    PUBLIC_PROTOCOL = "public_protocol"
    PROVIDER_ADAPTER = "provider_adapter"
    MODEL = "model"
    API_MODE = "api_mode"
    ROUTE_POLICY = "route_policy"


class _CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityEvidence(_CapabilityModel):
    """Content-free evidence reference retained by effective decisions."""

    evidence_id: EvidenceId
    source: CapabilitySource
    revision: Revision


class CapabilityDecision(_CapabilityModel):
    """One tri-state decision with stable, inspectable provenance."""

    state: CapabilityState
    reason_id: ReasonId
    source: CapabilitySource
    evidence_ids: tuple[EvidenceId, ...] = ()
    revision: Revision

    @model_validator(mode="after")
    def _canonicalize_evidence(self) -> CapabilityDecision:
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(sorted(set(self.evidence_ids))),
        )
        return self


class CapabilityLayer(_CapabilityModel):
    """Complete capability input for one resolver dimension."""

    schema_version: Literal["gpt2giga.capability-layer.v1"] = (
        "gpt2giga.capability-layer.v1"
    )
    scope: CapabilityScope
    scope_id: MachineId
    capabilities: dict[CapabilityKey, CapabilityDecision]
    revision: Revision
    evidence: tuple[CapabilityEvidence, ...] = ()

    @model_validator(mode="after")
    def _validate_complete_layer(self) -> CapabilityLayer:
        missing = set(CapabilityKey) - set(self.capabilities)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"capability layer is missing decisions: {names}")
        evidence = {item.evidence_id: item for item in self.evidence}
        object.__setattr__(
            self,
            "capabilities",
            dict(sorted(self.capabilities.items(), key=lambda item: item[0].value)),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(evidence[key] for key in sorted(evidence)),
        )
        return self


class EffectiveModelCapabilities(_CapabilityModel):
    """Effective protocol/provider/model/API-mode/route capability result."""

    schema_version: Literal["gpt2giga.model-capabilities.v1"] = (
        "gpt2giga.model-capabilities.v1"
    )
    model_id: MachineId
    provider_kind: MachineId
    public_protocol: MachineId
    api_mode: MachineId | None = None
    capabilities: dict[CapabilityKey, CapabilityDecision]
    revision: Revision
    evidence: tuple[CapabilityEvidence, ...] = ()
    layer_revisions: tuple[Revision, ...]

    @model_validator(mode="after")
    def _validate_complete_result(self) -> EffectiveModelCapabilities:
        missing = set(CapabilityKey) - set(self.capabilities)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"effective result is missing decisions: {names}")
        evidence = {item.evidence_id: item for item in self.evidence}
        object.__setattr__(
            self,
            "capabilities",
            dict(sorted(self.capabilities.items(), key=lambda item: item[0].value)),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(evidence[key] for key in sorted(evidence)),
        )
        object.__setattr__(
            self,
            "layer_revisions",
            tuple(sorted(set(self.layer_revisions))),
        )
        return self


def capability_revision(payload: Any) -> str:
    """Return a deterministic revision for secret-free capability content."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
