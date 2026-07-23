"""Doctor command for Unified Harness diagnostics."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import tempfile
from typing import Any, Mapping

from gpt2giga_harness import proxy
from gpt2giga_harness.cli_capabilities import cli_capability_snapshot_to_dict
from gpt2giga_harness.config import (
    DEFAULT_MODEL_HINTS,
    HarnessConfig,
    pass_model_env_note,
)
from gpt2giga_harness.managed_mcp import HeadlessManagedMCPSnapshotStore
from gpt2giga_harness.integration_catalog import IntegrationCatalogStore
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.native_cli_contracts import WORKBENCH_INTEGRATION_SPECS
from gpt2giga_harness.project import load_project_config, resolve_project
from gpt2giga_harness.provider_settings import ProviderSettingsService
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime.store import RUNTIME_DB_NAME
from gpt2giga_harness.types import AvailabilityStatus, redact_secrets

DOCTOR_SCHEMA_VERSION = 1
DOCTOR_REPORT_KIND = "gpt2giga_harness_doctor_report"
_WORKER_STALE_AFTER_SECONDS = 30.0
_MAX_SNAPSHOT_VALIDATIONS = 100
_MAX_SNAPSHOT_BYTES = 1_000_000


def build_doctor_report(
    config: HarnessConfig,
    registry: HarnessRegistry | None = None,
    *,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Build a redaction-safe, machine-readable first-run readiness report."""
    registry = registry or create_default_registry()
    health = proxy.health_check(config)
    sidecar = proxy.sidecar_preflight(config.to_context())
    models = proxy.discover_models(config, config.default_api_mode)
    route_probes = (
        _chat_route_probes(config, _route_probe_model(config, models))
        if health.ok
        else {}
    )
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "runtime",
            "runtime",
            "ready",
            f"Runtime / Python: {platform.python_version()}; package import: OK",
            evidence={"python": platform.python_version(), "package_import": True},
        )
    )
    checks.extend(_proxy_checks(config, health, sidecar, models, route_probes))
    checks.append(_gigachat_check(config, health))
    checks.extend(_harness_checks(registry))
    checks.extend(_workspace_checks(config, workspace))
    checks.append(_worker_check(config))
    checks.append(_managed_homes_check(config))
    checks.append(_managed_mcp_check(config))
    checks.extend(_bootstrap_discovery_checks(config))
    if registry.discovery_errors:
        checks.append(
            _check(
                "plugin-discovery",
                "harnesses",
                "degraded",
                f"Harness plugins: {len(registry.discovery_errors)} discovery error(s)",
                evidence={"errors": list(registry.discovery_errors)},
                remediation=(
                    _remedy(
                        "Inspect or remove the failing Harness plugin.",
                        "giga harness list --json",
                    ),
                ),
            )
        )
    summary = {
        status: sum(check["status"] == status for check in checks)
        for status in ("ready", "degraded", "blocked")
    }
    report = {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "kind": DOCTOR_REPORT_KIND,
        "environment": {
            "packages": {
                "gpt2giga": _package_version("gpt2giga"),
                "gpt2giga-harness": _package_version("gpt2giga-harness"),
            },
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
        },
        "ok": summary["blocked"] == 0,
        "summary": summary,
        "checks": checks,
    }
    return dict(_sanitize_report(report))


def run_doctor(
    config: HarnessConfig,
    registry: HarnessRegistry | None = None,
    *,
    workspace: str | Path | None = None,
) -> str:
    """Build a human-readable diagnostic report without printing secrets."""
    return format_doctor_report(
        build_doctor_report(config, registry, workspace=workspace)
    )


