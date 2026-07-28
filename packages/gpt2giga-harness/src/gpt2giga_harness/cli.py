"""Command-line interface for the gpt2giga Unified Harness."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

import uvicorn
import yaml

from gpt2giga_harness import __version__
from gpt2giga_harness.adapter_scaffold import (
    render_adapter_module,
    scaffold_adapter_package,
)
from gpt2giga_harness.adapter_sdk import (
    adapter_conformance_report_to_dict,
    load_installed_conformance_subject,
    run_adapter_conformance,
)
from gpt2giga_harness.application import SessionApplicationService
from gpt2giga_harness.bootstrap import BootstrapService
from gpt2giga_harness.agents import (
    agent_profile_to_dict,
    agent_run_payload,
    discover_agent_profiles,
    load_agent_profile,
    parse_agent_profile,
)
from gpt2giga_harness.capability_matrix import (
    build_adapter_capability_matrix,
    render_adapter_capability_matrix_markdown,
    render_agent_surface_capability_matrix_markdown,
)
from gpt2giga_harness.product_inventory import (
    build_product_inventory,
    canonical_inventory_json,
    load_product_inventory,
    validate_product_inventory,
)
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.completion import SHELLS, render_completion
from gpt2giga_harness.cli_capabilities import cli_capability_snapshot_to_dict
from gpt2giga_harness.compatibility_guardian import run_compatibility_guardian
from gpt2giga_harness.doctor import (
    build_doctor_report,
    format_doctor_report,
    write_doctor_support_report,
)
from gpt2giga_harness.editor import (
    build_open_diff_plan,
    build_open_file_plan,
    build_open_run_workspace_plan,
    build_open_terminal_plan,
    build_open_workspace_plan,
    editor_open_plan_to_dict,
    execute_editor_plan,
    workspace_for_run,
)
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.integration_flows import (
    IntegrationFlowConflictError,
    IntegrationFlowError,
    IntegrationFlowNotFoundError,
    IntegrationFlowService,
    integration_flow_record_to_dict,
)
from gpt2giga_harness.integration_groups import (
    GroupedIntegrationService,
    IntegrationGroupConflictError,
    IntegrationGroupError,
    IntegrationGroupNotFoundError,
    integration_group_record_to_dict,
)
from gpt2giga_harness.integration_scaffold import scaffold_integration_package
from gpt2giga_harness.integration_sdk import (
    integration_conformance_report_to_dict,
    load_extension_target_document,
    load_integration_package_document,
    run_integration_conformance,
)
from gpt2giga_harness.handoff_capsules import HandoffCapsuleService
from gpt2giga_harness.executables import (
    executable_resolution_to_dict,
    set_user_executable,
    unset_user_executable,
    user_config_path,
)
from gpt2giga_harness.evals import (
    EvalSpecNotFoundError,
    FilesystemHarnessEvalStore,
    discover_eval_specs,
    eval_run_to_dict,
    eval_spec_load_error_to_dict,
    eval_spec_to_dict,
    load_eval_spec,
    run_eval,
)
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.native.base import (
    discovery_error_to_dict,
    native_command_plan_to_dict,
)
from gpt2giga_harness.native.discovery import normalize_native_workspace
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    execution_snapshot_to_dict,
)
from gpt2giga_harness.native.registry import (
    UnknownNativeHistoryConnectorError,
    create_default_native_registry,
)
from gpt2giga_harness.native.store import (
    FilesystemNativeSessionIndexStore,
    native_session_ref_to_dict,
)
from gpt2giga_harness.project import (
    init_project_config,
    load_project_config,
    project_config_path,
    project_config_to_dict,
    project_to_dict,
    render_project_preset,
    rendered_project_preset_to_dict,
    resolve_project,
)
from gpt2giga_harness.project_memory import (
    FilesystemProjectMemoryStore,
    ProjectMemoryNotFoundError,
    memory_entry_to_dict,
)
from gpt2giga_harness.provider_settings import (
    ProviderRegistryConflict,
    ProviderSettingsNotFoundError,
    ProviderSettingsService,
)
from gpt2giga_harness.provider_migration import ProviderMigrationService
from gpt2giga_harness.preflight import (
    build_preflight_report,
    format_preflight_block_message,
    preflight_report_to_dict,
)
from gpt2giga_harness.permission_simulator import build_permission_simulation
from gpt2giga_harness.performance_baseline import (
    run_performance_baseline,
    write_performance_report,
)
from gpt2giga_harness.pr_artifacts import build_pr_artifact, pr_artifact_to_dict
from gpt2giga_harness.plugins import (
    harness_validation_report_to_dict,
    validate_harness_spec,
)
from gpt2giga_harness.provenance import (
    build_replay_request,
    build_run_provenance,
    run_provenance_to_dict,
)
from gpt2giga_harness.readiness import build_execution_readiness
from gpt2giga_harness.reviewed_evidence import reviewed_evidence_manifest
from gpt2giga_harness.registry import UnknownHarnessError, create_default_registry
from gpt2giga_harness.runtime.models import job_to_dict
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.policy import (
    ApprovalDecision,
    approval_request_to_dict,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import (
    DurableJobDispatcher,
    DurableJobWorker,
    worker_status,
)
from gpt2giga_harness.schedules import (
    ScheduleService,
    build_schedule_definition,
    next_occurrences,
    schedule_definition_to_dict,
)
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    RunNotFoundError,
    SessionNotFoundError,
)
from gpt2giga_harness.sessions.models import (
    bundle_to_dict,
    event_to_dict,
    run_to_dict,
    session_to_dict,
)
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessNativeLink,
    HarnessStoredEvent,
    message_to_dict,
    native_link_to_dict,
)
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.session_titles import provider_native_title_metadata
from gpt2giga_harness.state_backup import (
    create_state_backup,
    restore_state_backup,
    verify_state_backup,
)
from gpt2giga_harness.settings import HarnessSettingsStore
from gpt2giga_harness.types import (
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    availability_to_dict,
    parse_api_mode,
    parse_capability,
    result_to_dict,
    spec_capability_values,
    spec_to_dict,
)
from gpt2giga_harness.worktrees import parse_workspace_policy
from gpt2giga_harness.ui.app import create_app, validate_ui_bind
from gpt2giga_harness.ui.remote_identity import (
    RemoteIdentityError,
    RemoteIdentityStore,
    RemoteOIDCSettings,
)
from gpt2giga_harness.ui.security import is_loopback_host
from gpt2giga_harness.workspace import resolve_workspace
from gpt2giga_harness.workbench_execution import workbench_transport_projection
from gpt2giga_harness.workflows import (
    WorkflowCoordinator,
    WorkflowRepository,
    discover_workflows,
    load_workflow,
    parse_workflow_definition,
    workflow_definition_to_dict,
    workflow_plan,
    workflow_run_to_dict,
)

AGENT_ALIASES = {
    "codex": "codex-cli",
    "claude": "claude-code",
    "gemini": "gemini-cli",
}

UI_WORKER_START_TIMEOUT_SECONDS = 10.0
UI_WORKER_STOP_TIMEOUT_SECONDS = 3.0
UI_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5
MAX_UI_WORKER_COUNT = 32


def main(argv: list[str] | None = None) -> int:
    """Run the Unified Harness CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    config = _config_from_args(args)
    try:
        return args.handler(args, config)
    except UnknownHarnessError as exc:
        print(f"Unknown harness: {exc.args[0]}", file=sys.stderr)
        return 2
    except UnknownNativeHistoryConnectorError as exc:
        print(f"Unknown native harness: {exc.args[0]}", file=sys.stderr)
        return 2
    except SessionNotFoundError as exc:
        print(f"Unknown session: {exc.args[0]}", file=sys.stderr)
        return 2
    except RunNotFoundError as exc:
        print(f"Unknown run: {exc.args[0]}", file=sys.stderr)
        return 2
    except ProjectMemoryNotFoundError as exc:
        print(f"Unknown memory: {exc.args[0]}", file=sys.stderr)
        return 2
    except ProviderSettingsNotFoundError as exc:
        print(f"Unknown provider: {exc.args[0]}", file=sys.stderr)
        return 2
    except ProviderRegistryConflict as exc:
        print(f"Provider registry conflict: {exc}", file=sys.stderr)
        return 2
    except EvalSpecNotFoundError as exc:
        print(f"Unknown eval: {exc.args[0]}", file=sys.stderr)
        return 2
    except IntegrationFlowNotFoundError as exc:
        print(f"Unknown integration flow: {exc.args[0]}", file=sys.stderr)
        return 2
    except (IntegrationFlowConflictError, IntegrationFlowError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except IntegrationGroupNotFoundError as exc:
        print(f"Unknown integration group: {exc.args[0]}", file=sys.stderr)
        return 2
    except (IntegrationGroupConflictError, IntegrationGroupError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RemoteIdentityError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--proxy-url", default=None, help="Local gpt2giga proxy URL")
    common.add_argument(
        "--start-proxy",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Start a local gpt2giga sidecar if the proxy is down",
    )
    common.add_argument(
        "--non-interactive",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Keep this invocation on the automation/admin command surface",
    )

    parser = argparse.ArgumentParser(prog="giga")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Keep this invocation on the automation/admin command surface",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"GigaLoom {__version__} (gpt2giga-harness)",
    )
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", parents=[common])
    doctor.add_argument("workspace", nargs="?", default=None)
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument(
        "--output",
        default=None,
        help="Atomically write a private canonical JSON support report",
    )
    doctor.add_argument(
        "--fail-on",
        choices=("blocked", "degraded"),
        default=None,
        help="Return 1 when the selected CI readiness threshold is reached",
    )
    doctor.set_defaults(handler=_handle_doctor)

    bootstrap = subparsers.add_parser("bootstrap", parents=[common])
    bootstrap_subparsers = bootstrap.add_subparsers(dest="bootstrap_command")

    bootstrap_preview = bootstrap_subparsers.add_parser("preview")
    bootstrap_preview.add_argument("--workspace", default=None)
    bootstrap_preview.add_argument("--json", action="store_true")
    bootstrap_preview.set_defaults(handler=_handle_bootstrap_preview)

    bootstrap_apply = bootstrap_subparsers.add_parser("apply")
    bootstrap_apply.add_argument("plan_id")
    bootstrap_apply.add_argument("--workspace", default=None)
    bootstrap_apply.add_argument("--step", action="append", default=[])
    bootstrap_apply.add_argument("--all-reversible", action="store_true")
    bootstrap_apply.add_argument("--json", action="store_true")
    bootstrap_apply.set_defaults(handler=_handle_bootstrap_apply)

    bootstrap_status = bootstrap_subparsers.add_parser("status")
    bootstrap_status.add_argument("application_id")
    bootstrap_status.add_argument("--json", action="store_true")
    bootstrap_status.set_defaults(handler=_handle_bootstrap_status)

    bootstrap_rollback = bootstrap_subparsers.add_parser("rollback")
    bootstrap_rollback.add_argument("application_id")
    bootstrap_rollback.add_argument("--workspace", default=None)
    bootstrap_rollback.add_argument("--json", action="store_true")
    bootstrap_rollback.set_defaults(handler=_handle_bootstrap_rollback)

    compatibility = subparsers.add_parser("compatibility")
    compatibility_subparsers = compatibility.add_subparsers(
        dest="compatibility_command"
    )
    compatibility_check = compatibility_subparsers.add_parser("check")
    compatibility_check.add_argument("--harness", action="append", default=[])
    compatibility_check.add_argument("--json", action="store_true")
    compatibility_check.set_defaults(handler=_handle_compatibility_check)

    handoff = subparsers.add_parser("handoff", parents=[common])
    handoff_subparsers = handoff.add_subparsers(dest="handoff_command")
    handoff_capsule = handoff_subparsers.add_parser("capsule")
    handoff_capsule.add_argument("run_id")
    handoff_capsule.add_argument("--target-harness", required=True)
    handoff_capsule.add_argument("--json", action="store_true")
    handoff_capsule.set_defaults(handler=_handle_handoff_capsule)

    completion = subparsers.add_parser(
        "completion",
        help="Print shell completion for the stable giga command boundary",
    )
    completion.add_argument("shell", choices=SHELLS)
    completion.set_defaults(handler=_handle_completion)

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_path = config_subparsers.add_parser("path")
    config_path.set_defaults(handler=_handle_config_path)
    config_set = config_subparsers.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.set_defaults(handler=_handle_config_set)
    config_unset = config_subparsers.add_parser("unset")
    config_unset.add_argument("key")
    config_unset.set_defaults(handler=_handle_config_unset)

    provider = subparsers.add_parser("provider")
    provider_subparsers = provider.add_subparsers(dest="provider_command")
    provider_list = provider_subparsers.add_parser("list")
    provider_list.add_argument("--json", action="store_true")
    provider_list.set_defaults(handler=_handle_provider_list)
    provider_show = provider_subparsers.add_parser("show")
    provider_show.add_argument("provider_id")
    provider_show.add_argument("--json", action="store_true")
    provider_show.set_defaults(handler=_handle_provider_show)
    provider_add = provider_subparsers.add_parser("add")
    provider_add.add_argument("provider_id")
    provider_add.add_argument("--name", required=True)
    provider_add.add_argument(
        "--protocol",
        required=True,
        choices=("openai_compatible", "anthropic_compatible", "gemini_compatible"),
    )
    provider_add.add_argument("--dialect", default=None)
    provider_add.add_argument("--base-url", required=True)
    provider_add.add_argument("--route-prefix", default=None)
    _add_provider_auth_arguments(provider_add, optional=False)
    _add_provider_model_arguments(provider_add)
    provider_add.add_argument("--offline", action="store_true")
    provider_add.add_argument("--disabled", action="store_true")
    provider_add.add_argument("--json", action="store_true")
    provider_add.set_defaults(handler=_handle_provider_add)
    provider_edit = provider_subparsers.add_parser("edit")
    provider_edit.add_argument("provider_id")
    provider_edit.add_argument("--expected-revision", type=int, required=True)
    provider_edit.add_argument("--name", default=None)
    provider_edit.add_argument(
        "--protocol",
        choices=("openai_compatible", "anthropic_compatible", "gemini_compatible"),
        default=None,
    )
    provider_edit.add_argument("--dialect", default=None)
    provider_edit.add_argument("--base-url", default=None)
    provider_edit.add_argument("--route-prefix", default=None)
    _add_provider_auth_arguments(provider_edit, optional=True)
    _add_provider_model_arguments(provider_edit)
    provider_edit.add_argument(
        "--enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    provider_edit.add_argument(
        "--offline",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    provider_edit.add_argument("--json", action="store_true")
    provider_edit.set_defaults(handler=_handle_provider_edit)
    for command, handler in (
        ("test", _handle_provider_test),
        ("discover", _handle_provider_discover),
    ):
        provider_probe = provider_subparsers.add_parser(command)
        provider_probe.add_argument("provider_id")
        provider_probe.add_argument("--json", action="store_true")
        provider_probe.set_defaults(handler=handler)
    provider_migrate = provider_subparsers.add_parser(
        "migrate-legacy", aliases=("migrate",)
    )
    provider_migrate.add_argument("--backup", default=None)
    provider_migrate.add_argument("--dry-run", action="store_true")
    provider_migrate.add_argument("--json", action="store_true")
    provider_migrate.set_defaults(handler=_handle_provider_migrate)

    integration = subparsers.add_parser("integration")
    integration_subparsers = integration.add_subparsers(dest="integration_command")
    integration_list = integration_subparsers.add_parser("list")
    integration_list.add_argument("--json", action="store_true")
    integration_list.set_defaults(handler=_handle_integration_list)
    integration_preview = integration_subparsers.add_parser("preview")
    integration_preview.add_argument(
        "--source",
        required=True,
        choices=("catalog", "marketplace", "git", "local", "package", "raw_descriptor"),
    )
    integration_preview.add_argument("--catalog-id")
    integration_preview.add_argument("--manifest")
    integration_preview.add_argument("--target", required=True)
    integration_preview.add_argument(
        "--scope",
        required=True,
        choices=("managed_home", "project", "user_home"),
    )
    integration_preview.add_argument("--workspace")
    integration_preview.add_argument("--package-id")
    integration_preview.add_argument("--configuration-json", default="{}")
    integration_preview.add_argument("--json", action="store_true")
    integration_preview.set_defaults(handler=_handle_integration_preview)
    integration_status = integration_subparsers.add_parser("status")
    integration_status.add_argument("flow_id")
    integration_status.add_argument("--json", action="store_true")
    integration_status.set_defaults(handler=_handle_integration_status)
    integration_apply = integration_subparsers.add_parser("apply")
    integration_apply.add_argument("flow_id")
    integration_apply.add_argument("--plan-id", required=True)
    integration_apply.add_argument("--authority", required=True)
    integration_apply.add_argument("--allow-network", action="store_true")
    integration_apply.add_argument("--allow-user-home", action="store_true")
    integration_apply.add_argument("--ack-native-consent", action="store_true")
    integration_apply.add_argument("--json", action="store_true")
    integration_apply.set_defaults(handler=_handle_integration_apply)
    integration_rollback = integration_subparsers.add_parser("rollback")
    integration_rollback.add_argument("flow_id")
    integration_rollback.add_argument("--json", action="store_true")
    integration_rollback.set_defaults(handler=_handle_integration_rollback)
    integration_group_preview = integration_subparsers.add_parser("group-preview")
    integration_group_preview.add_argument("--catalog-id", required=True)
    integration_group_preview.add_argument(
        "--scope",
        default="managed_home",
        choices=("managed_home", "project"),
    )
    integration_group_preview.add_argument("--workspace")
    integration_group_preview.add_argument("--configuration-json", default="{}")
    integration_group_preview.add_argument("--json", action="store_true")
    integration_group_preview.set_defaults(handler=_handle_integration_group_preview)
    integration_pack_preview = integration_subparsers.add_parser("pack-preview")
    integration_pack_preview.add_argument("--pack-id", required=True)
    integration_pack_preview.add_argument("--pack-version", required=True)
    integration_pack_preview.add_argument("--skill-catalog-id", required=True)
    integration_pack_preview.add_argument("--mcp-catalog-id", required=True)
    integration_pack_preview.add_argument(
        "--scope",
        default="managed_home",
        choices=("managed_home", "project"),
    )
    integration_pack_preview.add_argument("--workspace")
    integration_pack_preview.add_argument("--mcp-configuration-json", default="{}")
    integration_pack_preview.add_argument("--json", action="store_true")
    integration_pack_preview.set_defaults(handler=_handle_integration_pack_preview)
    integration_group_status = integration_subparsers.add_parser("group-status")
    integration_group_status.add_argument("group_id")
    integration_group_status.add_argument("--json", action="store_true")
    integration_group_status.set_defaults(handler=_handle_integration_group_status)
    integration_group_apply = integration_subparsers.add_parser("group-apply")
    integration_group_apply.add_argument("group_id")
    integration_group_apply.add_argument("--plan-id", required=True)
    integration_group_apply.add_argument("--authority", required=True)
    integration_group_apply.add_argument("--allow-network", action="store_true")
    integration_group_apply.add_argument("--allow-user-home", action="store_true")
    integration_group_apply.add_argument("--ack-native-consent", action="store_true")
    integration_group_apply.add_argument("--json", action="store_true")
    integration_group_apply.set_defaults(handler=_handle_integration_group_apply)
    for command, handler in (
        ("group-recover", _handle_integration_group_recover),
        ("group-rollback", _handle_integration_group_rollback),
    ):
        integration_group_action = integration_subparsers.add_parser(command)
        integration_group_action.add_argument("group_id")
        integration_group_action.add_argument("--json", action="store_true")
        integration_group_action.set_defaults(handler=handler)
    integration_scaffold = integration_subparsers.add_parser("scaffold")
    integration_scaffold.add_argument("package_id")
    integration_scaffold.add_argument("--output", type=Path, required=True)
    integration_scaffold.set_defaults(handler=_handle_integration_scaffold)
    integration_conformance = integration_subparsers.add_parser("conformance")
    integration_conformance.add_argument("manifest", type=Path)
    integration_conformance.add_argument(
        "--target-descriptor",
        action="append",
        default=[],
        type=Path,
    )
    integration_conformance.add_argument("--json", action="store_true")
    integration_conformance.set_defaults(handler=_handle_integration_conformance)

    init = subparsers.add_parser("init")
    init.add_argument("--workspace", default=None)
    init.add_argument("--name", default=None)
    init.add_argument("--overwrite", action="store_true")
    init.add_argument("--json", action="store_true")
    init.set_defaults(handler=_handle_project_init)

    chat = subparsers.add_parser("chat", parents=[common])
    chat.add_argument("--model", default=None)
    chat.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    chat.add_argument("--json", action="store_true")
    chat.add_argument("--dry-run", action="store_true")
    chat.add_argument("prompt", nargs="+")
    chat.set_defaults(handler=_handle_chat)

    ui = subparsers.add_parser("ui", parents=[common])
    ui.add_argument("--host", default=None)
    ui.add_argument("--port", type=int, default=None)
    ui.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Allow a non-loopback listener only with the complete single-issuer "
            "OIDC profile and deployment TLS/proxy controls"
        ),
    )
    ui.add_argument(
        "--start-worker",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start local durable workers until the target worker count is online",
    )
    ui.add_argument(
        "--worker-count",
        type=int,
        default=1,
        metavar="N",
        help="Target durable worker pool size when worker auto-start is enabled",
    )
    ui.set_defaults(handler=_handle_ui)
    ui_identity = subparsers.add_parser(
        "ui-identity",
        help="Validate or recover the deployment-owned remote UI identity boundary",
    )
    ui_identity_subparsers = ui_identity.add_subparsers(dest="ui_identity_command")
    ui_identity_validate = ui_identity_subparsers.add_parser("validate")
    ui_identity_validate.add_argument("--json", action="store_true")
    ui_identity_validate.set_defaults(handler=_handle_ui_identity_validate)
    ui_identity_revoke = ui_identity_subparsers.add_parser("revoke-all")
    ui_identity_revoke.add_argument("--confirm", action="store_true", required=True)
    ui_identity_revoke.add_argument("--json", action="store_true")
    ui_identity_revoke.set_defaults(handler=_handle_ui_identity_revoke_all)

    run = subparsers.add_parser("run", parents=[common])
    run.add_argument("--agent", choices=tuple(AGENT_ALIASES), default=None)
    run.add_argument("--mode", choices=("plan", "read", "edit"), default="plan")
    run.add_argument("--model", default=None)
    run.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    run.add_argument("--workspace", default=None)
    run.add_argument("--native", action="store_true")
    run.add_argument("--json", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("prompt", nargs="*")
    run.set_defaults(handler=_handle_run_command)

    session = subparsers.add_parser("session")
    session_subparsers = session.add_subparsers(dest="session_command")

    session_list = session_subparsers.add_parser("list", parents=[common])
    session_list.add_argument("--json", action="store_true")
    session_list.add_argument("--workspace", default=None)
    session_list.add_argument("--harness", dest="harness_id", default=None)
    session_list.add_argument("--include-archived", action="store_true")
    session_list.set_defaults(handler=_handle_session_list)

    session_show = session_subparsers.add_parser("show", parents=[common])
    session_show.add_argument("session_id")
    session_show.add_argument("--json", action="store_true")
    session_show.set_defaults(handler=_handle_session_show)

    session_create = session_subparsers.add_parser("create", parents=[common])
    session_create.add_argument("--title", default=None)
    session_create.add_argument("--workspace", default=None)
    session_create.add_argument("--harness", dest="harness_id", default=None)
    session_create.add_argument("--model", default=None)
    session_create.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    session_create.add_argument(
        "--mode", choices=("plan", "read", "edit"), default=None
    )
    session_create.add_argument("--json", action="store_true")
    session_create.set_defaults(handler=_handle_session_create)

    session_turn = session_subparsers.add_parser("turn", parents=[common])
    session_turn.add_argument("session_id")
    session_turn.add_argument("--prompt", required=True)
    session_turn.add_argument("--harness", dest="harness_id", default=None)
    session_turn.add_argument("--model", default=None)
    session_turn.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    session_turn.add_argument(
        "--capability",
        choices=tuple(capability.value for capability in HarnessCapability),
        default=None,
    )
    session_turn.add_argument("--mode", choices=("plan", "read", "edit"), default=None)
    session_turn.add_argument("--workspace", default=None)
    session_turn.add_argument("--permission-profile", default="interactive")
    session_turn.add_argument(
        "--transport",
        choices=("native_structured", "native_terminal", "one_shot"),
        default=None,
        help="Execution transport (default: backend Workbench setting)",
    )
    session_turn.add_argument("--idempotency-key", default=None)
    session_turn.add_argument("--json", action="store_true")
    session_turn.set_defaults(handler=_handle_session_turn)

    session_events = session_subparsers.add_parser("events")
    session_events.add_argument("run_id")
    session_events.add_argument("--after-id", default=None)
    session_events.add_argument("--json", action="store_true")
    session_events.set_defaults(handler=_handle_session_events)

    session_approve = session_subparsers.add_parser("approve")
    session_approve.add_argument("approval_id")
    session_approve.add_argument(
        "--decision",
        choices=tuple(decision.value for decision in ApprovalDecision),
        required=True,
    )
    session_approve.add_argument("--expires-in-seconds", type=float, default=None)
    session_approve.add_argument("--json", action="store_true")
    session_approve.set_defaults(handler=_handle_session_approve)

    runtime = subparsers.add_parser("runtime")
    runtime_subparsers = runtime.add_subparsers(dest="runtime_command")

    runtime_inspect = runtime_subparsers.add_parser("inspect")
    runtime_inspect.add_argument("--json", action="store_true")
    runtime_inspect.set_defaults(handler=_handle_runtime_inspect)

    runtime_export = runtime_subparsers.add_parser("export")
    runtime_export.add_argument("--output", default=None)
    runtime_export.set_defaults(handler=_handle_runtime_export)

    state = subparsers.add_parser("state")
    state_subparsers = state.add_subparsers(dest="state_command")

    state_backup = state_subparsers.add_parser("backup")
    state_backup.add_argument("--output", required=True)
    state_backup.add_argument("--json", action="store_true")
    state_backup.set_defaults(handler=_handle_state_backup)

    state_verify = state_subparsers.add_parser("verify")
    state_verify.add_argument("archive")
    state_verify.add_argument("--json", action="store_true")
    state_verify.set_defaults(handler=_handle_state_verify)

    state_restore = state_subparsers.add_parser("restore")
    state_restore.add_argument("archive")
    state_restore.add_argument("--destination", default=None)
    state_restore.add_argument("--replace", action="store_true")
    state_restore.add_argument("--json", action="store_true")
    state_restore.set_defaults(handler=_handle_state_restore)
    state_migrate_providers = state_subparsers.add_parser("migrate-providers")
    state_migrate_providers.add_argument("--backup", default=None)
    state_migrate_providers.add_argument("--dry-run", action="store_true")
    state_migrate_providers.add_argument("--json", action="store_true")
    state_migrate_providers.set_defaults(handler=_handle_provider_migrate)

    worker = subparsers.add_parser("worker", parents=[common])
    worker_subparsers = worker.add_subparsers(dest="worker_command")

    worker_start = worker_subparsers.add_parser("start", parents=[common])
    worker_start.add_argument("--once", action="store_true")
    worker_start.add_argument("--poll-seconds", type=float, default=0.25)
    worker_start.add_argument("--max-idle-seconds", type=float, default=1.0)
    worker_start.add_argument("--lease-seconds", type=float, default=15.0)
    worker_start.add_argument("--heartbeat-seconds", type=float, default=2.0)
    worker_start.set_defaults(handler=_handle_worker_start)

    worker_status_parser = worker_subparsers.add_parser("status")
    worker_status_parser.add_argument("--json", action="store_true")
    worker_status_parser.set_defaults(handler=_handle_worker_status)

    worker_idle = worker_subparsers.add_parser("stop-on-idle", parents=[common])
    worker_idle.add_argument("--idle-seconds", type=float, default=5.0)
    worker_idle.add_argument("--poll-seconds", type=float, default=0.25)
    worker_idle.add_argument("--max-idle-seconds", type=float, default=1.0)
    worker_idle.add_argument("--lease-seconds", type=float, default=15.0)
    worker_idle.add_argument("--heartbeat-seconds", type=float, default=2.0)
    worker_idle.set_defaults(handler=_handle_worker_stop_on_idle)

    benchmark = subparsers.add_parser("benchmark")
    benchmark_subparsers = benchmark.add_subparsers(dest="benchmark_command")
    benchmark_performance = benchmark_subparsers.add_parser("performance")
    benchmark_performance.add_argument(
        "--profile",
        choices=("ci-smoke", "local-detail", "tui-detail", "runtime-detail"),
        default="ci-smoke",
    )
    benchmark_performance.add_argument("--samples", type=int, default=5)
    benchmark_performance.add_argument(
        "--output",
        default=None,
        help="Atomically write a private canonical JSON report",
    )
    benchmark_performance.set_defaults(handler=_handle_benchmark_performance)

    schedule = subparsers.add_parser("schedule")
    schedule_subparsers = schedule.add_subparsers(dest="schedule_command")
    schedule_list = schedule_subparsers.add_parser("list")
    schedule_list.add_argument("--workspace", default=None)
    schedule_list.add_argument("--json", action="store_true")
    schedule_list.set_defaults(handler=_handle_schedule_list)
    schedule_show = schedule_subparsers.add_parser("show")
    schedule_show.add_argument("schedule_id")
    schedule_show.add_argument("--workspace", default=None)
    schedule_show.add_argument("--json", action="store_true")
    schedule_show.set_defaults(handler=_handle_schedule_show)
    for action in ("preview", "create", "update"):
        command = schedule_subparsers.add_parser(action)
        command.add_argument("definition")
        command.add_argument("--workspace", default=None)
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=_handle_schedule_write, schedule_action=action)
    for action in ("test-now", "enable", "pause", "resume", "run-now", "delete"):
        command = schedule_subparsers.add_parser(action)
        command.add_argument("schedule_id")
        command.add_argument("--workspace", default=None)
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=_handle_schedule_action, schedule_action=action)

    native = subparsers.add_parser("native")
    native_subparsers = native.add_subparsers(dest="native_command")

    native_sync = native_subparsers.add_parser("sync", parents=[common])
    native_sync.add_argument("--harness", dest="harness_id", default=None)
    native_sync.add_argument("--workspace", default=None)
    native_sync.add_argument("--include-external", action="store_true")
    native_sync.add_argument("--cursor", default=None)
    native_sync.add_argument("--limit", type=int, default=100)
    native_sync.add_argument("--json", action="store_true")
    native_sync.set_defaults(handler=_handle_native_sync)

    native_list = native_subparsers.add_parser("list", parents=[common])
    native_list.add_argument("--harness", dest="harness_id", default=None)
    native_list.add_argument("--workspace", default=None)
    native_list.add_argument("--include-external", action="store_true")
    native_list.add_argument(
        "--status",
        choices=tuple(status.value for status in NativeSessionStatus),
        default=None,
    )
    native_list.add_argument("--limit", type=int, default=100)
    native_list.add_argument("--json", action="store_true")
    native_list.set_defaults(handler=_handle_native_list)

    native_import = native_subparsers.add_parser("import", parents=[common])
    native_import.add_argument("native_ref_id")
    native_import.add_argument("--json", action="store_true")
    native_import.set_defaults(handler=_handle_native_import)

    project = subparsers.add_parser("project")
    project_subparsers = project.add_subparsers(dest="project_command")

    project_info = project_subparsers.add_parser("info")
    project_info.add_argument("--workspace", default=None)
    project_info.add_argument("--json", action="store_true")
    project_info.set_defaults(handler=_handle_project_info)

    project_init = project_subparsers.add_parser("init")
    project_init.add_argument("--workspace", default=None)
    project_init.add_argument("--name", default=None)
    project_init.add_argument("--overwrite", action="store_true")
    project_init.add_argument("--json", action="store_true")
    project_init.set_defaults(handler=_handle_project_init)

    preset = subparsers.add_parser("preset")
    preset_subparsers = preset.add_subparsers(dest="preset_command")

    preset_list = preset_subparsers.add_parser("list")
    preset_list.add_argument("--workspace", default=None)
    preset_list.add_argument("--json", action="store_true")
    preset_list.set_defaults(handler=_handle_preset_list)

    preset_run = preset_subparsers.add_parser("run", parents=[common])
    preset_run.add_argument("preset_name")
    preset_run.add_argument("--workspace", default=None)
    preset_run.add_argument("--prompt", default=None)
    preset_run.add_argument("--selected-file", action="append", default=[])
    preset_run.add_argument("--last-run-diff", default=None)
    preset_run.add_argument("--model", default=None)
    preset_run.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    preset_run.add_argument("--mode", choices=("plan", "read", "edit"), default=None)
    preset_run.add_argument("--native", action="store_true")
    preset_run.add_argument("--json", action="store_true")
    preset_run.add_argument("--dry-run", action="store_true")
    preset_run.set_defaults(handler=_handle_preset_run)

    memory = subparsers.add_parser("memory")
    memory_subparsers = memory.add_subparsers(dest="memory_command")

    memory_list = memory_subparsers.add_parser("list")
    memory_list.add_argument("--workspace", default=None)
    memory_list.add_argument("--include-disabled", action="store_true")
    memory_list.add_argument("--json", action="store_true")
    memory_list.set_defaults(handler=_handle_memory_list)

    memory_add = memory_subparsers.add_parser("add")
    memory_add.add_argument("text", nargs="+")
    memory_add.add_argument("--workspace", default=None)
    memory_add.add_argument("--tag", action="append", default=[])
    memory_add.add_argument("--session-id", default=None)
    memory_add.add_argument("--run-id", default=None)
    memory_add.add_argument("--disabled", action="store_true")
    memory_add.add_argument("--json", action="store_true")
    memory_add.set_defaults(handler=_handle_memory_add)

    memory_disable = memory_subparsers.add_parser("disable")
    memory_disable.add_argument("memory_id")
    memory_disable.add_argument("--workspace", default=None)
    memory_disable.add_argument("--json", action="store_true")
    memory_disable.set_defaults(handler=_handle_memory_disable)

    memory_enable = memory_subparsers.add_parser("enable")
    memory_enable.add_argument("memory_id")
    memory_enable.add_argument("--workspace", default=None)
    memory_enable.add_argument("--json", action="store_true")
    memory_enable.set_defaults(handler=_handle_memory_enable)

    memory_delete = memory_subparsers.add_parser("delete")
    memory_delete.add_argument("memory_id")
    memory_delete.add_argument("--workspace", default=None)
    memory_delete.add_argument("--json", action="store_true")
    memory_delete.set_defaults(handler=_handle_memory_delete)

    eval_parser = subparsers.add_parser("eval")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command")

    eval_list = eval_subparsers.add_parser("list")
    eval_list.add_argument("--workspace", default=None)
    eval_list.add_argument("--json", action="store_true")
    eval_list.set_defaults(handler=_handle_eval_list)

    eval_run = eval_subparsers.add_parser("run", parents=[common])
    eval_run.add_argument("eval_name")
    eval_run.add_argument("--workspace", default=None)
    eval_run.add_argument(
        "--harness",
        action="append",
        default=[],
        help="Comma-separated harness ids; can be repeated.",
    )
    eval_run.add_argument("--model", default=None)
    eval_run.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    eval_run.add_argument("--mode", choices=("plan", "read", "edit"), default=None)
    eval_run.add_argument(
        "--workspace-policy",
        choices=("auto", "current", "worktree", "temp_copy"),
        default=None,
    )
    eval_run.add_argument("--dry-run", action="store_true")
    eval_run.add_argument("--json", action="store_true")
    eval_run.set_defaults(handler=_handle_eval_run)

    agent = subparsers.add_parser("agent")
    agent_subparsers = agent.add_subparsers(dest="agent_command")

    agent_list = agent_subparsers.add_parser("list")
    agent_list.add_argument("--workspace", default=None)
    agent_list.add_argument("--json", action="store_true")
    agent_list.set_defaults(handler=_handle_agent_list)

    agent_show = agent_subparsers.add_parser("show")
    agent_show.add_argument("agent_id")
    agent_show.add_argument("--workspace", default=None)
    agent_show.add_argument("--json", action="store_true")
    agent_show.set_defaults(handler=_handle_agent_show)

    agent_validate = agent_subparsers.add_parser("validate")
    agent_validate.add_argument("path")
    agent_validate.add_argument("--json", action="store_true")
    agent_validate.set_defaults(handler=_handle_agent_validate)

    agent_run = agent_subparsers.add_parser("run", parents=[common])
    agent_run.add_argument("agent_id")
    agent_run.add_argument("--workspace", default=None)
    agent_run.add_argument("--prompt", required=True)
    agent_run.add_argument("--dry-run", action="store_true")
    agent_run.add_argument("--json", action="store_true")
    agent_run.set_defaults(handler=_handle_agent_profile_run)

    workflow = subparsers.add_parser("workflow")
    workflow_subparsers = workflow.add_subparsers(dest="workflow_command")

    workflow_list = workflow_subparsers.add_parser("list")
    workflow_list.add_argument("--workspace", default=None)
    workflow_list.add_argument("--json", action="store_true")
    workflow_list.set_defaults(handler=_handle_workflow_list)

    workflow_show = workflow_subparsers.add_parser("show")
    workflow_show.add_argument("workflow_id")
    workflow_show.add_argument("--workspace", default=None)
    workflow_show.add_argument("--json", action="store_true")
    workflow_show.set_defaults(handler=_handle_workflow_show)

    workflow_validate = workflow_subparsers.add_parser("validate")
    workflow_validate.add_argument("path")
    workflow_validate.add_argument("--json", action="store_true")
    workflow_validate.set_defaults(handler=_handle_workflow_validate)

    workflow_run = workflow_subparsers.add_parser("run", parents=[common])
    workflow_run.add_argument("workflow_id")
    workflow_run.add_argument("--workspace", default=None)
    workflow_run.add_argument("--prompt", default=None)
    workflow_run.add_argument("--input", action="append", default=[])
    workflow_run.add_argument("--dry-run", action="store_true")
    workflow_run.add_argument("--json", action="store_true")
    workflow_run.set_defaults(handler=_handle_workflow_run)

    workflow_status = workflow_subparsers.add_parser("status", parents=[common])
    workflow_status.add_argument("run_id")
    workflow_status.add_argument("--json", action="store_true")
    workflow_status.set_defaults(handler=_handle_workflow_status)

    workflow_cancel = workflow_subparsers.add_parser("cancel", parents=[common])
    workflow_cancel.add_argument("run_id")
    workflow_cancel.add_argument("--json", action="store_true")
    workflow_cancel.set_defaults(handler=_handle_workflow_cancel)

    open_parser = subparsers.add_parser("open")
    open_subparsers = open_parser.add_subparsers(dest="open_command")

    open_session = open_subparsers.add_parser("session")
    open_session.add_argument("session_id")
    open_session.add_argument("--dry-run", action="store_true")
    open_session.add_argument("--json", action="store_true")
    open_session.set_defaults(handler=_handle_open_session)

    open_run = open_subparsers.add_parser("run")
    open_run.add_argument("run_id")
    open_run_target = open_run.add_mutually_exclusive_group()
    open_run_target.add_argument("--diff", action="store_true")
    open_run_target.add_argument("--terminal", action="store_true")
    open_run.add_argument("--dry-run", action="store_true")
    open_run.add_argument("--json", action="store_true")
    open_run.set_defaults(handler=_handle_open_run)

    open_file = open_subparsers.add_parser("file")
    open_file.add_argument("path")
    open_file.add_argument("--workspace", default=None)
    open_file.add_argument("--line", type=int, default=None)
    open_file.add_argument("--column", type=int, default=None)
    open_file.add_argument("--dry-run", action="store_true")
    open_file.add_argument("--json", action="store_true")
    open_file.set_defaults(handler=_handle_open_file)

    harness = subparsers.add_parser("harness")
    harness_subparsers = harness.add_subparsers(dest="harness_command")

    harness_list = harness_subparsers.add_parser("list", parents=[common])
    harness_list.add_argument("--json", action="store_true")
    harness_list.set_defaults(handler=_handle_harness_list)

    harness_capabilities = harness_subparsers.add_parser("capabilities")
    harness_capabilities.add_argument("--json", action="store_true")
    harness_capabilities.add_argument(
        "--agents",
        action="store_true",
        help="Show Direct Chat and coding-agent behavior contracts",
    )
    harness_capabilities.add_argument(
        "--inventory",
        action="store_true",
        help="Show the complete versioned product truth inventory",
    )
    harness_capabilities.add_argument(
        "--check",
        action="store_true",
        help="Fail when the packaged inventory, docs, or contract evidence drift",
    )
    harness_capabilities.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write canonical inventory JSON to this path",
    )
    harness_capabilities.set_defaults(handler=_handle_harness_capabilities)

    harness_inspect = harness_subparsers.add_parser("inspect", parents=[common])
    harness_inspect.add_argument("harness_id")
    harness_inspect.add_argument("--json", action="store_true")
    harness_inspect.set_defaults(handler=_handle_harness_inspect)

    harness_validate = harness_subparsers.add_parser("validate")
    harness_validate.add_argument("harness_id")
    harness_validate.add_argument("--json", action="store_true")
    harness_validate.set_defaults(handler=_handle_harness_validate)

    harness_run = harness_subparsers.add_parser("run", parents=[common])
    harness_run.add_argument("harness_id")
    harness_run.add_argument("--prompt", required=True)
    harness_run.add_argument("--model", default=None)
    harness_run.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    harness_run.add_argument(
        "--capability",
        choices=tuple(capability.value for capability in HarnessCapability),
        default=HarnessCapability.CHAT_COMPLETIONS.value,
    )
    harness_run.add_argument("--mode", choices=("plan", "read", "edit"), default="plan")
    harness_run.add_argument("--workspace", default=None)
    harness_run.add_argument("--native", action="store_true")
    harness_run.add_argument("--json", action="store_true")
    harness_run.add_argument("--dry-run", action="store_true")
    harness_run.set_defaults(handler=_handle_harness_run)

    harness_scaffold = harness_subparsers.add_parser("scaffold")
    harness_scaffold.add_argument("harness_id")
    harness_scaffold.add_argument("--output", type=Path, default=None)
    harness_scaffold.set_defaults(handler=_handle_harness_scaffold)

    harness_conformance = harness_subparsers.add_parser("conformance")
    harness_conformance.add_argument("harness_id")
    harness_conformance.add_argument("--json", action="store_true")
    harness_conformance.set_defaults(handler=_handle_harness_conformance)

    return parser


