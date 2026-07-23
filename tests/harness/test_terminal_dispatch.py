from __future__ import annotations

import io
import os

import pytest

from gpt2giga_harness.terminal_dispatch import (
    CLASSIFIED_ROOT_COMMANDS,
    ConsoleSurface,
    DispatchReadiness,
    TerminalContext,
    plan_terminal_dispatch,
)


PTY = TerminalContext(
    stdin_is_tty=True,
    stdout_is_tty=True,
    stderr_is_tty=True,
    term="xterm-256color",
)
PIPE = TerminalContext(
    stdin_is_tty=False,
    stdout_is_tty=False,
    stderr_is_tty=True,
    term="xterm-256color",
)


@pytest.mark.parametrize(
    "argv",
    (
        (),
        ("tui",),
        ("chat", "inspect"),
        ("run", "--agent", "codex", "inspect"),
        ("session", "list"),
        ("session", "turn", "sess_1", "--prompt", "inspect"),
    ),
)
def test_interactive_human_paths_target_the_canonical_tui(argv):
    plan = plan_terminal_dispatch(argv, context=PTY)

    assert plan.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW
    assert plan.readiness is DispatchReadiness.READY
    assert plan.initialize_textual is True
    assert plan.terminal_control_allowed is True


@pytest.mark.parametrize(
    "argv",
    (
        ("bootstrap", "preview"),
        ("doctor",),
        ("completion", "bash"),
        ("config", "path"),
        ("run", "provenance", "run_1"),
        ("run", "--agent", "codex", "--json", "inspect"),
        ("chat", "--dry-run", "inspect"),
        ("session", "list", "--non-interactive"),
        ("--non-interactive", "--help"),
        ("open", "--help"),
    ),
)
def test_machine_and_admin_paths_never_initialize_textual_or_allow_ansi(argv):
    plan = plan_terminal_dispatch(argv, context=PTY)

    assert plan.surface is ConsoleSurface.NON_INTERACTIVE_AUTOMATION
    assert plan.readiness is DispatchReadiness.READY
    assert plan.initialize_textual is False
    assert plan.terminal_control_allowed is False


@pytest.mark.parametrize("argv", (("tui", "--help"), ("--help",), ("--version",)))
def test_root_metadata_belongs_to_tui_without_initializing_textual(argv):
    plan = plan_terminal_dispatch(argv, context=PIPE)

    assert plan.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW
    assert plan.readiness is DispatchReadiness.READY
    assert plan.initialize_textual is False
    assert plan.terminal_control_allowed is False


@pytest.mark.parametrize(
    "context",
    (
        PIPE,
        TerminalContext(True, True, True, "xterm-256color", ci=True),
    ),
)
def test_pipe_and_ci_make_implicit_human_paths_non_interactive(context):
    plan = plan_terminal_dispatch(
        ("run", "--agent", "gemini", "inspect"),
        context=context,
    )

    assert plan.surface is ConsoleSurface.NON_INTERACTIVE_AUTOMATION
    assert plan.initialize_textual is False
    assert plan.terminal_control_allowed is False


@pytest.mark.parametrize(
    "context",
    (
        PIPE,
        TerminalContext(True, True, True, "dumb"),
        TerminalContext(True, True, True, "xterm-256color", terminal_supported=False),
    ),
)
def test_explicit_tui_fails_closed_in_unsupported_environments(context):
    plan = plan_terminal_dispatch(("tui",), context=context)

    assert plan.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW
    assert plan.readiness is DispatchReadiness.BLOCKED
    assert plan.initialize_textual is False
    assert plan.terminal_control_allowed is False
    assert plan.remediation


def test_term_dumb_requires_an_explicit_automation_escape_for_human_paths():
    context = TerminalContext(True, True, True, "dumb")

    blocked = plan_terminal_dispatch(("chat", "inspect"), context=context)
    escaped = plan_terminal_dispatch(
        ("chat", "--non-interactive", "inspect"), context=context
    )

    assert blocked.readiness is DispatchReadiness.BLOCKED
    assert blocked.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW
    assert escaped.readiness is DispatchReadiness.READY
    assert escaped.surface is ConsoleSurface.NON_INTERACTIVE_AUTOMATION


