import base64
import os
import json
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness import proxy
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.native.base import NativeCommandPlan
from gpt2giga_harness.native.claude import ClaudeNativeHistoryConnector
from gpt2giga_harness.native.codex import CodexNativeHistoryConnector
from gpt2giga_harness.native.gemini import GeminiNativeHistoryConnector
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
    create_execution_snapshot,
)
from gpt2giga_harness.native.process import NativeProcessManager
from gpt2giga_harness.native.registry import NativeHistoryConnectorRegistry
from gpt2giga_harness.native.store import FilesystemNativeSessionIndexStore
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.runtime.policy import NATIVE_PROCESS_SPAWN_OWNER
from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    InMemoryHarnessSessionStore,
)
from gpt2giga_harness.session_titles import title_diagnostics
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessContext,
    HarnessRequest,
    REDACTED,
)
from gpt2giga_harness.ui.app import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_native_process_api_start_poll_input_and_stop(tmp_path):
    script = _write_echo_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    process_id = started.json()["process"]["id"]
    assert started.json()["process"]["status"] == "running"
    assert started.json()["run"]["invocation_mode"] == "native"

    cursor, output = _wait_for_output(client, process_id, 0, "ready")
    assert "ready" in output

    sent = client.post(
        f"/api/native/processes/{process_id}/input",
        json={"data": "hello\n", "message": "hello"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["message"]["content"] == "hello"
    assert sent.json()["message"]["metadata"] == {"source": "native_stdin"}
    cursor, output = _wait_for_output(client, process_id, cursor, "echo:hello")
    assert "echo:hello" in output
    assert [message.content for message in store.list_messages(session.id)] == [
        "boot",
        "hello",
    ]

    stopped = client.delete(f"/api/native/processes/{process_id}")

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["process"]["status"] in {"stopped", "exited"}
    event_types = {event.type for event in store.list_events(session.id)}
    assert event_types >= {
        "terminal_start",
        "terminal_input",
        "terminal_output",
        "terminal_stop",
    }


def test_native_process_api_rejects_unproven_builtin_cli_contract(tmp_path):
    registry = create_default_registry(include_entry_points=False)
    harness = registry.get("codex-cli")
    harness.capability_probe = lambda: CliCapabilitySnapshot(
        harness_id="codex-cli",
        status="unsupported",
        version="fixture 0.0.0",
        parsed_version="0.0.0",
        command=("/tmp/codex-fixture",),
        capabilities={"--json": False},
        event_schema="codex-exec-jsonl-v1",
        history_schema="codex-session-jsonl-v1",
        warning="Codex CLI fixture is missing --json.",
        evidence="test fixture",
    )
    script = _write_once_cli(tmp_path)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script, harness_id="codex-cli"),
        registry=registry,
    )
    session = store.create_session(
        title="Unsupported native CLI",
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "codex-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Codex CLI fixture is missing --json."
    assert store.list_runs(session.id) == ()


def test_native_process_output_stream_resumes_from_persisted_cursor(tmp_path):
    script = _write_echo_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native output stream",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )
    process_id = started.json()["process"]["id"]
    ready_cursor, _ = _wait_for_output(client, process_id, 0, "ready")
    client.post(
        f"/api/native/processes/{process_id}/input",
        json={"data": "streamed\n"},
    )
    echo_cursor, _ = _wait_for_output(client, process_id, ready_cursor, "echo:streamed")
    client.delete(f"/api/native/processes/{process_id}")

    response = client.get(
        f"/api/native/processes/{process_id}/output/stream",
        headers={"Last-Event-ID": str(ready_cursor)},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert len(payloads) == 1
    assert payloads[0]["cursor"] == echo_cursor
    assert "echo:streamed" in "".join(
        output["text"] for output in payloads[0]["outputs"]
    )
    assert "ready" not in str(payloads[0]["outputs"])
    assert payloads[0]["status"] in {"stopped", "exited"}
    assert f"id: {echo_cursor}" in response.text


def test_native_process_resize_api_validates_terminal_limits(tmp_path):
    script = _write_echo_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native resize",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )
    process_id = started.json()["process"]["id"]

    invalid = client.post(
        f"/api/native/processes/{process_id}/resize",
        json={"rows": 1, "columns": 120},
    )
    unavailable = client.post(
        f"/api/native/processes/{process_id}/resize",
        json={"rows": 36, "columns": 120},
    )

    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "rows must be between 2 and 200"
    assert unavailable.status_code == 400
    assert "unavailable for this process transport" in unavailable.json()["detail"]
    client.delete(f"/api/native/processes/{process_id}")


def test_native_process_api_submit_sends_enter_after_input(tmp_path):
    script = _write_echo_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native submit",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )
    process_id = started.json()["process"]["id"]
    _wait_for_output(client, process_id, 0, "ready")

    before = time.monotonic()
    sent = client.post(
        f"/api/native/processes/{process_id}/input",
        json={"data": "second turn", "message": "second turn", "submit": True},
    )

    assert sent.status_code == 200, sent.text
    assert time.monotonic() - before >= 0.04
    terminal_inputs = [
        event.payload["text"]
        for event in store.list_events(session.id)
        if event.type == "terminal_input"
    ]
    assert terminal_inputs[-2:] == ["second turn", "\r"]
    assert sent.json()["message"]["content"] == "second turn"


def test_native_process_failure_is_rendered_as_chat_error_once(tmp_path):
    script = tmp_path / "failing_native.py"
    script.write_text(
        "import sys\n"
        "print('selected model is unavailable', file=sys.stderr, flush=True)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native failure",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "boot",
            "workspace": str(tmp_path),
        },
    )

    process_id = started.json()["process"]["id"]
    completed = _wait_for_process_status(client, process_id, {"failed"})
    client.get(f"/api/native/processes/{process_id}")

    assert completed["run"]["error"] == "Native process exited with code 3"
    error_messages = [
        message
        for message in store.list_messages(session.id)
        if message.role == "error"
    ]
    assert len(error_messages) == 1
    assert "Native process exited with code 3" in error_messages[0].content
    assert "selected model is unavailable" in error_messages[0].content
    assert error_messages[0].metadata == {
        "source": "native_process",
        "process_id": process_id,
        "exit_code": 3,
    }


@pytest.mark.parametrize(
    ("harness_id", "native_ref_id", "native_session_id"),
    [
        ("claude-code", "native_claude_live", "claude-live-session"),
        ("gemini-cli", "native_gemini_live", "gemini-live-session"),
    ],
)
def test_native_process_syncs_assistant_message_while_running(
    tmp_path,
    harness_id,
    native_ref_id,
    native_session_id,
):
    script = _write_echo_cli(tmp_path)

    class TranscriptConnector(FakeProcessConnector):
        def __init__(self):
            super().__init__(start_script=script, harness_id=harness_id)
            self.snapshot = None

        def build_start_command(self, request, context):
            plan = super().build_start_command(request, context)
            self.snapshot = create_execution_snapshot(
                harness_id=self.harness_id,
                api_mode=request.api_mode.value,
                model=request.model,
                native_home=request.workspace,
                workspace=request.workspace,
                project_id="proj_native_transcript",
                permission_mode=request.mode,
                tool_config_hash=None,
            )
            return replace(plan, execution_snapshot=self.snapshot)

        def discover(self, *, workspace, include_external):
            del include_external
            return (
                NativeSessionRef(
                    id=native_ref_id,
                    harness_id=self.harness_id,
                    native_session_id=native_session_id,
                    title="Live native session",
                    workspace=workspace,
                    source="managed-live.jsonl",
                    status=NativeSessionStatus.MANAGED_NATIVE,
                    created_at="2099-01-01T00:00:00Z",
                    updated_at="2099-01-01T00:00:01Z",
                    message_count=2,
                    can_preview=True,
                    can_import=True,
                    can_resume=True,
                    execution_snapshot=self.snapshot,
                ),
            )

        def import_ref(self, ref):
            del ref
            return (
                NativeTranscriptMessage(
                    role="assistant",
                    content="Привет! Всё хорошо.",
                    created_at="2099-01-01T00:00:01Z",
                    metadata={"native_message_id": "assistant-live-1"},
                ),
            )

    connector = TranscriptConnector()
    client, store = _client(tmp_path, connector)
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id=harness_id,
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": harness_id,
            "action": "start",
            "prompt": "Привет как дела?",
            "workspace": str(tmp_path),
        },
    )

    process_id = started.json()["process"]["id"]
    _wait_for_output(client, process_id, 0, "ready")
    first_poll = client.get(f"/api/native/processes/{process_id}/output").json()
    second_poll = client.get(f"/api/native/processes/{process_id}/output").json()

    assert first_poll["status"] == "running"
    assert [message["content"] for message in first_poll["messages"]] == [
        "Привет! Всё хорошо."
    ]
    assert [message["content"] for message in second_poll["messages"]] == [
        "Привет! Всё хорошо."
    ]
    assistant_messages = [
        message
        for message in store.list_messages(session.id)
        if message.role == "assistant"
    ]
    assert len(assistant_messages) == 1
    assert (
        assistant_messages[0]
        .metadata["native_message_key"]
        .endswith(":id:assistant-live-1")
    )
    (run,) = store.list_runs(session.id)
    assert run.native_session_id == native_session_id
    indexed = client.get("/api/native/sessions").json()["sessions"]
    assert [item["id"] for item in indexed] == [native_ref_id]
    links = store.list_native_links(session.id)
    assert links[-1].native_ref_id == native_ref_id
    assert links[-1].native_session_id == native_session_id
    assert links[-1].metadata["auto_reconciled"] is True
    titled = store.get_session(session.id)
    assert titled.title == "Live native session"
    assert title_diagnostics(titled)["provenance"] == "provider_native"


