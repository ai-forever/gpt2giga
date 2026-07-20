"""Low-overhead console entry point for the Harness CLI."""

from __future__ import annotations

import sys

from gpt2giga_harness import __version__


def main(argv: list[str] | None = None) -> int:
    """Handle metadata-only commands before importing the full CLI runtime."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"gpt2giga-harness {__version__}")
        return 0
    if arguments and arguments[0] == "tui":
        from gpt2giga_harness.tui.entrypoint import main as tui_main

        return tui_main(arguments[1:])

    from gpt2giga_harness.cli import main as cli_main

    return cli_main(arguments)
