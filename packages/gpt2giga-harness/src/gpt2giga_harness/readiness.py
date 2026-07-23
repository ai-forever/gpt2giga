"""Capability-scoped readiness for one selected Harness execution plan."""

from __future__ import annotations

from typing import Any, Mapping

from gpt2giga_harness import proxy
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.compatibility_guardian import compatibility_readiness_check
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.doctor import (
    _gigachat_check,
    _harness_checks,
    _managed_homes_check,
    _proxy_checks,
    _sanitize_report,
    _worker_check,
    _workspace_checks,
)
from gpt2giga_harness.native.models import HarnessInvocationMode
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.structured import (
    DurableStructuredAdmissionError,
    admitted_durable_structured_capabilities,
)
from gpt2giga_harness.types import GigaChatApiMode
from gpt2giga_harness.worktrees import WorkspacePolicy

READINESS_SCHEMA_VERSION = 2
READINESS_STATUSES = (
    "ready",
    "not_checked",
    "unknown",
    "degraded",
    "blocked",
)
_PROXY_HARNESSES = {"direct-chat", "codex-cli", "claude-code", "gemini-cli"}


def build_execution_readiness(
    config: HarnessConfig,
    registry: HarnessRegistry,
    *,
    harness_id: str,
    invocation_mode: HarnessInvocationMode,
    api_mode: GigaChatApiMode,
    model: str | None,
    mode: str,
    workspace: str | None,
    workspace_policy: WorkspacePolicy,
    durable: bool,
    execution_transport: ExecutionTransport | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Project doctor checks onto only the selected pre-spawn execution plan."""
    harness = registry.get(harness_id)
    spec = harness.spec()
    checks: list[dict[str, Any]] = []

    harness_check = next(
        check
        for check in _harness_checks(
            registry,
            harness_ids=(harness_id,),
            include_compatibility=False,
        )
        if check["id"] == f"harness-{harness_id}"
    )
    checks.append(_required_check(harness_check, block_when_unready=True))
    guardian_check = compatibility_readiness_check(harness)
    if guardian_check is not None:
        checks.append(guardian_check)
    checks.append(
        _invocation_check(
            harness_id=harness_id,
            invocation_mode=invocation_mode,
            supports_native=spec.supports_native_sessions,
        )
    )

    if harness_id in _PROXY_HARNESSES and {"proxy", "agent"}.intersection(spec.tags):
        if dry_run:
            checks.append(_dry_run_proxy_check(api_mode))
        else:
            checks.extend(
                _selected_proxy_checks(
                    config,
                    api_mode=api_mode,
                    model=model,
                )
            )
    if spec.kind == "agent-cli":
        checks.append(_required_check(_managed_homes_check(config)))

    needs_workspace = bool(spec.supports_workspace or mode == "edit")
    if needs_workspace:
        workspace_checks = _workspace_checks(config, workspace)
        workspace_check = next(
            check for check in workspace_checks if check["id"] == "workspace"
        )
        checks.append(_required_check(workspace_check))
        git_required = _requires_git_worktree(
            harness_kind=spec.kind,
            mode=mode,
            workspace_policy=workspace_policy,
        )
        if git_required:
            git_check = next(
                (check for check in workspace_checks if check["id"] == "git-readiness"),
                _missing_git_check(),
            )
            checks.append(_required_check(git_check, block_when_unready=True))
        checks.append(
            _workspace_policy_check(
                harness_kind=spec.kind,
                mode=mode,
                workspace_policy=workspace_policy,
            )
        )

    checks.append(
        _delivery_check(
            durable=durable,
            invocation_mode=invocation_mode,
            execution_transport=execution_transport,
        )
    )
    if execution_transport is ExecutionTransport.NATIVE_STRUCTURED:
        checks.insert(
            -1,
            _structured_transport_check(harness, harness_id=harness_id),
        )
    if durable:
        checks.append(_required_check(_worker_check(config)))

    checks = _deduplicate_checks(checks)
    if dry_run:
        checks = [_downgrade_for_dry_run(check) for check in checks]
    summary = {
        status: sum(check["status"] == status for check in checks)
        for status in READINESS_STATUSES
    }
    operational_status = (
        "blocked"
        if summary["blocked"]
        else "degraded"
        if summary["degraded"]
        else "ready"
    )
    evidence_status = (
        "unknown"
        if summary["unknown"]
        else "not_checked"
        if summary["not_checked"]
        else "observed"
    )
    report = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "status": operational_status,
        "evidence_status": evidence_status,
        "ok": summary["blocked"] == 0,
        "blocked": summary["blocked"] > 0,
        "summary": summary,
        "plan": {
            "harness_id": harness_id,
            "invocation_mode": invocation_mode.value,
            **(
                {"execution_transport": execution_transport.value}
                if execution_transport is not None
                else {}
            ),
            "api_mode": api_mode.value,
            "model": model,
            "mode": mode,
            "workspace_configured": workspace is not None,
            "workspace_policy": workspace_policy.value,
            "delivery": "durable" if durable else "synchronous",
            "dry_run": dry_run,
        },
        "findings": checks,
    }
    return dict(_sanitize_report(report))


def _selected_proxy_checks(
    config: HarnessConfig,
    *,
    api_mode: GigaChatApiMode,
    model: str | None,
) -> list[dict[str, Any]]:
    health = proxy.health_check(config)
    sidecar = proxy.sidecar_preflight(config.to_context())
    if health.ok:
        models = proxy.discover_models(
            config,
            api_mode,
            include_compat_paths=False,
            include_fallback=False,
        )
    else:
        models = proxy.ModelDiscovery(
            ok=False,
            models=(),
            source="proxy unavailable",
            error="model discovery skipped until the selected proxy is reachable",
        )
    route_path = f"/{api_mode.value}/models"
    route_probes = {
        route_path: proxy.RouteProbe(
            ok=models.ok,
            path=route_path,
            method="GET",
            status_code=200 if models.ok else None,
            detail=(
                "authenticated model discovery accepted"
                if models.ok
                else "authenticated model discovery failed"
            ),
            error=models.error,
        )
    }
    projected = _proxy_checks(
        config,
        health,
        sidecar,
        models,
        route_probes,
        selected_api_mode=api_mode.value,
        route_paths=(route_path,),
        selected_model=model,
    )
    projected.append(_gigachat_check(config, health))
    return [_required_check(check) for check in projected]


def _dry_run_proxy_check(api_mode: GigaChatApiMode) -> dict[str, Any]:
    check = _check(
        f"route-{api_mode.value}",
        "not_checked",
        (
            f"/{api_mode.value}/chat/completions readiness was not probed because "
            "this plan does not spawn a process."
        ),
        remediation=(
            {
                "message": "Run doctor before the first non-dry-run execution.",
                "command": "giga doctor --json",
            },
        ),
    )
    check["required"] = False
    return check


def _invocation_check(
    *,
    harness_id: str,
    invocation_mode: HarnessInvocationMode,
    supports_native: bool,
) -> dict[str, Any]:
    if invocation_mode is HarnessInvocationMode.NATIVE and not supports_native:
        return _check(
            "invocation-mode",
            "degraded",
            f"{harness_id} does not support native invocation.",
            remediation=(
                {
                    "message": "Choose the supported headless invocation mode.",
                    "command": "giga harness inspect " + harness_id + " --json",
                },
            ),
        )
    return _check(
        "invocation-mode",
        "ready",
        f"Selected {invocation_mode.value} invocation is supported.",
    )


def _delivery_check(
    *,
    durable: bool,
    invocation_mode: HarnessInvocationMode,
    execution_transport: ExecutionTransport | None,
) -> dict[str, Any]:
    if not durable and execution_transport is ExecutionTransport.NATIVE_STRUCTURED:
        return _check(
            "delivery",
            "blocked",
            "native_structured execution requires the durable worker runtime.",
            remediation=(
                {
                    "message": "Start a durable worker or choose an explicit fallback transport.",
                    "command": "giga worker start",
                },
            ),
        )
    if (
        durable
        and invocation_mode is HarnessInvocationMode.NATIVE
        and execution_transport is not ExecutionTransport.NATIVE_STRUCTURED
    ):
        return _check(
            "delivery",
            "blocked",
            "Durable admission excludes native terminal execution.",
            remediation=(
                {
                    "message": (
                        "Use a synchronous native terminal or select a proven "
                        "native_structured transport."
                    ),
                    "command": "giga harness inspect --help",
                },
            ),
        )
    delivery = "durable worker" if durable else "synchronous caller"
    if durable and execution_transport is ExecutionTransport.NATIVE_STRUCTURED:
        delivery = "durable structured-native worker"
    return _check("delivery", "ready", f"Run delivery uses the {delivery} path.")


def _structured_transport_check(harness: Any, *, harness_id: str) -> dict[str, Any]:
    try:
        capabilities = admitted_durable_structured_capabilities(harness)
    except (DurableStructuredAdmissionError, TypeError, ValueError):
        return _check(
            "native-structured",
            "blocked",
            f"{harness_id} has no proven durable native_structured driver.",
            remediation=(
                {
                    "message": (
                        "Inspect provider readiness, then choose one_shot or "
                        "native_terminal explicitly if continuity is not required."
                    ),
                    "command": f"giga harness inspect {harness_id} --json",
                },
            ),
        )
    return {
        **_check(
            "native-structured",
            "ready",
            f"{harness_id} admits provider-native structured continuity.",
        ),
        "evidence": {
            "protocol": capabilities.protocol,
            "protocol_version": capabilities.protocol_version,
            "capability_snapshot_hash": capabilities.snapshot_hash,
        },
    }


def _workspace_policy_check(
    *,
    harness_kind: str,
    mode: str,
    workspace_policy: WorkspacePolicy,
) -> dict[str, Any]:
    if mode == "edit" and workspace_policy is WorkspacePolicy.TEMP_COPY:
        return _check(
            "workspace-policy",
            "blocked",
            "The selected temp_copy workspace policy is not implemented.",
            remediation=(
                {
                    "message": "Choose the reviewed worktree isolation policy.",
                    "command": "giga harness run --help",
                },
            ),
        )
    effective = (
        "worktree"
        if _requires_git_worktree(
            harness_kind=harness_kind,
            mode=mode,
            workspace_policy=workspace_policy,
        )
        else "current workspace"
    )
    return _check(
        "workspace-policy",
        "ready",
        f"Selected workspace policy resolves to {effective}.",
    )


def _requires_git_worktree(
    *,
    harness_kind: str,
    mode: str,
    workspace_policy: WorkspacePolicy,
) -> bool:
    return mode == "edit" and (
        workspace_policy is WorkspacePolicy.WORKTREE
        or (workspace_policy is WorkspacePolicy.AUTO and harness_kind == "agent-cli")
    )


def _missing_git_check() -> dict[str, Any]:
    return {
        "id": "git-readiness",
        "category": "workspace",
        "status": "blocked",
        "summary": "Git readiness cannot be established for this workspace.",
        "evidence": {"is_repository": False},
        "remediation": [
            {
                "message": "Choose or initialize a Git repository for worktree isolation.",
                "command": "git init",
            }
        ],
    }


def _required_check(
    check: Mapping[str, Any],
    *,
    block_when_unready: bool = False,
) -> dict[str, Any]:
    projected = dict(check)
    projected["required"] = True
    if block_when_unready and projected.get("status") != "ready":
        projected["status"] = "blocked"
    return projected


def _check(
    check_id: str,
    status: str,
    summary: str,
    *,
    remediation: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "id": check_id,
        "category": "execution-plan",
        "status": status,
        "summary": summary,
        "required": True,
        "evidence": {},
        "remediation": list(remediation),
    }


def _downgrade_for_dry_run(check: Mapping[str, Any]) -> dict[str, Any]:
    downgraded = dict(check)
    if downgraded.get("status") == "blocked":
        downgraded["status"] = "unknown"
        downgraded["required"] = False
        downgraded["summary"] = (
            str(downgraded.get("summary") or "Readiness is blocked")
            + " Preview inspection cannot establish execution readiness, but may "
            "continue without process spawn."
        )
    return downgraded


def _deduplicate_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for check in checks:
        check_id = str(check.get("id") or "")
        if not check_id or check_id in seen:
            continue
        seen.add(check_id)
        result.append(check)
    return result
