"""Command-line interface for the gpt2giga Unified Harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import uvicorn
import yaml

from gpt2giga.harness.agents import (
    agent_profile_to_dict,
    agent_run_payload,
    discover_agent_profiles,
    load_agent_profile,
    parse_agent_profile,
)
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.doctor import run_doctor
from gpt2giga.harness.editor import (
    build_open_diff_plan,
    build_open_file_plan,
    build_open_run_workspace_plan,
    build_open_terminal_plan,
    build_open_workspace_plan,
    editor_open_plan_to_dict,
    execute_editor_plan,
    workspace_for_run,
)
from gpt2giga.harness.evals import (
    EvalSpecNotFoundError,
    FilesystemHarnessEvalStore,
    discover_eval_specs,
    eval_run_to_dict,
    eval_spec_load_error_to_dict,
    eval_spec_to_dict,
    load_eval_spec,
    run_eval,
)
from gpt2giga.harness.native import HarnessInvocationMode
from gpt2giga.harness.native.base import (
    discovery_error_to_dict,
    native_command_plan_to_dict,
)
from gpt2giga.harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
)
from gpt2giga.harness.native.registry import (
    UnknownNativeHistoryConnectorError,
    create_default_native_registry,
)
from gpt2giga.harness.native.store import (
    FilesystemNativeSessionIndexStore,
    native_session_ref_to_dict,
)
from gpt2giga.harness.project import (
    init_project_config,
    load_project_config,
    project_config_path,
    project_config_to_dict,
    project_to_dict,
    render_project_preset,
    rendered_project_preset_to_dict,
    resolve_project,
)
from gpt2giga.harness.project_memory import (
    FilesystemProjectMemoryStore,
    ProjectMemoryNotFoundError,
    memory_entry_to_dict,
)
from gpt2giga.harness.preflight import (
    build_preflight_report,
    format_preflight_block_message,
    preflight_report_to_dict,
)
from gpt2giga.harness.pr_artifacts import build_pr_artifact, pr_artifact_to_dict
from gpt2giga.harness.plugins import (
    harness_validation_report_to_dict,
    validate_harness_spec,
)
from gpt2giga.harness.provenance import (
    build_replay_request,
    build_run_provenance,
    run_provenance_to_dict,
)
from gpt2giga.harness.registry import UnknownHarnessError, create_default_registry
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga.harness.runtime.worker import (
    DurableJobDispatcher,
    DurableJobWorker,
    worker_status,
)
from gpt2giga.harness.schedules import (
    ScheduleService,
    build_schedule_definition,
    next_occurrences,
    schedule_definition_to_dict,
)
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.sessions import (
    FilesystemHarnessSessionStore,
    RunNotFoundError,
    SessionNotFoundError,
)
from gpt2giga.harness.sessions.models import (
    bundle_to_dict,
    run_to_dict,
    session_to_dict,
)
from gpt2giga.harness.sessions.models import (
    HarnessMessage,
    HarnessNativeLink,
    HarnessStoredEvent,
    message_to_dict,
    native_link_to_dict,
)
from gpt2giga.harness.sessions.redaction import redact_for_storage
from gpt2giga.harness.sessions.store import new_id, utc_now
from gpt2giga.harness.types import (
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
from gpt2giga.harness.ui.app import create_app, validate_ui_bind
from gpt2giga.harness.ui.security import is_loopback_host
from gpt2giga.harness.workspace import resolve_workspace
from gpt2giga.harness.workflows import (
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
    except EvalSpecNotFoundError as exc:
        print(f"Unknown eval: {exc.args[0]}", file=sys.stderr)
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

    parser = argparse.ArgumentParser(prog="giga")
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", parents=[common])
    doctor.set_defaults(handler=_handle_doctor)

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
    ui.add_argument("--allow-remote", action="store_true")
    ui.set_defaults(handler=_handle_ui)

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

    runtime = subparsers.add_parser("runtime")
    runtime_subparsers = runtime.add_subparsers(dest="runtime_command")

    runtime_inspect = runtime_subparsers.add_parser("inspect")
    runtime_inspect.add_argument("--json", action="store_true")
    runtime_inspect.set_defaults(handler=_handle_runtime_inspect)

    runtime_export = runtime_subparsers.add_parser("export")
    runtime_export.add_argument("--output", default=None)
    runtime_export.set_defaults(handler=_handle_runtime_export)

    worker = subparsers.add_parser("worker", parents=[common])
    worker_subparsers = worker.add_subparsers(dest="worker_command")

    worker_start = worker_subparsers.add_parser("start", parents=[common])
    worker_start.add_argument("--once", action="store_true")
    worker_start.add_argument("--poll-seconds", type=float, default=0.25)
    worker_start.add_argument("--lease-seconds", type=float, default=15.0)
    worker_start.add_argument("--heartbeat-seconds", type=float, default=2.0)
    worker_start.set_defaults(handler=_handle_worker_start)

    worker_status_parser = worker_subparsers.add_parser("status")
    worker_status_parser.add_argument("--json", action="store_true")
    worker_status_parser.set_defaults(handler=_handle_worker_status)

    worker_idle = worker_subparsers.add_parser("stop-on-idle", parents=[common])
    worker_idle.add_argument("--idle-seconds", type=float, default=5.0)
    worker_idle.add_argument("--poll-seconds", type=float, default=0.25)
    worker_idle.add_argument("--lease-seconds", type=float, default=15.0)
    worker_idle.add_argument("--heartbeat-seconds", type=float, default=2.0)
    worker_idle.set_defaults(handler=_handle_worker_stop_on_idle)

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
    harness_scaffold.set_defaults(handler=_handle_harness_scaffold)

    return parser


def _handle_doctor(args: argparse.Namespace, config: HarnessConfig) -> int:
    print(run_doctor(config))
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
        "validation": harness_validation_report_to_dict(validation),
    }
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
        replay_payload = build_replay_request(run, raw_request=raw_request)
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
        worker.run_forever(poll_seconds=args.poll_seconds)
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
        stop_on_idle_seconds=max(args.idle_seconds, 0.0),
    )
    print(f"Worker {worker.worker_id} stopped after idle timeout.")
    return 0


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
    workspace = resolve_workspace(args.workspace) if args.workspace else None
    project_id = _project_id_for_workspace(workspace, config)
    registry = create_default_native_registry(data_dir=config.data_dir)
    index_store = FilesystemNativeSessionIndexStore(config.data_dir)
    result = registry.discover(
        harness_id=args.harness_id,
        workspace=workspace,
        include_external=args.include_external,
    )
    stored = [
        index_store.upsert_ref(ref, project_id=project_id) for ref in result.sessions
    ]
    payload = {
        "sessions": [native_session_ref_to_dict(ref) for ref in stored],
        "errors": [discovery_error_to_dict(error) for error in result.errors],
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Synced {len(stored)} native session(s).")
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
    session = session_store.create_session(
        title=f"Imported: {ref.title}",
        workspace=ref.workspace,
        default_harness_id=ref.harness_id,
        default_model=_optional_text(ref.metadata.get("model")),
        default_api_mode=parse_api_mode(ref.metadata.get("api_mode")),
        native={
            "source": "native_import",
            "native_ref_id": ref.id,
            "native_session_id": ref.native_session_id,
        },
        metadata=_native_import_session_metadata(ref),
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
    payload = agent_run_payload(profile, args.prompt, workspace=project.root)
    payload["dry_run"] = args.dry_run
    runner = HarnessSessionRunner(
        registry=create_default_registry(),
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
    validate_ui_bind(config.ui_host, allow_remote=args.allow_remote)
    if args.allow_remote and not is_loopback_host(config.ui_host):
        if config.ui_bootstrap_token:
            warning = "Remote UI browser authentication is enabled."
        else:
            warning = (
                "Remote UI APIs require GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN; "
                "mutating APIs are disabled."
            )
        print(f"Warning: {warning}", file=sys.stderr)
    print(
        f"Starting gpt2giga Unified Harness UI at http://{config.ui_host}:{config.ui_port}/"
    )
    app = create_app(config)
    uvicorn.run(app, host=config.ui_host, port=config.ui_port, log_level="info")
    return 0


def _handle_harness_scaffold(args: argparse.Namespace, config: HarnessConfig) -> int:
    class_name = "".join(part.title() for part in args.harness_id.split("-"))
    print(
        f'''from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class {class_name}Harness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="{args.harness_id}",
            title="{class_name}",
            kind="custom",
            description="Describe this harness",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            icon="plug",
            supports_workspace=True,
            supports_attachments=False,
            tags=("plugin",),
            config_schema={{
                "type": "object",
                "properties": {{
                    "endpoint": {{
                        "type": "string",
                        "title": "Endpoint",
                        "description": "Optional local service URL.",
                    }},
                    "dry_run": {{
                        "type": "boolean",
                        "title": "Dry run",
                        "default": True,
                    }},
                }},
                "additionalProperties": False,
            }},
            metadata={{
                "package": "my-package",
                "version": "0.1.0",
            }},
        )

    def availability(self) -> Availability:
        return Availability.available("custom harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=False, text="", error="not implemented")
'''
    )
    return 0


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
    request = HarnessRequest(
        prompt=prompt,
        model=model,
        api_mode=parse_api_mode(api_mode or config.default_api_mode),
        capability=parse_capability(
            capability or (known_capabilities[0] if known_capabilities else None)
        ),
        mode=mode,
        invocation_mode=invocation_mode,
        workspace=resolve_workspace(workspace),
        extra=_run_extra(dry_run=dry_run, workspace_policy=workspace_policy),
    )
    preflight = build_preflight_report(
        prompt=request.prompt,
        workspace=request.workspace,
        data_dir=config.data_dir,
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
            return HarnessResult(
                ok=False,
                text="",
                error=f"Harness does not support native sessions: {harness_id}",
            )
        if not dry_run:
            return HarnessResult(
                ok=False,
                text="",
                error="Native CLI runs currently require --dry-run",
            )
        try:
            connector = create_default_native_registry(data_dir=config.data_dir).get(
                harness_id
            )
        except UnknownNativeHistoryConnectorError:
            return HarnessResult(
                ok=False,
                text="",
                error=f"Native connector is not registered: {harness_id}",
            )
        plan = connector.build_start_command(request, config.to_context())
        return HarnessResult(
            ok=True,
            text="native dry run",
            raw={"native_command_plan": native_command_plan_to_dict(plan)},
            command=plan.command,
        )
    return harness.run(request, config.to_context())


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
    if result.ok:
        print(result.text)
    else:
        print(result.error or "harness failed", file=sys.stderr)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


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
    return metadata


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
