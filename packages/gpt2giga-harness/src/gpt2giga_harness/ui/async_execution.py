"""Bounded offload and content-free diagnostics for Harness HTTP work."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import inspect
from threading import Lock
from time import perf_counter
from typing import Any

import anyio
from fastapi.routing import APIRoute

from gpt2giga_harness.instrumentation import (
    bind_diagnostic_recorder,
    record_duration,
    reset_diagnostic_recorder,
)
from gpt2giga_harness.ui.execution_contracts import (
    CancellationContract,
    ExecutionAdapter,
    RouteExecutionContract,
    WorkloadClass,
    route_execution_contract,
)


_CURRENT_CONTRACT: ContextVar[RouteExecutionContract | None] = ContextVar(
    "harness_route_execution_contract",
    default=None,
)
_HANDLER_FINISHED_AT: ContextVar[float | None] = ContextVar(
    "harness_handler_finished_at",
    default=None,
)

_CAPACITY = {
    WorkloadClass.FILESYSTEM: 16,
    WorkloadClass.SQLITE: 8,
    WorkloadClass.NETWORK: 8,
    WorkloadClass.SUBPROCESS: 4,
    WorkloadClass.DURABLE_JOB: 8,
    WorkloadClass.EVENT_LOOP_SAFE: 16,
    WorkloadClass.STREAM: 16,
}
_LIMITERS: dict[WorkloadClass, anyio.CapacityLimiter] = {}


def _limiter(workload: WorkloadClass) -> anyio.CapacityLimiter:
    limiter = _LIMITERS.get(workload)
    if limiter is None:
        limiter = anyio.CapacityLimiter(_CAPACITY[workload])
        _LIMITERS[workload] = limiter
    return limiter


async def run_in_threadpool(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run synchronous work behind the current workload's bounded adapter."""
    contract = _CURRENT_CONTRACT.get()
    workload = contract.workload if contract is not None else WorkloadClass.FILESYSTEM
    deadline = contract.deadline_seconds if contract is not None else 10.0
    atomic = (
        contract is not None
        and contract.cancellation is CancellationContract.ATOMIC_COMPLETION
    )
    return await _run_bounded(
        workload,
        func,
        *args,
        deadline=deadline,
        atomic=atomic,
        **kwargs,
    )


