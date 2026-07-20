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
            "title": "First\x1b]52;c;hidden\x07 session",
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
    assert snapshot.sessions[0].title == "First�]52;c;hidden� session"
    assert snapshot.readiness.harness_id == "echo"
    assert snapshot.readiness.harness_status == "available"
    assert snapshot.readiness.model == "local-model"
    assert snapshot.readiness.transport == "one_shot"
    assert snapshot.readiness.provider_status == "not_checked"

    created = await client.create_session(str(first), title="From TUI")
    resumed = await client.load(str(first))

    assert resumed.selected_session_id == created.id
    assert {session.title for session in resumed.sessions} == {
        "First�]52;c;hidden� session",
        "From TUI",
    }


@pytest.mark.anyio
async def test_in_process_client_submits_idempotent_turn_and_resnapshots(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = InProcessWorkbenchClient(HarnessConfig(data_dir=str(tmp_path / "state")))
    session = client.sessions.create_session(
        {"workspace": str(workspace), "harness_id": "echo"},
        validate_harness=True,
    )

    first = await client.submit_turn(session.id, "hello", idempotency_key="turn_1")
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

    snapshot = await client.load("/tmp/demo", selected_session_id="sess_1")
    created = await client.create_session("/tmp/demo", title="New")
    await client.remember_session("/tmp/demo", created.id)

    assert snapshot.transport_mode == "attach"
    assert snapshot.selected_session_id == "sess_1"
    assert snapshot.readiness.status == "ready"
    assert created.id == "sess_2"
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
    monkeypatch.setattr(tui_entrypoint, "main", lambda arguments: len(arguments))
    monkeypatch.setattr(entrypoint, "_tui_environment_supported", lambda: True)

    assert entrypoint.main(["--workspace", "."]) == 2
    assert entrypoint.main(["tui", "--workspace", "."]) == 2
    assert "gpt2giga_harness.cli" not in sys.modules


def test_automation_cli_does_not_advertise_a_competing_tui_command():
    from gpt2giga_harness import cli

    help_text = cli.build_parser().format_help()
    assert "tui" not in help_text


def test_bare_console_entrypoint_dispatches_to_tui(monkeypatch):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)
    monkeypatch.setattr(entrypoint, "_tui_environment_supported", lambda: True)
    calls = []
    monkeypatch.setattr(
        tui_entrypoint,
        "main",
        lambda arguments: calls.append(arguments) or 0,
    )

    assert entrypoint.main([]) == 0
    assert calls == [[]]
    assert "gpt2giga_harness.cli" not in sys.modules


def test_bare_console_entrypoint_fails_closed_without_an_interactive_terminal(
    monkeypatch, capsys
):
    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)
    monkeypatch.setattr(entrypoint, "_tui_environment_supported", lambda: False)

    assert entrypoint.main([]) == 2

    assert "requires a supported interactive terminal" in capsys.readouterr().err
    assert "gpt2giga_harness.cli" not in sys.modules


def test_tui_run_uses_textual_8_signature_and_scopes_no_color(monkeypatch, tmp_path):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    calls = []

    class FakeApplication:
        def run(self, **kwargs):
            calls.append((kwargs, dict(os.environ)))

    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NO_COLOR", raising=False)
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

    assert tui_entrypoint.main(["--no-color"]) == 0

    assert calls[0][0] == {"mouse": False}
    assert calls[0][1]["NO_COLOR"] == "1"
    assert "NO_COLOR" not in os.environ


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
