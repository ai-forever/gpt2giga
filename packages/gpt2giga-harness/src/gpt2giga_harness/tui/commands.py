"""Shared command and runtime-control registry for the canonical TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from textual.binding import Binding


@dataclass(frozen=True)
class CommandSpec:
    """One discoverable Workbench command exposed through every TUI surface."""

    id: str
    slash: str
    action: str
    title_key: str
    description_key: str
    key: str | None = None
    requires_session: bool = False
    control_id: str | None = None
    show_in_footer: bool = False


@dataclass(frozen=True)
class RuntimeControlState:
    """Contextual presentation state for one provider-neutral runtime control."""

    id: str
    current: str
    effect_scope: str
    state: str
    limitation: str | None = None
    remediation: str | None = None


COMMAND_REGISTRY: tuple[CommandSpec, ...] = (
    CommandSpec(
        "commands",
        "/commands",
        "command_palette",
        "command.commands",
        "command.commands.help",
        "ctrl+p",
    ),
    CommandSpec(
        "status", "/status", "status_view", "command.status", "command.status.help"
    ),
    CommandSpec(
        "project",
        "/project",
        "choose_project",
        "command.project",
        "command.project.help",
        "p",
    ),
    CommandSpec(
        "new-session",
        "/new",
        "new_session",
        "command.new_session",
        "command.new_session.help",
        "n",
        show_in_footer=True,
    ),
    CommandSpec(
        "sessions",
        "/sessions",
        "sessions",
        "command.sessions",
        "command.sessions.help",
        "s",
    ),
    CommandSpec(
        "rename-session",
        "/rename",
        "rename_session",
        "command.rename_session",
        "command.rename_session.help",
        requires_session=True,
    ),
    CommandSpec(
        "archive-session",
        "/archive",
        "archive_session",
        "command.archive_session",
        "command.archive_session.help",
        requires_session=True,
    ),
    CommandSpec(
        "delete-session",
        "/delete",
        "delete_session",
        "command.delete_session",
        "command.delete_session.help",
        requires_session=True,
    ),
    CommandSpec(
        "fork-session",
        "/fork",
        "fork_session",
        "command.fork_session",
        "command.fork_session.help",
        requires_session=True,
    ),
    CommandSpec(
        "transcript-search",
        "/search",
        "transcript_search",
        "command.transcript_search",
        "command.transcript_search.help",
        requires_session=True,
    ),
    CommandSpec(
        "export-session",
        "/export",
        "export_session",
        "command.export_session",
        "command.export_session.help",
        requires_session=True,
    ),
    CommandSpec("tasks", "/tasks", "tasks", "command.tasks", "command.tasks.help"),
    CommandSpec(
        "processes",
        "/processes",
        "processes",
        "command.processes",
        "command.processes.help",
    ),
    CommandSpec("usage", "/usage", "usage", "command.usage", "command.usage.help"),
    CommandSpec(
        "preferences",
        "/preferences",
        "preferences",
        "command.preferences",
        "command.preferences.help",
    ),
    CommandSpec(
        "integrations",
        "/integrations",
        "integrations",
        "command.integrations",
        "command.integrations.help",
    ),
    CommandSpec(
        "refresh",
        "/refresh",
        "refresh",
        "command.refresh",
        "command.refresh.help",
        "r",
        show_in_footer=True,
    ),
    CommandSpec(
        "environment-commit",
        "/commit",
        "environment_commit",
        "command.environment_commit",
        "command.environment_commit.help",
        requires_session=True,
    ),
    CommandSpec(
        "files", "/files", "files", "command.files", "command.files.help", "a", True
    ),
    CommandSpec(
        "evidence",
        "/evidence",
        "evidence",
        "command.evidence",
        "command.evidence.help",
        "e",
        True,
    ),
    CommandSpec(
        "terminal",
        "/terminal",
        "native_terminal",
        "command.terminal",
        "command.terminal.help",
        "t",
        True,
    ),
    CommandSpec(
        "provider-handoff",
        "/provider-ui",
        "provider_handoff",
        "command.provider_handoff",
        "command.provider_handoff.help",
        "o",
        True,
    ),
    CommandSpec(
        "web-handoff",
        "/web",
        "web_handoff",
        "command.web_handoff",
        "command.web_handoff.help",
        "w",
        True,
    ),
    CommandSpec(
        "harness",
        "/harness",
        "runtime_control('harness')",
        "control.harness",
        "control.harness.help",
        control_id="harness",
    ),
    CommandSpec(
        "model",
        "/model",
        "runtime_control('model')",
        "control.model",
        "control.model.help",
        control_id="model",
    ),
    CommandSpec(
        "effort",
        "/effort",
        "runtime_control('effort')",
        "control.effort",
        "control.effort.help",
        control_id="effort",
    ),
    CommandSpec(
        "mode",
        "/mode",
        "runtime_control('mode')",
        "control.mode",
        "control.mode.help",
        control_id="mode",
    ),
    CommandSpec(
        "permission",
        "/permission",
        "runtime_control('permission')",
        "control.permission",
        "control.permission.help",
        control_id="permission",
    ),
    CommandSpec(
        "policy",
        "/policy",
        "runtime_control('policy')",
        "control.policy",
        "control.policy.help",
        control_id="policy",
    ),
    CommandSpec(
        "sandbox",
        "/sandbox",
        "runtime_control('sandbox')",
        "control.sandbox",
        "control.sandbox.help",
        control_id="sandbox",
    ),
    CommandSpec(
        "help",
        "/help",
        "help",
        "command.help",
        "command.help.help",
        "?",
        show_in_footer=True,
    ),
    CommandSpec(
        "quit",
        "/quit",
        "quit",
        "command.quit",
        "command.quit.help",
        "q",
        show_in_footer=True,
    ),
)


def command_bindings(translate: Callable[[str], str]) -> list[Binding]:
    """Build keyboard bindings and footer labels from the shared registry."""
    return [
        Binding(
            command.key,
            command.action,
            translate(command.title_key),
            show=command.show_in_footer,
        )
        for command in COMMAND_REGISTRY
        if command.key is not None
    ]


def slash_commands() -> tuple[str, ...]:
    """Return canonical slash completions in registry order."""
    return tuple(command.slash for command in COMMAND_REGISTRY)


def command_for_slash(value: str) -> CommandSpec | None:
    """Resolve one exact slash command without interpreting its arguments."""
    token = value.strip().split(maxsplit=1)[0]
    return next((item for item in COMMAND_REGISTRY if item.slash == token), None)


def visible_commands(*, has_session: bool) -> Iterable[CommandSpec]:
    """Hide commands that cannot be meaningful in the current context."""
    return (
        command
        for command in COMMAND_REGISTRY
        if has_session or not command.requires_session
    )
