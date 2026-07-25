"""Authoritative asynchronous execution contracts for Harness UI routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from gpt2giga_harness.ui.mutation_contracts import (
    MUTATION_ROUTE_CONTRACTS,
    MutationClass,
)


class WorkloadClass(str, Enum):
    """Potentially blocking boundary owned by one route."""

    EVENT_LOOP_SAFE = "event_loop_safe_cpu"
    FILESYSTEM = "filesystem"
    SQLITE = "sqlite"
    NETWORK = "network"
    SUBPROCESS = "subprocess"
    DURABLE_JOB = "durable_job"
    STREAM = "stream"


class ExecutionAdapter(str, Enum):
    """Adapter that keeps a declared workload off the event-loop thread."""

    EVENT_LOOP = "event_loop"
    BOUNDED_THREAD = "bounded_thread"
    NATIVE_ASYNC = "native_async"
    DURABLE_WORKER = "durable_worker"
    ASYNC_STREAM = "async_stream"


class CancellationContract(str, Enum):
    """Meaning of request cancellation at the execution boundary."""

    REQUEST_SCOPED = "request_scoped"
    ATOMIC_COMPLETION = "atomic_completion"
    DURABLE_IDENTITY = "durable_identity"
    DISCONNECT_CLEANUP = "disconnect_cleanup"


class IdempotencyContract(str, Enum):
    """Replay behavior declared by a route."""

    READ_ONLY = "read_only"
    ATOMIC_STORE = "atomic_store"
    CLIENT_KEY = "client_key"
    DURABLE_JOB = "durable_job"
    STREAM_CURSOR = "stream_cursor"


@dataclass(frozen=True)
class RouteExecutionContract:
    """One exact route's semantic, workload, and bounded execution contract."""

    method: str
    path: str
    mutation_class: MutationClass
    workload: WorkloadClass
    storage_owner: str
    execution_owner: str
    adapter: ExecutionAdapter
    deadline_seconds: float | None
    cancellation: CancellationContract
    idempotency: IdempotencyContract
    max_response_bytes: int
    cursor: str | None
    latency_p95_ms: int

    @property
    def identity(self) -> tuple[str, str]:
        """Return the exact HTTP method and normalized FastAPI path."""
        return self.method, self.path