def _handle_doctor(args: argparse.Namespace, config: HarnessConfig) -> int:
    report = build_doctor_report(config, workspace=args.workspace)
    if args.output is not None:
        write_doctor_support_report(report, args.output)
    if args.json:
        _print_json(report)
    else:
        print(format_doctor_report(report))
    summary = report.get("summary") or {}
    blocked = int(summary.get("blocked") or 0)
    degraded = int(summary.get("degraded") or 0)
    if args.fail_on == "blocked" and blocked:
        return 1
    if args.fail_on == "degraded" and (blocked or degraded):
        return 1
    return 0


def _handle_bootstrap_preview(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = BootstrapService(config).preview(workspace=args.workspace)
    _print_bootstrap(payload, as_json=args.json)
    return 0


def _handle_bootstrap_apply(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = BootstrapService(config).apply(
        plan_id=args.plan_id,
        selected_steps=tuple(args.step),
        all_reversible=args.all_reversible,
        workspace=args.workspace,
    )
    _print_bootstrap(payload, as_json=args.json)
    return 0


def _handle_bootstrap_status(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = BootstrapService(config).status(args.application_id)
    _print_bootstrap(payload, as_json=args.json)
    return 0


def _handle_bootstrap_rollback(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = BootstrapService(config).rollback(
        args.application_id,
        workspace=args.workspace,
    )
    _print_bootstrap(payload, as_json=args.json)
    return 0


def _handle_compatibility_check(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    del config
    report = run_compatibility_guardian(
        create_default_registry(),
        harness_ids=tuple(args.harness) or None,
    )
    if args.json:
        _print_json(report)
    else:
        print(
            "Compatibility guardian: "
            f"{report['status']} ({report['summary']['passed']} passed, "
            f"{report['summary']['blocked']} blocked)"
        )
        for fixture in report["fixtures"]:
            print(
                f"- {fixture['id']}: {fixture['status']} "
                f"({fixture['category']}/{fixture['code']})"
            )
    return 0 if report["ok"] else 1


def _handle_handoff_capsule(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    store = FilesystemHarnessSessionStore(config.data_dir)
    service = HandoffCapsuleService(
        store=store,
        registry=create_default_registry(),
        runtime_store=RuntimeCoordinationStore(config.data_dir),
    )
    capsule = service.build(args.run_id, args.target_harness)
    if args.json:
        _print_json({"capsule": capsule})
    else:
        summary = capsule["summary"]
        provenance = capsule["provenance"]
        print(
            "Handoff capsule: "
            f"{capsule['capsule_id']} "
            f"({provenance['source']['harness_id']} -> "
            f"{provenance['target']['harness_id']})"
        )
        print(
            f"Artifacts: {summary['artifact_count']}; "
            f"pending approvals: {summary['pending_approval_count']}; "
            f"unresolved questions: {summary['unresolved_question_count']}"
        )
        print(
            "Continuity: evidence handoff only; native session identity is not moved."
        )
    return 0


def _handle_completion(args: argparse.Namespace, config: HarnessConfig) -> int:
    del config
    print(render_completion(args.shell), end="")
    return 0


def _handle_project_info(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = _project_payload(
        workspace=args.workspace,
        config=config,
        load_config_name=True,
    )
    if args.json:
        _print_json(payload)
    else:
        project = payload["project"]
        defaults = payload["defaults"]
        print(f"Project: {project['name']} ({project['id']})")
        print(f"Root: {project['root']}")
        if project["git_branch"]:
            print(f"Branch: {project['git_branch']}")
        print(f"Config: {payload['config']['path']}")
        print(f"Config exists: {payload['config']['exists']}")
        print(
            "Defaults: "
            f"{defaults['harness']} / {defaults['model']} / "
            f"{defaults['api_mode']} / {defaults['mode']}"
        )
    return 0


def _handle_project_init(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    existed = project_config_path(project.root).exists()
    loaded = init_project_config(
        project.root,
        project_name=args.name,
        overwrite=args.overwrite,
    )
    payload = _project_payload(
        workspace=project.root,
        config=config,
        load_config_name=True,
    )
    if args.json:
        _print_json(payload)
    else:
        action = "Updated" if existed and args.overwrite else "Using existing"
        if not existed:
            action = "Initialized"
        print(f"{action} project config: {loaded.path}")
        print(f"Project: {payload['project']['name']} ({payload['project']['id']})")
    return 0


def _handle_harness_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    registry = create_default_registry()
    rows = []
    for harness in registry.list():
        spec = harness.spec()
        spec_payload = spec_to_dict(spec)
        availability = harness.availability()
        validation = registry.validation_report(spec.id) or validate_harness_spec(spec)
        rows.append(
            {
                "id": spec_payload["id"],
                "kind": spec_payload["kind"],
                "status": availability.status.value,
                "native": spec_payload["supports_native_sessions"],
                "default_invocation_mode": spec_payload["default_invocation_mode"],
                "workbench_transport": workbench_transport_projection(harness),
                "description": spec_payload["description"],
                "plugin_metadata": spec_payload["plugin_metadata"],
                "validation": harness_validation_report_to_dict(validation),
            }
        )
    if args.json:
        _print_json(rows)
    else:
        _print_table(rows)
    return 0


def _handle_harness_capabilities(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    registry = create_default_registry(include_entry_points=False)
    if args.agents and args.inventory:
        print(
            "product inventory: --agents and --inventory are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    if args.inventory:
        with tempfile.TemporaryDirectory(prefix="gigaloom-product-inventory-") as root:
            app = create_app(
                HarnessConfig(data_dir=root),
                registry=registry,
            )
            inventory = build_product_inventory(
                registry,
                cli_parser=build_parser(),
                api_routes=app.routes,
            )
        if args.check:
            errors = validate_product_inventory(
                inventory,
                repository_root=Path.cwd(),
            )
            if errors:
                for error in errors:
                    print(f"product inventory: {error}", file=sys.stderr)
                return 1
        payload = canonical_inventory_json(inventory)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        if args.json or (not args.check and args.output is None):
            print(payload, end="")
        return 0
    if args.check or args.output is not None:
        print(
            "product inventory: --check and --output require --inventory",
            file=sys.stderr,
        )
        return 2
    if args.agents:
        matrix = load_product_inventory()["agent_surface_capability_matrix"]
        renderer = render_agent_surface_capability_matrix_markdown
    else:
        matrix = build_adapter_capability_matrix(registry)
        renderer = render_adapter_capability_matrix_markdown
    if args.json:
        _print_json(matrix)
    else:
        print(renderer(matrix), end="")
    return 0


def _handle_config_path(args: argparse.Namespace, config: HarnessConfig) -> int:
    print(user_config_path())
    return 0


def _handle_config_set(args: argparse.Namespace, config: HarnessConfig) -> int:
    harness_id = _executable_config_harness_id(args.key)
    path = set_user_executable(
        harness_id,
        args.value,
        config_path=user_config_path(),
    )
    print(f"Updated {args.key} in {path}")
    return 0


def _handle_config_unset(args: argparse.Namespace, config: HarnessConfig) -> int:
    harness_id = _executable_config_harness_id(args.key)
    path, removed = unset_user_executable(
        harness_id,
        config_path=user_config_path(),
    )
    if removed:
        print(f"Removed {args.key} from {path}")
    else:
        print(f"No override configured for {args.key} in {path}")
    return 0


def _handle_integration_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = IntegrationFlowService(config.data_dir).inventory()
    if args.json:
        _print_json(payload)
    else:
        print(
            "Integration sources: "
            + ", ".join(item["id"] for item in payload["sources"])
        )
        print(f"Targets: {len(payload['targets'])}")
        print(f"Catalog entries: {len(payload['catalog'])}")
        print(f"Recent flows: {len(payload['flows'])}")
    return 0


def _handle_integration_preview(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    try:
        configuration = json.loads(args.configuration_json)
    except json.JSONDecodeError as exc:
        raise ValueError("configuration-json must be valid JSON") from exc
    manifest = None
    if args.manifest:
        try:
            manifest = json.loads(
                Path(args.manifest).expanduser().read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("manifest must be a readable JSON object") from exc
    payload = IntegrationFlowService(config.data_dir).preview(
        {
            "source": args.source,
            "catalog_id": args.catalog_id,
            "manifest": manifest,
            "target_id": args.target,
            "scope": args.scope,
            "workspace": args.workspace,
            "package_id": args.package_id,
            "configuration": configuration,
        }
    )
    if args.json:
        _print_json(payload)
    else:
        plan = payload["plan"]
        print(f"Flow: {payload['flow']['id']}")
        print(f"Plan: {plan['plan_id']}")
        print(f"Package: {plan['package']['id']}@{plan['package']['version']}")
        print(f"Target: {plan['target']['id']} ({plan['target']['scope']})")
        print(f"Risk: {plan['risk']['decision']}")
        print(
            "Next: integration apply "
            f"{payload['flow']['id']} --plan-id {plan['plan_id']} "
            "--authority <operator>"
        )
    return 0


def _handle_integration_status(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = {
        "flow": integration_flow_record_to_dict(
            IntegrationFlowService(config.data_dir).get(args.flow_id)
        )
    }
    if args.json:
        _print_json(payload)
    else:
        flow = payload["flow"]
        print(f"Flow: {flow['id']}")
        print(f"Status: {flow['status']}")
        print(f"Verification: {flow['verification_status']}")
    return 0


def _handle_integration_apply(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = IntegrationFlowService(config.data_dir).apply(
        args.flow_id,
        plan_id=args.plan_id,
        authority=args.authority,
        allow_network=args.allow_network,
        allow_user_home=args.allow_user_home,
        native_consent_acknowledged=args.ack_native_consent,
    )
    if args.json:
        _print_json(payload)
    else:
        print(f"Flow: {payload['flow']['id']}")
        print(f"Status: {payload['flow']['status']}")
        print(f"Verification: {payload['flow']['verification_status']}")
    return 0


def _handle_integration_rollback(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = IntegrationFlowService(config.data_dir).rollback(args.flow_id)
    if args.json:
        _print_json(payload)
    else:
        print(f"Flow: {payload['flow']['id']}")
        print(f"Status: {payload['flow']['status']}")
    return 0


def _handle_integration_group_preview(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    try:
        configuration = json.loads(args.configuration_json)
    except json.JSONDecodeError as exc:
        raise ValueError("configuration-json must be valid JSON") from exc
    payload = GroupedIntegrationService(config.data_dir).preview(
        {
            "source": "catalog",
            "catalog_id": args.catalog_id,
            "scope": args.scope,
            "workspace": args.workspace,
            "configuration": configuration,
            "target_mode": "all_supported",
        }
    )
    if args.json:
        _print_json(payload)
    else:
        print(f"Group: {payload['group']['id']}")
        print(f"Plan: {payload['plan']['plan_id']}")
        print("Targets: " + ", ".join(payload["plan"]["target_ids"]))
        print(
            "Next: integration group-apply "
            f"{payload['group']['id']} --plan-id {payload['plan']['plan_id']} "
            "--authority <operator>"
        )
    return 0


def _handle_integration_pack_preview(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    try:
        mcp_configuration = json.loads(args.mcp_configuration_json)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP configuration JSON is invalid") from exc
    payload = GroupedIntegrationService(config.data_dir).preview(
        {
            "component": "extension_pack",
            "pack_id": args.pack_id,
            "pack_version": args.pack_version,
            "skill_catalog_id": args.skill_catalog_id,
            "mcp_catalog_id": args.mcp_catalog_id,
            "scope": args.scope,
            "workspace": args.workspace,
            "target_mode": "all_supported",
            "mcp_configuration": mcp_configuration,
        }
    )
    if args.json:
        _print_json(payload)
    else:
        print(f"Pack: {payload['plan']['package']['id']}")
        print(f"Group: {payload['group']['id']}")
        print(f"Plan: {payload['plan']['plan_id']}")
        for item in payload["plan"]["compatibility"]:
            included = "included" if item["included"] else "excluded"
            print(f"Compatibility: {item['target']} {item['status']} ({included})")
        print(
            "Next: integration group-apply "
            f"{payload['group']['id']} --plan-id {payload['plan']['plan_id']} "
            "--authority <operator>"
        )
    return 0


def _handle_integration_group_status(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = {
        "group": integration_group_record_to_dict(
            GroupedIntegrationService(config.data_dir).get(args.group_id)
        )
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Group: {payload['group']['id']}")
        print(f"Status: {payload['group']['status']}")
    return 0


def _handle_integration_group_apply(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = GroupedIntegrationService(config.data_dir).apply(
        args.group_id,
        plan_id=args.plan_id,
        authority=args.authority,
        allow_network=args.allow_network,
        allow_user_home=args.allow_user_home,
        native_consent_acknowledged=args.ack_native_consent,
    )
    return _print_group_result(payload, json_output=args.json)


def _handle_integration_group_recover(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = GroupedIntegrationService(config.data_dir).recover(args.group_id)
    return _print_group_result(payload, json_output=args.json)


def _handle_integration_group_rollback(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    payload = GroupedIntegrationService(config.data_dir).rollback(args.group_id)
    return _print_group_result(payload, json_output=args.json)


def _print_group_result(payload: dict[str, Any], *, json_output: bool) -> int:
    if json_output:
        _print_json(payload)
    else:
        print(f"Group: {payload['group']['id']}")
        print(f"Status: {payload['group']['status']}")
        if payload["group"]["repair_actions"]:
            print("Repair: " + ", ".join(payload["group"]["repair_actions"]))
    return 0


def _handle_integration_scaffold(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    try:
        result = scaffold_integration_package(args.package_id, args.output)
    except FileExistsError as exc:
        raise ValueError(str(exc)) from exc
    print(f"Created integration scaffold: {result.root}")
    return 0


def _handle_integration_conformance(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    package = load_integration_package_document(args.manifest)
    descriptors = tuple(
        load_extension_target_document(path) for path in args.target_descriptor
    )
    report = run_integration_conformance(
        package,
        target_descriptors=descriptors,
    )
    payload = integration_conformance_report_to_dict(report)
    if args.json:
        _print_json(payload)
    else:
        print(
            f"Integration {report.package_id} {report.package_version}: "
            f"{'passed' if report.ok else 'failed'}"
        )
        for result in report.results:
            print(f"- {result.claim}: {result.status} ({result.detail})")
    return 0 if report.ok else 1


def _handle_provider_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = ProviderSettingsService(config.data_dir).list()
    if args.json:
        _print_json(payload)
    else:
        _print_provider_table(payload["providers"])
    return 0


def _handle_provider_show(args: argparse.Namespace, config: HarnessConfig) -> int:
    provider = ProviderSettingsService(config.data_dir).get(args.provider_id)
    if args.json:
        _print_json(provider)
    else:
        _print_provider_detail(provider)
    return 0


def _handle_provider_add(args: argparse.Namespace, config: HarnessConfig) -> int:
    service = ProviderSettingsService(config.data_dir)
    result = service.create(
        args.provider_id,
        _provider_payload_from_args(args, create=True),
    )
    if args.json:
        _print_json(
            {"saved": True, "provider": result.provider, "effects": result.effects}
        )
    else:
        _print_provider_detail(result.provider)
    return 0


def _handle_provider_edit(args: argparse.Namespace, config: HarnessConfig) -> int:
    service = ProviderSettingsService(config.data_dir)
    result = service.update(
        args.provider_id,
        _provider_payload_from_args(args, create=False),
        expected_revision=args.expected_revision,
    )
    if args.json:
        _print_json(
            {"saved": True, "provider": result.provider, "effects": result.effects}
        )
    else:
        _print_provider_detail(result.provider)
    return 0


def _handle_provider_test(args: argparse.Namespace, config: HarnessConfig) -> int:
    return _handle_provider_probe(args, config, discover_models=False)


def _handle_provider_discover(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    return _handle_provider_probe(args, config, discover_models=True)


def _handle_provider_probe(
    args: argparse.Namespace,
    config: HarnessConfig,
    *,
    discover_models: bool,
) -> int:
    payload = ProviderSettingsService(config.data_dir).check(
        args.provider_id,
        discover_models=discover_models,
    )
    if args.json:
        _print_json(payload)
    else:
        health = payload["health"]
        print(f"Provider: {payload['provider_id']}")
        print(f"Health: {health['status']}")
        print(f"Discovery: {health['discovery_status']}")
        if health["failure_kind"]:
            print(
                f"Failure: {health['failure_kind']} ({health['reason_code']})",
                file=sys.stderr,
            )
        for model in health["models"]:
            print(f"- {model['model']} [{model['source']}]")
    return 0 if payload["health"]["status"] == "ready" else 1


def _handle_provider_migrate(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    service = ProviderMigrationService(config.data_dir, config)
    if args.dry_run:
        payload = service.plan().to_dict()
    else:
        if args.backup is None:
            raise ValueError("provider migration requires --backup or --dry-run")
        payload = service.migrate(args.backup).to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"Provider migration: {payload['status']}")
        print(f"Providers: {', '.join(payload['provider_ids'])}")
        print(f"Routes: {payload['route_count']}")
        if payload.get("applied"):
            print(f"Pre-upgrade backup SHA-256: {payload['backup_sha256']}")
        print("Rollback: stop Harness and restore the verified pre-upgrade archive.")
    return 0


def _provider_payload_from_args(
    args: argparse.Namespace,
    *,
    create: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for argument, field in (
        ("name", "display_name"),
        ("protocol", "protocol"),
        ("dialect", "dialect"),
        ("base_url", "base_url"),
        ("route_prefix", "route_prefix"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    authentication = getattr(args, "authentication", None)
    auth_values = {
        "ownership": authentication,
        "reference_kind": getattr(args, "secret_reference_kind", None),
        "reference_name": getattr(args, "secret_reference_name", None),
        "service": getattr(args, "keychain_service", None),
        "account": getattr(args, "keychain_account", None),
    }
    if create or any(value is not None for value in auth_values.values()):
        payload["authentication"] = {
            key: value for key, value in auth_values.items() if value is not None
        }
    defaults = {
        purpose: getattr(args, f"{purpose}_model", None)
        for purpose in ("coding", "title", "evaluation", "fallback")
    }
    if any(value is not None for value in defaults.values()):
        payload["default_models"] = {
            purpose: value for purpose, value in defaults.items() if value is not None
        }
    if create:
        payload["enabled"] = not args.disabled
        payload["offline"] = args.offline
    else:
        if args.enabled is not None:
            payload["enabled"] = args.enabled
        if args.offline is not None:
            payload["offline"] = args.offline
    return payload


def _add_provider_auth_arguments(
    parser: argparse.ArgumentParser,
    *,
    optional: bool,
) -> None:
    parser.add_argument(
        "--authentication",
        choices=("secret_reference", "provider_native", "none"),
        default=None if optional else "secret_reference",
    )
    parser.add_argument(
        "--secret-reference-kind",
        choices=("environment", "keychain"),
        default=None if optional else "environment",
    )
    parser.add_argument("--secret-reference-name", default=None)
    parser.add_argument("--keychain-service", default=None)
    parser.add_argument("--keychain-account", default=None)


def _add_provider_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--coding-model", default=None)
    parser.add_argument("--title-model", default=None)
    parser.add_argument("--evaluation-model", default=None)
    parser.add_argument("--fallback-model", default=None)


def _handle_harness_inspect(args: argparse.Namespace, config: HarnessConfig) -> int:
    registry = create_default_registry()
    harness = registry.get(args.harness_id)
    spec = harness.spec()
    validation = registry.validation_report(args.harness_id) or validate_harness_spec(
        spec
    )
    payload = {
        "spec": spec_to_dict(spec),
        "availability": availability_to_dict(harness.availability()),
        "workbench_transport": workbench_transport_projection(harness),
        "validation": harness_validation_report_to_dict(validation),
    }
    resolution = getattr(harness, "executable_resolution", None)
    if callable(resolution):
        payload.update(executable_resolution_to_dict(resolution()))
    capability_probe = getattr(harness, "capability_probe", None)
    if callable(capability_probe):
        payload["compatibility"] = cli_capability_snapshot_to_dict(capability_probe())
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _handle_harness_validate(args: argparse.Namespace, config: HarnessConfig) -> int:
    registry = create_default_registry()
    harness = registry.get(args.harness_id)
    spec = harness.spec()
    report = registry.validation_report(args.harness_id) or validate_harness_spec(spec)
    payload = {
        "spec": spec_to_dict(spec),
        "validation": harness_validation_report_to_dict(report),
    }
    if args.json:
        _print_json(payload)
    else:
        status = "ok" if report.ok else "failed"
        print(f"Harness validation {status}: {args.harness_id}")
        for issue in report.issues:
            field = f" {issue.field}:" if issue.field else ""
            print(f"- {issue.level}{field} {issue.message}")
    return 0 if report.ok else 1


def _executable_config_harness_id(key: str) -> str:
    prefix = "executables."
    if not key.startswith(prefix) or len(key) == len(prefix):
        raise ValueError("Config key must use executables.<harness-id>")
    return key[len(prefix) :]


def _handle_harness_run(args: argparse.Namespace, config: HarnessConfig) -> int:
    result = _run_harness(
        harness_id=args.harness_id,
        prompt=args.prompt,
        model=args.model,
        api_mode=args.api_mode,
        capability=args.capability,
        mode=args.mode,
        workspace=args.workspace,
        dry_run=args.dry_run,
        native=args.native,
        config=config,
    )
    _print_result(result, as_json=args.json)
    return 0 if result.ok else 1


def _handle_chat(args: argparse.Namespace, config: HarnessConfig) -> int:
    result = _run_harness(
        harness_id="direct-chat",
        prompt=" ".join(args.prompt),
        model=args.model,
        api_mode=args.api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS.value,
        mode="plan",
        workspace=None,
        dry_run=args.dry_run,
        native=False,
        config=config,
    )
    _print_result(result, as_json=args.json)
    return 0 if result.ok else 1


def _handle_run_command(args: argparse.Namespace, config: HarnessConfig) -> int:
    action = args.prompt[0] if args.prompt else None
    if args.agent is None and action in {"patch", "pr-summary", "provenance", "replay"}:
        return _handle_run_artifact(args, config)
    if args.agent is None:
        print(
            "giga run requires --agent codex|claude|gemini or "
            "patch|pr-summary|provenance|replay <run_id>",
            file=sys.stderr,
        )
        return 2
    if not args.prompt:
        print("giga run --agent requires a prompt", file=sys.stderr)
        return 2
    return _handle_agent_alias(args, config)


def _handle_agent_alias(args: argparse.Namespace, config: HarnessConfig) -> int:
    harness_id = AGENT_ALIASES[args.agent]
    result = _run_harness(
        harness_id=harness_id,
        prompt=" ".join(args.prompt),
        model=args.model,
        api_mode=args.api_mode,
        capability=HarnessCapability.AGENT_CLI.value,
        mode=args.mode,
        workspace=args.workspace,
        dry_run=args.dry_run,
        native=args.native,
        config=config,
    )
    _print_result(result, as_json=args.json)
    return 0 if result.ok else 1


def _handle_run_artifact(args: argparse.Namespace, config: HarnessConfig) -> int:
    if len(args.prompt) != 2:
        print(f"Usage: giga run {args.prompt[0]} <run_id>", file=sys.stderr)
        return 2
    action, run_id = args.prompt
    store = FilesystemHarnessSessionStore(config.data_dir)
    run = store.get_run(run_id)
    if action == "replay":
        registry = create_default_registry()
        raw_request = _latest_raw_request_for_run(store, run)
        runtime = RuntimeCoordinationStore(config.data_dir)
        replay_payload = build_replay_request(
            run,
            raw_request=raw_request,
            reviewed_evidence=reviewed_evidence_manifest(
                run.id,
                runtime.list_policy_audit_events(run_id=run.id),
            ),
        )
        runner = HarnessSessionRunner(registry=registry, config=config, store=store)
        result = runner.run_in_session(run.session_id, replay_payload)
        if args.json:
            payload = result.to_dict()
            payload["source_run"] = run_to_dict(run)
            payload["replay_request"] = replay_payload
            _print_json(payload)
        else:
            _print_result(result.result, as_json=False)
        return 0 if result.result.ok else 1
    if action == "provenance":
        registry = create_default_registry()
        runtime = RuntimeCoordinationStore(config.data_dir)
        session = store.get_session(run.session_id)
        try:
            spec = registry.get(run.harness_id).spec()
        except UnknownHarnessError:
            spec = None
        provenance = build_run_provenance(
            run,
            session=session,
            spec=spec,
            raw_requests=store.list_raw_requests(run.session_id),
            raw_responses=store.list_raw_responses(run.session_id),
            events=store.list_events(run.session_id, run_id=run.id),
            policy_audit_events=runtime.list_policy_audit_events(run_id=run.id),
            data_dir=config.data_dir,
        )
        payload = {
            "run": run_to_dict(run),
            "provenance": run_provenance_to_dict(provenance),
        }
        if args.json:
            _print_json(payload)
        else:
            print(f"Run: {run.id}")
            print(f"Harness: {run.harness_id}")
            print(f"Status: {run.status.value}")
            print(f"Workspace: {run.workspace or '-'}")
            print(f"Replay: giga run replay {run.id}")
        return 0
    artifact = build_pr_artifact(run)
    artifact_payload = pr_artifact_to_dict(artifact)
    if action == "patch":
        if args.json:
            _print_json(
                {
                    "run": run_to_dict(run),
                    "patch": artifact.patch,
                    "pr_artifact": artifact_payload,
                }
            )
        else:
            print(artifact.patch)
        return 0
    if args.json:
        _print_json({"run": run_to_dict(run), "pr_artifact": artifact_payload})
    else:
        print(f"Title: {artifact.title}")
        print()
        print(artifact.body)
    return 0


def _handle_session_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    store = FilesystemHarnessSessionStore(config.data_dir)
    workspace = resolve_workspace(args.workspace) if args.workspace else None
    sessions = store.list_sessions(
        workspace=workspace,
        harness_id=args.harness_id,
        include_archived=args.include_archived,
    )
    rows = [_session_row(store, session.id) for session in sessions]
    if args.json:
        _print_json(rows)
    else:
        _print_session_table(rows)
    return 0


def _handle_session_show(args: argparse.Namespace, config: HarnessConfig) -> int:
    store = FilesystemHarnessSessionStore(config.data_dir)
    bundle = bundle_to_dict(store.get_session_bundle(args.session_id))
    if args.json:
        _print_json(bundle)
    else:
        session = bundle["session"]
        print(f"{session['title']} ({session['id']})")
        print(f"Harness: {session['default_harness_id']}")
        print(f"Updated: {session['updated_at']}")
        print(f"Messages: {len(bundle['messages'])}")
        print(f"Runs: {len(bundle['runs'])}")
    return 0


def _handle_session_create(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = _defined_values(
        title=args.title,
        workspace=args.workspace,
        harness_id=args.harness_id,
        model=args.model,
        api_mode=args.api_mode,
        mode=args.mode,
    )
    session = _session_application_service(config).create_session(
        payload,
        validate_harness=args.harness_id is not None,
    )
    serialized = session_to_dict(session)
    if args.json:
        _print_json({"session": serialized})
    else:
        print(f"Created session: {session.id}")
    return 0


def _handle_session_turn(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = _defined_values(
        prompt=args.prompt,
        harness_id=args.harness_id,
        model=args.model,
        api_mode=args.api_mode,
        capability=args.capability,
        mode=args.mode,
        workspace=args.workspace,
        permission_profile=args.permission_profile,
        execution_transport=args.transport,
    )
    service = _session_application_service(config)
    submission = service.submit_turn(
        args.session_id,
        payload,
        idempotency_key=args.idempotency_key or f"cli_{new_id('submit')}",
        origin="interactive",
    )
    response = {
        "session": session_to_dict(submission.queued.session),
        "run": run_to_dict(submission.queued.run),
        "job": job_to_dict(submission.job),
        "created": submission.created,
    }
    if args.json:
        _print_json(response)
    else:
        print(f"Submitted turn: {submission.queued.run.id}")
        print(f"Job: {submission.job.id} ({submission.job.status.value})")
    return 0


def _handle_session_events(args: argparse.Namespace, config: HarnessConfig) -> int:
    service = _session_application_service(config)
    run = service.get_run(args.run_id)
    events = service.list_run_events(args.run_id, after_id=args.after_id)
    payload = {
        "run": run_to_dict(run),
        "events": [event_to_dict(event) for event in events],
    }
    if args.json:
        _print_json(payload)
    else:
        for event in events:
            print(f"{event.created_at}  {event.type}  {event.message}")
    return 0


def _handle_session_approve(args: argparse.Namespace, config: HarnessConfig) -> int:
    service = _session_application_service(config)
    try:
        result = service.decide_approval(
            args.approval_id,
            args.decision,
            project_expiry_seconds=args.expires_in_seconds,
        )
    except KeyError as exc:
        raise ValueError(f"Unknown approval: {exc.args[0]}") from exc
    payload = {
        "approval": approval_request_to_dict(result.approval),
        "job_status": result.job.status.value if result.job else None,
        "retry_action": result.retry_action,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Approval {result.approval.id}: {result.approval.status.value}")
        if result.job is not None:
            print(f"Job: {result.job.id} ({result.job.status.value})")
    return 0


def _session_application_service(config: HarnessConfig) -> SessionApplicationService:
    registry = create_default_registry()
    store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(registry=registry, config=config, store=store)
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime_store,
        payload_store=DurableJobPayloadStore(config.data_dir),
        runner=runner,
    )
    return SessionApplicationService(
        runner=runner,
        settings_store=HarnessSettingsStore(config.data_dir, config),
        runtime_store=runtime_store,
        dispatcher=dispatcher,
    )


def _defined_values(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _handle_runtime_inspect(args: argparse.Namespace, config: HarnessConfig) -> int:
    store = RuntimeCoordinationStore(config.data_dir)
    payload = store.inspect()
    if args.json:
        _print_json(payload)
    else:
        print(f"Runtime database: {payload['path']}")
        print(f"Schema version: {payload['schema_version']}")
        print(f"Journal mode: {payload['journal_mode']}")
        print(f"Pending outbox: {payload['pending_outbox']}")
        for name, count in payload["counts"].items():
            print(f"{name}: {count}")
    return 0


def _handle_runtime_export(args: argparse.Namespace, config: HarnessConfig) -> int:
    store = RuntimeCoordinationStore(config.data_dir)
    payload = store.export()
    if args.output is None:
        _print_json(payload)
        return 0
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.name}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(output)
    print(f"Exported runtime coordination state to {output}")
    return 0


def _handle_state_backup(args: argparse.Namespace, config: HarnessConfig) -> int:
    result = create_state_backup(config.data_dir, args.output)
    if args.json:
        _print_json(result.to_dict())
    else:
        print(f"Backed up Harness state to {Path(args.output).expanduser()}")
        print(f"SHA-256: {result.sha256}")
        print(f"Files: {result.file_count}; bytes: {result.total_bytes}")
    return 0


def _handle_state_verify(args: argparse.Namespace, config: HarnessConfig) -> int:
    del config
    result = verify_state_backup(args.archive)
    if args.json:
        _print_json(result.to_dict())
    else:
        print(f"Verified Harness state backup: {Path(args.archive).expanduser()}")
        print(f"SHA-256: {result.sha256}")
        print(f"Files: {result.file_count}; bytes: {result.total_bytes}")
    return 0


def _handle_state_restore(args: argparse.Namespace, config: HarnessConfig) -> int:
    destination = args.destination or config.data_dir
    result = restore_state_backup(
        args.archive,
        destination,
        replace=args.replace,
    )
    if args.json:
        _print_json(result.to_dict())
    else:
        print(f"Restored Harness state to {Path(destination).expanduser()}")
        print(f"SHA-256: {result.backup.sha256}")
        print(f"Files: {result.backup.file_count}; bytes: {result.backup.total_bytes}")
    return 0


def _handle_worker_start(args: argparse.Namespace, config: HarnessConfig) -> int:
    worker = DurableJobWorker(
        config,
        lease_seconds=args.lease_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    if args.once:
        claimed = worker.run_once()
        worker.runtime_store.stop_worker(worker.worker_id)
        print("processed" if claimed else "idle")
        return 0
    print(f"Starting durable Harness worker {worker.worker_id}")
    print("Proxy auto-start is disabled; configure a running proxy/API key if needed.")
    try:
        worker.run_forever(
            poll_seconds=args.poll_seconds,
            max_idle_seconds=args.max_idle_seconds,
        )
    except KeyboardInterrupt:
        return 130
    return 0


def _handle_worker_status(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = worker_status(RuntimeCoordinationStore(config.data_dir))
    if args.json:
        _print_json(payload)
    elif not payload["workers"]:
        print("No durable Harness workers registered.")
    else:
        print(f"Online workers: {payload['online']}")
        for worker in payload["workers"]:
            print(
                f"{worker['id']}  {worker['status']}  "
                f"pid={worker['process_id']}  heartbeat={worker['heartbeat_at']}"
            )
    return 0


def _handle_worker_stop_on_idle(args: argparse.Namespace, config: HarnessConfig) -> int:
    worker = DurableJobWorker(
        config,
        lease_seconds=args.lease_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    worker.run_forever(
        poll_seconds=args.poll_seconds,
        max_idle_seconds=args.max_idle_seconds,
        stop_on_idle_seconds=max(args.idle_seconds, 0.0),
    )
    print(f"Worker {worker.worker_id} stopped after idle timeout.")
    return 0


def _handle_benchmark_performance(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    del config
    report = run_performance_baseline(
        samples=args.samples,
        profile=args.profile,
    )
    if args.output:
        write_performance_report(args.output, report)
        print(f"Wrote private performance report to {Path(args.output).expanduser()}")
    else:
        _print_json(report)
    return 0 if report["status"] == "passed" else 1


def _handle_schedule_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = _schedule_project(args.workspace, config)
    rows = list(_schedule_service(config).list(project))
    if args.json:
        _print_json({"schedules": rows})
    else:
        for row in rows:
            state = row.get("state") or {}
            definition = row["definition"]
            print(
                f"{definition['id']}  {state.get('status', 'paused')}  "
                f"next={state.get('next_run_at') or '-'}  "
                f"target={definition['target']['kind']}:{definition['target']['id']}"
            )
    return 0


def _handle_schedule_show(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = _schedule_service(config).detail(
        _schedule_project(args.workspace, config), args.schedule_id
    )
    _print_json(payload)
    return 0


def _handle_schedule_write(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = _schedule_project(args.workspace, config)
    source = Path(args.definition).expanduser().read_text(encoding="utf-8")
    payload = yaml.safe_load(source)
    if not isinstance(payload, Mapping):
        raise ValueError("Schedule definition must be a YAML/JSON mapping")
    payload = {**payload, "workspace": project.root}
    if args.schedule_action == "preview":
        definition = build_schedule_definition(project, payload)
        result = {
            "definition": schedule_definition_to_dict(definition),
            "occurrences": list(next_occurrences(definition)),
            "dry_run": True,
        }
    else:
        result = _schedule_service(config).upsert(project, payload)
    _print_json(result)
    return 0


def _handle_schedule_action(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = _schedule_project(args.workspace, config)
    service = _schedule_service(config)
    method = args.schedule_action.replace("-", "_")
    if method == "delete":
        result = service.archive(project, args.schedule_id)
    elif method == "resume":
        result = service.enable(project, args.schedule_id)
    else:
        result = getattr(service, method)(project, args.schedule_id)
    _print_json(result)
    return 0


def _schedule_project(workspace: str | None, config: HarnessConfig):
    return resolve_project(
        workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )


def _schedule_service(config: HarnessConfig) -> ScheduleService:
    registry = create_default_registry()
    store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(registry=registry, config=config, store=store)
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime_store,
        payload_store=DurableJobPayloadStore(config.data_dir),
        runner=runner,
    )
    return ScheduleService(
        runtime_store=runtime_store,
        runner=runner,
        dispatcher=dispatcher,
        eval_store=FilesystemHarnessEvalStore(config.data_dir),
    )


def _handle_native_sync(args: argparse.Namespace, config: HarnessConfig) -> int:
    if not 1 <= args.limit <= 500:
        raise ValueError("native sync limit must be between 1 and 500")
    workspace = resolve_workspace(args.workspace) if args.workspace else None
    project_id = _project_id_for_workspace(workspace, config)
    registry = create_default_native_registry(data_dir=config.data_dir)
    index_store = FilesystemNativeSessionIndexStore(config.data_dir)
    result = registry.discover(
        harness_id=args.harness_id,
        workspace=workspace,
        include_external=args.include_external,
        cursor=args.cursor,
        limit=args.limit,
    )
    stored = [
        index_store.upsert_ref(
            ref,
            project_id=_native_ref_project_id(
                ref,
                workspace=workspace,
                project_id=project_id,
            ),
        )
        for ref in result.sessions
    ]
    payload = {
        "sessions": [native_session_ref_to_dict(ref) for ref in stored],
        "errors": [discovery_error_to_dict(error) for error in result.errors],
        "next_cursor": result.next_cursor,
        "scanned_count": result.scanned_count,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Synced {len(stored)} native session(s).")
        if result.next_cursor is not None:
            print(f"Next cursor: {result.next_cursor}")
        _print_native_table(payload["sessions"])
        for error in payload["errors"]:
            print(f"{error['harness_id']}: {error['message']}", file=sys.stderr)
    return 0 if not result.errors else 1


def _handle_native_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    workspace = resolve_workspace(args.workspace) if args.workspace else None
    project_id = _project_id_for_workspace(workspace, config)
    refs = FilesystemNativeSessionIndexStore(config.data_dir).list_refs(
        harness_id=args.harness_id,
        workspace=workspace,
        project_id=project_id,
        status=args.status,
        limit=args.limit,
    )
    if not args.include_external:
        refs = tuple(
            ref for ref in refs if ref.status is not NativeSessionStatus.EXTERNAL_NATIVE
        )
    rows = [native_session_ref_to_dict(ref) for ref in refs]
    if args.json:
        _print_json(rows)
    else:
        _print_native_table(rows)
    return 0


def _handle_native_import(args: argparse.Namespace, config: HarnessConfig) -> int:
    index_store = FilesystemNativeSessionIndexStore(config.data_dir)
    ref = index_store.get_ref(args.native_ref_id)
    if ref is None:
        raise ValueError(f"Native session not found: {args.native_ref_id}")
    connector = create_default_native_registry(data_dir=config.data_dir).get(
        ref.harness_id
    )
    imported = connector.import_ref(ref)
    session_store = FilesystemHarnessSessionStore(config.data_dir)
    snapshot = ref.execution_snapshot
    session = session_store.create_session(
        title=ref.title,
        workspace=ref.workspace,
        default_harness_id=ref.harness_id,
        default_model=(
            snapshot.model
            if snapshot is not None
            else _optional_text(ref.metadata.get("model"))
        ),
        default_api_mode=parse_api_mode(
            snapshot.api_mode if snapshot is not None else ref.metadata.get("api_mode")
        ),
        native={
            "source": "native_import",
            "native_ref_id": ref.id,
            "native_session_id": ref.native_session_id,
        },
        metadata=provider_native_title_metadata(
            _native_import_session_metadata(ref),
            provider=ref.harness_id,
            source_id=ref.native_session_id or ref.id,
        ),
    )
    messages = []
    skipped_count = 0
    for item in imported:
        role = _native_import_message_role(item.role)
        if role is None:
            skipped_count += 1
            session_store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=session.id,
                    run_id="native_import",
                    type="native_import_warning",
                    message="Skipped native transcript item with unknown role.",
                    payload={
                        "native_ref_id": ref.id,
                        "native_session_id": ref.native_session_id,
                        "role": item.role,
                        "metadata": _redacted_mapping(item.metadata),
                    },
                    created_at=item.created_at or utc_now(),
                )
            )
            continue
        messages.append(
            session_store.append_message(
                HarnessMessage(
                    id=new_id("msg"),
                    session_id=session.id,
                    run_id=None,
                    role=role,
                    content=str(redact_for_storage(item.content)),
                    created_at=item.created_at or utc_now(),
                    harness_id=ref.harness_id,
                    metadata={
                        "source": "native_import",
                        "native_ref_id": ref.id,
                        "native_session_id": ref.native_session_id,
                        **_redacted_mapping(item.metadata),
                    },
                )
            )
        )
    now = utc_now()
    link = session_store.append_native_link(
        session.id,
        HarnessNativeLink(
            id=new_id("nlink"),
            session_id=session.id,
            harness_id=ref.harness_id,
            status=NativeSessionStatus.IMPORTED,
            created_at=now,
            updated_at=now,
            native_session_id=ref.native_session_id,
            native_ref_id=ref.id,
            source=ref.source,
            workspace=ref.workspace,
            metadata={
                "source_status": ref.status.value,
                "imported_message_count": len(messages),
                "skipped_item_count": skipped_count,
                "project_id": ref.metadata.get("project_id"),
                **_native_snapshot_metadata(ref),
            },
        ),
    )
    payload = {
        "session": session_to_dict(session),
        "native_link": native_link_to_dict(link),
        "messages": [message_to_dict(message) for message in messages],
        "imported_message_count": len(messages),
        "skipped_item_count": skipped_count,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Imported native session into {session.id}")
        print(f"Messages: {len(messages)}")
        if skipped_count:
            print(f"Skipped: {skipped_count}")
    return 0


def _handle_preset_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    payload = _project_payload(
        workspace=args.workspace,
        config=config,
        load_config_name=True,
    )
    if args.json:
        _print_json(payload["presets"])
    else:
        _print_preset_table(payload["presets"])
    return 0


def _handle_preset_run(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    loaded = load_project_config(project.root)
    rendered = render_project_preset(
        project,
        loaded,
        args.preset_name,
        user_prompt=args.prompt,
        selected_files=tuple(args.selected_file or ()),
        last_run_diff=args.last_run_diff,
    )
    result = _run_harness(
        harness_id=rendered.harness or loaded.defaults.harness,
        prompt=rendered.prompt,
        model=args.model or rendered.model or loaded.defaults.model,
        api_mode=(
            args.api_mode
            or (rendered.api_mode.value if rendered.api_mode is not None else None)
            or loaded.defaults.api_mode.value
        ),
        capability=None,
        mode=args.mode or rendered.mode or loaded.defaults.mode,
        workspace=project.root,
        workspace_policy=rendered.workspace_policy,
        dry_run=args.dry_run,
        native=args.native
        or (
            rendered.invocation_mode is not None
            and rendered.invocation_mode is HarnessInvocationMode.NATIVE
        ),
        config=config,
    )
    if args.json:
        payload = rendered_project_preset_to_dict(rendered)
        payload["result"] = result_to_dict(result)
        _print_json(payload)
    else:
        _print_result(result, as_json=False)
    return 0 if result.ok else 1


def _handle_memory_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    memories = FilesystemProjectMemoryStore().list(
        project,
        include_disabled=args.include_disabled,
    )
    rows = [memory_entry_to_dict(memory) for memory in memories]
    if args.json:
        _print_json({"project": project_to_dict(project), "memories": rows})
    else:
        _print_memory_table(rows)
    return 0


def _handle_memory_add(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    memory = FilesystemProjectMemoryStore().add(
        project,
        text=" ".join(args.text),
        tags=tuple(args.tag or ()),
        source_session_id=args.session_id,
        source_run_id=args.run_id,
        enabled=not args.disabled,
    )
    payload = {
        "project": project_to_dict(project),
        "memory": memory_entry_to_dict(memory),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Added memory: {memory.id}")
    return 0


def _handle_memory_disable(args: argparse.Namespace, config: HarnessConfig) -> int:
    return _set_memory_enabled(args, config, enabled=False)


def _handle_memory_enable(args: argparse.Namespace, config: HarnessConfig) -> int:
    return _set_memory_enabled(args, config, enabled=True)


def _handle_memory_delete(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    FilesystemProjectMemoryStore().delete(project, args.memory_id)
    payload = {"deleted": True, "project": project_to_dict(project)}
    if args.json:
        _print_json(payload)
    else:
        print(f"Deleted memory: {args.memory_id}")
    return 0


def _set_memory_enabled(
    args: argparse.Namespace,
    config: HarnessConfig,
    *,
    enabled: bool,
) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    memory = FilesystemProjectMemoryStore().update(
        project,
        args.memory_id,
        enabled=enabled,
    )
    payload = {
        "project": project_to_dict(project),
        "memory": memory_entry_to_dict(memory),
    }
    if args.json:
        _print_json(payload)
    else:
        action = "Enabled" if enabled else "Disabled"
        print(f"{action} memory: {memory.id}")
    return 0


def _handle_eval_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    specs, errors = discover_eval_specs(project.root)
    payload = {
        "project": project_to_dict(project),
        "specs": [eval_spec_to_dict(spec, include_cases=False) for spec in specs],
        "errors": [eval_spec_load_error_to_dict(error) for error in errors],
    }
    if args.json:
        _print_json(payload)
    else:
        _print_eval_spec_table(payload["specs"])
        for error in payload["errors"]:
            print(f"{error['path']}: {error['message']}", file=sys.stderr)
    return 0 if not errors else 1


def _handle_eval_run(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    spec = load_eval_spec(project.root, args.eval_name)
    store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(
        registry=create_default_registry(),
        config=config,
        store=store,
    )
    eval_run = run_eval(
        runner=runner,
        eval_store=FilesystemHarnessEvalStore(config.data_dir),
        project=project,
        spec=spec,
        harness_ids=_split_harness_args(args.harness),
        model=args.model,
        api_mode=args.api_mode,
        mode=args.mode,
        workspace_policy=args.workspace_policy,
        dry_run=args.dry_run,
    )
    payload = eval_run_to_dict(eval_run)
    if args.json:
        _print_json(payload)
    else:
        _print_eval_run_summary(payload)
    return 0 if eval_run.status == "passed" else 1


def _handle_agent_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    profiles, errors = discover_agent_profiles(project.root)
    payload = {
        "project": project_to_dict(project),
        "agents": [agent_profile_to_dict(profile) for profile in profiles],
        "errors": [error.__dict__ for error in errors],
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"{'ID':<22}{'Harness':<18}{'Mode':<8}Title")
        for profile in profiles:
            print(
                f"{profile.id:<22}{profile.harness_id:<18}{profile.mode:<8}{profile.title}"
            )
        for error in errors:
            print(f"{error.path}: {error.error}", file=sys.stderr)
    return 0 if not errors else 1


def _handle_agent_show(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    profile = load_agent_profile(project.root, args.agent_id)
    payload = agent_profile_to_dict(profile)
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _handle_agent_validate(args: argparse.Namespace, config: HarnessConfig) -> int:
    path = Path(args.path).expanduser()
    profile = parse_agent_profile(
        path.read_text(encoding="utf-8"), source_path=str(path)
    )
    payload = {"valid": True, "profile": agent_profile_to_dict(profile)}
    if args.json:
        _print_json(payload)
    else:
        print(f"Agent profile valid: {profile.id}")
    return 0


def _handle_agent_profile_run(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    profile = load_agent_profile(project.root, args.agent_id)
    registry = create_default_registry()
    payload = agent_run_payload(
        profile,
        args.prompt,
        workspace=project.root,
        harness=registry.get(profile.harness_id),
        default_timeout_seconds=config.timeout_seconds,
    )
    payload["dry_run"] = args.dry_run
    runner = HarnessSessionRunner(
        registry=registry,
        config=config,
        store=FilesystemHarnessSessionStore(config.data_dir),
    )
    result = runner.create_and_run(payload)
    if args.json:
        _print_json(result.to_dict())
    else:
        _print_result(result.result, as_json=False)
    return 0 if result.result.ok else 1


def _handle_workflow_list(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    definitions, errors = discover_workflows(project.root)
    payload = {
        "workflows": [workflow_definition_to_dict(item) for item in definitions],
        "errors": [{"path": item.path, "error": item.error} for item in errors],
    }
    if args.json:
        _print_json(payload)
    else:
        _print_table(payload["workflows"])
        for error in payload["errors"]:
            print(f"Invalid {error['path']}: {error['error']}", file=sys.stderr)
    return 0 if not errors else 1


def _handle_workflow_show(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    definition = load_workflow(project.root, args.workflow_id)
    payload = {
        "workflow": workflow_definition_to_dict(definition),
        "plan": workflow_plan(definition),
    }
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _handle_workflow_validate(args: argparse.Namespace, config: HarnessConfig) -> int:
    path = Path(args.path).expanduser()
    definition = parse_workflow_definition(
        path.read_text(encoding="utf-8"), source_path=str(path)
    )
    payload = {
        "valid": True,
        "workflow": workflow_definition_to_dict(definition),
        "plan": workflow_plan(definition),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Workflow valid: {definition.id} ({definition.source_hash})")
    return 0


def _handle_workflow_run(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(args.workspace, data_dir=config.data_dir)
    definition = load_workflow(project.root, args.workflow_id)
    inputs = _parse_workflow_inputs(args.input)
    if args.dry_run:
        payload = {
            "workflow": workflow_definition_to_dict(definition),
            "plan": workflow_plan(definition),
            "inputs": inputs,
        }
    else:
        coordinator = _workflow_coordinator(config, project)
        run = coordinator.start(definition, inputs=inputs, prompt=args.prompt)
        payload = {
            "run": workflow_run_to_dict(run, coordinator.repository.list_steps(run.id))
        }
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _handle_workflow_status(args: argparse.Namespace, config: HarnessConfig) -> int:
    repository = WorkflowRepository(RuntimeCoordinationStore(config.data_dir))
    current = repository.get_run(args.run_id)
    project = resolve_project(current.project_root, data_dir=config.data_dir)
    coordinator = _workflow_coordinator(config, project)
    run = coordinator.advance(args.run_id)
    payload = workflow_run_to_dict(run, coordinator.repository.list_steps(run.id))
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _handle_workflow_cancel(args: argparse.Namespace, config: HarnessConfig) -> int:
    repository = WorkflowRepository(RuntimeCoordinationStore(config.data_dir))
    current = repository.get_run(args.run_id)
    project = resolve_project(current.project_root, data_dir=config.data_dir)
    coordinator = _workflow_coordinator(config, project)
    run = coordinator.cancel(args.run_id)
    payload = workflow_run_to_dict(run, coordinator.repository.list_steps(run.id))
    if args.json:
        _print_json(payload)
    else:
        print(f"Canceled workflow run: {run.id}")
    return 0


def _workflow_coordinator(config: HarnessConfig, project: Any) -> WorkflowCoordinator:
    registry = create_default_registry()
    store = FilesystemHarnessSessionStore(config.data_dir)
    runner = HarnessSessionRunner(registry=registry, config=config, store=store)
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime_store,
        payload_store=DurableJobPayloadStore(config.data_dir),
        runner=runner,
    )
    return WorkflowCoordinator(
        project=project,
        runtime_store=runtime_store,
        runner=runner,
        dispatcher=dispatcher,
    )


def _parse_workflow_inputs(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise ValueError("workflow --input values must use key=value")
        parsed[key.strip()] = value
    return parsed


def _handle_open_session(args: argparse.Namespace, config: HarnessConfig) -> int:
    store = FilesystemHarnessSessionStore(config.data_dir)
    session = store.get_session(args.session_id)
    workspace = (
        session.workspace or resolve_project(None, data_dir=config.data_dir).root
    )
    command = _editor_command_for_workspace(workspace, config)
    plan = build_open_workspace_plan(workspace, command=command)
    result = execute_editor_plan(plan, dry_run=args.dry_run)
    payload = {
        "session": session_to_dict(session),
        "editor": editor_open_plan_to_dict(result),
    }
    _print_editor_open(payload, as_json=args.json)
    return 0


def _handle_open_run(args: argparse.Namespace, config: HarnessConfig) -> int:
    store = FilesystemHarnessSessionStore(config.data_dir)
    run = store.get_run(args.run_id)
    workspace = workspace_for_run(run)
    if args.terminal:
        if workspace is None:
            raise ValueError("Run does not have a workspace to open in a terminal.")
        command = _terminal_command_for_workspace(workspace, config)
        plan = build_open_terminal_plan(workspace, command=command)
    elif args.diff:
        command = _editor_command_for_workspace(workspace, config)
        plan = build_open_diff_plan(run, data_dir=config.data_dir, command=command)
    else:
        command = _editor_command_for_workspace(workspace, config)
        plan = build_open_run_workspace_plan(run, command=command)
    result = execute_editor_plan(plan, dry_run=args.dry_run)
    payload = {
        "run": run_to_dict(run),
        "editor": editor_open_plan_to_dict(result),
    }
    _print_editor_open(payload, as_json=args.json)
    return 0


def _handle_open_file(args: argparse.Namespace, config: HarnessConfig) -> int:
    project = resolve_project(
        args.workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    loaded = load_project_config(project.root)
    plan = build_open_file_plan(
        project.root,
        args.path,
        command=loaded.editor.command,
        line=args.line,
        column=args.column,
    )
    result = execute_editor_plan(plan, dry_run=args.dry_run)
    payload = {
        "project": project_to_dict(project),
        "editor": editor_open_plan_to_dict(result),
    }
    _print_editor_open(payload, as_json=args.json)
    return 0


def _handle_ui(args: argparse.Namespace, config: HarnessConfig) -> int:
    config = config.with_overrides(ui_host=args.host, ui_port=args.port)
    validate_ui_bind(config, allow_remote=args.allow_remote)
    if not 1 <= args.worker_count <= MAX_UI_WORKER_COUNT:
        raise ValueError(
            f"UI worker count must be between 1 and {MAX_UI_WORKER_COUNT}."
        )
    ui_url = (
        config.ui_oidc_public_origin
        if not is_loopback_host(config.ui_host)
        else f"http://{config.ui_host}:{config.ui_port}"
    )
    print(f"Starting GigaLoom UI at {ui_url}/")
    worker_processes = (
        _start_ui_workers(config, worker_count=args.worker_count)
        if args.start_worker
        else ()
    )
    try:
        app = create_app(config)
        uvicorn.run(
            app,
            host=config.ui_host,
            port=config.ui_port,
            log_level="info",
            timeout_graceful_shutdown=UI_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
        )
    finally:
        _stop_ui_workers(worker_processes)
    return 0


def _handle_ui_identity_validate(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    settings = RemoteOIDCSettings.from_config(config)
    payload = {
        "valid": True,
        "issuer": settings.issuer,
        "public_origin": settings.public_origin,
        "callback_uri": settings.callback_uri,
        "roles": {
            "viewer": sum(role == "viewer" for role in settings.roles.values()),
            "operator": sum(role == "operator" for role in settings.roles.values()),
        },
        "trusted_proxy_count": len(settings.trusted_proxies),
        "client_secret_configured": True,
    }
    if args.json:
        _print_json(payload)
    else:
        print(
            "Remote UI identity configuration is valid for "
            f"{settings.public_origin} ({len(settings.roles)} mapped subjects)."
        )
    return 0


def _handle_ui_identity_revoke_all(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    if not args.confirm:
        raise ValueError("Remote session revocation requires --confirm.")
    settings = RemoteOIDCSettings.from_config(config)
    revoked = RemoteIdentityStore(config.data_dir, settings).revoke_all()
    payload = {
        "revoked": revoked,
        "session_generation_rotated": True,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Revoked {revoked} remote UI session(s) and rotated the generation.")
    return 0


def _start_ui_workers(
    config: HarnessConfig,
    *,
    worker_count: int,
) -> tuple[subprocess.Popen[bytes], ...]:
    runtime_store = RuntimeCoordinationStore(config.data_dir)
    online = int(worker_status(runtime_store)["online"])
    missing = max(worker_count - online, 0)
    if missing == 0:
        print(f"Using {online} existing online durable Harness worker(s).")
        return ()
    if online:
        print(
            f"Using {online} existing online durable Harness worker(s); "
            f"starting {missing} more."
        )

    environment = os.environ.copy()
    environment.update(
        {
            "GPT2GIGA_HARNESS_DATA_DIR": config.data_dir,
            "GPT2GIGA_HARNESS_PROXY_URL": config.proxy_url,
            "GPT2GIGA_HARNESS_DEFAULT_API_MODE": config.default_api_mode.value,
            "GPT2GIGA_HARNESS_TIMEOUT_SECONDS": str(config.timeout_seconds),
            "GPT2GIGA_HARNESS_AUTO_START_PROXY": "false",
        }
    )
    if config.api_key:
        environment["GPT2GIGA_HARNESS_API_KEY"] = config.api_key
    if config.default_model:
        environment["GPT2GIGA_HARNESS_DEFAULT_MODEL"] = config.default_model

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for _ in range(missing):
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "gpt2giga_harness.cli",
                        "worker",
                        "start",
                    ],
                    env=environment,
                )
            except OSError as exc:
                raise ValueError(
                    f"Failed to start durable Harness worker: {exc}"
                ) from exc
            processes.append(process)
            _wait_for_ui_worker(runtime_store, process)
            print(f"Started durable Harness worker pid={process.pid}.")
    except Exception:
        _stop_ui_workers(processes)
        raise
    return tuple(processes)


def _wait_for_ui_worker(
    runtime_store: RuntimeCoordinationStore,
    process: subprocess.Popen[bytes],
) -> None:
    deadline = time.monotonic() + UI_WORKER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise ValueError(
                f"Durable Harness worker exited during startup with code {return_code}."
            )
        status = worker_status(runtime_store)
        if any(
            worker["status"] == "online" and int(worker["process_id"]) == process.pid
            for worker in status["workers"]
        ):
            return
        time.sleep(0.05)
    raise ValueError("Timed out waiting for the durable Harness worker to start.")


def _stop_ui_workers(
    processes: tuple[subprocess.Popen[bytes], ...] | list[subprocess.Popen[bytes]],
) -> None:
    for process in reversed(processes):
        _stop_ui_worker(process)


def _stop_ui_worker(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            process.send_signal(signal.SIGINT)
        else:
            process.terminate()
        process.wait(timeout=UI_WORKER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=UI_WORKER_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=UI_WORKER_STOP_TIMEOUT_SECONDS)


def _handle_harness_scaffold(args: argparse.Namespace, config: HarnessConfig) -> int:
    if args.output is None:
        print(render_adapter_module(args.harness_id), end="")
        return 0
    try:
        result = scaffold_adapter_package(args.harness_id, args.output)
    except FileExistsError as exc:
        raise ValueError(str(exc)) from exc
    print(f"Created adapter scaffold: {result.root}")
    print(f"Package: {result.package_name}")
    print(f"Files: {len(result.files)}")
    return 0


def _handle_harness_conformance(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> int:
    subject = load_installed_conformance_subject(args.harness_id)
    report = run_adapter_conformance(subject)
    payload = adapter_conformance_report_to_dict(report)
    if args.json:
        _print_json(payload)
    else:
        print(
            f"Adapter {report.adapter_id} {report.adapter_version}: "
            f"{'passed' if report.ok else 'failed'}"
        )
        for result in report.results:
            print(f"- {result.claim.value}: {result.status}")
    return 0 if report.ok else 1


def _run_harness(
    *,
    harness_id: str,
    prompt: str,
    model: str | None,
    api_mode: str | None,
    capability: str | None,
    mode: str,
    workspace: str | None,
    dry_run: bool,
    native: bool,
    config: HarnessConfig,
    workspace_policy: str | None = None,
):
    registry = create_default_registry()
    harness = registry.get(harness_id)
    spec = harness.spec()
    known_capabilities = spec_capability_values(spec)
    invocation_mode = (
        HarnessInvocationMode.NATIVE if native else HarnessInvocationMode.HEADLESS
    )
    execution_transport = (
        ExecutionTransport.NATIVE_TERMINAL if native else ExecutionTransport.ONE_SHOT
    )
    request = HarnessRequest(
        prompt=prompt,
        model=model,
        api_mode=parse_api_mode(api_mode or config.default_api_mode),
        capability=parse_capability(
            capability or (known_capabilities[0] if known_capabilities else None)
        ),
        mode=mode,
        invocation_mode=invocation_mode,
        execution_transport=execution_transport,
        workspace=resolve_workspace(workspace),
        extra=_run_extra(dry_run=dry_run, workspace_policy=workspace_policy),
    )
    preflight = build_preflight_report(
        prompt=request.prompt,
        workspace=request.workspace,
        data_dir=config.data_dir,
        permission_simulation=build_permission_simulation(
            spec=spec,
            execution_transport=execution_transport,
            invocation_mode=invocation_mode.value,
            permission_profile_id="interactive",
            mode=request.mode,
            workspace=request.workspace,
            api_mode=request.api_mode.value,
            model=request.model or config.default_model,
        ).to_dict(),
        readiness=build_execution_readiness(
            config,
            registry,
            harness_id=harness_id,
            invocation_mode=invocation_mode,
            execution_transport=execution_transport,
            api_mode=request.api_mode,
            model=request.model or config.default_model,
            mode=request.mode,
            workspace=request.workspace,
            workspace_policy=parse_workspace_policy(workspace_policy),
            durable=False,
            dry_run=dry_run,
        ),
    )
    if preflight.hard_block:
        return HarnessResult(
            ok=False,
            text="",
            raw={"preflight": preflight_report_to_dict(preflight)},
            error=format_preflight_block_message(preflight),
        )
    if native:
        if not spec.supports_native_sessions:
            return _result_with_preflight(
                HarnessResult(
                    ok=False,
                    text="",
                    error=f"Harness does not support native sessions: {harness_id}",
                ),
                preflight,
            )
        if not dry_run:
            return _result_with_preflight(
                HarnessResult(
                    ok=False,
                    text="",
                    error="Native CLI runs currently require --dry-run",
                ),
                preflight,
            )
        try:
            connector = create_default_native_registry(data_dir=config.data_dir).get(
                harness_id
            )
        except UnknownNativeHistoryConnectorError:
            return _result_with_preflight(
                HarnessResult(
                    ok=False,
                    text="",
                    error=f"Native connector is not registered: {harness_id}",
                ),
                preflight,
            )
        plan = connector.build_start_command(request, config.to_context())
        return _result_with_preflight(
            HarnessResult(
                ok=True,
                text="native dry run",
                raw={"native_command_plan": native_command_plan_to_dict(plan)},
                command=plan.command,
            ),
            preflight,
        )
    return _result_with_preflight(harness.run(request, config.to_context()), preflight)


def _config_from_args(args: argparse.Namespace) -> HarnessConfig:
    config = HarnessConfig.from_env()
    return config.with_overrides(
        proxy_url=getattr(args, "proxy_url", None),
        auto_start_proxy=getattr(args, "start_proxy", None),
    )


def _print_result(result, *, as_json: bool) -> None:
    payload = result_to_dict(result)
    if as_json:
        _print_json(payload)
        return
    _print_readiness_remediation(payload)
    if result.ok:
        print(result.text)
    else:
        print(result.error or "harness failed", file=sys.stderr)


def _result_with_preflight(result: HarnessResult, preflight) -> HarnessResult:
    return replace(
        result,
        raw={
            **dict(result.raw),
            "preflight": preflight_report_to_dict(preflight),
        },
    )


def _print_readiness_remediation(payload: Mapping[str, Any]) -> None:
    raw = payload.get("raw")
    preflight = raw.get("preflight") if isinstance(raw, Mapping) else None
    readiness = preflight.get("readiness") if isinstance(preflight, Mapping) else None
    findings = readiness.get("findings") if isinstance(readiness, Mapping) else None
    for finding in findings or ():
        if not isinstance(finding, Mapping) or finding.get("status") == "ready":
            continue
        status = str(finding.get("status") or "degraded").upper()
        summary = str(finding.get("summary") or finding.get("id") or "readiness")
        print(f"Readiness [{status}]: {summary}", file=sys.stderr)
        for remedy in finding.get("remediation") or ():
            if not isinstance(remedy, Mapping):
                continue
            message = remedy.get("message")
            command = remedy.get("command")
            if message:
                print(f"  Remedy: {message}", file=sys.stderr)
            if command:
                print(f"  Command: {command}", file=sys.stderr)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _print_bootstrap(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        _print_json(payload)
        return
    plan = payload.get("plan")
    if isinstance(plan, Mapping):
        print(f"Bootstrap plan: {plan.get('plan_id')}")
        for step in plan.get("steps") or ():
            if not isinstance(step, Mapping):
                continue
            status = "available" if step.get("available") else "not needed"
            print(f"- {step.get('id')}: {status}")
        print(f"Support export: {plan.get('support_export')}")
        return
    print(
        "Bootstrap application: "
        f"{payload.get('application_id')} ({payload.get('status')})"
    )
    if payload.get("rollback_available"):
        print(f"Rollback: giga bootstrap rollback {payload.get('application_id')}")


def _print_editor_open(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        _print_json(payload)
        return
    editor = payload["editor"]
    if editor.get("executed"):
        print(f"Opened {editor['target_path']}")
    else:
        print(editor["command_display"])


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'ID':<16}{'Kind':<14}{'Status':<12}{'Native':<8}Description")
    for row in rows:
        native = row.get("default_invocation_mode") if row.get("native") else "-"
        print(
            f"{row['id']:<16}{row['kind']:<14}{row['status']:<12}"
            f"{native:<8}{row['description']}"
        )


def _print_provider_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'ID':<24}{'Protocol':<24}{'Status':<16}Name")
    for row in rows:
        health = row.get("health") or {}
        status = "disabled" if not row["enabled"] else health.get("status", "unchecked")
        print(
            f"{row['id'][:23]:<24}{row['protocol'][:23]:<24}"
            f"{status[:15]:<16}{row['display_name']}"
        )


def _print_provider_detail(provider: Mapping[str, Any]) -> None:
    print(f"Provider: {provider['display_name']} ({provider['id']})")
    print(f"Protocol: {provider['protocol']} / {provider['dialect']}")
    print(f"Endpoint: {provider['effective_base_url']}")
    print(f"Source: {provider['source']}")
    print(
        "Authentication: "
        f"{provider['authentication']['ownership']} "
        f"({provider['authentication']['reference_kind'] or 'provider-owned'})"
    )
    print(f"Registry revision: {provider['registry_revision']}")
    for purpose, model in provider["default_models"].items():
        print(f"- {purpose}: {model}")


def _print_preset_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'Name':<18}{'Harness':<16}{'Mode':<8}{'Policy':<10}Title")
    for row in rows:
        print(
            f"{row['name']:<18}{(row.get('harness') or '-'):<16}"
            f"{(row.get('mode') or '-'):<8}"
            f"{(row.get('workspace_policy') or '-'):<10}{row['title']}"
        )


def _print_memory_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'ID':<38}{'Enabled':<10}{'Tags':<24}Text")
    for row in rows:
        tags = ",".join(row.get("tags") or ())
        preview = " ".join(str(row.get("text") or "").split())[:100]
        print(
            f"{row['id']:<38}{str(row.get('enabled', True)):<10}"
            f"{tags[:23]:<24}{preview}"
        )


def _print_eval_spec_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'Name':<20}{'Cases':<8}{'Harnesses':<28}Description")
    for row in rows:
        harnesses = ",".join(row.get("harnesses") or ()) or "echo"
        print(
            f"{row['name']:<20}{str(row.get('case_count') or 0):<8}"
            f"{harnesses[:27]:<28}{row.get('description') or ''}"
        )


def _print_eval_run_summary(payload: Mapping[str, Any]) -> None:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    print(f"Eval: {payload.get('spec_name')} ({payload.get('id')})")
    print(f"Status: {payload.get('status')}")
    print(
        "Score: "
        f"{summary.get('passed', 0)}/{summary.get('total', 0)} "
        f"passed, {summary.get('failed', 0)} failed, "
        f"{summary.get('errors', 0)} errors"
    )
    for result in payload.get("results") or ():
        print(
            f"- {result['case_id']} / {result['harness_id']}: "
            f"{result['status']} ({result['score']:.2f})"
        )


def _split_harness_args(values: list[str]) -> tuple[str, ...]:
    items: list[str] = []
    for value in values or ():
        items.extend(part.strip() for part in str(value).split(",") if part.strip())
    return tuple(dict.fromkeys(items))


def _run_extra(*, dry_run: bool, workspace_policy: str | None) -> dict[str, Any]:
    extra: dict[str, Any] = {"dry_run": dry_run}
    if workspace_policy is not None:
        extra["workspace_policy"] = workspace_policy
    return extra


def _session_row(
    store: FilesystemHarnessSessionStore,
    session_id: str,
) -> dict[str, Any]:
    session = store.get_session(session_id)
    messages = store.list_messages(session_id)
    runs = store.list_runs(session_id)
    row = session_to_dict(session)
    row.update(
        {
            "last_message_preview": (
                " ".join(messages[-1].content.split())[:120] if messages else ""
            ),
            "last_run_status": runs[-1].status if runs else None,
        }
    )
    return row


def _print_session_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'ID':<38}{'Updated':<22}{'Harness':<16}Title")
    for row in rows:
        print(
            f"{row['id']:<38}{row['updated_at']:<22}"
            f"{row['default_harness_id']:<16}{row['title']}"
        )


def _project_payload(
    *,
    workspace: str | None,
    config: HarnessConfig,
    load_config_name: bool,
) -> dict[str, Any]:
    project = resolve_project(
        workspace,
        data_dir=config.data_dir,
        load_config_name=load_config_name,
    )
    loaded = load_project_config(project.root)
    config_payload = project_config_to_dict(loaded)
    return {
        "project": project_to_dict(project),
        "config": config_payload,
        "defaults": config_payload["defaults"],
        "presets": list(config_payload["presets"].values()),
        "tools": list(config_payload["tools"].values()),
    }


def _project_id_for_workspace(
    workspace: str | None,
    config: HarnessConfig,
) -> str | None:
    if workspace is None:
        return None
    return resolve_project(
        workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    ).id


def _native_ref_project_id(
    ref: NativeSessionRef,
    *,
    workspace: str | None,
    project_id: str | None,
) -> str | None:
    if (
        project_id is not None
        and ref.workspace is not None
        and normalize_native_workspace(ref.workspace)
        == normalize_native_workspace(workspace)
    ):
        return project_id
    value = ref.metadata.get("project_id")
    return str(value).strip() if value is not None and str(value).strip() else None


def _editor_command_for_workspace(
    workspace: str | None,
    config: HarnessConfig,
) -> str:
    project = resolve_project(
        workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    return load_project_config(project.root).editor.command


def _terminal_command_for_workspace(
    workspace: str | None,
    config: HarnessConfig,
) -> str:
    project = resolve_project(
        workspace,
        data_dir=config.data_dir,
        load_config_name=False,
    )
    return load_project_config(project.root).editor.terminal_command


def _latest_raw_request_for_run(
    store: FilesystemHarnessSessionStore,
    run,
):
    records = [
        record
        for record in store.list_raw_requests(run.session_id)
        if record.run_id == run.id
    ]
    return records[-1] if records else None


def _print_native_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'ID':<38}{'Harness':<16}{'Status':<18}{'Resume':<8}Title")
    for row in rows:
        resume = "yes" if row.get("can_resume") else "-"
        print(
            f"{row['id']:<38}{row['harness_id']:<16}"
            f"{row['status']:<18}{resume:<8}{row['title']}"
        )


def _native_import_session_metadata(ref: NativeSessionRef) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": "native_import",
        "source_harness_id": ref.harness_id,
        "native_ref_id": ref.id,
        "native_session_id": ref.native_session_id,
        "native_status": ref.status.value,
    }
    project_id = _optional_text(ref.metadata.get("project_id"))
    if project_id is not None:
        metadata["project_id"] = project_id
    if ref.workspace is not None:
        metadata["project_root"] = ref.workspace
    metadata.update(_native_snapshot_metadata(ref))
    return metadata


def _native_snapshot_metadata(ref: NativeSessionRef) -> dict[str, Any]:
    if ref.execution_snapshot is None:
        return {"limitations": ["route_unknown"]} if ref.can_resume else {}
    return {
        "execution_snapshot": execution_snapshot_to_dict(ref.execution_snapshot),
        "limitations": (
            [] if ref.execution_snapshot.route_known else ["route_unknown"]
        ),
    }


def _native_import_message_role(role: str) -> str | None:
    normalized = str(role).strip().lower()
    if normalized in {"user", "assistant", "system", "tool"}:
        return normalized
    if normalized == "model":
        return "assistant"
    return None


def _redacted_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        value = {}
    redacted = redact_for_storage(dict(value))
    return dict(redacted) if isinstance(redacted, dict) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
