from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading
from time import perf_counter

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.async_execution import (
    AsyncDiagnosticsMiddleware,
    AsyncExecutionDiagnostics,
    async_handler_contract_errors,
)
from gpt2giga_harness.ui.execution_contracts import (
    ROUTE_EXECUTION_CONTRACTS,
    CancellationContract,
    ExecutionAdapter,
    IdempotencyContract,
    WorkloadClass,
    execution_contract_errors,
    route_identities,
)


def _app(tmp_path):
    return create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )


def test_all_ui_routes_have_complete_async_execution_contract(tmp_path):
    app = _app(tmp_path)

    assert len(ROUTE_EXECUTION_CONTRACTS) == 201
    assert route_identities(app.routes) == {
        contract.identity for contract in ROUTE_EXECUTION_CONTRACTS
    }
    assert execution_contract_errors(app.routes) == ()
    assert async_handler_contract_errors(app.routes) == ()
    assert {contract.workload for contract in ROUTE_EXECUTION_CONTRACTS} == set(
        WorkloadClass
    )
    assert {contract.adapter for contract in ROUTE_EXECUTION_CONTRACTS} == set(
        ExecutionAdapter
    )
    assert {contract.cancellation for contract in ROUTE_EXECUTION_CONTRACTS} == set(
        CancellationContract
    )
    assert {contract.idempotency for contract in ROUTE_EXECUTION_CONTRACTS} == set(
        IdempotencyContract
    )
    for contract in ROUTE_EXECUTION_CONTRACTS:
        assert contract.storage_owner
        assert contract.execution_owner
        assert contract.max_response_bytes > 0
        assert contract.latency_p95_ms > 0


def test_execution_contract_rejects_new_unclassified_read_route(tmp_path):
    app = _app(tmp_path)

    @app.get("/api/new-read")
    async def new_read():
        return {"ok": True}

    errors = execution_contract_errors(app.routes)

    assert any(
        "unclassified routes" in error and "('GET', '/api/new-read')" in error
        for error in errors
    )


def test_blocking_session_read_does_not_stall_event_loop(tmp_path, monkeypatch):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    original = store.list_sessions
    entered = threading.Event()
    release = threading.Event()

    def slow_list_sessions(**kwargs):
        entered.set()
        release.wait(timeout=2)
        return original(**kwargs)

    monkeypatch.setattr(store, "list_sessions", slow_list_sessions)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.get, "/api/sessions")
        assert entered.wait(timeout=1)
        timer = threading.Timer(0.75, release.set)
        timer.start()
        started_at = perf_counter()
        response = client.get("/api/defaults")
        elapsed = perf_counter() - started_at
        release.set()
        timer.cancel()
        assert pending.result(timeout=2).status_code == 200

    assert response.status_code == 200
    assert elapsed < 0.5


def test_async_diagnostics_are_content_free_and_measure_durable_storage(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"title": "diagnostics"})
        session_id = created.json()["session"]["id"]
        started = client.post(
            f"/api/sessions/{session_id}/run/start",
            json={"harness_id": "echo", "prompt": "measure"},
        )
        assert started.status_code == 200

    snapshot = app.state.harness_async_diagnostics.snapshot()
    assert snapshot["content_free"] is True
    assert snapshot["requests"] >= 2
    assert snapshot["response_bytes"] > 0
    assert snapshot["durations_ms"]["handler_ms"]["count"] >= 2
    assert snapshot["durations_ms"]["serialization_ms"]["count"] >= 2
    assert snapshot["durations_ms"]["executor_queue_ms"]["count"] >= 2
    assert snapshot["durations_ms"]["db_wait_ms"]["count"] >= 1
    assert "measure" not in str(snapshot)
    assert session_id not in str(snapshot)


@pytest.mark.asyncio
async def test_async_diagnostics_count_request_cancellation():
    diagnostics = AsyncExecutionDiagnostics()

    async def cancelled_app(scope, receive, send):
        raise asyncio.CancelledError

    middleware = AsyncDiagnosticsMiddleware(cancelled_app, diagnostics=diagnostics)
    scope = {"type": "http", "method": "GET", "path": "/api/sessions"}

    with pytest.raises(asyncio.CancelledError):
        await middleware(scope, lambda: None, lambda _message: None)

    snapshot = diagnostics.snapshot()
    assert snapshot["requests"] == 1
    assert snapshot["cancellations"] == 1
    assert snapshot["response_bytes"] == 0