READ_ROUTE_IDENTITIES = frozenset(
    {
        ("GET", "/api/agents"),
        ("GET", "/api/agents/{agent_id}"),
        ("GET", "/api/approvals"),
        ("GET", "/api/arena/runs"),
        ("GET", "/api/arena/runs/{arena_id}"),
        ("GET", "/api/arena/runs/{arena_id}/events/stream"),
        ("GET", "/api/attachments/{attachment_id}"),
        ("GET", "/api/attachments/{attachment_id}/metadata"),
        ("GET", "/api/attention"),
        ("GET", "/api/automation"),
        ("GET", "/api/cockpit/runs/{run_id}"),
        ("GET", "/api/cockpit/runs/{run_id}/diff"),
        ("GET", "/api/cockpit/runs/{run_id}/raw"),
        ("GET", "/api/cockpit/runs/{run_id}/report"),
        ("GET", "/api/cockpit/sessions"),
        ("GET", "/api/cockpit/sessions/{session_id}"),
        ("GET", "/api/cockpit/sessions/{session_id}/artifacts"),
        ("GET", "/api/cockpit/sessions/{session_id}/events"),
        ("GET", "/api/cockpit/sessions/{session_id}/messages"),
        (
            "GET",
            "/api/cockpit/sessions/{session_id}/messages/{message_id}/content",
        ),
        ("GET", "/api/cockpit/sessions/{session_id}/runs"),
        ("GET", "/api/cockpit/sessions/{session_id}/updates/stream"),
        ("GET", "/api/compatibility/guardian"),
        ("GET", "/api/defaults"),
        ("GET", "/api/evals"),
        ("GET", "/api/evals/runs/{eval_run_id}"),
        ("GET", "/api/evaluate"),
        ("GET", "/api/evaluate/{eval_name}/matrix"),
        ("GET", "/api/environment"),
        ("GET", "/api/files/generated/{run_key}/{filename}"),
        ("GET", "/api/files/preview"),
        ("GET", "/api/harnesses"),
        ("GET", "/api/health"),
        ("GET", "/api/integrations"),
        ("GET", "/api/integrations/search"),
        ("GET", "/api/integrations/source-detail"),
        ("GET", "/api/integrations/skills/preview"),
        ("GET", "/api/integrations/flows/{flow_id}"),
        ("GET", "/api/integrations/groups/{group_id}"),
        ("GET", "/api/models"),
        ("GET", "/api/native/processes/{process_id}"),
        ("GET", "/api/native/processes/{process_id}/output"),
        ("GET", "/api/native/processes/{process_id}/output/stream"),
        ("GET", "/api/native/sessions"),
        ("GET", "/api/native/sessions/{native_ref_id}/preview"),
        ("GET", "/api/policy/profiles"),
        ("GET", "/api/project"),
        ("GET", "/api/project/config"),
        ("GET", "/api/project/memory"),
        ("GET", "/api/project/presets"),
        ("GET", "/api/project/state"),
        ("GET", "/api/providers"),
        ("GET", "/api/providers/{provider_id}"),
        ("GET", "/api/provider-accounts"),
        ("GET", "/api/provider-handoffs/{harness_id}/preview"),
        ("GET", "/api/runs"),
        ("GET", "/api/runs/updates/stream"),
        ("GET", "/api/runs/{run_id}"),
        ("GET", "/api/runs/{run_id}/diff"),
        ("GET", "/api/runs/{run_id}/events/stream"),
        ("GET", "/api/runs/{run_id}/events/{event_id}"),
        ("GET", "/api/runs/{run_id}/handoff-capsule"),
        ("GET", "/api/runs/{run_id}/patch"),
        ("GET", "/api/runs/{run_id}/pr"),
        ("GET", "/api/runs/{run_id}/provenance"),
        ("GET", "/api/runs/{run_id}/summary"),
        ("GET", "/api/runs/{run_id}/support-bundle"),
        ("GET", "/api/runs/{run_id}/trace"),
        ("GET", "/api/runs/{run_id}/trace-replay"),
        ("GET", "/api/schedules"),
        ("GET", "/api/schedules/{schedule_id}"),
        ("GET", "/api/settings"),
        ("GET", "/api/sessions"),
        ("GET", "/api/sessions/{session_id}"),
        ("GET", "/api/sessions/{session_id}/navigation-preview"),
        ("GET", "/api/sessions/{session_id}/attachments"),
        ("GET", "/api/sessions/{session_id}/attachments/workspace/preview"),
        ("GET", "/api/sessions/{session_id}/attachments/workspace/search"),
        ("GET", "/api/sessions/{session_id}/events"),
        ("GET", "/api/tool-servers"),
        ("GET", "/api/tool-servers/{server_id}"),
        ("GET", "/api/tools"),
        ("GET", "/api/workbench/state"),
        ("GET", "/api/workbench/resources"),
        ("GET", "/api/workflow-runs/{run_id}"),
        ("GET", "/api/workflow-runs/{run_id}/handoffs"),
        ("GET", "/api/workflows"),
        ("GET", "/api/workflows/{workflow_id}"),
        ("GET", "/api/workflows/{workflow_id}/export"),
        ("GET", "/api/workspace/file/metadata"),
        ("GET", "/api/workspace/tree"),
        ("GET", "/assets/{asset_name:path}"),
        ("GET", "/cockpit-v2"),
        ("GET", "/cockpit-v2/assets/{asset_name:path}"),
        ("GET", "/cockpit-v2/{spa_path:path}"),
        ("GET", "/auth/status"),
        ("GET", "/healthz"),
        ("GET", "/legacy"),
        ("GET", "/legacy/{spa_path:path}"),
        ("GET", "/local-access"),
        ("GET", "/openapi.json"),
        ("GET", "/{spa_path:path}"),
        ("HEAD", "/openapi.json"),
    }
)

