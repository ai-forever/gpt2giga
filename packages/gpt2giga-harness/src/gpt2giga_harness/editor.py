"""Safe editor command planning for the Unified Harness cockpit."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
from typing import Any, Mapping

from gpt2giga_harness.sessions.models import HarnessRun
from gpt2giga_harness.safe_paths import (
    PathBoundaryError,
    resolve_operator_path,
    resolve_path_within,
)

DEFAULT_EDITOR_COMMAND = "code"
DEFAULT_TERMINAL_COMMAND = "auto"
SUPPORTED_EDITOR_COMMANDS = {
    "atom",
    "code",
    "code-insiders",
    "codium",
    "cursor",
    "emacs",
    "mate",
    "nvim",
    "open",
    "subl",
    "sublime_text",
    "vim",
    "zed",
}
SUPPORTED_TERMINAL_COMMANDS = {
    "alacritty",
    "foot",
    "gnome-terminal",
    "kitty",
    "konsole",
    "open",
    "wezterm",
    "wt",
    "x-terminal-emulator",
    "xfce4-terminal",
}
SUPPORTED_MACOS_TERMINAL_APPS = {"iTerm", "iTerm2", "Terminal", "Warp"}


class EditorOpenError(ValueError):
    """Raised when an editor target or command is unsafe or unavailable."""


@dataclass(frozen=True)
class EditorOpenPlan:
    """A shell-free editor open plan suitable for API/CLI display or execution."""

    kind: str
    target_path: str
    workspace: str | None
    command: tuple[str, ...]
    command_display: str
    exists: bool
    dry_run: bool = True
    executed: bool = False


def parse_editor_command(command: str | None = None) -> tuple[str, ...]:
    """Parse and validate a configured editor command without invoking a shell."""
    text = (command or DEFAULT_EDITOR_COMMAND).strip()
    if not text:
        raise EditorOpenError("Editor command must not be empty.")
    if any(ord(char) < 32 for char in text):
        raise EditorOpenError("Editor command must not contain control characters.")
    try:
        parts = tuple(shlex.split(text, posix=True))
    except ValueError as exc:
        raise EditorOpenError(f"Invalid editor command: {exc}") from exc
    if not parts:
        raise EditorOpenError("Editor command must not be empty.")
    executable = Path(parts[0]).name
    if executable not in SUPPORTED_EDITOR_COMMANDS:
        raise EditorOpenError(
            "Unsupported editor command. Supported commands: "
            f"{', '.join(sorted(SUPPORTED_EDITOR_COMMANDS))}"
        )
    return parts


def parse_terminal_command(command: str | None = None) -> tuple[str, ...]:
    """Parse a terminal launcher without allowing an embedded shell command."""
    text = (command or DEFAULT_TERMINAL_COMMAND).strip()
    if text == DEFAULT_TERMINAL_COMMAND:
        return _default_terminal_command()
    if not text:
        raise EditorOpenError("Terminal command must not be empty.")
    if any(ord(char) < 32 for char in text):
        raise EditorOpenError("Terminal command must not contain control characters.")
    try:
        parts = tuple(shlex.split(text, posix=True))
    except ValueError as exc:
        raise EditorOpenError(f"Invalid terminal command: {exc}") from exc
    if not parts:
        raise EditorOpenError("Terminal command must not be empty.")
    executable = Path(parts[0]).name
    if executable not in SUPPORTED_TERMINAL_COMMANDS:
        raise EditorOpenError(
            "Unsupported terminal command. Supported commands: "
            f"{', '.join(sorted(SUPPORTED_TERMINAL_COMMANDS))}"
        )
    if parts[0] != executable:
        raise EditorOpenError(
            "Terminal command must use an allowlisted launcher name without a path."
        )
    if executable == "open":
        if (
            len(parts) != 3
            or parts[1] != "-a"
            or parts[2] not in SUPPORTED_MACOS_TERMINAL_APPS
        ):
            raise EditorOpenError(
                "macOS terminal command must be 'open -a' followed by one of: "
                f"{', '.join(sorted(SUPPORTED_MACOS_TERMINAL_APPS))}"
            )
    elif len(parts) != 1:
        raise EditorOpenError(
            "Terminal command must contain only an allowlisted launcher name."
        )
    return parts


def build_open_workspace_plan(
    workspace: str | Path,
    *,
    command: str | None = None,
) -> EditorOpenPlan:
    """Build an editor plan that opens a workspace directory."""
    path = resolve_operator_path(workspace)
    if not path.exists() or not path.is_dir():
        raise EditorOpenError(f"Workspace does not exist: {path}")
    command_parts = (*parse_editor_command(command), str(path))
    return _plan(
        kind="workspace",
        target_path=path,
        workspace=path,
        command=command_parts,
    )


def build_open_file_plan(
    workspace: str | Path,
    file_path: str | Path,
    *,
    command: str | None = None,
    line: int | None = None,
    column: int | None = None,
) -> EditorOpenPlan:
    """Build an editor plan that opens a file inside a workspace."""
    root = resolve_operator_path(workspace)
    if not root.exists() or not root.is_dir():
        raise EditorOpenError(f"Workspace does not exist: {root}")
    target = _resolve_inside(root, file_path)
    if target.exists() and not target.is_file():
        raise EditorOpenError(f"Editor target is not a file: {target}")
    command_parts = parse_editor_command(command)
    target_arg = _target_arg_for_editor(command_parts, target, line=line, column=column)
    if _supports_goto(command_parts[0]) and (line is not None or column is not None):
        command_parts = (*command_parts, "--goto", target_arg)
    else:
        command_parts = (*command_parts, target_arg)
    return _plan(
        kind="file",
        target_path=target,
        workspace=root,
        command=command_parts,
    )


def build_open_run_workspace_plan(
    run: HarnessRun,
    *,
    command: str | None = None,
) -> EditorOpenPlan:
    """Build an editor plan for the best workspace associated with a run."""
    workspace = workspace_for_run(run)
    if workspace is None:
        raise EditorOpenError("Run does not have a workspace to open.")
    return build_open_workspace_plan(workspace, command=command)


def build_open_terminal_plan(
    workspace: str | Path,
    *,
    command: str | None = None,
) -> EditorOpenPlan:
    """Build a shell-free plan that opens a terminal in a workspace."""
    path = resolve_operator_path(workspace)
    if not path.exists() or not path.is_dir():
        raise EditorOpenError(f"Workspace does not exist: {path}")
    command_parts = _terminal_command_for_workspace(
        parse_terminal_command(command),
        path,
    )
    return _plan(
        kind="terminal",
        target_path=path,
        workspace=path,
        command=command_parts,
    )


def build_open_diff_plan(
    run: HarnessRun,
    *,
    data_dir: str | Path,
    command: str | None = None,
) -> EditorOpenPlan:
    """Write a run patch to a transparent diff file and build an editor plan."""
    patch = _patch_for_run(run)
    if not patch or patch == "No diff captured.":
        raise EditorOpenError("Run has no captured diff to open.")
    diff_dir = Path(data_dir).expanduser() / "editor" / "diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    diff_path = diff_dir / f"{_safe_path_part(run.id)}.diff"
    header = (
        f"# gpt2giga run diff\n"
        f"# run_id: {run.id}\n"
        f"# session_id: {run.session_id}\n"
        f"# harness_id: {run.harness_id}\n\n"
    )
    diff_path.write_text(header + patch, encoding="utf-8")
    command_parts = (*parse_editor_command(command), str(diff_path.resolve()))
    workspace = _existing_workspace_or_default(workspace_for_run(run), diff_dir)
    return _plan(
        kind="diff",
        target_path=diff_path.resolve(),
        workspace=workspace,
        command=command_parts,
    )


def execute_editor_plan(
    plan: EditorOpenPlan,
    *,
    dry_run: bool,
) -> EditorOpenPlan:
    """Execute an editor open plan unless dry-run mode is requested."""
    if dry_run:
        return replace(plan, dry_run=True, executed=False)
    try:
        subprocess.Popen(
            plan.command,
            cwd=plan.workspace,
            start_new_session=True,
        )
    except OSError as exc:
        raise EditorOpenError(f"Could not start {plan.kind} launcher: {exc}") from exc
    return replace(plan, dry_run=False, executed=True)


def editor_open_plan_to_dict(plan: EditorOpenPlan) -> dict[str, Any]:
    """Serialize an editor open plan for API and CLI responses."""
    return {
        "kind": plan.kind,
        "target_path": plan.target_path,
        "workspace": plan.workspace,
        "command": list(plan.command),
        "command_display": plan.command_display,
        "exists": plan.exists,
        "dry_run": plan.dry_run,
        "executed": plan.executed,
    }


def workspace_for_run(run: HarnessRun) -> str | None:
    """Return the best workspace path for a stored run."""
    execution = _workspace_execution(run.metadata)
    for key in ("worktree_path", "effective_workspace", "source_workspace"):
        value = _optional_text(execution.get(key))
        if value:
            return value
    return run.workspace


def _plan(
    *,
    kind: str,
    target_path: Path,
    workspace: Path | None,
    command: tuple[str, ...],
) -> EditorOpenPlan:
    return EditorOpenPlan(
        kind=kind,
        target_path=str(target_path),
        workspace=str(workspace) if workspace is not None else None,
        command=command,
        command_display=shlex.join(command),
        exists=target_path.exists(),
    )


def _resolve_inside(root: Path, value: str | Path) -> Path:
    try:
        return resolve_path_within(root, value)
    except PathBoundaryError as exc:
        raise EditorOpenError("Editor target must stay inside the workspace.") from exc


def _target_arg_for_editor(
    command: tuple[str, ...],
    target: Path,
    *,
    line: int | None,
    column: int | None,
) -> str:
    if not _supports_goto(command[0]):
        return str(target)
    if line is None and column is None:
        return str(target)
    clean_line = max(int(line or 1), 1)
    clean_column = max(int(column or 1), 1)
    return f"{target}:{clean_line}:{clean_column}"


def _supports_goto(executable: str) -> bool:
    return Path(executable).name in {"code", "code-insiders", "codium", "cursor"}


def _default_terminal_command() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("open", "-a", "Terminal")
    if sys.platform == "win32":
        return ("wt",)
    for executable in (
        "x-terminal-emulator",
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "kitty",
        "wezterm",
        "alacritty",
        "foot",
    ):
        if shutil.which(executable):
            return (executable,)
    return ("x-terminal-emulator",)


def _terminal_command_for_workspace(
    command: tuple[str, ...],
    workspace: Path,
) -> tuple[str, ...]:
    executable = Path(command[0]).name
    if executable == "open":
        return (*command, str(workspace))
    if executable in {"alacritty", "foot", "gnome-terminal", "xfce4-terminal"}:
        return (*command, "--working-directory", str(workspace))
    if executable == "kitty":
        return (*command, "--directory", str(workspace))
    if executable == "konsole":
        return (*command, "--workdir", str(workspace))
    if executable == "wezterm":
        return (*command, "start", "--cwd", str(workspace))
    if executable == "wt":
        return (*command, "-d", str(workspace))
    return command


def _patch_for_run(run: HarnessRun) -> str:
    execution = _workspace_execution(run.metadata)
    patch = execution.get("patch") or run.metadata.get("diff")
    return str(patch or "")


def _workspace_execution(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    value = metadata.get("workspace_execution")
    return value if isinstance(value, Mapping) else {}


def _existing_workspace_or_default(value: str | None, default: Path) -> Path:
    if value is not None:
        path = Path(value).expanduser().resolve()
        if path.exists() and path.is_dir():
            return path
    return default.resolve()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in value)