def test_native_process_auto_reconciles_codex_history_ref(tmp_path):
    script = _write_echo_cli(tmp_path)

    class CodexReconcileConnector(FakeProcessConnector):
        def __init__(self):
            super().__init__(start_script=script, harness_id="codex-cli")
            self.snapshot = None

        def build_start_command(self, request, context):
            plan = super().build_start_command(request, context)
            self.snapshot = create_execution_snapshot(
                harness_id=self.harness_id,
                api_mode=request.api_mode.value,
                model=request.model,
                native_home=request.workspace,
                workspace=request.workspace,
                project_id=project_id_for_root(request.workspace),
                permission_mode=request.mode,
                tool_config_hash=None,
            )
            return replace(plan, execution_snapshot=self.snapshot)

        def discover(self, *, workspace, include_external):
            del include_external
            return (
                NativeSessionRef(
                    id="native_codex_reconciled",
                    harness_id=self.harness_id,
                    native_session_id="codex-reconciled-session",
                    title="Reconciled Codex session",
                    workspace=workspace,
                    source="managed-codex.jsonl",
                    status=NativeSessionStatus.MANAGED_NATIVE,
                    created_at="2099-01-01T00:00:00Z",
                    updated_at="2099-01-01T00:00:01Z",
                    message_count=1,
                    can_preview=True,
                    can_import=True,
                    can_resume=True,
                    metadata={"project_id": project_id_for_root(workspace)},
                    execution_snapshot=self.snapshot,
                ),
            )

    connector = CodexReconcileConnector()
    client, store = _client(tmp_path, connector)
    session = store.create_session(
        title="Codex reconciliation",
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "codex-cli",
            "action": "start",
            "prompt": "inspect",
            "workspace": str(tmp_path),
        },
    )
    process_id = started.json()["process"]["id"]

    _wait_for_output(client, process_id, 0, "ready")
    client.get(f"/api/native/processes/{process_id}/output")

    (run,) = store.list_runs(session.id)
    assert run.native_session_id == "codex-reconciled-session"
    assert client.get("/api/native/sessions").json()["sessions"][0]["id"] == (
        "native_codex_reconciled"
    )
    assert store.get_native_link(session.id, "codex-cli").native_ref_id == (
        "native_codex_reconciled"
    )


