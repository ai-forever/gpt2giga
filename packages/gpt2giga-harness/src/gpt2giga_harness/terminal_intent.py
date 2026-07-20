"""Low-overhead parsing for human terminal deep links."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from gpt2giga_harness.terminal_dispatch import TuiLaunchIntent


AGENT_HARNESSES = {
    "codex": "codex-cli",
    "claude": "claude-code",
    "gemini": "gemini-cli",
}


def parse_tui_launch_intent(
    argv: Sequence[str],
) -> tuple[TuiLaunchIntent, list[str]]:
    """Return the exact TUI intent and standalone TUI arguments."""
    arguments = list(argv)
    command = arguments[0] if arguments and not arguments[0].startswith("-") else None
    if command in {None, "tui"}:
        return TuiLaunchIntent(), arguments[1:] if command == "tui" else arguments
    if command == "chat":
        args = _chat_parser().parse_args(arguments[1:])
        return (
            TuiLaunchIntent(
                create_session=True,
                harness_id="direct-chat",
                model=args.model,
                api_mode=args.api_mode,
                mode="plan",
                prompt=" ".join(args.prompt),
                proxy_url=args.proxy_url,
                auto_start_proxy=args.start_proxy,
            ),
            [],
        )
    if command == "run":
        args = _run_parser().parse_args(arguments[1:])
        return (
            TuiLaunchIntent(
                workspace=args.workspace,
                create_session=True,
                harness_id=AGENT_HARNESSES[args.agent],
                model=args.model,
                api_mode=args.api_mode,
                mode=args.mode,
                execution_transport="native_terminal" if args.native else "one_shot",
                prompt=" ".join(args.prompt) or None,
                proxy_url=args.proxy_url,
                auto_start_proxy=args.start_proxy,
            ),
            [],
        )
    if command == "session":
        return _parse_session(arguments[1:]), []
    raise ValueError(f"Unclassified TUI command: {command}")


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--proxy-url", default=None)
    parser.add_argument(
        "--start-proxy",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    return parser


def _chat_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="giga chat", parents=[_common_parser()])
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    parser.add_argument("prompt", nargs="+")
    return parser


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="giga run", parents=[_common_parser()])
    parser.add_argument("--agent", choices=tuple(AGENT_HARNESSES), required=True)
    parser.add_argument("--mode", choices=("plan", "read", "edit"), default="plan")
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("prompt", nargs="*")
    return parser


def _parse_session(arguments: list[str]) -> TuiLaunchIntent:
    parser = argparse.ArgumentParser(prog="giga session")
    subparsers = parser.add_subparsers(dest="action")
    list_parser = subparsers.add_parser("list", parents=[_common_parser()])
    list_parser.add_argument("--workspace", default=None)
    show_parser = subparsers.add_parser("show", parents=[_common_parser()])
    show_parser.add_argument("session_id")
    create_parser = subparsers.add_parser("create", parents=[_common_parser()])
    create_parser.add_argument("--title", default=None)
    create_parser.add_argument("--workspace", default=None)
    _add_session_defaults(create_parser)
    turn_parser = subparsers.add_parser("turn", parents=[_common_parser()])
    turn_parser.add_argument("session_id")
    turn_parser.add_argument("--prompt", required=True)
    turn_parser.add_argument("--workspace", default=None)
    _add_session_defaults(turn_parser)
    turn_parser.add_argument("--capability", default=None)
    turn_parser.add_argument(
        "--transport",
        choices=("native_structured", "native_terminal", "one_shot"),
        default=None,
    )
    args = parser.parse_args(arguments)
    common = {
        "workspace": getattr(args, "workspace", None),
        "proxy_url": getattr(args, "proxy_url", None),
        "auto_start_proxy": getattr(args, "start_proxy", None),
    }
    if args.action in {None, "list"}:
        return TuiLaunchIntent(**common)
    if args.action == "show":
        return TuiLaunchIntent(session_id=args.session_id, **common)
    defaults = {
        "harness_id": args.harness_id,
        "model": args.model,
        "api_mode": args.api_mode,
        "mode": args.mode,
    }
    if args.action == "create":
        return TuiLaunchIntent(
            create_session=True,
            title=args.title,
            **common,
            **defaults,
        )
    return TuiLaunchIntent(
        session_id=args.session_id,
        prompt=args.prompt,
        capability=args.capability,
        execution_transport=args.transport,
        **common,
        **defaults,
    )


def _add_session_defaults(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--harness", dest="harness_id", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-mode", choices=("v1", "v2"), default=None)
    parser.add_argument("--mode", choices=("plan", "read", "edit"), default=None)
