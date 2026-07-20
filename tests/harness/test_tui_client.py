from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from gpt2giga_harness import entrypoint
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import utc_now
from gpt2giga_harness.terminal_dispatch import TerminalContext
from gpt2giga_harness.terminal_intent import parse_tui_launch_intent
from gpt2giga_harness.tui.client import (
    AttachedWorkbenchClient,
    InProcessWorkbenchClient,
    WorkbenchClientError,
)
from gpt2giga_harness.tui.i18n import CATALOGS, resolve_locale, translator


@pytest.mark.anyio
async def test_in_process_client_navigates_projects_and_sessions(tmp_path):
    data_dir = tmp_path / "state"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(data_dir)))

    first_session = client.sessions.create_session(
        {
            "workspace": str(first),
            "title": "First\x1b]52;c;hidden\x07 \u202esession",
            "harness_id": "echo",
            "model": "local-model",
        },
        validate_harness=True,
    )
    client.sessions.create_session(
        {"workspace": str(second), "title": "Second", "harness_id": "echo"},
        validate_harness=True,
    )

    snapshot = await client.load(str(first), selected_session_id=first_session.id)

    assert snapshot.transport_mode == "in_process"
    assert snapshot.project.root == str(first)
    assert {project.root for project in snapshot.projects} == {str(first), str(second)}
    assert [session.id for session in snapshot.sessions] == [first_session.id]
    assert snapshot.sessions[0].title == "First⟦terminal-control⟧ �session"
    assert snapshot.readiness.harness_id == "echo"
    assert snapshot.readiness.harness_status == "available"
    assert snapshot.readiness.model == "local-model"
    assert snapshot.readiness.transport == "one_shot"
    assert snapshot.readiness.provider_status == "not_checked"

    created = await client.create_session(str(first), title="From TUI")
    resumed = await client.load(str(first))

    assert resumed.selected_session_id == created.id
    assert {session.title for session in resumed.sessions} == {
        "First⟦terminal-control⟧ �session",
        "From TUI",
    }


@pytest.mark.anyio
async def test_in_process_client_resolves_an_exact_session_deep_link_workspace(
    tmp_path,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(tmp_path / "state")))
    client.sessions.create_session({"workspace": str(first)})
    selected = client.sessions.create_session({"workspace": str(second)})

    snapshot = await client.load(None, selected_session_id=selected.id)

    assert snapshot.project.root == str(second.resolve())
    assert snapshot.selected_session_id == selected.id


@pytest.mark.anyio
async def test_in_process_client_submits_idempotent_turn_and_resnapshots(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(tmp_path / "state")))
    session = client.sessions.create_session(
        {"workspace": str(workspace), "harness_id": "echo"},
        validate_harness=True,
    )

    first = await client.submit_turn(
        session.id,
        "hello",
        idempotency_key="turn_1",
        harness_id="echo",
        model="intent-model",
        mode="read",
        execution_transport="one_shot",
    )
    for _ in range(100):
        if first.events:
            break
        await asyncio.sleep(0.01)
        first = await client.snapshot_run(first.binding.run_id)
    duplicate = await client.submit_turn(session.id, "hello", idempotency_key="turn_1")
    gap = await client.snapshot_run(first.binding.run_id, cursor="invalid")

    assert duplicate.binding.run_id == first.binding.run_id
    assert {event.type for event in first.events} >= {"run_started"}
    assert gap.resnapshot_reason == "cursor_gap"
    assert gap.binding.session_id == session.id
    run = client.store.get_run(first.binding.run_id)
    assert run.model == "intent-model"
    assert run.mode == "read"
    assert run.metadata["execution_transport"] == "one_shot"


@pytest.mark.anyio
async def test_in_process_client_bounds_slow_consumer_and_rejects_stale_action(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(tmp_path / "state")))
    session = client.sessions.create_session(
        {"workspace": str(workspace), "harness_id": "echo"},
        validate_harness=True,
    )
    submitted = await client.submit_turn(
        session.id, "bounded", idempotency_key="turn_bounded"
    )
    for index in range(110):
        client.store.append_event(
            HarnessStoredEvent(
                id=f"evt_extra_{index}",
                session_id=session.id,
                run_id=submitted.binding.run_id,
                type="warning",
                message=f"event {index}",
                payload={},
                created_at=utc_now(),
            )
        )

    snapshot = await client.snapshot_run(submitted.binding.run_id)

    assert len(snapshot.events) <= 100
    assert snapshot.resnapshot_reason == "slow_consumer"
    with pytest.raises(WorkbenchClientError, match="revision changed"):
        await client.fork_run(replace(snapshot.binding, revision="0" * 64))