def test_native_process_syncs_claude_tool_events_while_running(tmp_path):
    script = _write_echo_cli(tmp_path)

    class ToolTranscriptConnector(FakeProcessConnector):
        def __init__(self):
            super().__init__(start_script=script, harness_id="claude-code")
            self.snapshot = None

        def build_start_command(self, request, context):
            plan = super().build_start_command(request, context)
            self.snapshot = create_execution_snapshot(
                harness_id=self.harness_id,
                api_mode=request.api_mode.value,
                model=request.model,
                native_home=request.workspace,
                workspace=request.workspace,
                project_id="proj_native_tools",
                permission_mode=request.mode,
                tool_config_hash=None,
            )
            return replace(plan, execution_snapshot=self.snapshot)

        def discover(self, *, workspace, include_external):
            del include_external
            return (
                NativeSessionRef(
                    id="native_claude_tools",
                    harness_id=self.harness_id,
                    native_session_id="claude-tools-session",
                    title="Native tools",
                    workspace=workspace,
                    source="managed-tools.jsonl",
                    status=NativeSessionStatus.MANAGED_NATIVE,
                    created_at="2099-01-01T00:00:00Z",
                    updated_at="2099-01-01T00:00:03Z",
                    message_count=3,
                    can_preview=True,
                    can_import=True,
                    can_resume=True,
                    execution_snapshot=self.snapshot,
                ),
            )

        def import_ref(self, ref):
            del ref
            return (
                NativeTranscriptMessage(
                    role="assistant",
                    content="",
                    created_at="2099-01-01T00:00:01Z",
                    metadata={
                        "native_message_id": "tool-start-message",
                        "tool_calls": [
                            {
                                "tool_call_id": "toolu_read",
                                "name": "Read",
                                "arguments": {"file_path": "/repo/README.md"},
                                "status": "running",
                                "parent_tool_call_id": "toolu_agent",
                                "subagent_id": "agent-explore",
                                "subagent_type": "Explore",
                                "subagent_description": "Inspect repository",
                                "subagent_depth": 1,
                            }
                        ],
                    },
                ),
                NativeTranscriptMessage(
                    role="tool",
                    content="",
                    created_at="2099-01-01T00:00:02Z",
                    metadata={
                        "native_message_id": "tool-result-message",
                        "tool_results": [
                            {
                                "tool_call_id": "toolu_read",
                                "result": "README contents",
                                "status": "completed",
                                "parent_tool_call_id": "toolu_agent",
                                "subagent_id": "agent-explore",
                                "subagent_type": "Explore",
                                "subagent_description": "Inspect repository",
                                "subagent_depth": 1,
                            }
                        ],
                    },
                ),
                NativeTranscriptMessage(
                    role="assistant",
                    content="Done.",
                    created_at="2099-01-01T00:00:03Z",
                    metadata={"native_message_id": "assistant-final-message"},
                ),
            )

    connector = ToolTranscriptConnector()
    client, store = _client(tmp_path, connector)
    session = store.create_session(
        title="Native tools",
        workspace=str(tmp_path),
        default_harness_id="claude-code",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "claude-code",
            "action": "start",
            "prompt": "Read the repository",
            "workspace": str(tmp_path),
        },
    )

    process_id = started.json()["process"]["id"]
    _wait_for_output(client, process_id, 0, "ready")
    first_poll = client.get(f"/api/native/processes/{process_id}/output").json()
    second_poll = client.get(f"/api/native/processes/{process_id}/output").json()

    assert [message["content"] for message in first_poll["messages"]] == ["Done."]
    tool_events = [
        event
        for event in first_poll["events"]
        if event["type"].startswith("tool_call_")
    ]
    assert [event["type"] for event in tool_events] == [
        "tool_call_started",
        "tool_call_finished",
    ]
    assert tool_events[0]["payload"]["name"] == "Read"
    assert tool_events[0]["payload"]["arguments"] == {"file_path": "/repo/README.md"}
    assert tool_events[0]["payload"]["parent_tool_call_id"] == "toolu_agent"
    assert tool_events[0]["payload"]["subagent_type"] == "Explore"
    assert tool_events[1]["payload"]["result"] == "README contents"
    assert tool_events[1]["payload"]["subagent_id"] == "agent-explore"
    assert len(second_poll["events"]) == len(first_poll["events"])
    stored_tool_events = [
        event
        for event in store.list_events(session.id)
        if event.type.startswith("tool_call_")
    ]
    assert len(stored_tool_events) == 2


def test_native_process_api_approval_blocks_before_worktree_and_spawn(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    data_dir = tmp_path / "data"
    script = _write_workspace_cli(tmp_path)
    store = FilesystemHarnessSessionStore(data_dir)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script),
        config=HarnessConfig(data_dir=str(data_dir)),
        store=store,
    )
    session = store.create_session(
        title="Native approval",
        workspace=str(repo),
        default_harness_id="fake-cli",
        metadata={"project_id": "project_native_policy"},
    )
    payload = {
        "session_id": session.id,
        "harness_id": "fake-cli",
        "action": "start",
        "prompt": "edit safely",
        "mode": "edit",
        "workspace": str(repo),
        "workspace_policy": "auto",
        "permission_profile": "review_every_action",
        "idempotency_key": "native-approval-deny",
    }

    waiting = client.post("/api/native/processes/start", json=payload)

    assert waiting.status_code == 202, waiting.text
    approval = waiting.json()["approval"]
    assert approval["action"] == "process.spawn"
    assert approval["enforcement"] == "enforced_by_harness"
    assert approval["enforcement_owner"] == NATIVE_PROCESS_SPAWN_OWNER
    assert "edit safely" not in str(approval)
    assert store.list_runs(session.id) == ()
    assert not (data_dir / "worktrees").exists()
    assert not (repo / "native-cwd.txt").exists()

    denied = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "deny"},
    )

    assert denied.status_code == 200, denied.text
    assert denied.json()["approval"]["status"] == "denied"
    assert store.list_runs(session.id) == ()
    assert not (repo / "native-cwd.txt").exists()


def test_native_process_api_edit_fails_closed_when_worktree_is_unavailable(tmp_path):
    workspace = tmp_path / "plain-workspace"
    workspace.mkdir()
    script = _write_workspace_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native isolation failure",
        workspace=str(workspace),
        default_harness_id="fake-cli",
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "prompt": "edit safely",
            "mode": "edit",
            "workspace": str(workspace),
            "workspace_policy": "auto",
        },
    )

    assert response.status_code == 400, response.text
    assert "requires a Git repository" in response.json()["detail"]
    assert store.list_runs(session.id) == ()
    assert not (workspace / "native-cwd.txt").exists()


