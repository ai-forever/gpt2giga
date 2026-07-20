from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from gpt2giga_harness import entrypoint
from gpt2giga_harness.config import HarnessConfig
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


def test_tui_missing_extra_reports_remediation(monkeypatch, capsys):
    from gpt2giga_harness.tui import entrypoint as tui_entrypoint

    def missing_textual(name):
        assert name == "gpt2giga_harness.tui.app"
        raise ModuleNotFoundError("No module named 'textual'", name="textual")

    monkeypatch.setattr(importlib, "import_module", missing_textual)

    assert tui_entrypoint.main([]) == 2
    assert "gpt2giga-harness[tui]" in capsys.readouterr().err


def test_tui_help_does_not_import_textual_fastapi_or_uvicorn():
    source = """
import sys
from gpt2giga_harness import entrypoint
try:
    entrypoint.main(["tui", "--help"])
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

    assert entrypoint.main(["tui", "--workspace", "."]) == 2
    assert "gpt2giga_harness.cli" not in sys.modules


def test_main_cli_help_advertises_optional_tui():
    from gpt2giga_harness import cli

    assert "tui" in cli.build_parser().format_help()


def test_attach_error_is_content_free():
    error = WorkbenchClientError("attach endpoint is unavailable")
    assert "endpoint" in str(error)
