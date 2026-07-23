"""Portable, content-free process kernel for native CLI passthrough."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import errno
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import cast

from gpt2giga_harness.native_cli_contracts import NativeNamespaceSpec


class NativeProcessPlatform(str, Enum):
    """Process-launch contract selected for the current operating system."""

    POSIX = "posix"
    WINDOWS = "windows"


class NativeExecutableKind(str, Enum):
    """Reviewed executable form after one bounded PATH lookup."""

    POSIX = "posix"
    WINDOWS_EXECUTABLE = "windows_executable"
    WINDOWS_SHIM = "windows_shim"


class NativeResolutionStatus(str, Enum):
    """Content-free result of resolving one provider executable."""

    READY = "ready"
    MISSING = "missing"
    NON_EXECUTABLE = "non_executable"
    UNSAFE = "unsafe"


@dataclass(frozen=True)
class NativeExecutableResolution:
    """Pinned executable identity or a content-free pre-launch failure."""

    status: NativeResolutionStatus
    kind: NativeExecutableKind | None = None
    path: Path | None = None

    @property
    def exit_code(self) -> int | None:
        """Return the conventional pre-launch result, if resolution failed."""
        if self.status is NativeResolutionStatus.READY:
            return None
        if self.status is NativeResolutionStatus.MISSING:
            return 127
        return 126


@dataclass(frozen=True)
class WindowsLaunchPlan:
    """A Windows direct or reviewed-shim launch without provider content logs."""

    executable: Path
    argv: tuple[str, ...] | str
    kind: NativeExecutableKind


Execve = Callable[[str, Sequence[str], Mapping[str, str]], object]
WindowsSpawner = Callable[..., subprocess.Popen[bytes]]
NativeSpawner = Callable[..., subprocess.Popen[bytes]]


_WINDOWS_META = re.compile(r'([()\[\]{}%!^"`<>&|;,*? ])')
_WINDOWS_QUOTE = re.compile(r'(\\*)"')
_WINDOWS_TRAILING_SLASH = re.compile(r"(\\+)$")


def current_native_platform() -> NativeProcessPlatform:
    """Return the launch contract for the running interpreter."""
    if os.name == "nt":
        return NativeProcessPlatform.WINDOWS
    return NativeProcessPlatform.POSIX


def build_native_environment(
    *,
    inherited: Mapping[str, str] | None = None,
    overrides: Mapping[str, str | None] | None = None,
) -> dict[str, str]:
    """Copy the caller environment and apply explicit override precedence."""
    environment = dict(os.environ if inherited is None else inherited)
    for key, value in (overrides or {}).items():
        _validate_environment_component(key, field="name")
        if value is None:
            environment.pop(key, None)
            continue
        _validate_environment_component(value, field="value")
        environment[key] = value
    return environment


def resolve_native_executable(
    spec: NativeNamespaceSpec,
    *,
    environment: Mapping[str, str],
    facade_executable: str | os.PathLike[str] | None,
    platform: NativeProcessPlatform | None = None,
) -> NativeExecutableResolution:
    """Resolve and pin one provider executable without granting launch authority."""
    selected_platform = platform or current_native_platform()
    search_path = environment.get("PATH", os.defpath)
    if selected_platform is NativeProcessPlatform.WINDOWS:
        pathext = environment.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        candidates = _windows_candidates(spec.executable, search_path, pathext)
    else:
        candidates = _posix_candidates(spec.executable, search_path)

    for candidate, kind in candidates:
        try:
            exists = candidate.exists()
        except OSError:
            continue
        if not exists:
            continue
        try:
            pinned = candidate.resolve(strict=True)
        except OSError:
            return NativeExecutableResolution(NativeResolutionStatus.NON_EXECUTABLE)
        if not pinned.is_file():
            return NativeExecutableResolution(NativeResolutionStatus.NON_EXECUTABLE)
        if _same_file(pinned, facade_executable):
            return NativeExecutableResolution(NativeResolutionStatus.UNSAFE)
        if selected_platform is NativeProcessPlatform.POSIX and not os.access(
            pinned, os.X_OK
        ):
            return NativeExecutableResolution(NativeResolutionStatus.NON_EXECUTABLE)
        return NativeExecutableResolution(
            status=NativeResolutionStatus.READY,
            kind=kind,
            path=pinned,
        )
    return NativeExecutableResolution(NativeResolutionStatus.MISSING)


def run_native_l0(
    spec: NativeNamespaceSpec,
    suffix: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    environment_overrides: Mapping[str, str | None] | None = None,
    facade_executable: str | os.PathLike[str] | None = None,
    platform: NativeProcessPlatform | None = None,
    execve: Execve = os.execve,
    windows_spawner: WindowsSpawner = subprocess.Popen,
    windows_cmd: str | os.PathLike[str] | None = None,
) -> int:
    """Launch one L0 invocation, returning only for failure or on Windows."""
    selected_platform = platform or current_native_platform()
    native_environment = build_native_environment(
        inherited=environment,
        overrides=environment_overrides,
    )
    resolution = resolve_native_executable(
        spec,
        environment=native_environment,
        facade_executable=facade_executable,
        platform=selected_platform,
    )
    if resolution.status is not NativeResolutionStatus.READY:
        _write_prelaunch_diagnostic(spec.namespace, resolution.status)
        return resolution.exit_code or 126

    assert resolution.path is not None
    assert resolution.kind is not None
    native_suffix = tuple(_validate_native_argument(argument) for argument in suffix)
    if selected_platform is NativeProcessPlatform.POSIX:
        try:
            execve(
                os.fspath(resolution.path),
                (spec.executable, *native_suffix),
                native_environment,
            )
        except OSError as exc:
            status = _status_for_exec_error(exc)
            _write_prelaunch_diagnostic(spec.namespace, status)
            return 127 if status is NativeResolutionStatus.MISSING else 126
        raise RuntimeError("execve returned unexpectedly")

    try:
        plan = build_windows_launch_plan(
            resolution,
            native_suffix,
            environment=native_environment,
            windows_cmd=windows_cmd,
        )
        process = windows_spawner(
            plan.argv,
            executable=os.fspath(plan.executable),
            stdin=None,
            stdout=None,
            stderr=None,
            cwd=None,
            env=native_environment,
            shell=False,
            close_fds=False,
            creationflags=0,
        )
    except (OSError, ValueError):
        _write_prelaunch_diagnostic(
            spec.namespace, NativeResolutionStatus.NON_EXECUTABLE
        )
        return 126
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # The child shares the inherited console and receives the same event.
            continue


def run_native_l1_handoff(
    spec: NativeNamespaceSpec,
    suffix: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    environment_overrides: Mapping[str, str | None] | None = None,
    facade_executable: str | os.PathLike[str] | None = None,
    platform: NativeProcessPlatform | None = None,
    spawner: NativeSpawner = subprocess.Popen,
    windows_cmd: str | os.PathLike[str] | None = None,
) -> int:
    """Visibly supervise a provider that temporarily owns the terminal."""
    selected_platform = platform or current_native_platform()
    native_environment = build_native_environment(
        inherited=environment,
        overrides=environment_overrides,
    )
    resolution = resolve_native_executable(
        spec,
        environment=native_environment,
        facade_executable=facade_executable,
        platform=selected_platform,
    )
    if resolution.status is not NativeResolutionStatus.READY:
        _write_prelaunch_diagnostic(spec.namespace, resolution.status)
        return resolution.exit_code or 126
    assert resolution.path is not None
    assert resolution.kind is not None
    native_suffix = tuple(_validate_native_argument(argument) for argument in suffix)
    _write_handoff_notice(spec.namespace)
    terminal_state = _capture_terminal_state()
    try:
        if selected_platform is NativeProcessPlatform.WINDOWS:
            plan = build_windows_launch_plan(
                resolution,
                native_suffix,
                environment=native_environment,
                windows_cmd=windows_cmd,
            )
            argv: Sequence[str] | str = plan.argv
            executable = os.fspath(plan.executable)
            close_fds = False
        else:
            argv = (os.fspath(resolution.path), *native_suffix)
            executable = os.fspath(resolution.path)
            close_fds = True
        process = spawner(
            argv,
            executable=executable,
            stdin=None,
            stdout=None,
            stderr=None,
            cwd=None,
            env=native_environment,
            shell=False,
            close_fds=close_fds,
        )
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The provider shares the foreground console and receives the signal.
                continue
    except (OSError, ValueError):
        _write_prelaunch_diagnostic(
            spec.namespace, NativeResolutionStatus.NON_EXECUTABLE
        )
        return 126
    finally:
        _restore_terminal_state(terminal_state)


def build_windows_launch_plan(
    resolution: NativeExecutableResolution,
    suffix: Sequence[str],
    *,
    environment: Mapping[str, str],
    windows_cmd: str | os.PathLike[str] | None = None,
) -> WindowsLaunchPlan:
    """Build a direct CreateProcess or reviewed cmd-shim launch plan."""
    if (
        resolution.status is not NativeResolutionStatus.READY
        or resolution.path is None
        or resolution.kind is None
    ):
        raise ValueError("a ready executable resolution is required")
    if resolution.kind is NativeExecutableKind.WINDOWS_EXECUTABLE:
        return WindowsLaunchPlan(
            executable=resolution.path,
            argv=(os.fspath(resolution.path), *suffix),
            kind=resolution.kind,
        )
    if resolution.kind is not NativeExecutableKind.WINDOWS_SHIM:
        raise ValueError("Windows launch requires a Windows executable or shim")
    cmd_path = _trusted_windows_cmd(environment, explicit=windows_cmd)
    command = " ".join(
        (
            _encode_cmd_token(os.fspath(resolution.path), double_escape=False),
            *(_encode_cmd_token(argument, double_escape=True) for argument in suffix),
        )
    )
    command_line = f'"{os.fspath(cmd_path)}" /d /s /v:off /c "{command}"'
    return WindowsLaunchPlan(
        executable=cmd_path,
        argv=command_line,
        kind=resolution.kind,
    )


def _encode_cmd_token(value: str, *, double_escape: bool) -> str:
    """Encode one token for an npm-style cmd/bat shim without shell parsing."""
    _validate_shim_argument(value)
    escaped = _WINDOWS_QUOTE.sub(lambda match: match[1] * 2 + r"\"", value)
    escaped = _WINDOWS_TRAILING_SLASH.sub(lambda match: match[1] * 2, escaped)
    escaped = f'"{escaped}"'
    escaped = _WINDOWS_META.sub(r"^\1", escaped)
    if double_escape:
        escaped = _WINDOWS_META.sub(r"^\1", escaped)
    return escaped


def _trusted_windows_cmd(
    environment: Mapping[str, str],
    *,
    explicit: str | os.PathLike[str] | None,
) -> Path:
    if explicit is not None:
        candidate = Path(explicit)
    else:
        system_root = environment.get("SystemRoot")
        if not system_root:
            raise ValueError("SystemRoot is required for shim execution")
        candidate = Path(system_root) / "System32" / "cmd.exe"
    if not candidate.is_absolute() or candidate.name.casefold() != "cmd.exe":
        raise ValueError("an absolute trusted cmd.exe is required")
    return candidate


def _posix_candidates(
    executable: str, search_path: str
) -> tuple[tuple[Path, NativeExecutableKind], ...]:
    if os.sep in executable or (os.altsep and os.altsep in executable):
        return ((Path(executable), NativeExecutableKind.POSIX),)
    return tuple(
        (
            Path(entry or os.curdir) / executable,
            NativeExecutableKind.POSIX,
        )
        for entry in search_path.split(os.pathsep)
    )


def _windows_candidates(
    executable: str,
    search_path: str,
    pathext: str,
) -> tuple[tuple[Path, NativeExecutableKind], ...]:
    suffixes = tuple(
        extension if extension.startswith(".") else f".{extension}"
        for extension in pathext.split(";")
        if extension
    )
    executable_suffix = Path(executable).suffix.casefold()
    names = (
        (executable,)
        if executable_suffix
        else tuple(f"{executable}{extension}" for extension in suffixes)
    )
    entries = (
        (Path(executable).parent,)
        if "\\" in executable or "/" in executable
        else tuple(Path(entry or os.curdir) for entry in search_path.split(";"))
    )
    candidates: list[tuple[Path, NativeExecutableKind]] = []
    for entry in entries:
        for name in names:
            candidate = _case_insensitive_child(entry, Path(name).name)
            extension = candidate.suffix.casefold()
            kind = (
                NativeExecutableKind.WINDOWS_SHIM
                if extension in {".cmd", ".bat"}
                else NativeExecutableKind.WINDOWS_EXECUTABLE
            )
            candidates.append((candidate, kind))
    return tuple(candidates)


def _case_insensitive_child(parent: Path, name: str) -> Path:
    candidate = parent / name
    try:
        for child in parent.iterdir():
            if child.name.casefold() == name.casefold():
                return child
    except OSError:
        # A missing or unreadable PATH entry is equivalent to no matching child.
        pass
    return candidate


def _same_file(path: Path, facade_executable: str | os.PathLike[str] | None) -> bool:
    if facade_executable is None:
        return False
    try:
        return os.path.samefile(path, facade_executable)
    except OSError:
        return False


def _status_for_exec_error(error: OSError) -> NativeResolutionStatus:
    if error.errno == errno.ENOENT:
        return NativeResolutionStatus.MISSING
    return NativeResolutionStatus.NON_EXECUTABLE


def _validate_native_argument(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("native arguments must be strings")
    if "\x00" in value:
        raise ValueError("native argument is not representable by the launcher")
    return value


def _validate_shim_argument(value: str) -> str:
    _validate_native_argument(value)
    if "\r" in value or "\n" in value:
        raise ValueError("native argument is not representable by the launcher")
    return value


def _validate_environment_component(value: str, *, field: str) -> None:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"environment {field} must be NUL-free text")
    if field == "name" and (not value or "=" in value):
        raise ValueError("environment name must be non-empty and exclude equals")


def _write_prelaunch_diagnostic(namespace: str, status: NativeResolutionStatus) -> None:
    reason = "unavailable" if status is NativeResolutionStatus.MISSING else "unsafe"
    message = f"giga: native {namespace} target {reason}\n".encode("ascii")
    try:
        os.write(sys.stderr.fileno(), message)
    except (AttributeError, OSError, ValueError):
        # Diagnostics are best-effort and must never replace the native exit status.
        pass


def _write_handoff_notice(namespace: str) -> None:
    message = (
        f"giga: handing interactive {namespace} control to the provider terminal; "
        "structured Workbench features are unavailable\n"
    ).encode("ascii")
    try:
        os.write(sys.stderr.fileno(), message)
    except (AttributeError, OSError, ValueError):
        # Handoff remains provider-owned even when the advisory cannot be written.
        pass


def _capture_terminal_state() -> tuple[str, tuple[tuple[int, object], ...]]:
    if os.name == "nt":
        return "windows", _capture_windows_console_state()
    try:
        import termios
    except ImportError:  # pragma: no cover - non-POSIX runtime.
        return "posix", ()
    captured: list[tuple[int, list[object]]] = []
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            descriptor = stream.fileno()
            if os.isatty(descriptor) and all(fd != descriptor for fd, _ in captured):
                captured.append((descriptor, termios.tcgetattr(descriptor)))
        except (AttributeError, OSError, ValueError, termios.error):
            continue
    return "posix", tuple(captured)


def _restore_terminal_state(
    state: tuple[str, tuple[tuple[int, object], ...]],
) -> None:
    platform, entries = state
    if not entries:
        return
    if platform == "windows":
        _restore_windows_console_state(entries)
        return
    import termios

    for descriptor, attributes in entries:
        try:
            termios.tcsetattr(
                descriptor,
                termios.TCSANOW,
                cast(list[object], attributes),
            )
        except (OSError, termios.error):
            continue


def _capture_windows_console_state() -> tuple[tuple[int, object], ...]:
    try:
        import ctypes
        import msvcrt
    except ImportError:  # pragma: no cover - Windows-only imports.
        return ()
    captured: list[tuple[int, object]] = []
    kernel32 = ctypes.windll.kernel32
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            handle = msvcrt.get_osfhandle(stream.fileno())
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) and all(
                saved_handle != handle for saved_handle, _ in captured
            ):
                captured.append((handle, mode.value))
        except (AttributeError, OSError, ValueError):
            continue
    return tuple(captured)


def _restore_windows_console_state(state: tuple[tuple[int, object], ...]) -> None:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    for handle, mode in state:
        kernel32.SetConsoleMode(handle, int(mode))