_STREAMS = frozenset(
    {
        ("GET", "/api/arena/runs/{arena_id}/events/stream"),
        ("GET", "/api/cockpit/sessions/{session_id}/updates/stream"),
        ("GET", "/api/native/processes/{process_id}/output/stream"),
        ("GET", "/api/runs/updates/stream"),
        ("GET", "/api/runs/{run_id}/events/stream"),
    }
)
_EVENT_LOOP_SAFE = frozenset(
    {
        ("GET", "/api/policy/profiles"),
        ("GET", "/api/workbench/state"),
        ("GET", "/auth/status"),
        ("GET", "/healthz"),
        ("GET", "/local-access"),
        ("GET", "/openapi.json"),
        ("POST", "/auth/local/recover"),
        ("POST", "/auth/local/rotate"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/session"),
        ("HEAD", "/openapi.json"),
    }
)
_NETWORK = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/integrations/search"),
        ("GET", "/api/integrations/source-detail"),
        ("GET", "/api/models"),
        ("POST", "/api/providers/{provider_id}/discover"),
        ("POST", "/api/providers/{provider_id}/test"),
    }
)
_SQLITE_PREFIXES = (
    "/api/approvals",
    "/api/attention",
    "/api/automation",
    "/api/evaluate",
    "/api/runs",
    "/api/schedules",
    "/api/workflow-runs",
)
_SUBPROCESS_PREFIXES = (
    "/api/editor/",
    "/api/native/processes",
    "/api/provider-accounts",
    "/api/tool-servers/",
)
_SUBPROCESS_EXACT = frozenset(
    {
        ("GET", "/api/compatibility/guardian"),
        ("GET", "/api/environment"),
        ("POST", "/api/environment/commit/apply"),
        ("POST", "/api/environment/commit/preview"),
        ("POST", "/api/environment/push/apply"),
        ("POST", "/api/environment/push/preview"),
        ("POST", "/api/environment/pull-request/apply"),
        ("POST", "/api/environment/pull-request/preview"),
        ("POST", "/api/project/init"),
        ("POST", "/api/integrations/git/inspect"),
        ("POST", "/api/run"),
        ("POST", "/api/tools/sync"),
        ("POST", "/api/runs/{run_id}/apply"),
        ("POST", "/api/runs/{run_id}/branch"),
        ("POST", "/api/runs/{run_id}/discard"),
        ("POST", "/api/runs/{run_id}/open-worktree"),
        ("POST", "/api/workflow-runs/{run_id}/merge-queue/apply"),
    }
)
_DURABLE_JOB_IDENTITIES = frozenset(
    {
        ("POST", "/api/agents/{agent_id}/run"),
        ("POST", "/api/arena/runs"),
        ("POST", "/api/arena/runs/{arena_id}/children/{child_index}/retry"),
        ("POST", "/api/arena/runs/{arena_id}/turns"),
        ("POST", "/api/evals/{eval_name}/runs"),
        ("POST", "/api/runs/{run_id}/fork"),
        ("POST", "/api/runs/{run_id}/replay"),
        ("POST", "/api/runs/{run_id}/trace-replays"),
        ("POST", "/api/schedules/{schedule_id}/run-now"),
        ("POST", "/api/schedules/{schedule_id}/test-now"),
        ("POST", "/api/sessions/run"),
        ("POST", "/api/sessions/run/start"),
        ("POST", "/api/sessions/{session_id}/run"),
        ("POST", "/api/sessions/{session_id}/run/start"),
        ("POST", "/api/workflows/{workflow_id}/run"),
    }
)
_SYNC_DURABLE_SUBMISSIONS = frozenset(
    {
        ("POST", "/api/runs/{run_id}/fork"),
        ("POST", "/api/runs/{run_id}/replay"),
        ("POST", "/api/runs/{run_id}/trace-replays"),
        ("POST", "/api/sessions/run"),
        ("POST", "/api/sessions/{session_id}/run"),
    }
)
_NATIVE_ASYNC = frozenset(
    {
        ("GET", "/api/environment"),
        ("POST", "/api/environment/commit/apply"),
        ("POST", "/api/environment/commit/preview"),
        ("POST", "/api/environment/push/apply"),
        ("POST", "/api/environment/push/preview"),
        ("POST", "/api/environment/pull-request/apply"),
        ("POST", "/api/environment/pull-request/preview"),
        ("GET", "/api/integrations/search"),
        ("GET", "/api/integrations/source-detail"),
        ("POST", "/api/integrations/git/inspect"),
        ("POST", "/api/native/processes/{process_id}/input"),
    }
)
_EXPLICIT_BOUNDED_ASYNC = frozenset(
    {
        ("POST", "/api/runs/{run_id}/promotions/apply"),
        ("POST", "/api/runs/{run_id}/promotions/preview"),
        ("POST", "/api/tool-servers/{server_id}/probe"),
        ("POST", "/api/workflow-runs/{run_id}/cancel"),
        ("POST", "/api/workflow-runs/{run_id}/handoffs/{step_id}/choose"),
        ("POST", "/api/workflow-runs/{run_id}/handoffs/{step_id}/discard"),
        ("POST", "/api/workflow-runs/{run_id}/merge-queue"),
        ("PUT", "/api/workflows/{workflow_id}"),
    }
)

