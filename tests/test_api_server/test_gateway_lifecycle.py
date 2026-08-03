"""Bounded startup and shutdown behavior for the composed gateway."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import pytest

from gpt2giga.app.factory import create_app
from gpt2giga.app.request_lifecycle import BridgeRequestLifecycle
from gpt2giga.models.config import ProxyConfig, ProxySettings


class _GigaChat:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_shutdown_drains_then_cancels_the_remaining_request() -> None:
    lifecycle = BridgeRequestLifecycle()
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_request() -> None:
        async with lifecycle.track():
            started.set()
            await release.wait()

    task = asyncio.create_task(active_request())
    await started.wait()

    await lifecycle.shutdown(timeout_seconds=0.001)

    assert lifecycle.accepting is False
    assert lifecycle.active_requests == 0
    assert task.cancelled()


def test_shutdown_rejects_new_model_requests_with_machine_error() -> None:
    app = create_app(ProxyConfig())
    asyncio.run(app.state.bridge_request_lifecycle.shutdown(timeout_seconds=0.001))

    response = TestClient(app).post(
        "/responses",
        json={"input": "hello", "model": "GigaChat"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "schema_version": "gpt2giga.error.v1",
        "error": {
            "code": "gateway_not_ready",
            "message": "Gateway routes are not ready.",
            "details": [{"reason_id": "gateway_shutting_down"}],
        },
    }


def test_provider_client_is_closed_on_lifespan_shutdown(monkeypatch) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )

    app = create_app(ProxyConfig(proxy=ProxySettings(shutdown_timeout_seconds=0.01)))
    app.state.model_catalog_readiness = {
        "state": "fresh",
        "provider_profile_id": "legacy-gigachat",
        "inventory_revision": f"sha256:{'d' * 64}",
    }

    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert giga_client.closed is False

    assert giga_client.closed is True


def test_provider_runtime_startup_failure_closes_client_before_exposure(
    monkeypatch,
) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )

    class BrokenRuntime:
        def __init__(self, _state) -> None:
            raise RuntimeError("provider runtime failed")

    monkeypatch.setattr("gpt2giga.app.lifecycle.BridgeProviderRuntime", BrokenRuntime)
    client = TestClient(create_app(ProxyConfig()))

    with pytest.raises(RuntimeError, match="provider runtime failed"):
        with client:
            pass

    assert giga_client.closed is True