def test_native_process_api_edit_uses_approved_isolated_worktree(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    data_dir = tmp_path / "data"
    script = _write_workspace_cli(tmp_path)
    store = FilesystemHarnessSessionStore(data_dir)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script),
        config=HarnessConfig(data_dir=str(data_dir)),
        store=store,
    )
    session = store.create_session(
        title="Native worktree",
        workspace=str(repo),
        default_harness_id="fake-cli",
        metadata={"project_id": "project_native_worktree"},
    )
    payload = {
        "session_id": session.id,
        "harness_id": "fake-cli",
        "action": "start",
        "prompt": "edit safely",
        "mode": "edit",
        "workspace": str(repo),
        "workspace_policy": "auto",
        "permission_profile": "review_every_action",
        "idempotency_key": "native-approval-allow",
    }
    waiting = client.post("/api/native/processes/start", json=payload)
    approval_id = waiting.json()["approval"]["id"]
    approved = client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"decision": "allow_once"},
    )
    assert approved.status_code == 200, approved.text

    started = client.post("/api/native/processes/start", json=payload)

    assert started.status_code == 200, started.text
    run = started.json()["run"]
    execution = run["metadata"]["workspace_execution"]
    assert execution["requested_policy"] == "auto"
    assert execution["policy"] == "worktree"
    assert execution["source_workspace"] == str(repo)
    assert execution["effective_workspace"] != str(repo)
    assert run["workspace"] == execution["effective_workspace"]
    assert run["metadata"]["policy"] == {
        "action": "process.spawn",
        "decision": "allow",
        "enforcement": "enforced_by_harness",
        "policy_source": "approval_grant",
        "permission_profile": "review_every_action",
    }
    worktree = Path(execution["worktree_path"])
    _wait_for_process_status(client, started.json()["process"]["id"], {"succeeded"})
    assert (worktree / "native-cwd.txt").read_text(encoding="utf-8") == str(worktree)
    assert not (repo / "native-cwd.txt").exists()


def test_native_process_api_edit_resume_requires_isolation_evidence(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    script = _write_workspace_cli(tmp_path)
    snapshot = create_execution_snapshot(
        harness_id="fake-cli",
        api_mode="v2",
        model="ConfiguredModel",
        native_home=str(tmp_path / "managed-home"),
        workspace=str(repo),
        project_id="proj_native",
        permission_mode="edit",
        tool_config_hash="config-hash",
    )
    ref = replace(
        _native_ref(workspace=str(repo)),
        execution_snapshot=snapshot,
    )
    native_index = FilesystemNativeSessionIndexStore(tmp_path / "data")
    native_index.upsert_ref(ref, project_id="proj_native")
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script),
        native_index_store=native_index,
    )
    session = store.create_session(
        title="Unsafe legacy edit resume",
        workspace=str(repo),
        default_harness_id="fake-cli",
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "action": "resume",
            "native_ref_id": ref.id,
            "workspace_policy": "auto",
        },
    )

    assert response.status_code == 400, response.text
    assert "no isolated worktree evidence" in response.json()["detail"]
    assert store.list_runs(session.id) == ()
    assert not (repo / "native-cwd.txt").exists()


def test_native_process_api_start_creates_managed_native_link(tmp_path):
    script = _write_once_cli(tmp_path)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=script,
            native_session_id="managed-native-1",
        ),
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    assert started.json()["run"]["native_session_id"] == "managed-native-1"
    link = started.json()["native_link"]
    assert link["status"] == "managed_native"
    assert link["native_session_id"] == "managed-native-1"
    assert link["metadata"]["can_resume"] is True
    assert link["metadata"]["native_process_id"] == started.json()["process"]["id"]
    bundle = store.get_session_bundle(session.id)
    assert bundle.native_links[-1].native_session_id == "managed-native-1"


def test_native_process_api_start_promotes_empty_session_to_native_chat(tmp_path):
    script = _write_once_cli(tmp_path)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script, harness_id="codex-cli"),
    )
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id="direct-chat",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "codex-cli",
            "action": "start",
            "prompt": "Привет! Готов помочь.",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    bundle = store.get_session_bundle(session.id)
    assert bundle.session.title == "Привет! Готов помочь."
    assert bundle.session.default_harness_id == "codex-cli"
    assert [message.content for message in bundle.messages] == ["Привет! Готов помочь."]
    assert bundle.messages[0].run_id == started.json()["run"]["id"]
    assert bundle.messages[0].harness_id == "codex-cli"


def test_native_process_api_start_preserves_attachment_render_plan(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    script = _write_once_cli(tmp_path)
    data_dir = tmp_path / "data"
    session_store = FilesystemHarnessSessionStore(data_dir)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=script,
            harness_id="codex-cli",
            native_session_id="managed-native-attachments",
        ),
        config=HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(data_dir),
        ),
        store=session_store,
    )
    session = store.create_session(
        title="Native API",
        workspace=str(workspace),
        default_harness_id="codex-cli",
    )
    attachment = client.post(
        f"/api/sessions/{session.id}/attachments/workspace",
        json={"path": "src/app.py", "workspace": str(workspace)},
    ).json()["attachment"]

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "codex-cli",
            "action": "start",
            "prompt": "Inspect",
            "workspace": str(workspace),
            "attachment_ids": [attachment["id"]],
        },
    )

    assert started.status_code == 200, started.text
    process_id = started.json()["process"]["id"]
    metadata = started.json()["run"]["metadata"]
    assert metadata["attachment_ids"] == [attachment["id"]]
    assert metadata["attachments"][0]["workspace_path"] == "src/app.py"
    assert "@src/app.py" in metadata["attachment_render_plan"]["prompt_prefix"]
    output = client.get(f"/api/native/processes/{process_id}/output").json()
    assert (
        output["run"]["metadata"]["attachment_render_plan"]["prompt_prefix"]
        == metadata["attachment_render_plan"]["prompt_prefix"]
    )


