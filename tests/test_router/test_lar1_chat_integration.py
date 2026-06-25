from unittest.mock import MagicMock

import pytest

from gpt2giga.models.lar1 import LAR1Settings
from gpt2giga.routers.lar1_router import resolve_route_model
from gpt2giga.routers.openai.chat_completions import _apply_lar1_routing


def test_lar1_settings_rejects_invalid_threshold_order() -> None:
    with pytest.raises(ValueError, match="low < medium < high"):
        LAR1Settings(threshold_low=0.6, threshold_medium=0.5, threshold_high=0.7)


def test_resolve_route_model_maps_labels() -> None:
    settings = LAR1Settings(
        model_gigachat_pro="GigaChat-Pro",
        model_gigachat_fast="GigaChat",
        model_local="GigaChat-2-Max",
    )
    assert resolve_route_model("gigachat-pro", settings) == "GigaChat-Pro"
    assert resolve_route_model("gigachat-fast", settings) == "GigaChat"
    assert resolve_route_model("local", settings) == "GigaChat-2-Max"


@pytest.mark.asyncio
async def test_apply_lar1_routing_disabled_by_default() -> None:
    data = {
        "model": "GigaChat",
        "messages": [],
        "metadata": {"lar1": {"confidence": 0.2, "evidence": [], "time": "NOW"}},
    }
    result, decision = await _apply_lar1_routing(data, MagicMock())
    assert decision is None
    assert result["model"] == "GigaChat"


@pytest.mark.asyncio
async def test_apply_lar1_routing_overrides_model_when_enabled() -> None:
    data = {
        "model": "GigaChat",
        "messages": [],
        "metadata": {"lar1": {"confidence": 0.2, "evidence": [], "time": "NOW"}},
    }
    logger = MagicMock()
    state = MagicMock(
        logger=logger,
        lar1_settings=LAR1Settings(enabled=True),
    )

    result, decision = await _apply_lar1_routing(data, state)

    assert decision == "gigachat-fast"
    assert result["model"] == "GigaChat"
    assert "_lar1" not in result
    logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_apply_lar1_routing_invalid_metadata_is_non_fatal() -> None:
    data = {
        "model": "GigaChat",
        "messages": [],
        "metadata": {"lar1": {"confidence": "bad"}},
    }
    logger = MagicMock()
    state = MagicMock(
        logger=logger,
        lar1_settings=LAR1Settings(enabled=True),
    )

    result, decision = await _apply_lar1_routing(data, state)

    assert result["model"] == "GigaChat"
    assert decision is None
    logger.warning.assert_called_once()
