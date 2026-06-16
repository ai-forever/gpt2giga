import asyncio
from types import SimpleNamespace

import pytest

from gpt2giga.common.model_concurrency import (
    DEFAULT_GIGACHAT_MODEL,
    ModelConcurrencyLimiter,
    ModelConcurrencyTimeoutError,
    resolve_gigachat_model,
)


async def _hold_slot(
    limiter: ModelConcurrencyLimiter,
    model: str,
    entered: asyncio.Event,
    release: asyncio.Event,
) -> None:
    async with limiter.limit(model):
        entered.set()
        await release.wait()


async def test_disabled_mode_does_not_block() -> None:
    limiter = ModelConcurrencyLimiter({})
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    release = asyncio.Event()

    first = asyncio.create_task(_hold_slot(limiter, "GigaChat", first_entered, release))
    second = asyncio.create_task(
        _hold_slot(limiter, "GigaChat", second_entered, release)
    )
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    await asyncio.wait_for(second_entered.wait(), timeout=1)
    release.set()
    await asyncio.gather(first, second)

    assert limiter.limit_for("GigaChat") is None
    assert limiter.is_enabled_for("GigaChat") is False


async def test_explicit_model_limit_serializes_same_model() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1})
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    first_release = asyncio.Event()
    second_release = asyncio.Event()

    first = asyncio.create_task(
        _hold_slot(limiter, "GigaChat", first_entered, first_release)
    )
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    second = asyncio.create_task(
        _hold_slot(limiter, "GigaChat", second_entered, second_release)
    )
    await asyncio.sleep(0)

    assert second_entered.is_set() is False

    first_release.set()
    await asyncio.wait_for(second_entered.wait(), timeout=1)
    second_release.set()
    await asyncio.gather(first, second)


async def test_different_models_are_independent() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1, "GigaChat-Pro": 1})
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    release = asyncio.Event()

    first = asyncio.create_task(_hold_slot(limiter, "GigaChat", first_entered, release))
    second = asyncio.create_task(
        _hold_slot(limiter, "GigaChat-Pro", second_entered, release)
    )
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    await asyncio.wait_for(second_entered.wait(), timeout=1)
    release.set()
    await asyncio.gather(first, second)


async def test_default_limit_applies_per_unknown_model() -> None:
    limiter = ModelConcurrencyLimiter({}, default_limit=1)
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    third_entered = asyncio.Event()
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    third_release = asyncio.Event()

    first = asyncio.create_task(
        _hold_slot(limiter, "unknown-a", first_entered, first_release)
    )
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    second = asyncio.create_task(
        _hold_slot(limiter, "unknown-a", second_entered, second_release)
    )
    third = asyncio.create_task(
        _hold_slot(limiter, "unknown-b", third_entered, third_release)
    )
    await asyncio.sleep(0)

    assert second_entered.is_set() is False
    await asyncio.wait_for(third_entered.wait(), timeout=1)

    first_release.set()
    await asyncio.wait_for(second_entered.wait(), timeout=1)
    second_release.set()
    third_release.set()
    await asyncio.gather(first, second, third)


async def test_timeout_zero_is_fail_fast() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)

    async with limiter.limit("GigaChat"):
        with pytest.raises(ModelConcurrencyTimeoutError) as exc_info:
            async with limiter.limit("GigaChat"):
                pass

    assert exc_info.value.model == "GigaChat"
    assert exc_info.value.limit == 1
    assert exc_info.value.provider == "openai"


async def test_positive_timeout_raises_when_slot_is_unavailable() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0.01)

    async with limiter.limit("GigaChat"):
        with pytest.raises(ModelConcurrencyTimeoutError):
            async with limiter.limit("GigaChat"):
                pass


async def test_slot_released_after_normal_exit() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)

    async with limiter.limit("GigaChat"):
        pass

    async with limiter.limit("GigaChat"):
        pass


async def test_slot_released_after_exception() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)

    with pytest.raises(RuntimeError, match="boom"):
        async with limiter.limit("GigaChat"):
            raise RuntimeError("boom")

    async with limiter.limit("GigaChat"):
        pass


async def test_slot_released_after_cancellation() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    entered = asyncio.Event()
    release = asyncio.Event()

    task = asyncio.create_task(_hold_slot(limiter, "GigaChat", entered, release))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    async with limiter.limit("GigaChat"):
        pass


async def test_timeout_error_contains_model_limit_and_provider() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat-Max": 1}, acquire_timeout=0)

    async with limiter.limit("GigaChat-Max"):
        with pytest.raises(ModelConcurrencyTimeoutError) as exc_info:
            async with limiter.limit("GigaChat-Max", provider="anthropic"):
                pass

    error = exc_info.value
    assert error.model == "GigaChat-Max"
    assert error.limit == 1
    assert error.provider == "anthropic"
    assert str(error) == "Concurrency limit reached for model GigaChat-Max: 1"


@pytest.mark.parametrize(
    ("limits", "default_limit", "acquire_timeout"),
    [
        ({"GigaChat": 0}, None, None),
        ({"GigaChat": -1}, None, None),
        ({}, 0, None),
        ({}, -1, None),
        ({}, None, -1),
    ],
)
def test_invalid_limiter_configuration_raises(
    limits: dict[str, int],
    default_limit: int | None,
    acquire_timeout: float | None,
) -> None:
    with pytest.raises(ValueError):
        ModelConcurrencyLimiter(
            limits,
            default_limit=default_limit,
            acquire_timeout=acquire_timeout,
        )


def test_resolve_gigachat_model_prefers_payload_attribute() -> None:
    payload = SimpleNamespace(model="GigaChat-Pro")
    config = SimpleNamespace(
        gigachat_settings=SimpleNamespace(model="Configured-GigaChat")
    )

    assert resolve_gigachat_model(payload, config) == "GigaChat-Pro"


def test_resolve_gigachat_model_prefers_mapping_model() -> None:
    config = SimpleNamespace(
        gigachat_settings=SimpleNamespace(model="Configured-GigaChat")
    )

    assert resolve_gigachat_model({"model": "GigaChat-Max"}, config) == "GigaChat-Max"


def test_resolve_gigachat_model_uses_config_when_payload_has_no_model() -> None:
    config = SimpleNamespace(
        gigachat_settings=SimpleNamespace(model="Configured-GigaChat")
    )

    assert resolve_gigachat_model({"messages": []}, config) == "Configured-GigaChat"


def test_resolve_gigachat_model_falls_back_to_project_default() -> None:
    config = SimpleNamespace(gigachat_settings=SimpleNamespace(model=None))

    assert resolve_gigachat_model({"messages": []}, config) == DEFAULT_GIGACHAT_MODEL


def test_resolve_gigachat_model_ignores_raw_model_removed_by_transformer() -> None:
    transformed_payload = {"messages": []}
    config = SimpleNamespace(gigachat_settings=SimpleNamespace(model="GigaChat"))

    assert resolve_gigachat_model(transformed_payload, config) == "GigaChat"