def test_native_process_api_rejects_unproven_codex_image_transport(tmp_path):
    marker = tmp_path / "spawned"
    script = tmp_path / "marker_cli.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('spawned')\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    session_store = FilesystemHarnessSessionStore(data_dir)
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=script,
            harness_id="codex-cli",
        ),
        config=HarnessConfig(data_dir=str(data_dir)),
        store=session_store,
    )
    session = store.create_session(
        title="Native image",
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
    )
    attachment = client.post(
        f"/api/sessions/{session.id}/attachments",
        json={
            "filename": "screen.png",
            "mime_type": "image/png",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    ).json()["attachment"]

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "codex-cli",
            "prompt": "Inspect",
            "workspace": str(tmp_path),
            "attachment_ids": [attachment["id"]],
        },
    )

    assert response.status_code == 400
    assert "--image" in response.json()["detail"]
    assert marker.exists() is False


def test_native_process_api_resume_uses_cached_native_ref(tmp_path):
    resume_script = tmp_path / "resume_cli.py"
    resume_script.write_text(
        "import sys\nprint('resumed:' + sys.argv[1], flush=True)\n",
        encoding="utf-8",
    )
    native_index = FilesystemNativeSessionIndexStore(tmp_path / "data")
    ref = _native_ref(workspace=str(tmp_path))
    native_index.upsert_ref(ref, project_id="proj_native")
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=resume_script, resume_script=resume_script),
        native_index_store=native_index,
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "action": "resume",
            "native_ref_id": ref.id,
        },
    )

    assert started.status_code == 200, started.text
    process_id = started.json()["process"]["id"]
    assert started.json()["run"]["native_session_id"] == "native-session-1"
    _wait_for_output(client, process_id, 0, "resumed:native-session-1")
    completed = _wait_for_process_status(client, process_id, {"succeeded", "failed"})
    assert completed["run"]["status"] == "succeeded"


def test_native_process_api_resume_uses_stored_managed_link(tmp_path):
    start_script = _write_once_cli(tmp_path)
    resume_script = tmp_path / "resume_cli.py"
    resume_script.write_text(
        "import sys\nprint('resumed-link:' + sys.argv[1], flush=True)\n",
        encoding="utf-8",
    )
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=start_script,
            resume_script=resume_script,
            native_session_id="managed-native-2",
        ),
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )
    assert started.status_code == 200, started.text

    resumed = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "resume",
        },
    )

    assert resumed.status_code == 200, resumed.text
    process_id = resumed.json()["process"]["id"]
    assert resumed.json()["run"]["native_session_id"] == "managed-native-2"
    assert resumed.json()["native_link"]["native_session_id"] == "managed-native-2"
    _wait_for_output(client, process_id, 0, "resumed-link:managed-native-2")


def test_native_process_api_resume_reports_missing_native_id_from_link(tmp_path):
    script = _write_once_cli(tmp_path)
    client, store = _client(tmp_path, FakeProcessConnector(start_script=script))
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["native_link"]["metadata"]["can_resume"] is False

    resumed = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "resume",
        },
    )

    assert resumed.status_code == 400
    assert "Native session id was not detected" in resumed.json()["detail"]


def test_native_process_api_legacy_builtin_resume_requires_reviewed_route(tmp_path):
    script = _write_once_cli(tmp_path)
    ref = replace(
        _native_ref(workspace=str(tmp_path)),
        harness_id="codex-cli",
        metadata={
            "project_id": "proj_native",
            "native_home": str(tmp_path / "managed-home"),
        },
    )
    native_index = FilesystemNativeSessionIndexStore(tmp_path / "data")
    native_index.upsert_ref(ref, project_id="proj_native")
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script, harness_id="codex-cli"),
        native_index_store=native_index,
    )
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
    )

    rejected = client.post(
        "/api/native/processes/start",
        json={"session_id": session.id, "action": "resume", "native_ref_id": ref.id},
    )
    resumed = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "action": "resume",
            "native_ref_id": ref.id,
            "api_mode": "v1",
        },
    )

    assert rejected.status_code == 400
    assert "route_unknown" in rejected.json()["detail"]
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run"]["api_mode"] == "v1"
    snapshot = resumed.json()["native_link"]["metadata"]["execution_snapshot"]
    assert snapshot["route_known"] is False
    assert resumed.json()["native_link"]["metadata"]["limitations"] == ["route_unknown"]


def test_native_process_api_rejects_snapshot_override(tmp_path, monkeypatch):
    script = _write_once_cli(tmp_path)
    snapshot = create_execution_snapshot(
        harness_id="codex-cli",
        api_mode="v1",
        model="PinnedModel",
        native_home=str(tmp_path / "managed-home"),
        workspace=str(tmp_path),
        project_id="proj_native",
        permission_mode="read",
        tool_config_hash="config-hash",
    )
    ref = replace(
        _native_ref(workspace=str(tmp_path)),
        harness_id="codex-cli",
        metadata={
            "project_id": "proj_native",
            "native_home": str(tmp_path / "managed-home"),
        },
        execution_snapshot=snapshot,
    )
    native_index = FilesystemNativeSessionIndexStore(tmp_path / "data")
    native_index.upsert_ref(ref, project_id="proj_native")
    client, store = _client(
        tmp_path,
        FakeProcessConnector(
            start_script=script,
            harness_id="codex-cli",
            requires_proxy_preflight=True,
        ),
        native_index_store=native_index,
    )
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id="codex-cli",
    )
    observed_modes = []

    def successful_preflight(context, api_mode):
        observed_modes.append(api_mode)
        return _successful_route_preflight(
            context.proxy_url,
            api_mode,
            api_key="resume-proxy-key",
        )

    monkeypatch.setattr(proxy, "ensure_proxy_route_available", successful_preflight)

    rejected = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "action": "resume",
            "native_ref_id": ref.id,
            "api_mode": "v2",
        },
    )
    resumed = client.post(
        "/api/native/processes/start",
        json={"session_id": session.id, "action": "resume", "native_ref_id": ref.id},
    )

    assert rejected.status_code == 400
    assert "contradicts" in rejected.json()["detail"]
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run"]["api_mode"] == "v1"
    assert resumed.json()["run"]["model"] == "PinnedModel"
    assert resumed.json()["run"]["mode"] == "read"
    assert observed_modes == [GigaChatApiMode.V1]


