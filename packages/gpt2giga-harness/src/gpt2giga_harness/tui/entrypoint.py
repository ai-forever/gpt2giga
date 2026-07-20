"""Low-overhead CLI entry point for the built-in Textual client."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import importlib
import os
import sys

from gpt2giga_harness import __version__
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.tui.client import (
    AttachedWorkbenchClient,
    InProcessWorkbenchClient,
)
from gpt2giga_harness.tui.i18n import resolve_locale


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone TUI argument parser without importing Textual."""
    parser = argparse.ArgumentParser(
        prog="giga",
        description="Open the built-in provider-neutral terminal workbench.",
        epilog=(
            "Automation and administration commands remain available through "
            "explicit subcommands; use 'giga --non-interactive --help' to list "
            "that command API."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gpt2giga-harness {__version__}",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the built-in TUI or report an incomplete installation."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"gpt2giga-harness {__version__}")
        return 0
    args = build_parser().parse_args(arguments)
    with _no_color_environment(args.no_color):
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
        config = HarnessConfig.from_env()
        if args.attach:
            token = os.getenv(args.bootstrap_token_env)
            client = AttachedWorkbenchClient(args.attach, bootstrap_token=token)
        else:
            client = InProcessWorkbenchClient(config)
        application = app_module.WorkbenchTui(
            client,
            workspace=args.workspace,
            session_id=args.session_id,
            locale=resolve_locale(args.locale),
        )
        application.run(mouse=False)
    return 0


@contextmanager
def _no_color_environment(enabled: bool) -> Iterator[None]:
    """Apply the standard NO_COLOR contract before Textual is imported."""
    if not enabled:
        yield
        return
    previous = os.environ.get("NO_COLOR")
    os.environ["NO_COLOR"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = previous


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
