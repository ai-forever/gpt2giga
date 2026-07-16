import os
import struct
import sys
import threading
import time

import pytest

from gpt2giga_harness.native import process as native_process_module
from gpt2giga_harness.native.base import NativeCommandPlan, NativePromptDelivery
from gpt2giga_harness.native.process import (
    NativeProcessManager,
    NativeProcessStatus,
    native_output_chunk_to_dict,
)
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.types import REDACTED


def test_native_process_manager_starts_reads_writes_and_stops_fake_cli(tmp_path):
    script = _write_echo_cli(tmp_path)
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Native process")
    manager = NativeProcessManager(session_store=store, use_pty=False)

    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script)),
            env=_python_env(),
            cwd=str(tmp_path),
            metadata={"harness_id": "fake-cli"},
        ),
        session_id=session.id,
        workspace=str(tmp_path),
        run_id="run_fake",
    )

    cursor, output = _wait_for_text(manager, ref.id, 0, "ready")
    assert ref.status is NativeProcessStatus.RUNNING
    assert "ready" in output

    manager.write(ref.id, "hello\n")
    cursor, output = _wait_for_text(manager, ref.id, cursor, "echo:hello")
    assert "echo:hello" in output

    manager.write(ref.id, "quit\n")
    cursor, output = _wait_for_text(manager, ref.id, cursor, "bye")
    stopped = manager.stop(ref.id)

    assert "bye" in output
    assert stopped.status in {
        NativeProcessStatus.EXITED,
        NativeProcessStatus.STOPPED,
    }
    assert {event.type for event in store.list_events(session.id)} >= {
        "terminal_start",
        "terminal_input",
        "terminal_output",
        "terminal_exit",
        "terminal_stop",
    }


def test_native_process_manager_redacts_output_and_session_events(tmp_path):
    secret = "native-process-secret-value"
    script = tmp_path / "print_secret.py"
    script.write_text(
        "import os\nprint(os.environ['GPT2GIGA_API_KEY'], flush=True)\n",
        encoding="utf-8",
    )
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Native process")
    manager = NativeProcessManager(session_store=store, use_pty=False)

    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script)),
            env={**_python_env(), "GPT2GIGA_API_KEY": secret},
            cwd=str(tmp_path),
            metadata={"harness_id": "fake-cli", "api_key": secret},
        ),
        session_id=session.id,
    )

    _wait_for_status(manager, ref.id, NativeProcessStatus.EXITED)
    chunk = manager.read_since(ref.id, 0)
    payload = native_output_chunk_to_dict(chunk)
    events = store.list_events(session.id)

    assert secret not in str(payload)
    assert secret not in str(events)
    assert REDACTED in str(payload)
    assert REDACTED in str(events)


def test_native_process_manager_marks_argv_prompt_delivered_without_exposing_it(
    tmp_path,
):
    prompt = "first line\nsecond line\n"
    script = tmp_path / "argv.py"
    script.write_text(
        "import sys\nprint(repr(sys.argv[-1]), flush=True)\n",
        encoding="utf-8",
    )
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Native prompt")
    manager = NativeProcessManager(session_store=store, use_pty=False)

    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script), "--prompt-interactive", prompt),
            display_command=(
                sys.executable,
                str(script),
                "--prompt-interactive",
                "<initial-prompt>",
            ),
            env=_python_env(),
            cwd=str(tmp_path),
            metadata={"harness_id": "gemini-cli"},
            prompt_delivery=NativePromptDelivery(
                idempotency_key="nprompt_test",
                mechanism="gemini_prompt_interactive",
                prompt_sha256="prompt-hash",
                byte_count=len(prompt.encode("utf-8")),
            ),
        ),
        session_id=session.id,
    )

    _wait_for_status(manager, ref.id, NativeProcessStatus.EXITED)
    output = "".join(item.text for item in manager.read_since(ref.id, 0).outputs)
    events = store.list_events(session.id)

    assert repr(prompt) in output
    assert ref.command[-1] == "<initial-prompt>"
    assert ref.metadata["prompt_delivery"]["status"] == "delivered"
    assert prompt not in str(events)
    assert "<initial-prompt>" in str(events)


def test_native_process_manager_drains_output_before_reporting_exit(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "exit_after_output.py"
    script.write_text("print('final output', flush=True)\n", encoding="utf-8")
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Native output drain")
    manager = NativeProcessManager(session_store=store, use_pty=False)
    reader_started = threading.Event()
    release_reader = threading.Event()
    original_read_pipe = manager._read_pipe

    def delayed_read_pipe(process_id, pipe, stream):
        reader_started.set()
        release_reader.wait(timeout=3.0)
        original_read_pipe(process_id, pipe, stream)

    monkeypatch.setattr(manager, "_read_pipe", delayed_read_pipe)
    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script)),
            env=_python_env(),
            cwd=str(tmp_path),
            metadata={"harness_id": "fake-cli"},
        ),
        session_id=session.id,
    )

    try:
        assert reader_started.wait(timeout=3.0)
        manager._records[ref.id].process.wait(timeout=3.0)

        assert manager.status(ref.id).status is NativeProcessStatus.RUNNING
    finally:
        release_reader.set()

    _wait_for_status(manager, ref.id, NativeProcessStatus.EXITED)
    output = "".join(item.text for item in manager.read_since(ref.id, 0).outputs)

    assert "final output" in output