def test_native_process_api_redacts_start_output_and_events(tmp_path):
    secret = "native-process-api-secret-value"
    script = tmp_path / "print_secret.py"
    script.write_text(
        "import os\nprint(os.environ['GPT2GIGA_API_KEY'], flush=True)\n",
        encoding="utf-8",
    )
    client, store = _client(
        tmp_path,
        FakeProcessConnector(start_script=script, pass_context_api_key=True),
        config=HarnessConfig(
            api_key=secret,
            data_dir=str(tmp_path / "data"),
        ),
    )
    session = store.create_session(
        title="Native API",
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )

    started = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "action": "start",
            "workspace": str(tmp_path),
        },
    )

    assert started.status_code == 200, started.text
    assert secret not in str(started.json())
    assert REDACTED in str(started.json())
    process_id = started.json()["process"]["id"]
    _wait_for_process_status(client, process_id, {"succeeded"})
    output = client.get(f"/api/native/processes/{process_id}/output").json()

    assert secret not in str(output)
    assert secret not in str(store.list_events(session.id))
    assert REDACTED in str(output)
    assert REDACTED in str(store.list_events(session.id))


def test_native_proxy_preflight_failure_prevents_plan_and_process_start(
    tmp_path,
    monkeypatch,
):
    marker = tmp_path / "spawned"
    script = tmp_path / "must_not_run.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    connector = FakeProcessConnector(
        start_script=script,
        requires_proxy_preflight=True,
    )
    client, store = _client(tmp_path, connector)
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_route_available",
        lambda context, api_mode: proxy.ProxyRoutePreflight(
            ok=False,
            proxy_url=context.proxy_url,
            api_mode=api_mode,
            route_path=f"/{api_mode.value}/models",
            startup=proxy.ProxyStartup(ok=False, proxy_url=context.proxy_url),
            error="selected native proxy route is unavailable",
        ),
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "prompt": "Inspect",
            "api_mode": "v1",
            "workspace": str(tmp_path),
        },
    )

    assert response.status_code == 400
    assert "proxy route is unavailable" in response.json()["detail"]
    assert marker.exists() is False
    assert store.list_runs(session.id) == ()


def test_native_spawn_failure_stops_new_owned_sidecar(tmp_path, monkeypatch):
    missing_script = tmp_path / "missing-native-cli"

    class MissingExecutableConnector(FakeProcessConnector):
        def build_start_command(self, request, context):
            del context
            return NativeCommandPlan(
                command=(str(self.start_script),),
                env=_python_env(),
                cwd=request.workspace,
                metadata={"harness_id": self.harness_id},
            )

    connector = MissingExecutableConnector(
        start_script=missing_script,
        requires_proxy_preflight=True,
    )
    client, store = _client(tmp_path, connector)
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id="fake-cli",
    )
    startup = proxy.ProxyStartup(
        ok=True,
        proxy_url="http://127.0.0.1:8090",
        started=True,
        api_key="owned-proxy-key",
        pid=4321,
        ownership_id="owner-native-1",
        health_path="/health",
        health_status_code=200,
    )
    stopped = []
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_route_available",
        lambda context, api_mode: proxy.ProxyRoutePreflight(
            ok=True,
            proxy_url=context.proxy_url,
            api_mode=api_mode,
            route_path=f"/{api_mode.value}/models",
            startup=startup,
            status_code=200,
        ),
    )
    monkeypatch.setattr(
        proxy,
        "stop_owned_sidecar",
        lambda candidate: stopped.append(candidate) or True,
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "fake-cli",
            "workspace": str(tmp_path),
        },
    )

    assert response.status_code == 400
    assert stopped == [startup]
    (run,) = store.list_runs(session.id)
    assert run.status == "failed"
    assert run.metadata["proxy_preflight"]["ownership"] == "owned"


@pytest.mark.parametrize(
    ("harness_id", "api_mode", "proxy_env", "base_url_env"),
    [
        ("codex-cli", "v1", "GPT2GIGA_API_KEY", None),
        ("claude-code", "v2", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"),
        ("gemini-cli", "v1", "GEMINI_API_KEY", "GOOGLE_GEMINI_BASE_URL"),
    ],
)
def test_builtin_native_preflight_passes_only_local_proxy_key(
    tmp_path,
    monkeypatch,
    harness_id,
    api_mode,
    proxy_env,
    base_url_env,
):
    capture_path = tmp_path / f"{harness_id}-env.json"
    executable = _write_env_capture_cli(tmp_path, harness_id, capture_path)
    data_dir = tmp_path / "data"
    if harness_id == "codex-cli":
        connector = CodexNativeHistoryConnector(
            data_dir=data_dir,
            executable=str(executable),
        )
    elif harness_id == "claude-code":
        connector = ClaudeNativeHistoryConnector(
            data_dir=data_dir,
            executable=str(executable),
        )
    else:
        connector = GeminiNativeHistoryConnector(
            data_dir=data_dir,
            executable=str(executable),
            capability_probe_runner=_supported_gemini_probe,
        )
    local_proxy_key = "native-local-proxy-key"
    observed_modes = []

    def successful_preflight(context, selected_mode):
        observed_modes.append(selected_mode)
        return _successful_route_preflight(
            context.proxy_url,
            selected_mode,
            api_key=local_proxy_key,
        )

    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "upstream-secret-must-not-cross")
    monkeypatch.setattr(proxy, "ensure_proxy_route_available", successful_preflight)
    client, store = _client(
        tmp_path,
        connector,
        config=HarnessConfig(data_dir=str(data_dir)),
    )
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id=harness_id,
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": harness_id,
            "prompt": "Inspect",
            "api_mode": api_mode,
            "workspace": str(tmp_path),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    _wait_for_process_status(client, body["process"]["id"], {"succeeded"})
    captured_env = json.loads(capture_path.read_text(encoding="utf-8"))
    assert observed_modes == [GigaChatApiMode(api_mode)]
    assert captured_env[proxy_env] == local_proxy_key
    assert "GIGACHAT_CREDENTIALS" not in captured_env
    if base_url_env is not None:
        assert captured_env[base_url_env] == f"http://127.0.0.1:8090/{api_mode}"
    assert local_proxy_key not in str(body)
    assert body["run"]["metadata"]["proxy_preflight"] == {
        "ok": True,
        "proxy_url": "http://127.0.0.1:8090",
        "api_mode": api_mode,
        "route_path": f"/{api_mode}/models",
        "route_status_code": 200,
        "health_path": "/health",
        "health_status_code": 200,
        "auth": "configured",
        "ownership": "external",
        "sidecar_pid": None,
        "ownership_id": None,
        "detail": "route ready",
        "error": None,
    }
    assert body["run"]["metadata"]["telemetry"] == {
        "api_mode": api_mode,
        "binary_version": "1.0.0",
        "event_schema": "raw-terminal-v1",
        "structured_events": False,
        "transport": "raw_terminal",
        "observability_limits": [
            "tool_lifecycle_opaque",
            "usage_unavailable",
            "artifacts_unclassified",
        ],
    }


