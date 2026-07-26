"""Low-overhead CLI entry point for the built-in Textual client."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
import importlib
import os
import sys

from gpt2giga_harness import __version__
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.terminal_dispatch import TuiLaunchIntent
from gpt2giga_harness.tui.client import (
    AttachedWorkbenchClient,
    InProcessWorkbenchClient,
)
from gpt2giga_harness.tui.i18n import resolve_locale


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone TUI argument parser without importing Textual."""
    parser = argparse.ArgumentParser(
        prog="giga",
        description="Open GigaLoom, the built-in provider-neutral terminal workbench.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Prefix a native command with only 'giga': 'giga codex exec ...', "
            "'giga claude -p ...', or 'giga gemini -p ...'. Provider suffixes, "
            "help, version, JSON/JSONL, pipes, redirects, and exit status remain "
            "provider-owned. Legacy Harness automation remains available; use "
            "'giga --non-interactive --help' to list it and 'giga completion "
            "<bash|zsh|fish|powershell>' for shell setup."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"GigaLoom {__version__} (gpt2giga-harness)",
    )
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--session", dest="session_id", default=None)
    parser.add_argument("--attach", default=None, metavar="URL")
    parser.add_argument(
        "--bootstrap-token-env",
        default="GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN",
        metavar="NAME",
        help="Environment variable containing the explicit attach bootstrap token.",
    )
    parser.add_argument("--locale", choices=("en", "ru"), default=None)
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument(
        "--no-animation",
        action="store_true",
        help="Disable animations and smooth scrolling for reduced-motion terminals.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    launch_intent: TuiLaunchIntent | None = None,
) -> int:
    """Run the built-in TUI or report an incomplete installation."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"GigaLoom {__version__} (gpt2giga-harness)")
        return 0
    args = build_parser().parse_args(arguments)
    with _presentation_environment(
        no_color=args.no_color,
        no_animation=args.no_animation,
    ):
        try:
            app_module = importlib.import_module("gpt2giga_harness.tui.app")
        except ModuleNotFoundError as exc:
            if exc.name == "textual":
                print(
                    "The standard Harness installation is incomplete: Textual is "
                    "missing. Reinstall 'gpt2giga-harness' and retry.",
                    file=sys.stderr,
                )
                return 2
            raise
        intent = launch_intent or TuiLaunchIntent()
        intent = replace(
            intent,
            workspace=intent.workspace or args.workspace,
            session_id=intent.session_id or args.session_id,
        )
        config = HarnessConfig.from_env().with_overrides(
            proxy_url=intent.proxy_url,
            auto_start_proxy=intent.auto_start_proxy,
        )
        if args.attach:
            token = os.getenv(args.bootstrap_token_env)
            client = AttachedWorkbenchClient(args.attach, bootstrap_token=token)
        else:
            client = InProcessWorkbenchClient(config)
        application = app_module.WorkbenchTui(
            client,
            workspace=intent.workspace,
            session_id=intent.session_id,
            locale=resolve_locale(args.locale),
            launch_intent=intent,
        )
        application.run(mouse=False)
    return 0


@contextmanager
def _presentation_environment(
    *,
    no_color: bool,
    no_animation: bool,
) -> Iterator[None]:
    """Scope presentation accessibility flags before Textual is imported."""
    updates: dict[str, str] = {}
    if no_color:
        updates["NO_COLOR"] = "1"
    if no_animation:
        updates.update(
            {
                "TEXTUAL_ANIMATIONS": "none",
                "TEXTUAL_SMOOTH_SCROLL": "0",
            }
        )
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