def test_native_process_manager_cleanup_marks_exited_process(tmp_path):
    script = tmp_path / "exit.py"
    script.write_text("print('done', flush=True)\n", encoding="utf-8")
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Native process")
    manager = NativeProcessManager(session_store=store, use_pty=False)
    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script)),
            env=_python_env(),
            cwd=str(tmp_path),
            metadata={"harness_id": "fake-cli"},
        ),
        session_id=session.id,
    )

    _wait_for_status(manager, ref.id, NativeProcessStatus.EXITED)
    refs = manager.cleanup()

    assert refs[0].status is NativeProcessStatus.EXITED
    assert refs[0].exit_code == 0
    assert "done" in "".join(
        output.text for output in manager.read_since(ref.id, 0).outputs
    )


def test_native_process_manager_closes_pipes_after_natural_exit(tmp_path):
    script = tmp_path / "exit.py"
    script.write_text("print('done', flush=True)\n", encoding="utf-8")
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Native process")
    manager = NativeProcessManager(session_store=store, use_pty=False)
    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script)),
            env=_python_env(),
            cwd=str(tmp_path),
            metadata={"harness_id": "fake-cli"},
        ),
        session_id=session.id,
    )

    _wait_for_status(manager, ref.id, NativeProcessStatus.EXITED)
    record = manager._records[ref.id]

    assert record.resources_closed is True
    assert record.stdin is not None and record.stdin.closed
    assert record.process.stdout is not None and record.process.stdout.closed
    assert record.process.stderr is not None and record.process.stderr.closed


@pytest.mark.skipif(
    native_process_module.fcntl is None or native_process_module.termios is None,
    reason="PTY resize is POSIX-only",
)
def test_native_process_manager_resizes_owned_pty_with_bounded_dimensions(
    tmp_path,
    monkeypatch,
):
    script = _write_echo_cli(tmp_path)
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Resizable native process")
    manager = NativeProcessManager(session_store=store, use_pty=True)
    ref = manager.start(
        NativeCommandPlan(
            command=(sys.executable, str(script)),
            env=_python_env(),
            cwd=str(tmp_path),
            metadata={"harness_id": "fake-cli"},
        ),
        session_id=session.id,
    )
    _wait_for_text(manager, ref.id, 0, "ready")
    calls = []
    monkeypatch.setattr(
        native_process_module.fcntl,
        "ioctl",
        lambda fd, operation, payload: calls.append((fd, operation, payload)),
    )

    resized = manager.resize(ref.id, rows=36, columns=120)

    assert resized.status is NativeProcessStatus.RUNNING
    assert len(calls) == 1
    assert calls[0][1] == native_process_module.termios.TIOCSWINSZ
    assert struct.unpack("HHHH", calls[0][2]) == (36, 120, 0, 0)
    resize_events = [
        event
        for event in store.list_events(session.id)
        if event.type == "terminal_resize"
    ]
    assert resize_events[-1].payload == {
        "process_id": ref.id,
        "rows": 36,
        "columns": 120,
    }
    with pytest.raises(ValueError, match="rows must be between 2 and 200"):
        manager.resize(ref.id, rows=1, columns=120)
    manager.stop(ref.id)


def _write_echo_cli(tmp_path):
    script = tmp_path / "echo_cli.py"
    script.write_text(
        "import sys\n"
        "print('ready', flush=True)\n"
        "for line in sys.stdin:\n"
        "    text = line.strip()\n"
        "    print(f'echo:{text}', flush=True)\n"
        "    if text == 'quit':\n"
        "        break\n"
        "print('bye', flush=True)\n",
        encoding="utf-8",
    )
    return script


def _python_env():
    env = {"PYTHONUNBUFFERED": "1"}
    for key in ("PATH", "SYSTEMROOT"):
        if value := os.environ.get(key):
            env[key] = value
    return env


def _wait_for_text(manager, process_id, cursor, expected):
    deadline = time.monotonic() + 3.0
    seen = ""
    latest_cursor = cursor
    while time.monotonic() < deadline:
        chunk = manager.read_since(process_id, latest_cursor)
        latest_cursor = chunk.cursor
        seen += "".join(output.text for output in chunk.outputs)
        if expected in seen:
            return latest_cursor, seen
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {expected!r}; saw {seen!r}")


def _wait_for_status(manager, process_id, expected):
    deadline = time.monotonic() + 3.0
    status = None
    while time.monotonic() < deadline:
        ref = manager.status(process_id)
        status = ref.status
        if status is expected:
            return ref
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {expected}; last status was {status}")
