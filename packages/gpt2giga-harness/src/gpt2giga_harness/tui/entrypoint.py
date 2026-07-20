"""Lazy CLI entry point for the optional Textual client."""

from __future__ import annotations

import argparse
import importlib
import os
import sys

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.tui.client import (
    AttachedWorkbenchClient,
    InProcessWorkbenchClient,
)
from gpt2giga_harness.tui.i18n import resolve_locale


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone TUI argument parser without importing Textual."""
    parser = argparse.ArgumentParser(
        prog="giga tui",
        description="Open the optional provider-neutral terminal workbench.",
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
    """Run the optional TUI or report the exact missing-extra remediation."""
    args = build_parser().parse_args(argv)
    try:
        app_module = importlib.import_module("gpt2giga_harness.tui.app")
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print(
                "The optional TUI is not installed. Install "
                "'gpt2giga-harness[tui]' and retry.",
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
    application.run(mouse=False, ansi_color=False if args.no_color else None)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