@pytest.mark.parametrize(
    "argv",
    (
        ("open", "session", "sess_1"),
        ("open", "run", "run_1"),
        ("open", "file", "README.md"),
    ),
)
def test_open_commands_are_explicit_external_handoffs(argv):
    plan = plan_terminal_dispatch(argv, context=PTY)

    assert plan.surface is ConsoleSurface.EXTERNAL_HANDOFF
    assert plan.readiness is DispatchReadiness.READY
    assert plan.initialize_textual is False
    assert plan.terminal_control_allowed is False


def test_no_color_preserves_tui_ownership_without_color_output():
    plan = plan_terminal_dispatch(("tui", "--no-color"), context=PTY)

    assert plan.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW
    assert plan.initialize_textual is True
    assert plan.color_allowed is False


@pytest.mark.parametrize(
    "context",
    (
        TerminalContext(True, True, True, "xterm-256color", platform="darwin"),
        TerminalContext(True, True, True, "xterm", platform="linux"),
        TerminalContext(True, True, True, "screen", platform="linux"),
        TerminalContext(True, True, True, "tmux-256color", platform="darwin"),
        TerminalContext(
            True,
            True,
            True,
            None,
            platform="win32",
            windows_terminal=True,
        ),
        TerminalContext(True, True, True, "vt100", platform="linux"),
    ),
)
def test_supported_cross_platform_utf8_terminal_families_are_admitted(context):
    assert context.tui_supported is True


@pytest.mark.parametrize(
    "context",
    (
        TerminalContext(True, True, True, "xterm", platform="freebsd"),
        TerminalContext(True, True, True, "xterm", platform="linux", utf8=False),
        TerminalContext(True, True, True, None, platform="win32"),
    ),
)
def test_unverified_or_non_utf8_terminals_fail_before_textual_import(context):
    plan = plan_terminal_dispatch(("tui",), context=context)

    assert plan.readiness is DispatchReadiness.BLOCKED
    assert plan.initialize_textual is False
    assert plan.terminal_control_allowed is False


def test_terminal_context_captures_real_pty_and_non_pty_streams():
    master_fd, slave_fd = os.openpty()
    try:
        with (
            os.fdopen(os.dup(slave_fd), "rb") as stdin,
            os.fdopen(os.dup(slave_fd), "wb") as stdout,
            os.fdopen(os.dup(slave_fd), "wb") as stderr,
        ):
            pty_context = TerminalContext.capture(
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                environ={"TERM": "xterm-256color"},
                platform="darwin",
            )
        pipe_context = TerminalContext.capture(
            stdin=io.StringIO(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            environ={"TERM": "xterm-256color", "CI": "true"},
        )
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert pty_context.fully_interactive is True
    assert pty_context.tui_supported is True
    assert pipe_context.fully_interactive is False
    assert pipe_context.ci is True
    assert pipe_context.tui_supported is False


def test_console_handler_inventory_matches_the_cli_parser():
    from gpt2giga_harness.cli import build_parser

    parser = build_parser()
    command_action = next(
        action for action in parser._actions if action.dest == "command"
    )

    assert set(command_action.choices) | {"tui"} == CLASSIFIED_ROOT_COMMANDS


@pytest.mark.parametrize(
    "argv",
    (
        ("session", "events", "run_1"),
        ("session", "approve", "approval_1", "--decision", "deny"),
        ("session", "list", "--include-archived"),
        ("session", "list", "--harness", "echo"),
    ),
)
def test_session_admin_and_extended_inventory_routes_remain_automation(argv):
    plan = plan_terminal_dispatch(argv, context=PTY)

    assert plan.surface is ConsoleSurface.NON_INTERACTIVE_AUTOMATION
    assert plan.initialize_textual is False


def test_root_tui_options_do_not_become_false_commands():
    plan = plan_terminal_dispatch(("--workspace", ".", "--locale", "ru"), context=PTY)

    assert plan.surface is ConsoleSurface.TUI_HUMAN_WORKFLOW
    assert plan.command_path == ()
