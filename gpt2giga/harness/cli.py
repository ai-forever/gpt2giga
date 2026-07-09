"""Command-line interface for the gpt2giga Unified Harness."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

import uvicorn

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.doctor import run_doctor
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
from gpt2giga.harness.registry import UnknownHarnessError, create_default_registry
from gpt2giga.harness.sessions import (
    FilesystemHarnessSessionStore,
    SessionNotFoundError,
)
from gpt2giga.harness.sessions.models import bundle_to_dict, session_to_dict
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
    spec_to_dict,
)
from gpt2giga.harness.ui.app import create_app, validate_ui_bind
from gpt2giga.harness.workspace import resolve_workspace

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
    run.add_argument("--agent", required=True, choices=tuple(AGENT_ALIASES))
    run.add_argument("--mode", choices=("plan", "read", "edit"), default="plan")
    run.add_argument("--model", default=None)
    run.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    run.add_argument("--workspace", default=None)
    run.add_argument("--native", action="store_true")
    run.add_argument("--json", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("prompt", nargs="+")
    run.set_defaults(handler=_handle_agent_alias)

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

    harness = subparsers.add_parser("harness")
    harness_subparsers = harness.add_subparsers(dest="harness_command")

    harness_list = harness_subparsers.add_parser("list", parents=[common])
    harness_list.add_argument("--json", action="store_true")
    harness_list.set_defaults(handler=_handle_harness_list)

    harness_inspect = harness_subparsers.add_parser("inspect", parents=[common])
    harness_inspect.add_argument("harness_id")
    harness_inspect.add_argument("--json", action="store_true")
    harness_inspect.set_defaults(handler=_handle_harness_inspect)

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
        availability = harness.availability()
        rows.append(
            {
                "id": spec.id,
                "kind": spec.kind,
                "status": availability.status.value,
                "native": spec.supports_native_sessions,
                "default_invocation_mode": spec.default_invocation_mode.value,
                "description": spec.description,
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
    payload = {
        "spec": spec_to_dict(harness.spec()),
        "availability": availability_to_dict(harness.availability()),
    }
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


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


def _handle_ui(args: argparse.Namespace, config: HarnessConfig) -> int:
    config = config.with_overrides(ui_host=args.host, ui_port=args.port)
    validate_ui_bind(config.ui_host, allow_remote=args.allow_remote)
    if args.allow_remote and config.ui_host == "0.0.0.0":
        print(
            "Warning: UI is bound to 0.0.0.0 and may expose local harness execution.",
            file=sys.stderr,
        )
    print(
        f"Starting gpt2giga Unified Harness UI at http://{config.ui_host}:{config.ui_port}/"
    )
    app = create_app(config)
    uvicorn.run(app, host=config.ui_host, port=config.ui_port, log_level="info")
    return 0


def _handle_harness_scaffold(args: argparse.Namespace, config: HarnessConfig) -> int:
    class_name = "".join(part.title() for part in args.harness_id.split("-"))
    print(
        f"""from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import Availability, HarnessRequest, HarnessResult, HarnessSpec


class {class_name}Harness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="{args.harness_id}",
            title="{class_name}",
            kind="custom",
            description="Describe this harness",
            capabilities=(),
        )

    def availability(self) -> Availability:
        return Availability.available("custom harness")

    def run(self, request: HarnessRequest, context) -> HarnessResult:
        return HarnessResult(ok=False, text="", error="not implemented")
"""
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
    invocation_mode = (
        HarnessInvocationMode.NATIVE if native else HarnessInvocationMode.HEADLESS
    )
    request = HarnessRequest(
        prompt=prompt,
        model=model,
        api_mode=parse_api_mode(api_mode or config.default_api_mode),
        capability=parse_capability(
            capability or (spec.capabilities[0].value if spec.capabilities else None)
        ),
        mode=mode,
        invocation_mode=invocation_mode,
        workspace=resolve_workspace(workspace),
        extra=_run_extra(dry_run=dry_run, workspace_policy=workspace_policy),
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