async def run_stream_offload(
    func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Run one SSE poll behind the stream-specific capacity limiter."""
    return await _run_bounded(
        WorkloadClass.STREAM,
        func,
        *args,
        deadline=10.0,
        atomic=False,
        **kwargs,
    )


async def _run_bounded(
    workload: WorkloadClass,
    func: Callable[..., Any],
    *args: Any,
    deadline: float | None,
    atomic: bool,
    **kwargs: Any,
) -> Any:
    queued_at = perf_counter()

    def call() -> Any:
        started_at = perf_counter()
        record_duration("executor_queue_ms", (started_at - queued_at) * 1000)
        try:
            return func(*args, **kwargs)
        finally:
            record_duration("storage_ms", (perf_counter() - started_at) * 1000)

    async def invoke() -> Any:
        return await anyio.to_thread.run_sync(
            call,
            abandon_on_cancel=not atomic,
            limiter=_limiter(workload),
        )

    if deadline is None:
        return await invoke()
    with anyio.fail_after(deadline):
        return await invoke()


@dataclass
class _Metric:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)

    def snapshot(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "mean": round(self.total / self.count, 3) if self.count else 0.0,
            "max": round(self.maximum, 3),
        }


class AsyncExecutionDiagnostics:
    """Bounded, content-free measurements for the asynchronous data plane."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._metrics: dict[str, _Metric] = defaultdict(_Metric)
        self._requests = 0
        self._cancellations = 0
        self._response_bytes = 0
        self._lag_samples: deque[float] = deque(maxlen=1024)

    def record(self, metric: str, value: float) -> None:
        """Record one duration without retaining request content or identifiers."""
        with self._lock:
            self._metrics[metric].add(value)

    def record_response(
        self, *, duration_ms: float, size: int, cancelled: bool
    ) -> None:
        """Record one completed or cancelled HTTP request."""
        with self._lock:
            self._requests += 1
            self._response_bytes += max(0, size)
            self._metrics["request_ms"].add(duration_ms)
            if cancelled:
                self._cancellations += 1

    def record_lag(self, lag_ms: float) -> None:
        """Record a bounded event-loop lag sample."""
        with self._lock:
            self._lag_samples.append(max(0.0, lag_ms))

    def snapshot(self) -> dict[str, Any]:
        """Return aggregate measurements with no paths, payloads, or user content."""
        with self._lock:
            lag = sorted(self._lag_samples)
            return {
                "content_free": True,
                "requests": self._requests,
                "cancellations": self._cancellations,
                "response_bytes": self._response_bytes,
                "event_loop_lag_ms": {
                    "samples": len(lag),
                    "p95": _percentile(lag, 0.95),
                    "p99": _percentile(lag, 0.99),
                    "max": round(lag[-1], 3) if lag else 0.0,
                },
                "durations_ms": {
                    name: metric.snapshot()
                    for name, metric in sorted(self._metrics.items())
                },
                "capacity": {
                    workload.value: limit for workload, limit in _CAPACITY.items()
                },
            }

    async def monitor_event_loop(self, interval: float = 0.1) -> None:
        """Sample scheduling lag until the application lifespan cancels the task."""
        loop = asyncio.get_running_loop()
        expected = loop.time() + interval
        while True:
            await asyncio.sleep(interval)
            now = loop.time()
            self.record_lag((now - expected) * 1000)
            expected = now + interval


class AsyncDiagnosticsMiddleware:
    """Measure HTTP duration, response bytes, cancellation, and offload work."""

    def __init__(self, app: Any, *, diagnostics: AsyncExecutionDiagnostics) -> None:
        self.app = app
        self.diagnostics = diagnostics

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started_at = perf_counter()
        response_bytes = 0
        cancelled = False
        recorder_token = bind_diagnostic_recorder(self.diagnostics.record)
        handler_token = _HANDLER_FINISHED_AT.set(None)

        async def measured_send(message: dict[str, Any]) -> None:
            nonlocal response_bytes
            if message.get("type") == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            _HANDLER_FINISHED_AT.reset(handler_token)
            reset_diagnostic_recorder(recorder_token)
            self.diagnostics.record_response(
                duration_ms=(perf_counter() - started_at) * 1000,
                size=response_bytes,
                cancelled=cancelled,
            )


class ConformantAPIRoute(APIRoute):
    """Bind each route to its declared event-loop or bounded-offload adapter."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        methods = tuple(kwargs.get("methods") or ("GET",))
        method = str(methods[0]).upper()
        contract = route_execution_contract(method, path)
        original_is_async = inspect.iscoroutinefunction(endpoint)

        if contract is not None:
            original = endpoint

            if original_is_async:

                @wraps(original)
                async def instrumented(*args: Any, **inner_kwargs: Any) -> Any:
                    token = _CURRENT_CONTRACT.set(contract)
                    started_at = perf_counter()
                    try:
                        return await original(*args, **inner_kwargs)
                    finally:
                        record_duration(
                            "handler_ms", (perf_counter() - started_at) * 1000
                        )
                        _HANDLER_FINISHED_AT.set(perf_counter())
                        _CURRENT_CONTRACT.reset(token)

            else:

                @wraps(original)
                async def instrumented(*args: Any, **inner_kwargs: Any) -> Any:
                    token = _CURRENT_CONTRACT.set(contract)
                    started_at = perf_counter()
                    try:
                        return await run_in_threadpool(original, *args, **inner_kwargs)
                    finally:
                        record_duration(
                            "handler_ms", (perf_counter() - started_at) * 1000
                        )
                        _HANDLER_FINISHED_AT.set(perf_counter())
                        _CURRENT_CONTRACT.reset(token)

            endpoint = instrumented
        super().__init__(path, endpoint, **kwargs)
        self.execution_contract = contract
        self.original_endpoint_is_async = original_is_async

    def get_route_handler(self) -> Callable[[Any], Any]:
        """Measure FastAPI response validation and serialization separately."""
        handler = super().get_route_handler()

        async def measured_handler(request: Any) -> Any:
            response = await handler(request)
            handler_finished_at = _HANDLER_FINISHED_AT.get()
            if handler_finished_at is not None:
                record_duration(
                    "serialization_ms",
                    (perf_counter() - handler_finished_at) * 1000,
                )
            return response

        return measured_handler


def async_handler_contract_errors(routes: list[object]) -> tuple[str, ...]:
    """Reject route adapters whose original handler can block the event loop."""
    errors: list[str] = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            errors.extend(async_handler_contract_errors(included.routes))
            continue
        contract = getattr(route, "execution_contract", None)
        if contract is None:
            continue
        original_is_async = bool(getattr(route, "original_endpoint_is_async", False))
        if contract.adapter is ExecutionAdapter.EVENT_LOOP and not original_is_async:
            errors.append(f"{contract.identity} event-loop handler is not async")
        if contract.adapter is ExecutionAdapter.BOUNDED_THREAD and original_is_async:
            errors.append(f"{contract.identity} async handler lacks explicit offload")
        if (
            contract.adapter
            in {
                ExecutionAdapter.NATIVE_ASYNC,
                ExecutionAdapter.ASYNC_STREAM,
            }
            and not original_is_async
        ):
            errors.append(f"{contract.identity} declared async adapter is not async")
    return tuple(errors)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int((len(values) - 1) * quantile)))
    return round(values[index], 3)


async def stop_monitor(task: asyncio.Task[Any]) -> None:
    """Cancel one lifespan-owned lag monitor without leaking its task."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
