import os
import sys
import time

import pytest

from gpt2giga_harness.native.base import NativeCommandPlan
from gpt2giga_harness.native.process import (
    NativeProcessManager,
    NativeProcessStartError,
    NativeProcessStatus,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore


def test_native_process_owner_persists_output_and_accepts_foreign_cancel(tmp_path):
    script = _write_waiting_cli(tmp_path)
    sessions = InMemoryHarnessSessionStore()
    session = sessions.create_session(title="Durable native process")
    runtime = RuntimeCoordinationStore(tmp_path / "data")
    owner = NativeProcessManager(
        session_store=sessions,
        runtime_store=runtime,
        use_pty=False,
        owner_id="owner-a",
        lease_seconds=0.4,
        heartbeat_seconds=0.05,
    )

    ref = owner.start(
        _plan(script, tmp_path),
        session_id=session.id,
        run_id="run_durable",
    )
    _wait_for_text(owner, ref.id, "ready")

    durable = runtime.get_native_process(ref.id)
    assert durable.owner_id == "owner-a"
    assert durable.status == "running"
    assert durable.terminal_cursor >= 1
    assert runtime.read_native_process_outputs(ref.id, after_cursor=0)[0].text

    observer = NativeProcessManager(
        session_store=sessions,
        runtime_store=runtime,
        use_pty=False,
        owner_id="owner-b",
        heartbeat_seconds=0.05,
    )
    observed = observer.status(ref.id)
    assert observed.status is NativeProcessStatus.RUNNING
    assert observed.reconnectable is False
    with pytest.raises(RuntimeError, match="does not own"):
        observer.write(ref.id, "unsafe\n")

    stopped = observer.stop(ref.id)
    assert stopped.status is NativeProcessStatus.STOPPED
    assert stopped.cancel_requested_at is not None
    assert runtime.get_native_process(ref.id).recovery_outcome == "cancel_requested"
    owner.close()
    observer.close()


def test_native_process_timeout_is_supervised_and_persisted(tmp_path):
    script = _write_waiting_cli(tmp_path)
    sessions = InMemoryHarnessSessionStore()
    session = sessions.create_session(title="Timed native process")
    runtime = RuntimeCoordinationStore(tmp_path / "data")
    manager = NativeProcessManager(
        session_store=sessions,
        runtime_store=runtime,
        use_pty=False,
        lease_seconds=0.4,
        heartbeat_seconds=0.02,
    )

    ref = manager.start(
        _plan(script, tmp_path),
        session_id=session.id,
        timeout_seconds=0.1,
    )
    timed_out = _wait_for_status(manager, ref.id, NativeProcessStatus.TIMED_OUT)

    assert timed_out.recovery_outcome == "timeout_expired"
    durable = runtime.get_native_process(ref.id)
    assert durable.status == "timed_out"
    assert durable.finished_at is not None
    assert durable.timeout_at is not None
    manager.close()


def test_native_process_restart_marks_live_expired_owner_interrupted(tmp_path):
    script = _write_waiting_cli(tmp_path)
    sessions = InMemoryHarnessSessionStore()
    session = sessions.create_session(title="Interrupted native process")
    runtime = RuntimeCoordinationStore(tmp_path / "data")
    owner = NativeProcessManager(
        session_store=sessions,
        runtime_store=runtime,
        use_pty=False,
        owner_id="owner-before-restart",
        lease_seconds=0.12,
        heartbeat_seconds=0.03,
    )
    ref = owner.start(_plan(script, tmp_path), session_id=session.id)
    _wait_for_text(owner, ref.id, "ready")

    owner.close(terminate_owned=False)
    time.sleep(0.16)
    restarted = NativeProcessManager(
        session_store=sessions,
        runtime_store=runtime,
        use_pty=False,
        owner_id="owner-after-restart",
        lease_seconds=0.12,
        heartbeat_seconds=0.03,
    )

    recovered = restarted.status(ref.id)
    assert recovered.status is NativeProcessStatus.INTERRUPTED
    assert recovered.recovery_outcome == (
        "owner_lease_expired_process_alive_not_adopted"
    )
    assert recovered.reconnectable is False
    assert "ready" in "".join(
        output.text for output in restarted.read_since(ref.id, 0).outputs
    )
    with pytest.raises(RuntimeError, match="does not own"):
        restarted.write(ref.id, "unsafe\n")
    assert any(
        event.type == "terminal_recovery" for event in sessions.list_events(session.id)
    )

    owner.stop(ref.id)
    restarted.close()


def test_native_process_output_history_is_bounded_and_reports_truncation(tmp_path):
    script = _write_waiting_cli(tmp_path)
    sessions = InMemoryHarnessSessionStore()
    session = sessions.create_session(title="Bounded native output")
    runtime = RuntimeCoordinationStore(tmp_path / "data")
    manager = NativeProcessManager(
        session_store=sessions,
        runtime_store=runtime,
        use_pty=False,
        max_output_chunks=2,
    )
    ref = manager.start(_plan(script, tmp_path), session_id=session.id)
    _wait_for_text(manager, ref.id, "ready")

    for index in range(4):
        manager._append_output(ref.id, "stdout", f"chunk-{index}\n".encode())

    chunk = manager.read_since(ref.id, 0)
    persisted = runtime.read_native_process_outputs(ref.id, after_cursor=0)
    assert len(chunk.outputs) == 2
    assert len(persisted) == 2
    assert chunk.truncated is True
    assert chunk.oldest_cursor == persisted[0].cursor
    assert chunk.cursor == persisted[-1].cursor
    manager.stop(ref.id)
    manager.close()


def test_native_process_persistence_failure_terminates_unpublished_child(
    tmp_path,
    monkeypatch,
):
    class FailingRuntimeStore(RuntimeCoordinationStore):
        def create_native_process(self, record):
            raise OSError("disk unavailable")

    class FakeProcess:
        pid = os.getpid()
        stdin = None
        stdout = None
        stderr = None
        terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminated = True

        def poll(self):
            return None

    process = FakeProcess()
    sessions = InMemoryHarnessSessionStore()
    session = sessions.create_session(title="Crash window")
    manager = NativeProcessManager(
        session_store=sessions,
        runtime_store=FailingRuntimeStore(tmp_path / "data"),
        use_pty=False,
    )
    monkeypatch.setattr(
        manager,
        "_popen",
        lambda **kwargs: (process, None, None),
    )

    with pytest.raises(NativeProcessStartError, match="could not be persisted"):
        manager.start(
            NativeCommandPlan(
                command=("fake-cli",),
                env={},
                cwd=str(tmp_path),
                metadata={"harness_id": "fake-cli"},
            ),
            session_id=session.id,
        )

    assert process.terminated is True
    assert manager.cleanup() == ()


def _write_waiting_cli(tmp_path):
    script = tmp_path / "waiting_cli.py"
    script.write_text(
        "import sys\n"
        "print('ready', flush=True)\n"
        "for line in sys.stdin:\n"
        "    if line.strip() == 'quit':\n"
        "        break\n",
        encoding="utf-8",
    )
    return script


def _plan(script, tmp_path):
    return NativeCommandPlan(
        command=(sys.executable, str(script)),
        env=_python_env(),
        cwd=str(tmp_path),
        native_home=str(tmp_path / "managed-home"),
        metadata={
            "harness_id": "fake-cli",
            "workspace_execution": {"policy": "worktree", "retained": True},
        },
    )


def _python_env():
    env = {"PYTHONUNBUFFERED": "1"}
    for key in ("PATH", "SYSTEMROOT"):
        if value := os.environ.get(key):
            env[key] = value
    return env


def _wait_for_text(manager, process_id, expected):
    deadline = time.monotonic() + 3
    seen = ""
    cursor = 0
    while time.monotonic() < deadline:
        chunk = manager.read_since(process_id, cursor)
        cursor = chunk.cursor
        seen += "".join(output.text for output in chunk.outputs)
        if expected in seen:
            return seen
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {expected!r}; saw {seen!r}")


def _wait_for_status(manager, process_id, expected):
    deadline = time.monotonic() + 3
    status = None
    while time.monotonic() < deadline:
        ref = manager.status(process_id)
        status = ref.status
        if status is expected:
            return ref
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {expected}; last status was {status}")
