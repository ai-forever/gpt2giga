from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

import pytest

from gpt2giga_harness.native_cli_contracts import NATIVE_NAMESPACE_SPECS
from gpt2giga_harness.native_cli_process import (
    NativeExecutableKind,
    NativeExecutableResolution,
    NativeProcessPlatform,
    NativeResolutionStatus,
    build_native_environment,
    build_windows_launch_plan,
    resolve_native_executable,
    run_native_l0,
    run_native_l1_handoff,
)


CODEX = NATIVE_NAMESPACE_SPECS["codex"]


def _make_executable(path: Path, source: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _kernel_command(fake_path: Path, suffix: tuple[str, ...]) -> tuple[str, ...]:
    source = """
import os
import sys
from gpt2giga_harness.native_cli_contracts import NATIVE_NAMESPACE_SPECS
from gpt2giga_harness.native_cli_process import run_native_l0
raise SystemExit(run_native_l0(
    NATIVE_NAMESPACE_SPECS['codex'],
    sys.argv[2:],
    environment={**os.environ, 'PATH': sys.argv[1]},
    facade_executable=sys.executable,
))
"""
    return (sys.executable, "-c", source, os.fspath(fake_path.parent), *suffix)


@pytest.mark.skipif(os.name == "nt", reason="POSIX exec contract")
def test_posix_exec_preserves_opaque_suffix_cwd_environment_and_raw_stdio(tmp_path):
    fake = _make_executable(
        tmp_path / "codex",
        """
import json
import os
import sys
payload = {
    'argv': sys.argv[1:],
    'cwd': os.getcwd(),
    'marker': os.environ['NATIVE_MARKER'],
    'stdin': os.read(0, 100).decode('utf-8'),
}
os.write(1, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
os.write(2, b'early-stderr')
""",
    )
    suffix = (
        "",
        "duplicate",
        "duplicate",
        "Юникод",
        "line\nfeed",
        "space value",
        'quote"value',
        "equals=value",
        "-leading",
        "--",
    )
    completed = subprocess.run(
        _kernel_command(fake, suffix),
        cwd=tmp_path,
        env={**os.environ, "NATIVE_MARKER": "inherited"},
        input=b"stdin-bytes",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == b"early-stderr"
    assert json.loads(completed.stdout) == {
        "argv": list(suffix),
        "cwd": os.fspath(tmp_path),
        "marker": "inherited",
        "stdin": "stdin-bytes",
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX exec contract")
@pytest.mark.parametrize("exit_code", [0, 23])
def test_posix_exec_preserves_raw_bytes_large_output_and_exit_code(tmp_path, exit_code):
    fake = _make_executable(
        tmp_path / "codex",
        f"""
import os
os.write(1, b'\\xff' + b'x' * 262144)
os.write(2, b'\\xfe')
raise SystemExit({exit_code})
""",
    )
    completed = subprocess.run(
        _kernel_command(fake, ()),
        capture_output=True,
        check=False,
    )
    assert completed.returncode == exit_code
    assert completed.stdout == b"\xff" + b"x" * 262144
    assert completed.stderr == b"\xfe"


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal contract")
def test_posix_exec_is_the_provider_process_for_termination(tmp_path):
    fake = _make_executable(
        tmp_path / "codex",
        """
import os
import signal
import time
signal.signal(signal.SIGTERM, lambda *_: raise_exit())
def raise_exit():
    os._exit(41)
os.write(1, str(os.getpid()).encode('ascii'))
time.sleep(10)
""",
    )
    process = subprocess.Popen(_kernel_command(fake, ()), stdout=subprocess.PIPE)
    assert process.stdout is not None
    provider_pid = int(process.stdout.read(len(str(process.pid))))
    assert provider_pid == process.pid
    process.terminate()
    assert process.wait(timeout=5) == 41


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal contract")
def test_posix_exec_delivers_ctrl_c_directly_to_provider(tmp_path):
    fake = _make_executable(
        tmp_path / "codex",
        """
import os
import signal
import time
signal.signal(signal.SIGINT, lambda *_: os._exit(42))
os.write(1, b'ready')
time.sleep(10)
""",
    )
    process = subprocess.Popen(_kernel_command(fake, ()), stdout=subprocess.PIPE)
    assert process.stdout is not None
    assert process.stdout.read(5) == b"ready"
    process.send_signal(signal.SIGINT)
    assert process.wait(timeout=5) == 42


@pytest.mark.skipif(os.name == "nt", reason="POSIX pipe contract")
def test_posix_exec_preserves_slow_consumer_and_closed_pipe_behavior(tmp_path):
    fake = _make_executable(
        tmp_path / "codex",
        """
import os
import signal
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
for _ in range(64):
    os.write(1, b'x' * 65536)
""",
    )
    slow = subprocess.Popen(_kernel_command(fake, ()), stdout=subprocess.PIPE)
    time.sleep(0.05)
    stdout, _ = slow.communicate(timeout=5)
    assert slow.returncode == 0
    assert stdout == b"x" * 4194304

    closed = subprocess.Popen(_kernel_command(fake, ()), stdout=subprocess.PIPE)
    assert closed.stdout is not None
    closed.stdout.close()
    assert closed.wait(timeout=5) == -signal.SIGPIPE


@pytest.mark.skipif(os.name == "nt", reason="POSIX process topology contract")
def test_posix_exec_preserves_process_group_session_and_inheritable_descriptor(
    tmp_path,
):
    fake = _make_executable(
        tmp_path / "codex",
        """
import json
import os
import sys
fd = int(os.environ['INHERITED_FD'])
os.write(fd, b'descriptor-bytes')
os.write(1, json.dumps({'pgrp': os.getpgrp(), 'sid': os.getsid(0)}).encode())
""",
    )
    read_fd, write_fd = os.pipe()
    try:
        completed = subprocess.run(
            _kernel_command(fake, ()),
            env={**os.environ, "INHERITED_FD": str(write_fd)},
            pass_fds=(write_fd,),
            capture_output=True,
            check=False,
        )
    finally:
        os.close(write_fd)
    try:
        inherited = os.read(read_fd, 100)
    finally:
        os.close(read_fd)
    topology = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert inherited == b"descriptor-bytes"
    assert topology == {"pgrp": os.getpgrp(), "sid": os.getsid(0)}


def test_environment_overrides_are_explicit_and_do_not_mutate_input():
    inherited = {"KEEP": "yes", "REMOVE": "secret"}
    result = build_native_environment(
        inherited=inherited,
        overrides={"REMOVE": None, "ADD": "value"},
    )
    assert result == {"KEEP": "yes", "ADD": "value"}
    assert inherited == {"KEEP": "yes", "REMOVE": "secret"}


def test_process_kernel_imports_no_textual_or_argparse():
    source = """
import sys
import gpt2giga_harness.native_cli_process
print(','.join(sorted(name for name in sys.modules if name in {'argparse', 'textual'})))
"""
    completed = subprocess.run(
        (sys.executable, "-c", source),
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout == "\n"


def test_posix_resolution_rejects_first_confusing_entry_without_fallthrough(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "codex").write_text("not executable", encoding="utf-8")
    _make_executable(second / "codex", "raise SystemExit(0)\n")
    resolution = resolve_native_executable(
        CODEX,
        environment={"PATH": os.pathsep.join((os.fspath(first), os.fspath(second)))},
        facade_executable=None,
        platform=NativeProcessPlatform.POSIX,
    )
    assert resolution.status is NativeResolutionStatus.NON_EXECUTABLE
    assert resolution.exit_code == 126


def test_resolution_rejects_recursive_file_identity(tmp_path):
    facade = _make_executable(tmp_path / "giga", "raise SystemExit(0)\n")
    (tmp_path / "codex").symlink_to(facade)
    resolution = resolve_native_executable(
        CODEX,
        environment={"PATH": os.fspath(tmp_path)},
        facade_executable=facade,
        platform=NativeProcessPlatform.POSIX,
    )
    assert resolution.status is NativeResolutionStatus.UNSAFE
    assert resolution.exit_code == 126


def test_missing_target_is_content_free_and_returns_127(tmp_path, capfd):
    result = run_native_l0(
        CODEX,
        ("secret prompt",),
        environment={"PATH": os.fspath(tmp_path)},
        platform=NativeProcessPlatform.POSIX,
    )
    assert result == 127
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "giga: native codex target unavailable\n"
    assert "secret" not in captured.err


def test_posix_startup_failure_returns_126_without_traceback(tmp_path, capfd):
    _make_executable(tmp_path / "codex", "raise SystemExit(0)\n")

    def fail_execve(*_args):
        raise OSError(8, "provider details")

    result = run_native_l0(
        CODEX,
        (),
        environment={"PATH": os.fspath(tmp_path)},
        platform=NativeProcessPlatform.POSIX,
        execve=fail_execve,
    )
    assert result == 126
    assert capfd.readouterr().err == "giga: native codex target unsafe\n"


def test_windows_resolution_honors_case_insensitive_pathext_and_shim_kind(tmp_path):
    shim = tmp_path / "CoDeX.CmD"
    shim.write_bytes(b"@exit /b 0\r\n")
    resolution = resolve_native_executable(
        CODEX,
        environment={"PATH": os.fspath(tmp_path), "PATHEXT": ".EXE;.CMD;.BAT"},
        facade_executable=None,
        platform=NativeProcessPlatform.WINDOWS,
    )
    assert resolution == NativeExecutableResolution(
        status=NativeResolutionStatus.READY,
        kind=NativeExecutableKind.WINDOWS_SHIM,
        path=shim.resolve(),
    )


def test_windows_direct_plan_preserves_each_argument(tmp_path):
    executable = tmp_path / "codex.exe"
    executable.touch()
    resolution = NativeExecutableResolution(
        NativeResolutionStatus.READY,
        NativeExecutableKind.WINDOWS_EXECUTABLE,
        executable,
    )
    suffix = ("", "space value", 'quote"value', "backslash\\", "--")
    plan = build_windows_launch_plan(resolution, suffix, environment={})
    assert plan.executable == executable
    assert plan.argv == (os.fspath(executable), *suffix)


def test_windows_shim_plan_uses_trusted_cmd_and_escapes_metacharacters(tmp_path):
    shim = tmp_path / "codex.cmd"
    shim.touch()
    cmd = tmp_path / "System32" / "cmd.exe"
    cmd.parent.mkdir()
    cmd.touch()
    resolution = NativeExecutableResolution(
        NativeResolutionStatus.READY,
        NativeExecutableKind.WINDOWS_SHIM,
        shim,
    )
    suffix = (
        "",
        "space value",
        'quote"value',
        "trailing\\",
        "%PATH%",
        "!bang!",
        "caret^",
        "amp&pipe|redirect<out>",
        "(group)",
        "Юникод",
    )
    plan = build_windows_launch_plan(
        resolution,
        suffix,
        environment={"SystemRoot": os.fspath(tmp_path)},
        windows_cmd=cmd,
    )
    assert plan.executable == cmd
    assert isinstance(plan.argv, str)
    assert plan.argv.startswith(f'"{cmd}" /d /s /v:off /c "')
    assert "shell=True" not in plan.argv
    for metacharacter in "%!^&|<>()":
        assert f"^{metacharacter}" in plan.argv


@pytest.mark.parametrize("invalid", ["nul\x00value", "line\nfeed", "carriage\rreturn"])
def test_windows_shim_rejects_unrepresentable_tokens_before_spawn(tmp_path, invalid):
    shim = tmp_path / "codex.cmd"
    shim.touch()
    cmd = tmp_path / "cmd.exe"
    cmd.touch()
    resolution = NativeExecutableResolution(
        NativeResolutionStatus.READY,
        NativeExecutableKind.WINDOWS_SHIM,
        shim,
    )
    with pytest.raises(ValueError, match="not representable"):
        build_windows_launch_plan(
            resolution,
            (invalid,),
            environment={},
            windows_cmd=cmd,
        )


def test_windows_runner_inherits_handles_console_and_exit_code(tmp_path):
    executable = tmp_path / "codex.exe"
    executable.touch()
    calls = []

    class Process:
        def wait(self):
            return 37

    def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    result = run_native_l0(
        CODEX,
        ("--json",),
        environment={"PATH": os.fspath(tmp_path), "PATHEXT": ".EXE"},
        platform=NativeProcessPlatform.WINDOWS,
        windows_spawner=spawn,
    )
    assert result == 37
    _, kwargs = calls[0]
    assert kwargs == {
        "executable": os.fspath(executable.resolve()),
        "stdin": None,
        "stdout": None,
        "stderr": None,
        "cwd": None,
        "env": {"PATH": os.fspath(tmp_path), "PATHEXT": ".EXE"},
        "shell": False,
        "close_fds": False,
        "creationflags": 0,
    }


def test_l1_handoff_is_visible_and_inherits_provider_terminal(capfd, tmp_path):
    executable = tmp_path / "codex"
    executable.touch()
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    calls = []

    class Process:
        def wait(self):
            return 29

    def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    result = run_native_l1_handoff(
        CODEX,
        ("resume", "--last"),
        environment={"PATH": os.fspath(tmp_path)},
        platform=NativeProcessPlatform.POSIX,
        spawner=spawn,
    )

    assert result == 29
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "giga: handing interactive codex control to the provider terminal; "
        "structured Workbench features are unavailable\n"
    )
    args, kwargs = calls[0]
    assert args == ((os.fspath(executable.resolve()), "resume", "--last"),)
    assert kwargs["stdin"] is None
    assert kwargs["stdout"] is None
    assert kwargs["stderr"] is None
    assert kwargs["shell"] is False
    assert kwargs["close_fds"] is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX termios restoration contract")
def test_l1_handoff_restores_terminal_after_provider_failure(tmp_path):
    import pty
    import termios

    _make_executable(
        tmp_path / "codex",
        """
import sys
import termios
state = termios.tcgetattr(sys.stdin.fileno())
state[3] &= ~termios.ECHO
termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, state)
raise SystemExit(31)
""",
    )
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    source = """
import os
import sys
from gpt2giga_harness.native_cli_contracts import NATIVE_NAMESPACE_SPECS
from gpt2giga_harness.native_cli_process import run_native_l1_handoff
raise SystemExit(run_native_l1_handoff(
    NATIVE_NAMESPACE_SPECS['codex'],
    (),
    environment={**os.environ, 'PATH': sys.argv[1]},
    facade_executable=sys.executable,
))
"""
    try:
        completed = subprocess.run(
            (sys.executable, "-c", source, os.fspath(tmp_path)),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            check=False,
        )
        after = termios.tcgetattr(slave)
    finally:
        os.close(master)
        os.close(slave)

    assert completed.returncode == 31
    assert after == before
    assert not (tmp_path / ".giga").exists()


@pytest.mark.skipif(os.name != "nt", reason="real Windows cmd shim contract")
@pytest.mark.parametrize("extension", ["cmd", "bat"])
def test_windows_shim_round_trips_provider_arguments(tmp_path, extension):
    recorder = tmp_path / "record.py"
    recorder.write_text(
        "import json, sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))",
        encoding="utf-8",
    )
    shim = tmp_path / f"codex.{extension}"
    shim.write_text(
        f'@"{sys.executable}" "{recorder}" %*\r\n',
        encoding="utf-8",
    )
    suffix = (
        "",
        "space value",
        'quote"value',
        "trailing\\",
        "%PATH%",
        "!bang!",
        "caret^",
        "amp&pipe|redirect<out>",
        "(group)",
        "Юникод",
    )
    source = """
import os
import sys
from gpt2giga_harness.native_cli_contracts import NATIVE_NAMESPACE_SPECS
from gpt2giga_harness.native_cli_process import run_native_l0
raise SystemExit(run_native_l0(
    NATIVE_NAMESPACE_SPECS['codex'],
    sys.argv[3:],
    environment={**os.environ, 'PATH': sys.argv[1], 'PATHEXT': sys.argv[2]},
    facade_executable=sys.executable,
))
"""
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            source,
            os.fspath(tmp_path),
            f".{extension.upper()}",
            *suffix,
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == list(suffix)