@pytest.mark.anyio
async def test_in_process_client_files_diff_evidence_and_handoffs_are_bounded(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.md").write_text(
        "# Note\n\x1b]52;c;hidden\x07\u202e\n", encoding="utf-8"
    )
    (workspace / ".hidden.txt").write_text("hidden but safe\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (workspace / "outside-link.txt").symlink_to(outside)
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(tmp_path / "state")))
    session = client.sessions.create_session(
        {"workspace": str(workspace), "harness_id": "echo"},
        validate_harness=True,
    )

    candidates = await client.search_files(session.id, "")
    paths = {item.path for item in candidates}
    safe = next(item for item in candidates if item.path == "safe.md")
    attachment = await client.attach_file(session.id, safe.path)
    submitted = await client.submit_turn(
        session.id,
        "inspect",
        idempotency_key="turn_files",
        attachment_ids=(attachment.id,),
    )
    run = client.store.get_run(submitted.binding.run_id)
    client.store.update_run(
        run.id,
        metadata={
            **dict(run.metadata),
            "diff": "diff --git a/safe.md b/safe.md\n+line\x1b]52;c;x\x07\u202e\n",
        },
    )
    inspection = await client.inspect_run(run.id)
    provider = await client.provider_handoff(session.id)
    web = await client.web_handoff(session.id)

    assert {"safe.md", ".hidden.txt"} <= paths
    assert ".env" not in paths
    assert "outside-link.txt" not in paths
    assert safe.preview == "# Note\n⟦terminal-control⟧�\n"
    assert attachment.path == "safe.md"
    assert inspection.artifacts[0].type == "diff"
    assert "⟦terminal-control⟧�" in inspection.diff
    assert inspection.evidence[-1] == "environment=deferred_to_N6"
    assert provider.status == "blocked"
    assert web.status == "blocked"


