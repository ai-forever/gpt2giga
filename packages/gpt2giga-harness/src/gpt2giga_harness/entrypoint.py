"""Low-overhead console entry point for the canonical Harness TUI and CLI."""

from __future__ import annotations

import sys

from gpt2giga_harness.native_cli_facade import run_native_namespace
from gpt2giga_harness.terminal_dispatch import (
    ConsoleSurface,
    DispatchReadiness,
    TerminalContext,
    plan_terminal_dispatch,
)


def main(
    argv: list[str] | None = None,
    *,
    context: TerminalContext | None = None,
) -> int:
    """Launch the built-in TUI by default or an explicit command API route."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    terminal_context = context or TerminalContext.capture()
    native_result = run_native_namespace(
        arguments,
        facade_executable=sys.argv[0],
        context=terminal_context,
    )
    if native_result is not None:
        return native_result
    plan = plan_terminal_dispatch(
        arguments,
        context=terminal_context,
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
        from gpt2giga_harness.terminal_intent import parse_tui_launch_intent

        launch_intent, tui_arguments = parse_tui_launch_intent(arguments)
        return tui_main(tui_arguments, launch_intent=launch_intent)

    from gpt2giga_harness.cli import main as cli_main

    return cli_main(arguments)
