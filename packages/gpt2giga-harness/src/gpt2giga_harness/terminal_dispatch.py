"""Canonical terminal-surface routing contract for Harness console commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import locale
import os
import sys
from typing import Any, Sequence


class ConsoleSurface(str, Enum):
    """Exclusive product owner for a console invocation."""

    TUI_HUMAN_WORKFLOW = "tui_human_workflow"
    NON_INTERACTIVE_AUTOMATION = "non_interactive_automation"
    EXTERNAL_HANDOFF = "external_handoff"


class DispatchReadiness(str, Enum):
    """Whether the selected surface can safely own the invocation."""

    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TerminalContext:
    """Content-free terminal capabilities used by dispatch planning."""

    stdin_is_tty: bool
    stdout_is_tty: bool
    stderr_is_tty: bool
    term: str | None
    ci: bool = False
    terminal_supported: bool = True
    platform: str = sys.platform
    utf8: bool = True
    windows_terminal: bool = False

    @classmethod
    def capture(
        cls,
        *,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        environ: Mapping[str, str] | None = None,
        terminal_supported: bool = True,
        platform: str | None = None,
    ) -> TerminalContext:
        """Capture only routing-relevant process and stream capabilities."""
        environment = os.environ if environ is None else environ
        input_stream = sys.stdin if stdin is None else stdin
        output_stream = sys.stdout if stdout is None else stdout
        error_stream = sys.stderr if stderr is None else stderr
        encoding = (
            getattr(output_stream, "encoding", None)
            or locale.getpreferredencoding(False)
            or ""
        )
        return cls(
            stdin_is_tty=bool(input_stream.isatty()),
            stdout_is_tty=bool(output_stream.isatty()),
            stderr_is_tty=bool(error_stream.isatty()),
            term=environment.get("TERM"),
            ci=_environment_truthy(environment.get("CI")),
            terminal_supported=terminal_supported,
            platform=sys.platform if platform is None else platform,
            utf8="utf" in encoding.casefold(),
            windows_terminal=bool(environment.get("WT_SESSION")),
        )

    @property
    def fully_interactive(self) -> bool:
        """Return whether all standard streams are attached to one human terminal."""
        return self.stdin_is_tty and self.stdout_is_tty and self.stderr_is_tty

    @property
    def tui_supported(self) -> bool:
        """Return whether terminal control is safe for the canonical TUI."""
        terminal_control = bool(self.term) and self.term.casefold() != "dumb"
        if self.platform == "win32" and self.windows_terminal:
            terminal_control = True
        return (
            self.fully_interactive
            and not self.ci
            and self.terminal_supported
            and self.platform in {"darwin", "linux", "win32"}
            and self.utf8
            and terminal_control
        )


@dataclass(frozen=True)
class TerminalDispatchPlan:
    """Executable, side-effect-free routing decision for one invocation."""

    surface: ConsoleSurface
    readiness: DispatchReadiness
    command_path: tuple[str, ...]
    initialize_textual: bool
    terminal_control_allowed: bool
    color_allowed: bool
    reason: str
    remediation: str | None = None


_MACHINE_FLAGS = frozenset({"--dry-run", "--json", "--non-interactive"})
_METADATA_FLAGS = frozenset({"--help", "-h", "--version"})
_HUMAN_ROOT_COMMANDS = frozenset({"chat", "session", "tui"})


def _environment_truthy(value: str | None) -> bool:
    return value is not None and value.strip().casefold() not in {
        "",
        "0",
        "false",
        "no",
    }


def plan_terminal_dispatch(
    argv: Sequence[str],
    *,
    context: TerminalContext,
) -> TerminalDispatchPlan:
    """Classify a console invocation without importing or starting Textual."""
    arguments = tuple(argv)
    command = _first_command(arguments)
    command_path = _command_path(arguments, command)
    explicit_tui = command == "tui"

    if _is_metadata_request(arguments):
        if command in {None, "tui"} and "--non-interactive" not in arguments:
            return _ready_plan(
                ConsoleSurface.TUI_HUMAN_WORKFLOW,
                command_path,
                reason="tui_metadata_route",
            )
        return _ready_plan(
            ConsoleSurface.NON_INTERACTIVE_AUTOMATION,
            command_path,
            reason="metadata_route",
        )

    if command == "open":
        return _ready_plan(
            ConsoleSurface.EXTERNAL_HANDOFF,
            command_path,
            reason="explicit_external_handoff",
        )

    if _is_machine_request(arguments, context):
        if explicit_tui:
            return _blocked_tui(
                command_path, reason="tui_requires_interactive_terminal"
            )
        return _ready_plan(
            ConsoleSurface.NON_INTERACTIVE_AUTOMATION,
            command_path,
            reason="explicit_or_detected_machine_route",
        )

    if not _is_human_workflow(arguments, command):
        return _ready_plan(
            ConsoleSurface.NON_INTERACTIVE_AUTOMATION,
            command_path,
            reason="automation_or_admin_command",
        )

    if not context.tui_supported:
        return _blocked_tui(command_path, reason="unsupported_terminal_environment")

    return TerminalDispatchPlan(
        surface=ConsoleSurface.TUI_HUMAN_WORKFLOW,
        readiness=DispatchReadiness.READY,
        command_path=command_path,
        initialize_textual=True,
        terminal_control_allowed=True,
        color_allowed="--no-color" not in arguments,
        reason="canonical_human_terminal_frontend",
    )


def _first_command(arguments: tuple[str, ...]) -> str | None:
    return next(
        (argument for argument in arguments if not argument.startswith("-")), None
    )


def _command_path(arguments: tuple[str, ...], command: str | None) -> tuple[str, ...]:
    if command is None:
        return ()
    index = arguments.index(command)
    path = [command]
    for argument in arguments[index + 1 :]:
        if argument.startswith("-"):
            continue
        if command in {"open", "session"}:
            path.append(argument)
        break
    return tuple(path)


def _is_metadata_request(arguments: tuple[str, ...]) -> bool:
    return any(argument in _METADATA_FLAGS for argument in arguments)


def _is_machine_request(arguments: tuple[str, ...], context: TerminalContext) -> bool:
    return (
        any(argument in _MACHINE_FLAGS for argument in arguments)
        or context.ci
        or not context.fully_interactive
    )


def _is_human_workflow(arguments: tuple[str, ...], command: str | None) -> bool:
    if command is None:
        return True
    if command in _HUMAN_ROOT_COMMANDS:
        return True
    return command == "run" and "--agent" in arguments


def _ready_plan(
    surface: ConsoleSurface,
    command_path: tuple[str, ...],
    *,
    reason: str,
) -> TerminalDispatchPlan:
    return TerminalDispatchPlan(
        surface=surface,
        readiness=DispatchReadiness.READY,
        command_path=command_path,
        initialize_textual=False,
        terminal_control_allowed=False,
        color_allowed=False,
        reason=reason,
    )


def _blocked_tui(
    command_path: tuple[str, ...],
    *,
    reason: str,
) -> TerminalDispatchPlan:
    return TerminalDispatchPlan(
        surface=ConsoleSurface.TUI_HUMAN_WORKFLOW,
        readiness=DispatchReadiness.BLOCKED,
        command_path=command_path,
        initialize_textual=False,
        terminal_control_allowed=False,
        color_allowed=False,
        reason=reason,
        remediation=(
            "Use a supported interactive terminal, or choose an explicit "
            "non-interactive command route."
        ),
    )