_OPAQUE_CURSOR_IDENTITIES = frozenset(
    {
        ("GET", "/api/runs"),
        ("GET", "/api/runs/{run_id}/trace"),
        ("GET", "/api/cockpit/sessions"),
        ("GET", "/api/cockpit/sessions/{session_id}/artifacts"),
        ("GET", "/api/cockpit/sessions/{session_id}/events"),
        ("GET", "/api/cockpit/sessions/{session_id}/messages"),
        ("GET", "/api/cockpit/sessions/{session_id}/runs"),
        ("GET", "/api/workbench/state"),
    }
)


def _workload(identity: tuple[str, str]) -> WorkloadClass:
    if identity in _STREAMS:
        return WorkloadClass.STREAM
    if identity in _EVENT_LOOP_SAFE:
        return WorkloadClass.EVENT_LOOP_SAFE
    if identity in _DURABLE_JOB_IDENTITIES:
        return WorkloadClass.DURABLE_JOB
    if identity in _NETWORK:
        return WorkloadClass.NETWORK
    if identity in _SUBPROCESS_EXACT or identity[1].startswith(_SUBPROCESS_PREFIXES):
        return WorkloadClass.SUBPROCESS
    if identity[1].startswith(_SQLITE_PREFIXES):
        return WorkloadClass.SQLITE
    return WorkloadClass.FILESYSTEM


def _adapter(identity: tuple[str, str], workload: WorkloadClass) -> ExecutionAdapter:
    if workload is WorkloadClass.STREAM:
        return ExecutionAdapter.ASYNC_STREAM
    if identity in _EVENT_LOOP_SAFE:
        return ExecutionAdapter.EVENT_LOOP
    if (
        identity in _DURABLE_JOB_IDENTITIES
        and identity not in _SYNC_DURABLE_SUBMISSIONS
    ):
        return ExecutionAdapter.DURABLE_WORKER
    if identity in _NATIVE_ASYNC:
        return ExecutionAdapter.NATIVE_ASYNC
    if identity in _EXPLICIT_BOUNDED_ASYNC:
        return ExecutionAdapter.BOUNDED_THREAD
    return ExecutionAdapter.BOUNDED_THREAD


def _storage_owner(workload: WorkloadClass) -> str:
    return {
        WorkloadClass.EVENT_LOOP_SAFE: "none",
        WorkloadClass.FILESYSTEM: "filesystem_store",
        WorkloadClass.SQLITE: "runtime_sqlite",
        WorkloadClass.NETWORK: "proxy_client",
        WorkloadClass.SUBPROCESS: "process_boundary",
        WorkloadClass.DURABLE_JOB: "runtime_job_store",
        WorkloadClass.STREAM: "durable_event_store",
    }[workload]


def _execution_owner(adapter: ExecutionAdapter, workload: WorkloadClass) -> str:
    if adapter is ExecutionAdapter.EVENT_LOOP:
        return "event_loop_cpu"
    if adapter is ExecutionAdapter.DURABLE_WORKER:
        return "durable_job_dispatcher"
    if adapter is ExecutionAdapter.ASYNC_STREAM:
        return "bounded_sse_stream"
    return f"bounded_{workload.value}_offload"