def test_gemini_native_api_delivers_prompt_once_and_persists_outcome(
    tmp_path,
    monkeypatch,
):
    secret = "native-gemini-prompt-secret"
    capture_path = tmp_path / "captured-prompts.jsonl"
    script = _write_gemini_argv_cli(tmp_path, capture_path)
    data_dir = tmp_path / "data"
    store = FilesystemHarnessSessionStore(data_dir)
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        executable=str(script),
        capability_probe_runner=_supported_gemini_probe,
    )
    config = HarnessConfig(
        api_key=secret,
        default_model="ConfiguredModel",
        data_dir=str(data_dir),
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_route_available",
        lambda context, api_mode: _successful_route_preflight(
            context.proxy_url,
            api_mode,
            api_key=secret,
        ),
    )
    client, _ = _client(tmp_path, connector, config=config, store=store)
    session = store.create_session(
        title="Gemini native API",
        workspace=str(tmp_path),
        default_harness_id="gemini-cli",
    )
    prompt = f"Inspect this project\n{secret}\n"
    payload = {
        "session_id": session.id,
        "harness_id": "gemini-cli",
        "action": "start",
        "prompt": prompt,
        "workspace": str(tmp_path),
        "idempotency_key": "browser-submit-1",
    }

    started = client.post("/api/native/processes/start", json=payload)

    assert started.status_code == 200, started.text
    body = started.json()
    process_id = body["process"]["id"]
    assert body["process"]["command"][-1] == "<initial-prompt>"
    assert body["run"]["metadata"]["prompt_delivery"]["status"] == "delivered"
    assert body["native_link"]["metadata"]["prompt_delivery"]["status"] == ("delivered")
    assert secret not in str(body["process"])
    assert secret not in str(body["run"]["metadata"]["prompt_delivery"])
    assert secret not in str(body["native_link"]["metadata"])
    _wait_for_process_status(client, process_id, {"succeeded"})
    output_body = client.get(f"/api/native/processes/{process_id}/output").json()
    assert secret not in str(output_body["outputs"])
    assert REDACTED in str(output_body["outputs"])
    assert secret not in str(store.list_events(session.id))
    first_capture = capture_path.read_text(encoding="utf-8").splitlines()
    assert len(first_capture) == 1
    assert json.loads(first_capture[0]) == prompt

    client.get(f"/api/native/processes/{process_id}/output")
    client.get(f"/api/native/processes/{process_id}/output")
    duplicate = client.post("/api/native/processes/start", json=payload)
    rebound = client.post(
        "/api/native/processes/start",
        json={**payload, "prompt": "different prompt"},
    )

    assert duplicate.status_code == 400
    assert "already recorded as delivered" in duplicate.json()["detail"]
    assert rebound.status_code == 400
    assert "different prompt" in rebound.json()["detail"]
    assert len(capture_path.read_text(encoding="utf-8").splitlines()) == 1

    reloaded_connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        executable=str(script),
        capability_probe_runner=_supported_gemini_probe,
    )
    reloaded_client, _ = _client(
        tmp_path,
        reloaded_connector,
        config=config,
        store=FilesystemHarnessSessionStore(data_dir),
    )
    after_reload = reloaded_client.post("/api/native/processes/start", json=payload)

    assert after_reload.status_code == 400
    assert "already recorded as delivered" in after_reload.json()["detail"]
    assert len(capture_path.read_text(encoding="utf-8").splitlines()) == 1


def test_gemini_native_api_persists_failed_prompt_delivery_on_spawn_error(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    store = FilesystemHarnessSessionStore(data_dir)
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        executable=str(tmp_path / "missing-gemini"),
        capability_probe_runner=_supported_gemini_probe,
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_route_available",
        lambda context, api_mode: _successful_route_preflight(
            context.proxy_url,
            api_mode,
        ),
    )
    client, _ = _client(
        tmp_path,
        connector,
        config=HarnessConfig(data_dir=str(data_dir)),
        store=store,
    )
    session = store.create_session(
        workspace=str(tmp_path),
        default_harness_id="gemini-cli",
    )

    response = client.post(
        "/api/native/processes/start",
        json={
            "session_id": session.id,
            "harness_id": "gemini-cli",
            "prompt": "Inspect",
            "workspace": str(tmp_path),
            "idempotency_key": "failed-submit",
        },
    )

    assert response.status_code == 400
    (run,) = store.list_runs(session.id)
    assert run.status == "failed"
    assert run.metadata["prompt_delivery"]["status"] == "failed"
    assert run.metadata["prompt_delivery"]["idempotency_key"].startswith("nprompt_")
    assert "failed-submit" not in str(run.metadata)


