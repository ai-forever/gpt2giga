"""Low-overhead console entry point for the canonical Harness TUI and CLI."""

from __future__ import annotations

import sys

from gpt2giga_harness.terminal_dispatch import (
    ConsoleSurface,
    DispatchReadiness,
    TerminalContext,
    plan_terminal_dispatch,
)
from gpt2giga_harness.terminal_intent import parse_tui_launch_intent


def main(
    argv: list[str] | None = None,
    *,
    context: TerminalContext | None = None,
) -> int:
    """Launch the built-in TUI by default or an explicit command API route."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    plan = plan_terminal_dispatch(
        arguments,
        context=context or TerminalContext.capture(),
    )
    if plan.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW:
        if plan.readiness is DispatchReadiness.BLOCKED:
            print(
                "The built-in TUI requires a supported interactive terminal. "
                "Use an explicit automation/admin command for redirected or CI use.",
                file=sys.stderr,
            )
            return 2
        from gpt2giga_harness.tui.entrypoint import main as tui_main

        launch_intent, tui_arguments = parse_tui_launch_intent(arguments)
        return tui_main(tui_arguments, launch_intent=launch_intent)

    from gpt2giga_harness.cli import main as cli_main

    return cli_main(arguments)
