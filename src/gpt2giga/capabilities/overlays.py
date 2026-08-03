"""Versioned, reviewed model capability overlays."""

from __future__ import annotations

from importlib import resources
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gpt2giga.capabilities.models import (
    CapabilityDecision,
    CapabilityEvidence,
    CapabilityKey,
    CapabilityLayer,
    CapabilityScope,
    CapabilitySource,
    CapabilityState,
    EvidenceId,
    MachineId,
    ReasonId,
    capability_revision,
)


class _OverlayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OverlayCapabilityDecision(_OverlayModel):
    """Sparse reviewed decision stored in overlay data."""

    state: CapabilityState
    reason_id: ReasonId
    evidence_ids: tuple[EvidenceId, ...] = ()


class ModelCapabilityOverlay(_OverlayModel):
    """One exact-model or reviewed-family overlay."""

    overlay_id: MachineId
    selector_kind: Literal["exact", "family"]
    selector: str = Field(min_length=1, max_length=256)
    api_modes: tuple[Literal["v1", "v2"], ...] = Field(min_length=1)
    capabilities: dict[CapabilityKey, OverlayCapabilityDecision]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_selector(self) -> ModelCapabilityOverlay:
        if self.selector_kind == "family":
            if not self.selector.startswith("^") or not self.selector.endswith("$"):
                raise ValueError("reviewed family patterns must be anchored")
            re.compile(self.selector)
        object.__setattr__(self, "api_modes", tuple(sorted(set(self.api_modes))))
        object.__setattr__(
            self,
            "capabilities",
            dict(sorted(self.capabilities.items(), key=lambda item: item[0].value)),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(sorted(set(self.evidence_ids))),
        )
        return self

    def matches(self, model_id: str, api_mode: str) -> bool:
        """Return whether this reviewed selector applies exactly."""
        if api_mode not in self.api_modes:
            return False
        if self.selector_kind == "exact":
            return model_id == self.selector
        return re.fullmatch(self.selector, model_id) is not None


class GigaChatCapabilityOverlaySet(_OverlayModel):
    """Canonical versioned GigaChat overlay document."""

    schema_version: Literal["gpt2giga.gigachat-capability-overlays.v1"]
    overlays: tuple[ModelCapabilityOverlay, ...]

    @model_validator(mode="after")
    def _validate_unique_overlays(self) -> GigaChatCapabilityOverlaySet:
        overlay_ids = [overlay.overlay_id for overlay in self.overlays]
        if len(overlay_ids) != len(set(overlay_ids)):
            raise ValueError("overlay_id values must be unique")
        exact_keys = [
            (overlay.selector, mode, capability)
            for overlay in self.overlays
            if overlay.selector_kind == "exact"
            for mode in overlay.api_modes
            for capability in overlay.capabilities
        ]
        if len(exact_keys) != len(set(exact_keys)):
            raise ValueError("exact model/API-mode/capability decisions must be unique")
        object.__setattr__(
            self,
            "overlays",
            tuple(sorted(self.overlays, key=lambda item: item.overlay_id)),
        )
        return self

    @property
    def revision(self) -> str:
        """Return the digest of the complete reviewed overlay document."""
        return capability_revision(self.model_dump(mode="json"))


class AmbiguousCapabilityOverlayError(RuntimeError):
    """Signal conflicting reviewed family facts instead of guessing."""


def load_gigachat_capability_overlays() -> GigaChatCapabilityOverlaySet:
    """Load packaged GigaChat overlays without runtime network access."""
    data_path = resources.files("gpt2giga.capabilities.data").joinpath(
        "gigachat_v1.json"
    )
    return GigaChatCapabilityOverlaySet.model_validate_json(
        data_path.read_text(encoding="utf-8")
    )


def resolve_gigachat_model_layer(
    model_id: str,
    api_mode: Literal["v1", "v2"],
    *,
    overlays: GigaChatCapabilityOverlaySet | None = None,
) -> CapabilityLayer:
    """Resolve reviewed exact/family facts and keep all other facts unknown."""
    overlay_set = overlays or load_gigachat_capability_overlays()
    matches = [
        overlay
        for overlay in overlay_set.overlays
        if overlay.matches(model_id, api_mode)
    ]
    family = [item for item in matches if item.selector_kind == "family"]
    exact = [item for item in matches if item.selector_kind == "exact"]
    decisions: dict[CapabilityKey, CapabilityDecision] = {}
    evidence: dict[str, CapabilityEvidence] = {}

    for key in CapabilityKey:
        candidates = [item for item in family if key in item.capabilities]
        if len({item.capabilities[key].state for item in candidates}) > 1:
            raise AmbiguousCapabilityOverlayError(
                f"conflicting family capability overlays for {model_id}/{api_mode}/{key.value}"
            )
        exact_candidates = [item for item in exact if key in item.capabilities]
        if exact_candidates:
            selected = exact_candidates[0]
        elif candidates:
            selected = candidates[0]
        else:
            decisions[key] = _unknown_decision(model_id, api_mode, key)
            continue

        specification = selected.capabilities[key]
        source = (
            CapabilitySource.EXACT_MODEL_OVERLAY
            if selected.selector_kind == "exact"
            else CapabilitySource.FAMILY_OVERLAY
        )
        evidence_ids = tuple(
            sorted(set(selected.evidence_ids) | set(specification.evidence_ids))
        )
        decision_revision = capability_revision(
            {
                "overlay_revision": overlay_set.revision,
                "overlay_id": selected.overlay_id,
                "capability": key.value,
                "decision": specification.model_dump(mode="json"),
            }
        )
        decisions[key] = CapabilityDecision(
            state=specification.state,
            reason_id=specification.reason_id,
            source=source,
            evidence_ids=evidence_ids,
            revision=decision_revision,
        )
        for evidence_id in evidence_ids:
            evidence[evidence_id] = CapabilityEvidence(
                evidence_id=evidence_id,
                source=source,
                revision=overlay_set.revision,
            )

    layer_revision = capability_revision(
        {
            "overlay_revision": overlay_set.revision,
            "model_id": model_id,
            "api_mode": api_mode,
            "capabilities": {
                key.value: decision.model_dump(mode="json")
                for key, decision in decisions.items()
            },
        }
    )
    return CapabilityLayer(
        scope=CapabilityScope.MODEL,
        scope_id=model_id,
        capabilities=decisions,
        revision=layer_revision,
        evidence=tuple(evidence.values()),
    )


def _unknown_decision(
    model_id: str,
    api_mode: Literal["v1", "v2"],
    key: CapabilityKey,
) -> CapabilityDecision:
    revision = capability_revision(
        {
            "model_id": model_id,
            "api_mode": api_mode,
            "capability": key.value,
            "state": CapabilityState.UNKNOWN.value,
        }
    )
    return CapabilityDecision(
        state=CapabilityState.UNKNOWN,
        reason_id="unreviewed_model_capability",
        source=CapabilitySource.UNRESOLVED,
        revision=revision,
    )