class FakeProcessConnector:
    harness_id = "fake-cli"

    def __init__(
        self,
        *,
        start_script,
        resume_script=None,
        pass_context_api_key: bool = False,
        native_session_id: str | None = None,
        harness_id: str = "fake-cli",
        requires_proxy_preflight: bool = False,
    ) -> None:
        self.harness_id = harness_id
        self.start_script = start_script
        self.resume_script = resume_script or start_script
        self.pass_context_api_key = pass_context_api_key
        self.native_session_id = native_session_id
        self.requires_proxy_preflight = requires_proxy_preflight

    def discover(self, *, workspace, include_external):
        return ()

    def preview(self, ref, *, max_messages=20):
        return ()

    def import_ref(self, ref):
        return ()

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        env = _python_env()
        if self.pass_context_api_key and context.api_key:
            env["GPT2GIGA_API_KEY"] = context.api_key
        metadata = {"harness_id": self.harness_id}
        if self.native_session_id is not None:
            metadata["native_session_id"] = self.native_session_id
        return NativeCommandPlan(
            command=(sys.executable, str(self.start_script)),
            env=env,
            cwd=request.workspace,
            native_home=str(request.workspace) if request.workspace else None,
            metadata=metadata,
        )

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        return NativeCommandPlan(
            command=(
                sys.executable,
                str(self.resume_script),
                ref.native_session_id or ref.id,
            ),
            env=_python_env(),
            cwd=ref.workspace,
            metadata={
                "harness_id": self.harness_id,
                "native_ref_id": ref.id,
            },
            execution_snapshot=ref.execution_snapshot,
        )


def _client(
    tmp_path,
    connector: FakeProcessConnector,
    *,
    config: HarnessConfig | None = None,
    native_index_store=None,
    registry=None,
    store=None,
):
    store = store or InMemoryHarnessSessionStore()
    native_registry = NativeHistoryConnectorRegistry()
    native_registry.register(connector)
    manager = NativeProcessManager(session_store=store, use_pty=False)
    if registry is None:
        registry = create_default_registry(include_entry_points=False)
        if connector.harness_id in {"codex-cli", "claude-code", "gemini-cli"}:
            registry.get(connector.harness_id).capability_probe = lambda: (
                CliCapabilitySnapshot(
                    harness_id=connector.harness_id,
                    status="supported",
                    version="fixture 1.0.0",
                    parsed_version="1.0.0",
                    command=(f"/tmp/{connector.harness_id}-fixture",),
                    capabilities={},
                    event_schema="fixture-event-v1",
                    history_schema="fixture-history-v1",
                    warning=None,
                    evidence="test fixture",
                )
            )
    app = create_app(
        config
        or HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(tmp_path / "data"),
        ),
        registry=registry,
        store=store,
        native_registry=native_registry,
        native_index_store=native_index_store,
        native_process_manager=manager,
    )
    return TestClient(app), store


def _write_echo_cli(tmp_path):
    script = tmp_path / "echo_cli.py"
    script.write_text(
        "import sys\n"
        "print('ready', flush=True)\n"
        "for line in sys.stdin:\n"
        "    text = line.strip()\n"
        "    print(f'echo:{text}', flush=True)\n",
        encoding="utf-8",
    )
    return script


def _write_once_cli(tmp_path):
    script = tmp_path / "once_cli.py"
    script.write_text(
        "print('started', flush=True)\n",
        encoding="utf-8",
    )
    return script


def _write_workspace_cli(tmp_path):
    script = tmp_path / "workspace_cli.py"
    script.write_text(
        "from pathlib import Path\n"
        "Path('native-cwd.txt').write_text(str(Path.cwd()), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return script


def _write_gemini_argv_cli(tmp_path, capture_path):
    script = tmp_path / "fake_gemini"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import pathlib\n"
        "import sys\n"
        f"capture = pathlib.Path({str(capture_path)!r})\n"
        "prompt = sys.argv[sys.argv.index('--prompt-interactive') + 1]\n"
        "with capture.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(prompt) + '\\n')\n"
        "print(prompt, flush=True)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_env_capture_cli(tmp_path, harness_id, capture_path):
    script = tmp_path / f"fake-{harness_id}"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import pathlib\n"
        f"path = pathlib.Path({str(capture_path)!r})\n"
        "path.write_text(json.dumps(dict(os.environ)), encoding='utf-8')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _successful_route_preflight(proxy_url, api_mode, *, api_key=None):
    return proxy.ProxyRoutePreflight(
        ok=True,
        proxy_url=proxy_url,
        api_mode=api_mode,
        route_path=f"/{api_mode.value}/models",
        startup=proxy.ProxyStartup(
            ok=True,
            proxy_url=proxy_url,
            api_key=api_key,
            health_path="/health",
            health_status_code=200,
            detail="external proxy",
        ),
        status_code=200,
        detail="route ready",
    )


def _supported_gemini_probe(command, env, cwd):
    del env, cwd

    class Completed:
        returncode = 0
        stdout = "--prompt-interactive Execute prompt and continue interactively"
        stderr = ""

    assert command[-1] == "--help"
    return Completed()


def _native_ref(*, workspace: str) -> NativeSessionRef:
    return NativeSessionRef(
        id="native_fake_1",
        harness_id="fake-cli",
        native_session_id="native-session-1",
        title="Fake native session",
        workspace=workspace,
        source="fake",
        status=NativeSessionStatus.MANAGED_NATIVE,
        created_at="2026-07-09T09:00:00Z",
        updated_at="2026-07-09T10:00:00Z",
        message_count=1,
        can_preview=True,
        can_import=True,
        can_resume=True,
        metadata={"project_id": "proj_native"},
    )


def _python_env():
    env = {"PYTHONUNBUFFERED": "1"}
    for key in ("PATH", "SYSTEMROOT"):
        if value := os.environ.get(key):
            env[key] = value
    return env


def _wait_for_output(client: TestClient, process_id: str, cursor: int, expected: str):
    deadline = time.monotonic() + 3.0
    seen = ""
    latest_cursor = cursor
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/native/processes/{process_id}/output",
            params={"cursor": latest_cursor},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        latest_cursor = body["cursor"]
        seen += "".join(output["text"] for output in body["outputs"])
        if expected in seen:
            return latest_cursor, seen
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {expected!r}; saw {seen!r}")


def _wait_for_process_status(
    client: TestClient,
    process_id: str,
    run_statuses: set[str],
):
    deadline = time.monotonic() + 3.0
    body = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/native/processes/{process_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["run"]["status"] in run_statuses:
            return body
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {run_statuses}; last body was {body}")


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(("git", "init", str(path)), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(path), "config", "user.email", "test@example.com"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(path), "config", "user.name", "Test User"),
        check=True,
    )
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(path), "add", "base.txt"), check=True)
    subprocess.run(
        ("git", "-C", str(path), "commit", "-m", "initial"),
        check=True,
        capture_output=True,
    )
    return path
