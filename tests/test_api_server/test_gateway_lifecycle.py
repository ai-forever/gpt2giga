"""Bounded startup and shutdown behavior for the composed gateway."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import pytest

from gpt2giga.app.factory import create_app
from gpt2giga.app.request_lifecycle import BridgeRequestLifecycle
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.sinks.logs.composite import CompositeTrafficLogSink
from gpt2giga.sinks.logs.queue import QueuedTrafficLogSink
from gpt2giga.storage.resources import ResourceStoreError


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


async def test_stalled_telemetry_closes_workers_and_runtime(monkeypatch, tmp_path):
    client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client", lambda _: client
    )
    monkeypatch.setattr("gpt2giga.app.lifecycle.TELEMETRY_FLUSH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("gpt2giga.app.lifecycle.TELEMETRY_CLOSE_TIMEOUT_SECONDS", 0.01)

    class StalledSink:
        async def emit_many(self, events):
            await asyncio.Event().wait()

        async def flush(self):
            await asyncio.Event().wait()

    sinks = [QueuedTrafficLogSink(StalledSink()) for _ in range(2)]
    app = create_app(
        ProxyConfig(
            proxy=ProxySettings(resource_store_path=str(tmp_path / "resources"))
        )
    )
    app.state.traffic_log_sink = CompositeTrafficLogSink(sinks)
    async with app.router.lifespan_context(app):
        store = app.state.resource_store
        for sink in sinks:
            await sink.emit({"test": "event"})
        workers = [sink._worker_task for sink in sinks]
    assert client.closed
    assert all(worker.done() for worker in workers)
    assert all(sink._worker_task is None for sink in sinks)
    assert all(sink.dropped_events == 1 for sink in sinks)
    with pytest.raises(ResourceStoreError, match="not open"):
        await store.list("owner", "file")


async def test_shutdown_closes_postgres_after_stalled_queue_drain(
    monkeypatch, tmp_path
):
    from gpt2giga.sinks.logs.postgres import PostgresTrafficLogSink

    started = asyncio.Event()

    class Pool:
        closed = 0

        async def executemany(self, query, rows):
            started.set()
            await asyncio.Event().wait()

        async def close(self):
            self.closed += 1

    pool = Pool()
    raw_sink = PostgresTrafficLogSink("postgresql://unused")
    raw_sink._pool = pool
    sink = QueuedTrafficLogSink(raw_sink, batch_size=1)
    client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client", lambda _: client
    )
    monkeypatch.setattr("gpt2giga.app.lifecycle.TELEMETRY_FLUSH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("gpt2giga.app.lifecycle.TELEMETRY_CLOSE_TIMEOUT_SECONDS", 0.01)
    app = create_app(
        ProxyConfig(proxy=ProxySettings(resource_store_path=str(tmp_path)))
    )
    app.state.traffic_log_sink = CompositeTrafficLogSink([sink])
    async with app.router.lifespan_context(app):
        store = app.state.resource_store
        await sink.emit(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "request_id": "test",
                "protocol": "openai",
                "route": "/v1/chat/completions",
                "method": "POST",
            }
        )
        await asyncio.wait_for(started.wait(), 1)
        worker = sink._worker_task
    assert worker.done()
    assert sink._worker_task is None
    assert sink._queue.empty()
    assert pool.closed == 1
    assert raw_sink._pool is None
    assert client.closed
    with pytest.raises(ResourceStoreError, match="not open"):
        await store.list("owner", "file")


async def test_phoenix_lifespans_release_real_providers_and_workers(
    monkeypatch, tmp_path
):
    import gc
    import threading
    import weakref

    from opentelemetry.sdk.trace.export import SpanExportResult

    # Export assertions must not depend on the caller's sampling policy.
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    monkeypatch.delenv("OTEL_TRACES_SAMPLER_ARG", raising=False)
    exporters = []

    class Exporter:
        def __init__(self, **kwargs):
            self.names = []
            self.closed = 0
            exporters.append(self)

        def export(self, spans):
            self.names.extend(span.name for span in spans)
            return SpanExportResult.SUCCESS

        def shutdown(self):
            self.closed += 1

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter",
        Exporter,
    )
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client", lambda _: _GigaChat()
    )
    before = set(threading.enumerate())
    providers = []
    settings = ProxySettings(
        observability_enabled=True, resource_store_path=str(tmp_path)
    )
    for _ in range(3):
        app = create_app(ProxyConfig(proxy=settings))
        async with app.router.lifespan_context(app):
            sink = app.state.observability_sink
            providers.append(weakref.ref(sink.sink.tracer_provider))
            await sink.emit("before.flush")
            await sink.flush()
            assert exporters[-1].closed == 0
            await sink.emit("after.flush")
        assert exporters[-1].names == ["before.flush", "after.flush"]
        assert exporters[-1].closed == 1
        await sink.aclose()
        assert exporters[-1].closed == 1
        del app, sink
    gc.collect()
    assert all(reference() is None for reference in providers)
    assert not [
        thread
        for thread in set(threading.enumerate()) - before
        if thread.name.startswith("OtelBatch")
    ]


async def test_cancellation_during_telemetry_drain_still_closes_dependencies(
    monkeypatch, tmp_path
):
    from gpt2giga.app.lifecycle import _close_runtime_dependencies

    started = asyncio.Event()
    client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client", lambda _: client
    )

    class Sink:
        closed = 0

        async def flush(self):
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed += 1

    app = create_app(
        ProxyConfig(proxy=ProxySettings(resource_store_path=str(tmp_path)))
    )
    sink = Sink()
    async with app.router.lifespan_context(app):
        app.state.observability_sink = sink
        store = app.state.resource_store
        shutdown = asyncio.create_task(
            _close_runtime_dependencies(app, app.state.attachment_processor)
        )
        await started.wait()
        shutdown.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shutdown
        assert sink.closed == 1
        assert client.closed
        with pytest.raises(ResourceStoreError, match="not open"):
            await store.list("owner", "file")
        # The outer lifespan may close already-closed dependencies again.
        app.state.observability_sink = None