@pytest.mark.anyio
async def test_attach_client_uses_existing_api_contract(monkeypatch):
    client = AttachedWorkbenchClient("http://127.0.0.1:8091")
    calls: list[tuple[str, str, object]] = []

    async def request(method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/":
            return {}
        if path.startswith("/api/project?"):
            return {
                "project": {
                    "id": "proj_demo",
                    "name": "Demo",
                    "root": "/tmp/demo",
                    "git_branch": "main",
                },
                "defaults": {"harness": "echo", "model": "local"},
            }
        if path == "/api/sessions/sess_1":
            return {"session": {"id": "sess_1", "workspace": "/tmp/demo"}}
        if path.startswith("/api/sessions?"):
            return {
                "sessions": [
                    {
                        "id": "sess_1",
                        "title": "Attached",
                        "updated_at": "2026-07-20T00:00:00Z",
                        "workspace": "/tmp/demo",
                        "default_harness_id": "echo",
                        "default_model": "local",
                        "default_mode": "plan",
                    }
                ]
            }
        if path == "/api/harnesses":
            return {
                "harnesses": [
                    {
                        "spec": {"id": "echo", "title": "Echo"},
                        "availability": {
                            "status": "available",
                            "reason": "local",
                        },
                        "workbench_transport": {"default": "one_shot"},
                    }
                ]
            }
        if path == "/api/integrations":
            return {
                "catalog": [{"catalog_id": "pkg_1"}],
                "flows": [{"id": "flow_1", "status": "verified"}],
                "content_free": True,
            }
        if path == "/api/preflight/run":
            return {
                "preflight": {
                    "readiness": {
                        "status": "ready",
                        "plan": {"execution_transport": "one_shot"},
                        "findings": [],
                    }
                }
            }
        if path == "/api/sessions":
            return {
                "session": {
                    "id": "sess_2",
                    "title": payload["title"],
                    "updated_at": "2026-07-20T00:00:00Z",
                    "workspace": payload["workspace"],
                    "default_harness_id": "echo",
                    "default_model": "local",
                    "default_mode": "plan",
                }
            }
        if path == "/api/project/state":
            return {"state": payload}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", request)

    snapshot = await client.load(None, selected_session_id="sess_1")
    created = await client.create_session(
        "/tmp/demo",
        title="New",
        harness_id="codex-cli",
        model="reasoning-model",
        api_mode="v2",
        mode="read",
    )
    await client.remember_session("/tmp/demo", created.id)

    assert snapshot.transport_mode == "attach"
    assert snapshot.selected_session_id == "sess_1"
    assert snapshot.readiness.status == "ready"
    assert snapshot.integrations.verified_count == 1
    assert created.id == "sess_2"
    assert (
        "POST",
        "/api/sessions",
        {
            "workspace": "/tmp/demo",
            "title": "New",
            "harness_id": "codex-cli",
            "model": "reasoning-model",
            "api_mode": "v2",
            "mode": "read",
        },
    ) in calls
    assert (
        "PATCH",
        "/api/project/state",
        {
            "workspace": "/tmp/demo",
            "last_selected_session": "sess_2",
        },
    ) in calls


@pytest.mark.anyio
async def test_attach_client_stream_snapshot_and_actions_share_exact_binding(
    monkeypatch,
):
    client = AttachedWorkbenchClient("http://127.0.0.1:8091")
    calls: list[tuple[str, str, object]] = []

    async def request(method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/api/cockpit/runs/run_1":
            return {
                "snapshot_revision": "a" * 64,
                "run": {
                    "id": "run_1",
                    "session_id": "sess_1",
                    "status": "running",
                    "provider_session": {"revision": 3, "link_hash": "b" * 64},
                },
            }
        if path.startswith("/api/sessions/sess_1/events?"):
            return {
                "events": [
                    {
                        "id": "evt_1",
                        "session_id": "sess_1",
                        "run_id": "run_1",
                        "type": "message_delta",
                        "message": "delta",
                        "payload": {"delta": "hello"},
                        "created_at": "2026-07-20T00:00:00Z",
                    }
                ]
            }
        if path == "/api/approvals?status=pending&limit=100":
            return {
                "approvals": [
                    {
                        "id": "approval_1",
                        "run_id": "run_1",
                        "action": "tool.call",
                        "reason": "tool",
                        "status": "pending",
                    }
                ]
            }
        if path == "/api/runs/run_1/steer":
            return {"accepted": True}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", request)

    snapshot = await client.snapshot_run("run_1", cursor="invalid")
    steered = await client.steer_run(
        snapshot.binding,
        "continue",
        idempotency_key="steer_1",
    )

    assert snapshot.binding.generation == 3
    assert snapshot.resnapshot_reason == "cursor_gap"
    assert snapshot.events[0].delta == "hello"
    assert snapshot.pending_approvals[0].id == "approval_1"
    assert steered.binding == snapshot.binding
    steer_payload = next(
        payload for method, path, payload in calls if path == "/api/runs/run_1/steer"
    )
    assert steer_payload["revision"] == "a" * 64
    assert steer_payload["generation"] == 3


@pytest.mark.anyio
async def test_attach_client_uses_authoritative_file_evidence_and_handoff_queries(
    monkeypatch,
):
    client = AttachedWorkbenchClient("http://127.0.0.1:8091")
    calls: list[tuple[str, str, object]] = []

    async def request(method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if "/attachments/workspace/search?" in path:
            return {
                "files": [
                    {
                        "path": "src/app.py",
                        "name": "app.py",
                        "mime_type": "text/x-python",
                        "kind": "text",
                        "size_bytes": 8,
                    }
                ]
            }
        if "/attachments/workspace/preview?" in path:
            return {"preview": {"status": "ready", "text": "print(1)"}}
        if path == "/api/sessions/sess_1/attachments/workspace":
            return {
                "attachment": {
                    "id": "att_1",
                    "workspace_path": "src/app.py",
                    "mime_type": "text/x-python",
                    "kind": "workspace_file",
                    "size_bytes": 8,
                }
            }
        if path == "/api/cockpit/runs/run_1":
            return {
                "snapshot_revision": "a" * 64,
                "run": {
                    "id": "run_1",
                    "session_id": "sess_1",
                    "harness_id": "claude-code",
                    "status": "succeeded",
                    "provider_session": {"revision": 2, "recovery_state": "ready"},
                    "artifacts": [{"type": "diff", "byte_count": 12}],
                },
            }
        if path.startswith("/api/cockpit/runs/run_1/diff?"):
            return {
                "patch": {"text": "+safe\x1b]52;c;x\x07", "truncated": False},
                "changed_files": ["src/app.py"],
                "untracked_files": [],
            }
        if path == "/api/harnesses":
            return {
                "harnesses": [
                    {
                        "spec": {"id": "claude-code"},
                        "availability": {"status": "available"},
                    }
                ]
            }
        if path == "/api/runs/run_1/summary":
            return {"run": {"job": {"status": "succeeded"}}}
        if path == "/api/sessions/sess_1":
            return {
                "session": {
                    "id": "sess_1",
                    "workspace": "/tmp/demo",
                    "default_harness_id": "claude-code",
                }
            }
        if path.startswith("/api/provider-handoffs/claude-code/preview?"):
            return {
                "handoff": {
                    "status": "supported",
                    "surface": "Claude Desktop",
                    "instruction": "Review then open",
                    "command": ["claude", "/desktop"],
                    "observability_limits": ["structured_events_unavailable"],
                }
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", request)

    files = await client.search_files("sess_1", "app")
    attachment = await client.attach_file("sess_1", files[0].path)
    inspection = await client.inspect_run("run_1")
    provider = await client.provider_handoff("sess_1")
    web = await client.web_handoff("sess_1")

    assert files[0].preview == "print(1)"
    assert attachment.id == "att_1"
    assert inspection.changed_files == ("src/app.py",)
    assert "⟦terminal-control⟧" in inspection.diff
    assert provider.target == "Claude Desktop"
    assert provider.command == ("claude", "/desktop")
    assert web.target.endswith("/cockpit-v2/work/sess_1")
    assert (
        "POST",
        "/api/sessions/sess_1/attachments/workspace",
        {"path": "src/app.py"},
    ) in calls


@pytest.mark.anyio
async def test_attach_client_contains_native_terminal_through_existing_api(
    monkeypatch,
):
    client = AttachedWorkbenchClient("http://127.0.0.1:8091")
    calls: list[tuple[str, str, object]] = []

    def process(status="running", *, cursor=0, exit_code=None):
        return {
            "id": "proc_1",
            "session_id": "sess_1",
            "run_id": "run_1",
            "harness_id": "codex-cli",
            "transport": "pty",
            "status": status,
            "terminal_cursor": cursor,
            "exit_code": exit_code,
        }

    async def request(method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/api/native/processes/start":
            return {"process": process(), "run": {"id": "run_1"}}
        if path == "/api/native/processes/proc_1/output?cursor=0":
            return {
                "process_id": "proc_1",
                "status": "running",
                "cursor": 2,
                "run": {
                    "id": "run_1",
                    "session_id": "sess_1",
                    "harness_id": "codex-cli",
                },
                "outputs": [
                    {"text": "safe\n"},
                    {"text": "\x1b]52;c;clipboard\x07\x1b[?1049howned"},
                ],
            }
        if path == "/api/native/processes/proc_1/input":
            return {"process": process(cursor=2), "run": {"id": "run_1"}}
        if path == "/api/native/processes/proc_1/resize":
            return {"process": process(cursor=2), "run": {"id": "run_1"}}
        if method == "GET" and path == "/api/native/processes/proc_1":
            return {"process": process(cursor=2), "run": {"id": "run_1"}}
        if method == "DELETE" and path == "/api/native/processes/proc_1":
            return {
                "process": process("stopped", cursor=2, exit_code=0),
                "run": {"id": "run_1"},
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", request)

    started = await client.start_native_terminal(
        "sess_1",
        "inspect",
        idempotency_key="native_1",
        attachment_ids=("att_1",),
        harness_id="codex-cli",
        model="reasoning-model",
        api_mode="v2",
        mode="read",
    )
    output = await client.snapshot_native_terminal(started.process_id)
    status = await client.status_native_terminal("proc_1")
    await client.send_native_terminal_input("proc_1", "continue", submit=True)
    await client.resize_native_terminal("proc_1", rows=24, columns=80)
    stopped = await client.stop_native_terminal("proc_1")

    assert started.transport == "pty"
    assert output.cursor == 2
    assert output.handoff_required is True
    assert status.status == "running"
    assert "safe" in output.output
    assert "terminal-control" in output.output
    assert "\x1b" not in output.output
    assert stopped.status == "stopped"
    assert stopped.exit_code == 0
    assert (
        "POST",
        "/api/native/processes/start",
        {
            "action": "start",
            "session_id": "sess_1",
            "prompt": "inspect",
            "idempotency_key": "native_1",
            "attachment_ids": ["att_1"],
            "execution_transport": "native_terminal",
            "invocation_mode": "native",
            "harness_id": "codex-cli",
            "model": "reasoning-model",
            "api_mode": "v2",
            "mode": "read",
        },
    ) in calls
    assert (
        "POST",
        "/api/native/processes/proc_1/input",
        {"data": "continue", "submit": True},
    ) in calls


@pytest.mark.anyio
async def test_native_terminal_fails_closed_for_in_process_and_control_input(tmp_path):
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(tmp_path / "state")))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = client.sessions.create_session(
        {"workspace": str(workspace), "harness_id": "echo"},
        validate_harness=True,
    )

    with pytest.raises(WorkbenchClientError, match="requires attach mode"):
        await client.start_native_terminal(
            session.id, "inspect", idempotency_key="native_1"
        )
    with pytest.raises(WorkbenchClientError, match="terminal controls"):
        await client.send_native_terminal_input("proc_1", "\x1b[2J")


@pytest.mark.parametrize(
    "value",
    (
        "ftp://127.0.0.1",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1?token=secret",
        "http://127.0.0.1/base-path",
    ),
)
def test_attach_client_rejects_unsafe_origins(value):
    with pytest.raises(ValueError, match="HTTP\(S\) origin"):
        AttachedWorkbenchClient(value)


def test_tui_catalogs_have_exact_key_parity_and_english_fallback(monkeypatch):
    assert set(CATALOGS["en"]) == set(CATALOGS["ru"])
    assert translator("ru")("pane.sessions") == "Сессии"
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert resolve_locale() == "en"


def test_tui_missing_standard_dependency_reports_reinstall(monkeypatch, capsys):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    def missing_textual(name):
        assert name == "gpt2giga_harness.tui.app"
        raise ModuleNotFoundError("No module named 'textual'", name="textual")

    monkeypatch.setattr(importlib, "import_module", missing_textual)

    assert tui_entrypoint.main([]) == 2
    error = capsys.readouterr().err
    assert "standard Harness installation is incomplete" in error
    assert "gpt2giga-harness[tui]" not in error


def test_tui_help_does_not_import_textual_fastapi_or_uvicorn():
    source = """
import sys
from gpt2giga_harness import entrypoint
try:
    entrypoint.main(["--help"])
except SystemExit as exc:
    assert exc.code == 0
print("textual" in sys.modules, "fastapi" in sys.modules, "uvicorn" in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", source],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.rstrip().endswith("False False False")


def test_console_entrypoint_dispatches_tui_without_full_cli(monkeypatch):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)
    monkeypatch.setattr(
        tui_entrypoint,
        "main",
        lambda arguments, **_kwargs: len(arguments),
    )
    context = TerminalContext(True, True, True, "xterm-256color")

    assert entrypoint.main(["--workspace", "."], context=context) == 2
    assert entrypoint.main(["tui", "--workspace", "."], context=context) == 2
    assert "gpt2giga_harness.cli" not in sys.modules


def test_automation_cli_does_not_advertise_a_competing_tui_command():
    from gpt2giga_harness import cli

    help_text = cli.build_parser().format_help()
    assert "tui" not in help_text


def test_bare_console_entrypoint_dispatches_to_tui(monkeypatch):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)
    calls = []
    monkeypatch.setattr(
        tui_entrypoint,
        "main",
        lambda arguments, **kwargs: calls.append((arguments, kwargs)) or 0,
    )

    context = TerminalContext(True, True, True, "xterm-256color")
    assert entrypoint.main([], context=context) == 0
    assert calls[0][0] == []
    assert "gpt2giga_harness.cli" not in sys.modules


def test_bare_console_entrypoint_fails_closed_without_an_interactive_terminal(
    monkeypatch, capsys
):
    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)

    context = TerminalContext(False, False, True, "xterm-256color")
    assert entrypoint.main(["tui"], context=context) == 2

    assert "requires a supported interactive terminal" in capsys.readouterr().err
    assert "gpt2giga_harness.cli" not in sys.modules


def test_tui_run_scopes_accessibility_environment_and_restores_it(
    monkeypatch, tmp_path
):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    calls = []

    class FakeApplication:
        def run(self, **kwargs):
            calls.append((kwargs, dict(os.environ)))

    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TEXTUAL_ANIMATIONS", "basic")
    monkeypatch.delenv("TEXTUAL_SMOOTH_SCROLL", raising=False)
    monkeypatch.setattr(
        tui_entrypoint.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            WorkbenchTui=lambda *_args, **_kwargs: FakeApplication()
        ),
    )
    monkeypatch.setattr(
        tui_entrypoint, "InProcessWorkbenchClient", lambda _config: None
    )

    assert tui_entrypoint.main(["--no-color", "--no-animation"]) == 0

    assert calls[0][0] == {"mouse": False}
    assert calls[0][1]["NO_COLOR"] == "1"
    assert calls[0][1]["TEXTUAL_ANIMATIONS"] == "none"
    assert calls[0][1]["TEXTUAL_SMOOTH_SCROLL"] == "0"
    assert "NO_COLOR" not in os.environ
    assert os.environ["TEXTUAL_ANIMATIONS"] == "basic"
    assert "TEXTUAL_SMOOTH_SCROLL" not in os.environ


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "--non-interactive",
            "session",
            "approve",
            "approval_1",
            "--decision",
            "allow_once",
        ),
        ("--non-interactive", "chat", "inspect"),
        ("chat", "--non-interactive", "inspect"),
        ("run", "--agent", "codex", "--non-interactive", "inspect"),
        ("session", "list", "--non-interactive"),
    ),
)
def test_cli_accepts_the_explicit_non_interactive_escape(arguments):
    from gpt2giga_harness import cli

    assert cli.build_parser().parse_args(arguments).non_interactive is True


def test_attach_error_is_content_free():
    error = WorkbenchClientError("attach endpoint is unavailable")
    assert "endpoint" in str(error)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        (
            ("chat", "--model", "chat-model", "hello", "world"),
            {
                "create_session": True,
                "harness_id": "direct-chat",
                "model": "chat-model",
                "mode": "plan",
                "prompt": "hello world",
            },
        ),
        (
            (
                "run",
                "--agent",
                "codex",
                "--workspace",
                ".",
                "--mode",
                "read",
                "--native",
                "inspect",
            ),
            {
                "create_session": True,
                "workspace": ".",
                "harness_id": "codex-cli",
                "mode": "read",
                "execution_transport": "native_terminal",
                "prompt": "inspect",
            },
        ),
        (
            (
                "session",
                "turn",
                "sess_1",
                "--prompt",
                "continue",
                "--transport",
                "native_structured",
            ),
            {
                "session_id": "sess_1",
                "execution_transport": "native_structured",
                "prompt": "continue",
            },
        ),
    ),
)
def test_human_terminal_deep_links_preserve_typed_intent(arguments, expected):
    intent, tui_arguments = parse_tui_launch_intent(arguments)

    assert tui_arguments == []
    for key, value in expected.items():
        assert getattr(intent, key) == value


def test_console_entrypoint_deep_links_human_chat_without_importing_cli(monkeypatch):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)
    calls = []
    monkeypatch.setattr(
        tui_entrypoint,
        "main",
        lambda arguments, **kwargs: calls.append((arguments, kwargs)) or 0,
    )

    context = TerminalContext(True, True, True, "xterm-256color")
    assert entrypoint.main(["chat", "hello"], context=context) == 0

    assert calls[0][0] == []
    assert calls[0][1]["launch_intent"].harness_id == "direct-chat"
    assert calls[0][1]["launch_intent"].prompt == "hello"
    assert "gpt2giga_harness.cli" not in sys.modules
