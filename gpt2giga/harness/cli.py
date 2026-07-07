"""Command-line interface for the gpt2giga Unified Harness."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import uvicorn

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.doctor import run_doctor
from gpt2giga.harness.registry import UnknownHarnessError, create_default_registry
from gpt2giga.harness.types import (
    HarnessCapability,
    HarnessRequest,
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
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--proxy-url", default=None, help="Local gpt2giga proxy URL")

    parser = argparse.ArgumentParser(prog="giga")
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", parents=[common])
    doctor.set_defaults(handler=_handle_doctor)

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
    run.add_argument("--json", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("prompt", nargs="+")
    run.set_defaults(handler=_handle_agent_alias)

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
        config=config,
    )
    _print_result(result, as_json=args.json)
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
    config: HarnessConfig,
):
    registry = create_default_registry()
    harness = registry.get(harness_id)
    request = HarnessRequest(
        prompt=prompt,
        model=model,
        api_mode=parse_api_mode(api_mode or config.default_api_mode),
        capability=parse_capability(capability),
        mode=mode,
        workspace=resolve_workspace(workspace),
        extra={"dry_run": dry_run},
    )
    return harness.run(request, config.to_context())


def _config_from_args(args: argparse.Namespace) -> HarnessConfig:
    config = HarnessConfig.from_env()
    return config.with_overrides(proxy_url=getattr(args, "proxy_url", None))


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


def _print_table(rows: list[dict[str, str]]) -> None:
    print(f"{'ID':<16}{'Kind':<14}{'Status':<12}Description")
    for row in rows:
        print(
            f"{row['id']:<16}{row['kind']:<14}{row['status']:<12}{row['description']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
