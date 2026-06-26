"""Tests for LAR-1 routing in gpt2giga."""

from gpt2giga.models.lar1 import LAR1Evidence, LAR1Metadata, LAR1Time
from gpt2giga.routers.lar1_router import classify_request


def test_low_confidence_routes_to_gigachat_fast() -> None:
    lar1 = LAR1Metadata(confidence=0.2)
    assert classify_request(lar1) == "gigachat-fast"


def test_mid_confidence_routes_to_gigachat_pro() -> None:
    lar1 = LAR1Metadata(confidence=0.4)
    assert classify_request(lar1) == "gigachat-pro"


def test_high_confidence_routes_to_local() -> None:
    lar1 = LAR1Metadata(confidence=0.8)
    assert classify_request(lar1) == "local"


def test_unverified_evidence_overrides_confidence() -> None:
    lar1 = LAR1Metadata(confidence=0.9, evidence=[LAR1Evidence.UNVERIFIED])
    assert classify_request(lar1) == "gigachat-fast"


def test_mem_time_routes_to_gigachat_pro() -> None:
    lar1 = LAR1Metadata(confidence=0.9, time=LAR1Time.MEM)
    assert classify_request(lar1) == "gigachat-pro"


def test_default_confidence_routes_to_local() -> None:
    lar1 = LAR1Metadata()
    assert classify_request(lar1) == "local"


def test_custom_thresholds() -> None:
    lar1 = LAR1Metadata(confidence=0.85)
    thresholds = {"low": 0.1, "medium": 0.3, "high": 0.9}
    assert classify_request(lar1, thresholds) == "local"


def test_confidence_at_boundary() -> None:
    lar1 = LAR1Metadata(confidence=0.3)
    assert classify_request(lar1) == "gigachat-pro"


def test_zero_confidence() -> None:
    lar1 = LAR1Metadata(confidence=0.0)
    assert classify_request(lar1) == "gigachat-fast"


def test_full_confidence() -> None:
    lar1 = LAR1Metadata(confidence=1.0)
    assert classify_request(lar1) == "local"
