"""Model-level capability contracts and resolution."""

from gpt2giga.capabilities.admission import (
    CapabilityPredicateAdmission,
    capability_predicates_for_semantics,
    resolve_gigachat_route_capabilities,
)
from gpt2giga.capabilities.models import (
    CAPABILITY_KEYS_V1,
    CapabilityDecision,
    CapabilityEvidence,
    CapabilityKey,
    CapabilityLayer,
    CapabilityScope,
    CapabilitySource,
    CapabilityState,
    EffectiveModelCapabilities,
    capability_revision,
)
from gpt2giga.capabilities.overlays import (
    AmbiguousCapabilityOverlayError,
    GigaChatCapabilityOverlaySet,
    ModelCapabilityOverlay,
    load_gigachat_capability_overlays,
    resolve_gigachat_model_layer,
)
from gpt2giga.capabilities.resolver import (
    EffectiveCapabilityResolver,
    apply_provider_capability_metadata,
    build_capability_layer,
)

__all__ = [
    "AmbiguousCapabilityOverlayError",
    "CAPABILITY_KEYS_V1",
    "CapabilityDecision",
    "CapabilityEvidence",
    "CapabilityKey",
    "CapabilityLayer",
    "CapabilityPredicateAdmission",
    "CapabilityScope",
    "CapabilitySource",
    "CapabilityState",
    "EffectiveCapabilityResolver",
    "EffectiveModelCapabilities",
    "GigaChatCapabilityOverlaySet",
    "ModelCapabilityOverlay",
    "apply_provider_capability_metadata",
    "build_capability_layer",
    "capability_predicates_for_semantics",
    "capability_revision",
    "load_gigachat_capability_overlays",
    "resolve_gigachat_model_layer",
    "resolve_gigachat_route_capabilities",
]