def write_doctor_support_report(
    report: Mapping[str, Any],
    output: str | Path,
) -> Path:
    """Atomically write one canonical private JSON report for support."""
    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    payload = json.dumps(
        _sanitize_report(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{payload}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def format_doctor_report(report: Mapping[str, Any]) -> str:
    """Format one structured doctor report for terminal users."""
    summary = report.get("summary") or {}
    lines = [
        "gpt2giga Unified Harness doctor",
        (
            "Summary: "
            f"{summary.get('ready', 0)} ready, "
            f"{summary.get('degraded', 0)} degraded, "
            f"{summary.get('blocked', 0)} blocked"
        ),
    ]
    for raw_check in report.get("checks") or ():
        if not isinstance(raw_check, Mapping):
            continue
        status = str(raw_check.get("status") or "unknown").upper()
        lines.extend(["", f"[{status}] {raw_check.get('summary') or 'Unknown check'}"])
        native_facade = (raw_check.get("evidence") or {}).get("native_facade")
        if isinstance(native_facade, Mapping):
            levels = native_facade.get("levels") or {}
            lines.append(
                "  Native facade: "
                f"{native_facade.get('namespace')}; "
                f"executable={native_facade.get('executable') or 'missing'}; "
                f"version={native_facade.get('version') or 'unknown'}; "
                f"L0={levels.get('L0', 'unknown')}; "
                f"L1={levels.get('L1', 'unknown')}; "
                f"L2={levels.get('L2', 'unknown')}; "
                f"transport={native_facade.get('transport') or 'none'}; "
                f"fallback={native_facade.get('fallback') or 'none'}"
            )
            if native_facade.get("degradation"):
                lines.append(f"  Degradation: {native_facade['degradation']}")
            if native_facade.get("remediation"):
                lines.append(f"  Remedy: {native_facade['remediation']}")
        for remediation in raw_check.get("remediation") or ():
            if not isinstance(remediation, Mapping):
                continue
            message = remediation.get("message")
            command = remediation.get("command")
            if message:
                lines.append(f"  Remedy: {message}")
            if command:
                lines.append(f"  Command: {command}")
    return "\n".join(lines)


def _proxy_checks(
    config: HarnessConfig,
    health: proxy.ProxyHealth,
    sidecar: proxy.SidecarPreflight,
    models: proxy.ModelDiscovery,
    route_probes: Mapping[str, proxy.RouteProbe],
    *,
    selected_api_mode: str | None = None,
    route_paths: tuple[str, ...] = ("/v1/chat/completions", "/v2/chat/completions"),
    selected_model: str | None = None,
) -> list[dict[str, Any]]:
    if health.ok:
        proxy_status = "ready"
        proxy_remediation: tuple[dict[str, str], ...] = ()
    elif sidecar.ok:
        proxy_status = "degraded"
        proxy_remediation = (_remedy("Start the configured local proxy.", "gpt2giga"),)
    else:
        proxy_status = "blocked"
        proxy_remediation = (
            _remedy(
                "Configure proxy access or fix local auto-start prerequisites.",
                "giga doctor --json",
            ),
        )
    sidecar_ready = sidecar.ok or health.ok
    sidecar_text = (
        _sidecar_text(sidecar)
        if sidecar.ok or not health.ok
        else "not needed; proxy already reachable"
    )
    checks = [
        _check(
            "proxy-health",
            "proxy",
            proxy_status,
            f"Proxy / Health: {_health_text(health)}",
            evidence={
                "configured_url": config.proxy_url,
                "reachable": health.ok,
                "health_path": health.path,
                "status_code": health.status_code,
                "error": health.error,
            },
            remediation=proxy_remediation,
        ),
        _check(
            "proxy-autostart",
            "proxy",
            "ready" if sidecar_ready else "degraded",
            f"Proxy / Auto-start: {sidecar_text}",
            evidence={"ready": sidecar.ok, "reason": sidecar.reason},
            remediation=(
                ()
                if sidecar_ready
                else (
                    _remedy(
                        "Configure local GigaChat access or use an existing proxy.",
                        "giga doctor --no-start-proxy --json",
                    ),
                )
            ),
        ),
    ]
    selected_mode = selected_api_mode or config.default_api_mode.value
    for path in route_paths:
        route = route_probes.get(path)
        status = (
            "ready"
            if route is not None and route.ok
            else "degraded"
            if route is None and sidecar.ok
            else "blocked"
            if path.split("/")[1] == selected_mode
            else "degraded"
        )
        checks.append(
            _check(
                f"route-{path.split('/')[1]}",
                "routes",
                status,
                f"{path}: {_route_probe_text(route)}",
                evidence=(
                    {"reachable": False, "status_code": None}
                    if route is None
                    else {
                        "reachable": route.ok,
                        "status_code": route.status_code,
                        "detail": route.detail,
                    }
                ),
                remediation=(
                    ()
                    if status == "ready"
                    else (
                        _remedy(
                            "Start a compatible gateway and verify the selected route.",
                            "giga doctor --json",
                        ),
                    )
                ),
            )
        )
    model_status = (
        "ready"
        if models.models or selected_model or config.default_model
        else "degraded"
    )
    checks.append(
        _check(
            "model-discovery",
            "routes",
            model_status,
            f"Models: {len(models.models)} candidate(s) from {models.source}",
            evidence={
                "count": len(models.models),
                "source": models.source,
                "default_configured": bool(selected_model or config.default_model),
            },
            remediation=(
                ()
                if model_status == "ready"
                else (
                    _remedy(
                        "Set a default model or fix proxy model discovery.",
                        "export GPT2GIGA_HARNESS_DEFAULT_MODEL=<model-from-/v2/models>",
                    ),
                )
            ),
        )
    )
    return checks


def _gigachat_check(
    config: HarnessConfig,
    health: proxy.ProxyHealth,
) -> dict[str, Any]:
    source = _credentials_source()
    configured = source is not None
    status = "ready" if configured or health.ok else "degraded"
    model = config.default_model or "not configured"
    api_mode_env = os.getenv("GPT2GIGA_GIGACHAT_API_MODE") or "not set"
    pass_model = pass_model_env_note() or "not set"
    summary = (
        "GigaChat / Upstream access: "
        f"{'configured (redacted)' if configured else 'not configured'}; "
        f"default model: {model}"
    )
    return _check(
        "gigachat-upstream",
        "gigachat",
        status,
        summary,
        evidence={
            "configured": configured,
            "source_env": source,
            "api_mode_env": api_mode_env,
            "pass_model": pass_model,
            "running_proxy_reachable": health.ok,
        },
        remediation=(
            ()
            if status == "ready"
            else (
                _remedy(
                    "Configure GigaChat credentials for local proxy auto-start.",
                    "giga doctor --json",
                ),
            )
        ),
    )


def _harness_checks(
    registry: HarnessRegistry,
    *,
    harness_ids: tuple[str, ...] | None = None,
    include_compatibility: bool = True,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for harness in registry.list():
        spec = harness.spec()
        if harness_ids is not None and spec.id not in harness_ids:
            continue
        availability = harness.availability()
        status = (
            "ready"
            if availability.status is AvailabilityStatus.AVAILABLE
            else "degraded"
        )
        evidence: dict[str, Any] = {
            "availability": availability.status.value,
            "reason": availability.reason,
        }
        probe_method = getattr(harness, "capability_probe", None)
        if include_compatibility and callable(probe_method):
            probe = probe_method()
            compatibility = cli_capability_snapshot_to_dict(probe)
            compatibility.pop("command", None)
            evidence["compatibility"] = compatibility
            namespace = _native_namespace_for_harness(spec.id)
            if namespace is not None:
                resolution_method = getattr(harness, "executable_resolution", None)
                resolution = (
                    resolution_method() if callable(resolution_method) else None
                )
                evidence["native_facade"] = _native_facade_evidence(
                    namespace,
                    probe_status=probe.status,
                    compatible=probe.compatible,
                    version=probe.parsed_version or probe.version,
                    version_status=probe.version_window_status,
                    executable=(
                        resolution.executable if resolution is not None else None
                    ),
                    executable_source=(
                        resolution.source if resolution is not None else "unknown"
                    ),
                )
        suffix = f" - {availability.reason}" if availability.reason else ""
        checks.append(
            _check(
                f"harness-{spec.id}",
                "harnesses",
                status,
                f"Harness / {spec.id}: {availability.status.value}{suffix}",
                evidence=evidence,
                remediation=(
                    ()
                    if status == "ready"
                    else (
                        _remedy(
                            "Install or configure the adapter executable, then inspect it.",
                            f"giga harness inspect {spec.id} --json",
                        ),
                    )
                ),
            )
        )
    return checks


def _native_namespace_for_harness(harness_id: str) -> str | None:
    return {
        "codex-cli": "codex",
        "claude-code": "claude",
        "gemini-cli": "gemini",
    }.get(harness_id)


def _native_facade_evidence(
    namespace: str,
    *,
    probe_status: str,
    compatible: bool,
    version: str | None,
    version_status: str,
    executable: str | None,
    executable_source: str,
) -> dict[str, Any]:
    integration = WORKBENCH_INTEGRATION_SPECS[namespace]
    executable_ready = executable is not None and probe_status != "missing"
    l2_ready = (
        executable_ready and compatible and bool(integration.structured_transport)
    )
    degradation = None
    remediation = None
    if not executable_ready:
        degradation = "native_runtime_missing"
        remediation = (
            f"Install {namespace} on PATH or configure executables."
            f"{integration.harness_id}."
        )
    elif not l2_ready:
        degradation = (
            "provider_owned_l1"
            if integration.structured_transport is None
            else f"structured_{version_status}"
        )
        remediation = (
            "Use the visible provider-owned L1 handoff, or install a reviewed "
            "structured-transport version; L0 remains available."
        )
    return {
        "namespace": namespace,
        "executable": executable,
        "executable_source": executable_source,
        "version": version,
        "levels": {
            "L0": "ready" if executable_ready else "blocked",
            "L1": "ready" if executable_ready else "blocked",
            "L2": "ready"
            if l2_ready
            else "degraded"
            if executable_ready
            else "blocked",
        },
        "transport": integration.structured_transport,
        "fallback": integration.l1_fallback,
        "degradation": degradation,
        "remediation": remediation,
    }


def _workspace_checks(
    config: HarnessConfig,
    workspace: str | Path | None,
) -> list[dict[str, Any]]:
    requested = Path.cwd() if workspace is None else Path(workspace).expanduser()
    if not requested.exists() or not requested.is_dir():
        return [
            _check(
                "workspace",
                "workspace",
                "blocked",
                "Workspace: directory is missing or unreadable",
                evidence={"exists": requested.exists(), "is_directory": False},
                remediation=(
                    _remedy("Choose an existing project directory.", "giga doctor ."),
                ),
            )
        ]
    try:
        project = resolve_project(
            requested,
            data_dir=config.data_dir,
            load_config_name=False,
        )
        project_config = load_project_config(project.root)
    except (OSError, RuntimeError, ValueError) as exc:
        return [
            _check(
                "workspace",
                "workspace",
                "blocked",
                "Workspace: Harness project configuration is invalid",
                evidence={"error": str(exc)},
                remediation=(
                    _remedy(
                        "Fix the redacted project configuration error.", "giga init"
                    ),
                ),
            )
        ]
    dirty = dict(project.dirty_summary)
    git_status = "ready" if project.is_git_repo else "degraded"
    config_status = "ready" if project_config.exists else "degraded"
    return [
        _check(
            "workspace",
            "workspace",
            "ready",
            f"Workspace: ready ({project.name})",
            evidence={
                "exists": True,
                "project_id": project.id,
                "project_name": project.name,
            },
        ),
        _check(
            "git-readiness",
            "workspace",
            git_status,
            (
                "Git: repository ready"
                if project.is_git_repo
                else "Git: current workspace is not a repository"
            ),
            evidence={
                "is_repository": project.is_git_repo,
                "branch_present": bool(project.git_branch),
                "dirty_counts": dirty,
            },
            remediation=(
                ()
                if git_status == "ready"
                else (
                    _remedy("Initialize Git for reviewed worktree flows.", "git init"),
                )
            ),
        ),
        _check(
            "project-config",
            "workspace",
            config_status,
            (
                "Project config: .giga/harness.toml is ready"
                if project_config.exists
                else "Project config: not initialized"
            ),
            evidence={"configured": project_config.exists},
            remediation=(
                ()
                if config_status == "ready"
                else (
                    _remedy(
                        "Create safe starter project configuration.",
                        "giga init",
                    ),
                )
            ),
        ),
    ]


def _worker_check(config: HarnessConfig) -> dict[str, Any]:
    state = _read_worker_state(config.data_dir)
    readable = state.get("readable", True)
    status = "ready" if state["online"] else "degraded" if readable else "blocked"
    return _check(
        "durable-worker",
        "worker",
        status,
        f"Durable worker: {state['online']} online; {state['total']} recorded",
        evidence=state,
        remediation=(
            ()
            if status == "ready"
            else (
                _remedy(
                    (
                        "Start a durable Harness worker."
                        if readable
                        else "Inspect the unreadable runtime coordination store."
                    ),
                    "giga worker start" if readable else "giga runtime inspect --json",
                ),
            )
        ),
    )


def _managed_homes_check(config: HarnessConfig) -> dict[str, Any]:
    data_dir = Path(config.data_dir).expanduser()
    writable = _path_can_be_created(data_dir)
    homes_root = data_dir / "native"
    home_count = (
        sum(1 for path in homes_root.glob("*/homes/*") if path.is_dir())
        if homes_root.exists()
        else 0
    )
    status = "ready" if writable else "blocked"
    return _check(
        "managed-homes",
        "managed-state",
        status,
        f"Managed homes: storage {'ready' if writable else 'not writable'}; {home_count} home(s)",
        evidence={
            "storage_initialized": data_dir.exists(),
            "storage_writable": writable,
            "home_count": home_count,
        },
        remediation=(
            ()
            if status == "ready"
            else (
                _remedy(
                    "Choose a writable Harness data directory.",
                    "export GPT2GIGA_HARNESS_DATA_DIR=/path/to/writable/state",
                ),
            )
        ),
    )


def _managed_mcp_check(config: HarnessConfig) -> dict[str, Any]:
    data_dir = Path(config.data_dir).expanduser()
    root = data_dir / "tools" / "headless_mcp_snapshots"
    paths = sorted(root.glob("*.json")) if root.exists() else []
    invalid = 0
    checked = 0
    store = HeadlessManagedMCPSnapshotStore(data_dir)
    for path in paths[:_MAX_SNAPSHOT_VALIDATIONS]:
        checked += 1
        try:
            if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
                raise ValueError("snapshot is too large")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, Mapping):
                raise ValueError("snapshot must be an object")
            store.load(
                {
                    "snapshot_id": record.get("snapshot_id"),
                    "snapshot_hash": record.get("snapshot_hash"),
                    "project_id": record.get("project_id"),
                    "harness_id": record.get("harness_id"),
                }
            )
        except (OSError, ValueError, json.JSONDecodeError):
            invalid += 1
    skipped = max(0, len(paths) - checked)
    status = "ready" if invalid == 0 and skipped == 0 else "degraded"
    return _check(
        "managed-mcp-snapshots",
        "managed-state",
        status,
        f"Managed MCP snapshots: {len(paths)} stored; {invalid} invalid; {skipped} unchecked",
        evidence={
            "stored": len(paths),
            "validated": checked,
            "invalid": invalid,
            "unchecked": skipped,
        },
        remediation=(
            ()
            if status == "ready"
            else (
                _remedy(
                    "Inspect configured MCP profiles and recreate invalid snapshots.",
                    "giga doctor --json",
                ),
            )
        ),
    )


def _bootstrap_discovery_checks(config: HarnessConfig) -> list[dict[str, Any]]:
    """Return bounded local discovery used by doctor and reviewed bootstrap."""
    checks = [
        _github_cli_check(),
        _optional_dependencies_check(),
        _support_export_check(),
    ]
    try:
        providers = ProviderSettingsService(str(config.data_dir)).list()
        configured = providers.get("providers") or []
        ownership_counts: dict[str, int] = {}
        for provider in configured:
            if not isinstance(provider, Mapping):
                continue
            authentication = provider.get("authentication")
            if not isinstance(authentication, Mapping):
                continue
            ownership = str(authentication.get("ownership") or "unknown")
            ownership_counts[ownership] = ownership_counts.get(ownership, 0) + 1
        checks.append(
            _check(
                "provider-profiles",
                "bootstrap",
                "ready",
                (
                    f"Provider profiles: {len(configured)} configured; "
                    f"{len(providers.get('templates') or ())} templates"
                ),
                evidence={
                    "configured": len(configured),
                    "templates": len(providers.get("templates") or ()),
                    "authentication_ownership": ownership_counts,
                    "native_cli_authentication": {
                        namespace: {
                            "ownership": "provider_native",
                            "status": "not_checked",
                        }
                        for namespace in sorted(WORKBENCH_INTEGRATION_SPECS)
                    },
                    "values_resolved": False,
                },
                remediation=(
                    _remedy(
                        "Review provider profiles and reference-only authentication.",
                        "giga provider list --json",
                    ),
                ),
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        checks.append(
            _check(
                "provider-profiles",
                "bootstrap",
                "degraded",
                "Provider profiles: local registry is unreadable",
                evidence={"error": str(exc), "values_resolved": False},
                remediation=(
                    _remedy(
                        "Inspect the local provider registry without resolving secrets.",
                        "giga provider list --json",
                    ),
                ),
            )
        )
    try:
        catalog = IntegrationCatalogStore(config.data_dir).list()
        flows = IntegrationFlowService(config.data_dir).list()
        statuses: dict[str, int] = {}
        for flow in flows:
            status = flow.status.value
            statuses[status] = statuses.get(status, 0) + 1
        checks.append(
            _check(
                "extensions",
                "bootstrap",
                "ready",
                (
                    f"Extensions: {len(catalog)} cached catalog entries; "
                    f"{len(flows)} retained flow(s)"
                ),
                evidence={
                    "catalog_entries": len(catalog),
                    "retained_flows": len(flows),
                    "flow_statuses": statuses,
                    "installation_authorized": False,
                },
                remediation=(
                    _remedy(
                        "Review extension compatibility and retained flow state.",
                        "giga integration list --json",
                    ),
                ),
            )
        )
    except (OSError, ValueError) as exc:
        checks.append(
            _check(
                "extensions",
                "bootstrap",
                "degraded",
                "Extensions: local catalog or flow state is unreadable",
                evidence={"error": str(exc), "installation_authorized": False},
                remediation=(
                    _remedy(
                        "Inspect local integration state before any setup action.",
                        "giga integration list --json",
                    ),
                ),
            )
        )
    return checks


def _github_cli_check() -> dict[str, Any]:
    executable = shutil.which("gh")
    return _check(
        "github-cli",
        "bootstrap",
        "ready" if executable else "degraded",
        (
            "GitHub CLI: installed; authentication not checked"
            if executable
            else "GitHub CLI: not installed"
        ),
        evidence={
            "installed": executable is not None,
            "authentication_status": "not_checked",
            "network_contacted": False,
        },
        remediation=(
            _remedy(
                (
                    "Inspect local GitHub authentication explicitly."
                    if executable
                    else "Install GitHub CLI, then authenticate explicitly."
                ),
                "gh auth status" if executable else "giga doctor --json",
            ),
        ),
    )


def _optional_dependencies_check() -> dict[str, Any]:
    packages = {
        name: _optional_package_version(name)
        for name in ("claude-agent-sdk", "gigachat", "gpt2giga")
    }
    available = sum(value != "unknown" for value in packages.values())
    return _check(
        "optional-dependencies",
        "bootstrap",
        "ready",
        f"Optional dependencies: {available}/{len(packages)} installed",
        evidence={
            "packages": packages,
            "required_for_base_install": False,
        },
        remediation=(
            _remedy(
                "Install only the reviewed optional capability you intend to use.",
                "giga doctor --json",
            ),
        ),
    )


def _support_export_check() -> dict[str, Any]:
    return _check(
        "support-export",
        "bootstrap",
        "ready",
        "Support export: private canonical JSON is available",
        evidence={"content_free": True, "mode": "0600", "atomic": True},
        remediation=(
            _remedy(
                "Export the current redacted report for support.",
                "giga doctor --json --output doctor-support.json",
            ),
        ),
    )


def _read_worker_state(data_dir: str | Path) -> dict[str, Any]:
    path = Path(data_dir).expanduser() / RUNTIME_DB_NAME
    if not path.is_file():
        return {"initialized": False, "online": 0, "offline": 0, "total": 0}
    try:
        with closing(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        ) as connection:
            rows = connection.execute(
                "SELECT status, heartbeat_at FROM workers"
            ).fetchall()
    except (OSError, sqlite3.Error):
        return {
            "initialized": True,
            "online": 0,
            "offline": 0,
            "total": 0,
            "readable": False,
        }
    now = datetime.now(timezone.utc).timestamp()
    online = 0
    for status, heartbeat_at in rows:
        try:
            heartbeat = datetime.fromisoformat(str(heartbeat_at)).timestamp()
        except ValueError:
            heartbeat = 0.0
        if status == "online" and now - heartbeat <= _WORKER_STALE_AFTER_SECONDS:
            online += 1
    return {
        "initialized": True,
        "readable": True,
        "online": online,
        "offline": len(rows) - online,
        "total": len(rows),
    }


def _path_can_be_created(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def _check(
    check_id: str,
    category: str,
    status: str,
    summary: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    remediation: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "id": check_id,
        "category": category,
        "status": status,
        "summary": summary,
        "evidence": dict(evidence or {}),
        "remediation": list(remediation),
    }


def _remedy(message: str, command: str) -> dict[str, str]:
    return {"message": message, "command": command}


def _sanitize_report(value: Any) -> Any:
    """Redact secrets and collapse the operator home in diagnostic strings."""
    value = redact_secrets(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_report(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_sanitize_report(item) for item in value)
    if isinstance(value, list):
        return [_sanitize_report(item) for item in value]
    if isinstance(value, str):
        home = str(Path.home())
        return value.replace(home, "~") if home else value
    return value


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _optional_package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _health_text(health: proxy.ProxyHealth) -> str:
    if health.ok:
        return f"OK via {health.path} ({health.status_code})"
    return f"unreachable ({health.error})"


def _sidecar_text(sidecar: proxy.SidecarPreflight) -> str:
    if sidecar.ok:
        return "ready"
    return sidecar.reason


def _chat_route_probes(
    config: HarnessConfig,
    model: str,
) -> dict[str, proxy.RouteProbe]:
    return {
        path: proxy.probe_json_route(config, path, model=model)
        for path in ("/v1/chat/completions", "/v2/chat/completions")
    }


def _route_probe_model(
    config: HarnessConfig,
    models: proxy.ModelDiscovery,
) -> str:
    if config.default_model:
        return config.default_model
    if models.models:
        return models.models[0]
    return DEFAULT_MODEL_HINTS[0]


def _route_probe_text(route: proxy.RouteProbe | None) -> str:
    if route is None:
        return "not checked; proxy unreachable"
    status = (
        f"HTTP {route.status_code}" if route.status_code is not None else "no status"
    )
    detail = f"; {route.detail}" if route.detail else ""
    if route.ok:
        return f"reachable ({status}{detail})"
    return f"unreachable ({status}{detail})"


def _credentials_source() -> str | None:
    for name in (
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_ACCESS_TOKEN",
        "GIGACHAT_USER",
    ):
        value = os.getenv(name)
        if value:
            return name
    return None
