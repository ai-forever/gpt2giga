"""LAR-1 request classifier for gpt2giga."""

from typing import Mapping, Optional

from gpt2giga.models.lar1 import LAR1Evidence, LAR1Metadata, LAR1Settings, LAR1Time

DEFAULT_LOW = 0.3
DEFAULT_MEDIUM = 0.5
DEFAULT_HIGH = 0.7

DEFAULT_THRESHOLDS: dict[str, float] = {
    "low": DEFAULT_LOW,
    "medium": DEFAULT_MEDIUM,
    "high": DEFAULT_HIGH,
}

LAR1Route = str


def classify_request(
    lar1: LAR1Metadata,
    thresholds: Optional[Mapping[str, float]] = None,
) -> LAR1Route:
    """Classify request target based on LAR-1 metadata.

    Returns one of: ``gigachat-fast``, ``gigachat-pro``, ``local``.

    - ``gigachat-fast``: low confidence or ``UNVERIFIED`` evidence (economical tier)
    - ``gigachat-pro``: mid confidence or ``MEM`` time (advanced tier)
    - ``local``: high confidence (economical / fast tier)
    """
    t = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        t.update(thresholds)

    if LAR1Evidence.UNVERIFIED in lar1.evidence:
        return "gigachat-fast"

    if lar1.time == LAR1Time.MEM:
        return "gigachat-pro"

    confidence = lar1.confidence

    if confidence < t["low"]:
        return "gigachat-fast"
    if confidence < t["medium"]:
        return "gigachat-pro"
    return "local"


def resolve_route_model(route: LAR1Route, settings: LAR1Settings) -> str:
    """Map an internal LAR-1 route label to a GigaChat model id."""
    if route == "gigachat-pro":
        return settings.model_gigachat_pro
    if route == "gigachat-fast":
        return settings.model_gigachat_fast
    return settings.model_local
