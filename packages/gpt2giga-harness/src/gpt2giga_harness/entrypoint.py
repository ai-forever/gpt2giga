"""Low-overhead console entry point for the canonical Harness TUI and CLI."""

from __future__ import annotations

import sys

from gpt2giga_harness.terminal_dispatch import TerminalContext


def main(argv: list[str] | None = None) -> int:
    """Launch the built-in TUI by default or an explicit command API route."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if _is_tui_invocation(arguments):
        if not _is_tui_metadata(arguments) and not _tui_environment_supported():
            print(
                "The built-in TUI requires a supported interactive terminal. "
                "Use an explicit automation/admin command for redirected or CI use.",
                file=sys.stderr,
            )
            return 2
        from gpt2giga_harness.tui.entrypoint import main as tui_main

        return tui_main(arguments[1:] if arguments[:1] == ["tui"] else arguments)

    from gpt2giga_harness.cli import main as cli_main

    return cli_main(arguments)


def _is_tui_invocation(arguments: list[str]) -> bool:
    """Return whether arguments belong to the default human terminal surface."""
    if not arguments or arguments[0] == "tui":
        return True
    if arguments[0] == "--non-interactive":
        return False
    return arguments[0].startswith("-")


def _is_tui_metadata(arguments: list[str]) -> bool:
    return any(argument in {"-h", "--help", "--version"} for argument in arguments)


def _tui_environment_supported() -> bool:
    return TerminalContext.capture().tui_supported