def _build_contracts() -> tuple[RouteExecutionContract, ...]:
    mutation_by_identity = {
        contract.identity: contract for contract in MUTATION_ROUTE_CONTRACTS
    }
    identities = sorted({*mutation_by_identity, *READ_ROUTE_IDENTITIES})
    contracts: list[RouteExecutionContract] = []
    for identity in identities:
        mutation = mutation_by_identity.get(identity)
        mutation_class = (
            mutation.mutation_class if mutation is not None else MutationClass.READ_ONLY
        )
        workload = _workload(identity)
        adapter = _adapter(identity, workload)
        is_read = mutation_class is MutationClass.READ_ONLY
        is_stream = workload is WorkloadClass.STREAM
        is_job = workload is WorkloadClass.DURABLE_JOB
        cancellation = (
            CancellationContract.DISCONNECT_CLEANUP
            if is_stream
            else CancellationContract.DURABLE_IDENTITY
            if is_job
            else CancellationContract.REQUEST_SCOPED
            if is_read
            else CancellationContract.ATOMIC_COMPLETION
        )
        idempotency = (
            IdempotencyContract.STREAM_CURSOR
            if is_stream
            else IdempotencyContract.CLIENT_KEY
            if identity[1].endswith("/run/start")
            else IdempotencyContract.DURABLE_JOB
            if is_job
            else IdempotencyContract.READ_ONLY
            if is_read
            else IdempotencyContract.ATOMIC_STORE
        )
        contracts.append(
            RouteExecutionContract(
                method=identity[0],
                path=identity[1],
                mutation_class=mutation_class,
                workload=workload,
                storage_owner=_storage_owner(workload),
                execution_owner=_execution_owner(adapter, workload),
                adapter=adapter,
                deadline_seconds=(None if is_stream else 10.0),
                cancellation=cancellation,
                idempotency=idempotency,
                max_response_bytes=(
                    16 * 1024 * 1024
                    if "/files/" in identity[1]
                    or identity[1].endswith(("/diff", "/patch", "/support-bundle"))
                    else 1024 * 1024
                ),
                cursor=(
                    "Last-Event-ID"
                    if is_stream
                    else "opaque"
                    if identity in _OPAQUE_CURSOR_IDENTITIES
                    else None
                ),
                latency_p95_ms=(1500 if not identity[1].startswith("/api/") else 500),
            )
        )
    return tuple(contracts)


ROUTE_EXECUTION_CONTRACTS = _build_contracts()
_CONTRACT_BY_IDENTITY = {
    contract.identity: contract for contract in ROUTE_EXECUTION_CONTRACTS
}


def route_execution_contract(method: str, path: str) -> RouteExecutionContract | None:
    """Return the declared contract for one exact route identity."""
    return _CONTRACT_BY_IDENTITY.get((method.upper(), path))


def route_identities(routes: Sequence[object]) -> frozenset[tuple[str, str]]:
    """Recursively expand included FastAPI routers into route identities."""
    identities: set[tuple[str, str]] = set()
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            identities.update(route_identities(included.routes))
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or ()
        if isinstance(path, str):
            identities.update((method, path) for method in methods)
    return frozenset(identities)


def execution_contract_errors(routes: Sequence[object]) -> tuple[str, ...]:
    """Return deterministic route-drift and declaration errors."""
    errors: list[str] = []
    declared_list = [contract.identity for contract in ROUTE_EXECUTION_CONTRACTS]
    duplicates = sorted(
        identity for identity in set(declared_list) if declared_list.count(identity) > 1
    )
    if duplicates:
        errors.append(f"duplicate execution contracts: {duplicates}")
    runtime = route_identities(routes)
    declared = frozenset(declared_list)
    if missing := sorted(runtime - declared):
        errors.append(f"unclassified routes: {missing}")
    if stale := sorted(declared - runtime):
        errors.append(f"contracts without routes: {stale}")
    for contract in ROUTE_EXECUTION_CONTRACTS:
        label = f"{contract.method} {contract.path}"
        if not contract.storage_owner or not contract.execution_owner:
            errors.append(f"{label} lacks storage or execution owner")
        if (
            contract.deadline_seconds is None
            and contract.workload is not WorkloadClass.STREAM
        ):
            errors.append(f"{label} lacks a deadline")
        if contract.max_response_bytes <= 0 or contract.latency_p95_ms <= 0:
            errors.append(f"{label} has invalid payload or latency budget")
        if contract.workload is WorkloadClass.STREAM and not contract.cursor:
            errors.append(f"{label} stream lacks a cursor contract")
    return tuple(errors)


def install_execution_contracts(app: object) -> None:
    """Fail closed on route drift and expose the validated inventory."""
    errors = execution_contract_errors(getattr(app, "routes"))
    if errors:
        raise RuntimeError("Harness execution contract invalid: " + "; ".join(errors))
    state = getattr(app, "state")
    state.harness_execution_contracts = ROUTE_EXECUTION_CONTRACTS
