from __future__ import annotations

import asyncio
from dataclasses import replace
import os
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, ListView

from gpt2giga_harness.terminal_dispatch import TuiLaunchIntent
from gpt2giga_harness.tui.app import SessionBrowserScreen, WorkbenchTui
from gpt2giga_harness.tui.commands import (
    COMMAND_REGISTRY,
    command_bindings,
    command_for_slash,
    slash_commands,
)
from gpt2giga_harness.tui.i18n import CATALOGS, translator
from gpt2giga_harness.tui.client import (
    ApprovalSummary,
    ArtifactSummary,
    AttachmentSummary,
    EnvironmentSummary,
    FileCandidate,
    HandoffPreview,
    HarnessSummary,
    NativeTerminalSnapshot,
    NavigationSnapshot,
    ProjectSummary,
    ReadinessSummary,
    RunActionBinding,
    RunSnapshot,
    RunInspection,
    SessionSummary,
    SessionExport,
    SessionPreview,
    TimelineEvent,
)
from gpt2giga_harness.workbench_resources import (
    InventoryProjection,
    PreferenceSnapshot,
    ProcessProjection,
    TaskProjection,
    UsageMetric,
    WorkbenchPreferences,
    WorkbenchResourceSnapshot,
)


class FakeClient:
    def __init__(self) -> None:
        self.created = 0
        self.remembered: list[str] = []
        self.submitted: list[str] = []
        self.submitted_attachments: list[tuple[str, ...]] = []
        self.decisions: list[str] = []
        self.native_calls: list[tuple[str, object]] = []
        self.launch_calls: list[tuple[str, dict[str, object]]] = []
        self.native_snapshot = NativeTerminalSnapshot(
            "proc_1",
            "sess_1",
            "run_native",
            "codex-cli",
            "pty",
            "running",
            0,
        )
        self.current_run: RunSnapshot | None = None
        preferences = WorkbenchPreferences(reduced_motion=True)
        self.resources_snapshot = WorkbenchResourceSnapshot(
            "resource-revision",
            "sess_1",
            tasks=(
                TaskProjection(
                    "job_1",
                    "reviewer",
                    "root_1",
                    "sess_1",
                    "run_1",
                    "durable_worker",
                    "running",
                    2,
                    3,
                    "worker_1",
                    "2099-01-01T00:00:00+00:00",
                    cancelable=True,
                    result_run_id="run_1",
                ),
            ),
            processes=(
                ProcessProjection(
                    "proc_1",
                    "sess_1",
                    "run_1",
                    "server_1",
                    "running",
                    "pty",
                    2,
                    "2099-01-01T00:00:00+00:00",
                    4,
                    output="bounded output",
                ),
            ),
            usage=(UsageMetric("total_tokens", 42, "tokens", "codex"),),
            preferences=PreferenceSnapshot(preferences, "preference-revision"),
            inventory=(
                InventoryProjection("codex-mcp", "mcp", "codex", "provider-owned"),
            ),
        )
        self.snapshot = NavigationSnapshot(
            transport_mode="in_process",
            projects=(ProjectSummary("proj_1", "Demo", "/tmp/demo", "main", 1),),
            project=ProjectSummary("proj_1", "Demo", "/tmp/demo", "main", 1),
            sessions=(
                SessionSummary(
                    "sess_1",
                    "Existing",
                    "2026-07-20T00:00:00Z",
                    "/tmp/demo",
                    "echo",
                    "local",
                    "plan",
                ),
            ),
            selected_session_id="sess_1",
            harnesses=(
                HarnessSummary("echo", "Echo", "available", "local", "one_shot"),
            ),
            readiness=ReadinessSummary(
                "ready",
                "pending execution snapshot",
                "not_checked",
                "echo",
                "available",
                "local",
                "one_shot",
                (),
            ),
            environment=EnvironmentSummary(
                "fresh",
                branch="main",
                head="a" * 40,
                worktree_root="/tmp/demo",
                staged_count=1,
                unstaged_count=2,
                untracked_count=3,
                additions=12,
                deletions=3,
                commit_ready=True,
                push_ready=True,
                captured_at="2026-07-22T00:00:00Z",
            ),
        )

    async def load(self, workspace, *, selected_session_id=None):
        selected = selected_session_id or self.snapshot.selected_session_id
        return replace(self.snapshot, selected_session_id=selected)

    async def resources(self, session_id=None):
        return replace(self.resources_snapshot, session_id=session_id)

    async def cancel_task(self, task):
        updated = replace(task, cancel_requested=True)
        self.resources_snapshot = replace(self.resources_snapshot, tasks=(updated,))
        return updated

    async def stop_process(self, process):
        updated = replace(process, status="stopped")
        self.resources_snapshot = replace(self.resources_snapshot, processes=(updated,))
        return updated

    async def save_preferences(self, values, *, expected_revision):
        saved = PreferenceSnapshot(
            WorkbenchPreferences(**values), "preference-revision-next"
        )
        self.resources_snapshot = replace(self.resources_snapshot, preferences=saved)
        return saved

    async def create_session(self, workspace, *, title=None, **intent):
        self.created += 1
        self.launch_calls.append(("create", intent))
        created = SessionSummary(
            f"sess_{self.created + 1}",
            title or "Untitled session",
            "2026-07-20T00:00:01Z",
            workspace,
            str(intent.get("harness_id") or "echo"),
            str(intent.get("model") or "local"),
            str(intent.get("mode") or "plan"),
        )
        self.snapshot = replace(
            self.snapshot,
            sessions=(created, *self.snapshot.sessions),
            selected_session_id=created.id,
        )
        return created

    async def remember_session(self, workspace, session_id):
        self.remembered.append(session_id)

    async def search_sessions(
        self, query="", *, provider=None, project=None, include_archived=True
    ):
        items = self.snapshot.sessions
        if query:
            items = tuple(
                item for item in items if query.casefold() in item.title.casefold()
            )
        if provider:
            items = tuple(item for item in items if item.harness_id == provider)
        if project:
            items = tuple(item for item in items if item.project_id == project)
        return tuple(item for item in items if include_archived or not item.archived)

    async def preview_session(self, session_id, *, transcript_query=""):
        session = next(item for item in self.snapshot.sessions if item.id == session_id)
        return SessionPreview(
            session, (f"USER\n{transcript_query or 'preview'}",), 1, False
        )

    async def rename_session(self, binding, title):
        current = next(
            item for item in self.snapshot.sessions if item.id == binding.session_id
        )
        updated = replace(current, title=title, revision="renamed")
        self.snapshot = replace(
            self.snapshot,
            sessions=tuple(
                updated if item.id == updated.id else item
                for item in self.snapshot.sessions
            ),
        )
        return updated

    async def archive_session(self, binding, *, archived=True):
        current = next(
            item for item in self.snapshot.sessions if item.id == binding.session_id
        )
        updated = replace(current, archived=archived, revision="archived")
        self.snapshot = replace(
            self.snapshot,
            sessions=tuple(
                updated if item.id == updated.id else item
                for item in self.snapshot.sessions
            ),
        )
        return updated

    async def delete_session(self, binding):
        self.snapshot = replace(
            self.snapshot,
            sessions=tuple(
                item for item in self.snapshot.sessions if item.id != binding.session_id
            ),
        )

    async def fork_session(self, binding):
        fork = replace(
            next(
                item for item in self.snapshot.sessions if item.id == binding.session_id
            ),
            id="sess_forked",
            title="Forked",
            revision="forked",
            native_operation="fork",
        )
        self.snapshot = replace(self.snapshot, sessions=(fork, *self.snapshot.sessions))
        return fork

    async def export_session(self, binding):
        return SessionExport(binding.session_id, "/tmp/session.md", 1)

    async def latest_run(self, session_id):
        return self.current_run

    async def submit_turn(
        self,
        session_id,
        content,
        *,
        idempotency_key,
        attachment_ids=(),
        **intent,
    ):
        self.launch_calls.append(("submit", intent))
        self.submitted.append(content)
        self.submitted_attachments.append(attachment_ids)
        self.current_run = _run_snapshot(
            events=(
                TimelineEvent(
                    "evt_1", "message_delta", "Assistant delta", delta="hello"
                ),
                TimelineEvent(
                    "evt_2",
                    "tool_call_started",
                    "Tool started",
                    tool_name="search",
                ),
            )
        )
        return self.current_run

    async def snapshot_run(self, run_id, *, cursor=None):
        return self.current_run

    async def cancel_run(self, binding):
        self.current_run = replace(self.current_run, status="canceled")
        return self.current_run

    async def fork_run(self, binding):
        return SessionSummary(
            "sess_fork",
            "Fork",
            "2026-07-20T00:00:02Z",
            "/tmp/demo",
            "echo",
            "local",
            "plan",
        )

    async def decide_approval(self, binding, approval_id, decision):
        self.decisions.append(decision)
        self.current_run = replace(self.current_run, pending_approvals=())
        return self.current_run

    async def steer_run(self, binding, content, *, idempotency_key):
        self.submitted.append(f"steer:{content}")
        return self.current_run

    async def answer_input(self, binding, input_id, answer):
        return self.current_run

    async def search_files(self, session_id, query):
        return (
            FileCandidate(
                "src/app.py",
                "app.py",
                "text/x-python",
                "text",
                8,
                "print(1)",
                "ready",
            ),
        )

    async def attach_file(self, session_id, path):
        return AttachmentSummary("att_1", path, "text/x-python", "workspace_file", 8)

    async def inspect_run(self, run_id):
        return RunInspection(
            run_id,
            "running",
            "a" * 64,
            "provider link revision 1",
            "available",
            "not_required",
            (ArtifactSummary("diff", 8),),
            "+print(1)",
            False,
            ("src/app.py",),
            (),
            ("environment=deferred_to_N6",),
        )

    async def provider_handoff(self, session_id):
        return HandoffPreview(
            "provider",
            "blocked",
            "echo",
            "Harness session remains authoritative.",
            ("provider UI unavailable",),
            "Continue in the TUI.",
        )

    async def web_handoff(self, session_id):
        return HandoffPreview(
            "web",
            "ready",
            f"http://127.0.0.1:8091/cockpit-v2/work/{session_id}",
            "Shared session",
            ("browser rendering is Web-owned",),
            "Open after review.",
        )

    async def start_native_terminal(
        self,
        session_id,
        content,
        *,
        idempotency_key,
        attachment_ids=(),
        **intent,
    ):
        self.launch_calls.append(("native", intent))
        self.native_calls.append(("start", (session_id, content, attachment_ids)))
        return self.native_snapshot

    async def snapshot_native_terminal(self, process_id, *, cursor=0):
        self.native_calls.append(("snapshot", (process_id, cursor)))
        return replace(self.native_snapshot, output="", cursor=max(cursor, 1))

    async def status_native_terminal(self, process_id):
        self.native_calls.append(("status", process_id))
        return replace(self.native_snapshot, output="")

    async def send_native_terminal_input(self, process_id, data, *, submit=False):
        self.native_calls.append(("input", (process_id, data, submit)))
        self.native_snapshot = replace(
            self.native_snapshot,
            output=f"provider: {data}\n",
            cursor=self.native_snapshot.cursor + 1,
        )
        return self.native_snapshot

    async def resize_native_terminal(self, process_id, *, rows, columns):
        self.native_calls.append(("resize", (process_id, rows, columns)))
        return replace(self.native_snapshot, output="")

    async def stop_native_terminal(self, process_id):
        self.native_calls.append(("stop", process_id))
        self.native_snapshot = replace(self.native_snapshot, status="stopped")
        return self.native_snapshot


def _run_snapshot(
    *,
    events: tuple[TimelineEvent, ...] = (),
    approvals: tuple[ApprovalSummary, ...] = (),
) -> RunSnapshot:
    return RunSnapshot(
        binding=RunActionBinding("sess_1", "run_1", "a" * 64, 1, "turn_1"),
        status="running",
        events=events,
        cursor="ip1.1.2",
        pending_approvals=approvals,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("size", ((120, 40), (80, 24), (60, 20)))
async def test_tui_renders_keyboard_navigation_without_horizontal_overflow(size):
    app = WorkbenchTui(FakeClient(), workspace="/tmp/demo")

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert "Provider: pending execution snapshot" in str(
            app.query_one("#readiness").render()
        )
        assert "Git: main @ aaaaaaaa" in str(app.query_one("#readiness").render())
        assert "Commit: Ready · Push: Ready" in str(
            app.query_one("#readiness").render()
        )
        assert app.query_one("#body").has_class("narrow") is (size[0] < 84)
        for widget in app.screen.query(
            "#body, #sessions-pane, #detail-pane, #timeline, "
            "#interaction-actions, #composer-row, #actions"
        ):
            assert widget.region.x >= 0
            assert widget.region.right <= size[0]


@pytest.mark.anyio
async def test_tui_creates_and_resumes_session_from_keyboard():
    client = FakeClient()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        await pilot.press(*"Created")
        await pilot.press("enter")
        await pilot.pause()

        assert client.created == 1
        assert app.selected_session_id == "sess_2"
        assert any(session.title == "Created" for session in app.snapshot.sessions)


@pytest.mark.anyio
@pytest.mark.parametrize("size", [(120, 40), (80, 24), (60, 20)])
async def test_tui_session_browser_filters_previews_and_stays_in_viewport(size):
    client = FakeClient()
    session = replace(
        client.snapshot.sessions[0],
        project_id="project-demo",
        preview="Retained preview",
        native_authority="codex",
        native_session_id="thread-1",
        native_operation="resume",
        revision="revision-1",
        generation=2,
    )
    archived = replace(
        session,
        id="sess_archived",
        title="Archived",
        archived=True,
        revision="revision-archived",
    )
    client.snapshot = replace(client.snapshot, sessions=(session, archived))
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await app.action_sessions()
        await pilot.pause()
        assert isinstance(app.screen, SessionBrowserScreen)
        query = app.screen.query_one("#session-browser-query", Input)
        query.value = "provider:codex project:project-demo archived:true"
        await pilot.pause()
        results = app.screen.query_one("#session-browser-results", ListView)
        assert len(results.children) == 1
        assert app.screen.filtered[0].title == "Archived"
        assert app.screen.region.right <= size[0]
        assert app.screen.region.bottom <= size[1]
        app.screen.dismiss(None)


@pytest.mark.anyio
async def test_tui_later_resume_restores_archived_session_without_git():
    client = FakeClient()
    archived = replace(
        client.snapshot.sessions[0],
        id="sess_archived",
        title="Archived",
        archived=True,
        revision="revision-archived",
    )
    client.snapshot = replace(client.snapshot, sessions=(archived,))
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app._browser_session_chosen(archived)
        await pilot.pause()

    assert app.selected_session_id == archived.id
    assert client.snapshot.sessions[0].archived is False


@pytest.mark.anyio
async def test_tui_applies_exact_human_deep_link_once_on_mount():
    client = FakeClient()
    intent = TuiLaunchIntent(
        workspace="/tmp/demo",
        create_session=True,
        harness_id="codex-cli",
        model="reasoning-model",
        mode="read",
        execution_transport="one_shot",
        prompt="Inspect safely",
    )
    app = WorkbenchTui(client, launch_intent=intent)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert client.created == 1
        assert client.submitted == ["Inspect safely"]
        assert client.launch_calls == [
            (
                "create",
                {
                    "harness_id": "codex-cli",
                    "model": "reasoning-model",
                    "api_mode": None,
                    "mode": "read",
                },
            ),
            (
                "submit",
                {
                    "harness_id": "codex-cli",
                    "model": "reasoning-model",
                    "api_mode": None,
                    "mode": "read",
                    "capability": None,
                    "execution_transport": "one_shot",
                },
            ),
        ]


@pytest.mark.anyio
async def test_codex_resume_deep_link_preserves_native_thread_on_first_turn():
    client = FakeClient()
    intent = TuiLaunchIntent(
        workspace="/tmp/demo",
        create_session=True,
        provider_namespace="codex",
        harness_id="codex-cli",
        provider_transport="app-server",
        native_session_selector="thread_fixture",
        session_operation="resume",
        persistence="provider_native",
    )
    app = WorkbenchTui(client, launch_intent=intent)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#composer")
        await pilot.press(*"Continue")
        await pilot.press("enter")
        await pilot.pause()

    assert client.launch_calls[-1] == (
        "submit",
        {
            "harness_id": "codex-cli",
            "model": None,
            "api_mode": None,
            "mode": None,
            "native_session_id": "thread_fixture",
            "native_session_operation": "resume",
            "capability": None,
            "execution_transport": None,
        },
    )


@pytest.mark.anyio
async def test_tui_cancel_does_not_create_a_session():
    client = FakeClient()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("n")
        await pilot.press("escape")
        await pilot.pause()

        assert client.created == 0
        assert app.selected_session_id == "sess_1"


@pytest.mark.anyio
async def test_tui_composer_renders_incremental_content_and_tool_lifecycle():
    client = FakeClient()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#composer")
        await pilot.press(*"Do it")
        await pilot.press("enter")
        await pilot.pause()

        timeline = str(app.query_one("#timeline").render())
        assert client.submitted == ["Do it"]
        assert "hello" in timeline
        assert "search" in timeline
        assert app.run_snapshot.binding.run_id == "run_1"


@pytest.mark.anyio
async def test_tui_queued_turn_survives_disconnect_and_starts_exactly_once():
    class ReconnectingClient(FakeClient):
        disconnected = False
        finish_active = False

        async def snapshot_run(self, run_id, *, cursor=None):
            if self.disconnected:
                raise RuntimeError("transport unavailable")
            if self.finish_active:
                return replace(self.current_run, status="succeeded")
            return self.current_run

    client = ReconnectingClient()
    client.current_run = _run_snapshot(
        events=(TimelineEvent("evt_active", "run_started", "Active"),)
    )
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        composer = app.query_one("#composer")
        composer.focus()
        await pilot.press(*"Follow up")
        await pilot.click("#queue-turn")
        assert app.queued_turn is not None

        client.disconnected = True
        await app._poll_run()
        assert app.queued_turn is not None

        client.disconnected = False
        client.finish_active = True
        await app._poll_run()
        await pilot.pause()
        await app._flush_queued_turn()

        assert client.submitted == ["Follow up"]
        assert app.queued_turn is None


@pytest.mark.anyio
async def test_tui_transcript_cards_expand_with_keyboard_and_safe_artifact_refs():
    client = FakeClient()
    client.current_run = _run_snapshot(
        events=(
            TimelineEvent(
                "evt_diff",
                "diff",
                "Changed app.py",
                delta="+safe⟦terminal-control⟧�",
                category="diff",
                artifact_id="artifact_1",
                artifact_kind="diff",
                truncated=True,
            ),
        )
    )
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#timeline").focus()
        await pilot.press("enter")
        rendered = str(app.query_one("#timeline").render())

        assert "[−] [DIFF]" in rendered
        assert "artifact_1" in rendered
        assert "preview truncated" in rendered
        assert "\x1b" not in rendered


@pytest.mark.anyio
async def test_tui_approval_decision_uses_exact_presented_binding():
    client = FakeClient()
    client.current_run = _run_snapshot(
        events=(
            TimelineEvent(
                "evt_approval",
                "approval_requested",
                "Permission needed",
                approval_id="approval_1",
            ),
        ),
        approvals=(ApprovalSummary("approval_1", "tool", "needed", "pending"),),
    )
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#approve")
        await pilot.pause()
        assert "Revision:" in str(app.screen.query_one("#approval-detail").render())
        await pilot.click("#approval-allow-once")
        await pilot.pause()

        assert client.decisions == ["allow_once"]
        assert app.run_snapshot.pending_approvals == ()


@pytest.mark.anyio
async def test_tui_file_picker_evidence_and_handoff_are_keyboard_first():
    client = FakeClient()
    client.current_run = _run_snapshot()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press(*"app")
        await pilot.press("enter")
        await pilot.pause()
        assert "print(1)" in str(app.screen.query_one("#file-preview").render())
        await pilot.press("enter")
        await pilot.pause()
        assert "src/app.py" in str(app.query_one("#attachment-status").render())

        await pilot.click("#cancel-run")
        await pilot.pause()
        await pilot.click("#composer")
        await pilot.press(*"Use file")
        await pilot.press("enter")
        await pilot.pause()
        assert client.submitted_attachments == [("att_1",)]

        app.query_one("#session-list").focus()
        await pilot.press("e")
        await pilot.pause()
        detail = str(app.screen.query_one("#detail-body").render())
        assert "Environment: deferred to Phase N6" in detail
        assert "+print(1)" in detail
        await pilot.press("escape")

        app.query_one("#session-list").focus()
        await pilot.press("w")
        await pilot.pause()
        handoff = str(app.screen.query_one("#detail-body").render())
        assert "Exact target: http://127.0.0.1:8091" in handoff
        assert "browser rendering is Web-owned" in handoff


@pytest.mark.anyio
@pytest.mark.parametrize("size", ((120, 40), (80, 24), (60, 20)))
async def test_tui_file_and_evidence_modals_fit_supported_terminal_matrix(size):
    client = FakeClient()
    client.current_run = _run_snapshot()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press(*"app")
        await pilot.press("enter")
        await pilot.pause()
        for widget in app.screen.query(
            "#file-dialog, #file-list, #file-preview, #file-actions"
        ):
            assert widget.region.x >= 0
            assert widget.region.right <= size[0]
        await pilot.press("escape")

        app.query_one("#session-list").focus()
        await pilot.press("e")
        await pilot.pause()
        for widget in app.screen.query("#detail-dialog, #detail-body, #detail-close"):
            assert widget.region.x >= 0
            assert widget.region.right <= size[0]


@pytest.mark.anyio
@pytest.mark.parametrize("size", ((120, 40), (80, 24), (60, 20)))
async def test_tui_contains_native_terminal_and_restores_session_view(size):
    client = FakeClient()
    client.snapshot = replace(
        client.snapshot,
        readiness=replace(client.snapshot.readiness, transport="native_terminal"),
    )
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        composer = app.query_one("#composer")
        composer.focus()
        composer.value = "Start native"
        await pilot.press("enter")
        await pilot.pause()

        assert client.native_calls[0][0] == "start"
        for widget in app.screen.query(
            "#native-dialog, #native-output, #native-input-row, #native-actions"
        ):
            assert widget.region.x >= 0
            assert widget.region.right <= size[0]

        await pilot.click("#native-input")
        await pilot.press(*"continue")
        await pilot.press("enter")
        await pilot.pause()
        assert ("input", ("proc_1", "continue", True)) in client.native_calls
        assert "provider: continue" in str(
            app.screen.query_one("#native-output").render()
        )

        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.anyio
async def test_tui_blocks_fullscreen_provider_controls_and_stops_process():
    client = FakeClient()
    client.snapshot = replace(
        client.snapshot,
        readiness=replace(client.snapshot.readiness, transport="native_terminal"),
    )
    client.native_snapshot = replace(
        client.native_snapshot,
        output="safe\x1b]52;c;clipboard\x07\x1b[?1049howned",
        handoff_required=True,
    )
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        composer = app.query_one("#composer")
        composer.focus()
        composer.value = "Start native"
        await pilot.press("enter")
        await pilot.pause()

        rendered = str(app.screen.query_one("#native-output").render())
        assert "\x1b" not in rendered
        assert "terminal-control" in rendered
        assert "raw terminal fallback" in rendered
        assert ("stop", "proc_1") in client.native_calls
        assert app.screen.query_one("#native-input").disabled is True


def _quality_state_snapshot(state: str) -> RunSnapshot | None:
    if state in {"loading", "empty", "ready", "disconnected"}:
        return None
    event = {
        "streaming": TimelineEvent(
            "evt_stream", "message_delta", "Streaming", delta="partial response"
        ),
        "tool": TimelineEvent(
            "evt_tool", "tool_call_started", "Reading files", tool_name="read"
        ),
        "approval": TimelineEvent(
            "evt_approval",
            "approval_requested",
            "Allow project write?",
            approval_id="approval_1",
        ),
        "question": TimelineEvent(
            "evt_question",
            "input_requested",
            "Which target?",
            input_id="input_1",
        ),
        "error": TimelineEvent("evt_error", "error", "Provider unavailable"),
        "completed": TimelineEvent("evt_done", "run_finished", "Run completed"),
    }[state]
    approvals = (
        (ApprovalSummary("approval_1", "write", "review", "pending"),)
        if state == "approval"
        else ()
    )
    return replace(
        _run_snapshot(events=(event,), approvals=approvals),
        status="succeeded" if state == "completed" else "running",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("size", ((120, 40), (80, 24), (60, 20)))
@pytest.mark.parametrize(
    "state",
    (
        "loading",
        "empty",
        "ready",
        "streaming",
        "tool",
        "approval",
        "question",
        "error",
        "disconnected",
        "completed",
    ),
)
async def test_tui_quality_states_have_headless_artifacts_and_primary_actions(
    size, state
):
    client = FakeClient()
    client.current_run = _quality_state_snapshot(state)
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        if state == "loading":
            app._set_status(app.t("status.loading"))
        elif state == "disconnected":
            app._set_status(app.t("status.disconnected"))
        await pilot.pause()

        screenshot = app.export_screenshot(
            title=f"N5-05 {state} {size[0]}x{size[1]}", simplify=True
        )
        assert screenshot.startswith("<svg")
        if artifact_root := os.getenv("GIGALOOM_TUI_ARTIFACT_DIR"):
            root = Path(artifact_root)
            root.mkdir(parents=True, exist_ok=True)
            (root / f"{state}-{size[0]}x{size[1]}.svg").write_text(
                screenshot,
                encoding="utf-8",
            )
        for selector in (
            "#body",
            "#sessions-pane",
            "#detail-pane",
            "#timeline",
            "#composer-row",
            "#composer-state",
            "#send-turn",
            "#steer-turn",
            "#queue-turn",
            "#actions",
            "#new-session",
            "#status",
            "#runtime-status",
        ):
            widget = app.query_one(selector)
            assert widget.region.x >= 0
            assert widget.region.right <= size[0]
            assert widget.region.y >= 0
            assert widget.region.bottom <= size[1]


@pytest.mark.anyio
async def test_tui_keyboard_focus_help_palette_and_semantic_status_are_non_color():
    client = FakeClient()
    client.current_run = _quality_state_snapshot("approval")
    app = WorkbenchTui(client, workspace="/tmp/demo", locale="ru")

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        focused_ids: set[str | None] = set()
        for _ in range(24):
            focused_ids.add(app.focused.id if app.focused is not None else None)
            await pilot.press("tab")
        assert {"session-list", "composer", "steer-turn", "queue-turn", "help"} <= (
            focused_ids
        )

        timeline = str(app.query_one("#timeline").render())
        assert "[РАЗРЕШЕНИЕ]" in timeline
        app.query_one("#session-list").focus()
        await pilot.press("?")
        assert "Ctrl+P" in app.screen.body
        await pilot.press("escape")
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert type(app.screen).__name__ == "CommandPalette"


def test_tui_command_registry_is_the_single_discovery_inventory():
    assert len({item.id for item in COMMAND_REGISTRY}) == len(COMMAND_REGISTRY)
    assert len({item.slash for item in COMMAND_REGISTRY}) == len(COMMAND_REGISTRY)
    assert slash_commands() == tuple(item.slash for item in COMMAND_REGISTRY)
    assert command_for_slash("/status") is not None
    assert command_for_slash("/status ignored") is not None
    assert command_for_slash("/unknown") is None
    assert {binding.action for binding in command_bindings(translator("en"))} == {
        item.action for item in COMMAND_REGISTRY if item.key is not None
    }
    for item in COMMAND_REGISTRY:
        action_name = item.action.split("(", 1)[0]
        assert callable(getattr(WorkbenchTui, f"action_{action_name}"))
    assert set(CATALOGS["en"]) == set(CATALOGS["ru"])


@pytest.mark.anyio
@pytest.mark.parametrize("size", ((120, 40), (80, 24), (60, 20)))
async def test_tui_resource_drawers_are_bounded_and_narrow_safe(size):
    client = FakeClient()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await app.action_tasks()
        await pilot.pause()
        dialog = app.screen.query_one("#resource-dialog")
        assert dialog.region.x >= 0
        assert dialog.region.right <= size[0]
        assert "reviewer" in str(app.screen.query_one("#resource-detail").render())
        await pilot.press("escape")
        await pilot.pause()

        await app.action_processes()
        await pilot.pause()
        assert "bounded output" in str(
            app.screen.query_one("#resource-detail").render()
        )
        await pilot.press("escape")
        await pilot.pause()

        await app.action_usage()
        assert "source=codex" in app.screen.body
        await pilot.press("escape")
        await pilot.pause()

        await app.action_preferences()
        await pilot.pause()
        preferences = app.screen.query_one("#resource-list", ListView)
        preferences.index = 4
        await pilot.pause()
        assert "Reduced Motion: True" in str(
            app.screen.query_one("#resource-detail").render()
        )
        assert "content-free" in str(app.screen.query_one("#resource-detail").render())
        app.screen.query_one("#resource-change").press()
        await pilot.pause()
        assert client.resources_snapshot.preferences.values.reduced_motion is False

        await app.action_integrations()
        assert "explicit provider_handoff" in app.screen.body


@pytest.mark.anyio
@pytest.mark.parametrize("transport_mode", ("in_process", "attach"))
async def test_tui_resource_actions_bind_cancel_and_stop(transport_mode):
    client = FakeClient()
    client.snapshot = replace(client.snapshot, transport_mode=transport_mode)
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.action_tasks()
        await pilot.pause()
        app.screen.query_one("#resource-cancel").press()
        await pilot.pause()
        assert client.resources_snapshot.tasks[0].cancel_requested is True

        await app.action_processes()
        await pilot.pause()
        app.screen.query_one("#resource-stop").press()
        await pilot.pause()
        assert client.resources_snapshot.processes[0].status == "stopped"


@pytest.mark.anyio
@pytest.mark.parametrize("transport_mode", ("in_process", "attach"))
async def test_tui_slash_status_and_runtime_controls_are_contextual(transport_mode):
    client = FakeClient()
    client.snapshot = replace(client.snapshot, transport_mode=transport_mode)
    app = WorkbenchTui(client, workspace="/tmp/demo", locale="ru")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        composer = app.query_one("#composer")
        composer.focus()
        await pilot.press(*"/status")
        await pilot.press("enter")
        await pilot.pause()
        assert "Транспорт клиента" in app.screen.body
        assert transport_mode in app.screen.body
        assert "Разрешения" in app.screen.body
        assert "Политика" in app.screen.body
        assert "Песочница" in app.screen.body
        await pilot.press("escape")

        composer.focus()
        await pilot.press(*"/permission")
        await pilot.press("enter")
        await pilot.pause()
        assert "переход" in app.screen.body.lower()
        assert "значения не переводятся" in app.screen.body.lower()


@pytest.mark.anyio
async def test_tui_model_control_prompts_for_scope_and_applies_to_next_run():
    client = FakeClient()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        composer = app.query_one("#composer")
        composer.focus()
        await pilot.press(*"/model")
        await pilot.press("enter")
        await pilot.pause()
        assert "next run" in str(app.screen.query_one("#prompt-dialog Label").render())
        await pilot.press(*"review-model")
        await pilot.press("enter")
        await pilot.pause()
        assert "review-model" in str(app.query_one("#runtime-status").render())

        composer.focus()
        await pilot.press(*"Inspect")
        await pilot.press("enter")
        await pilot.pause()

    assert client.launch_calls[-1][0] == "submit"
    assert client.launch_calls[-1][1]["model"] == "review-model"


@pytest.mark.anyio
async def test_tui_marks_api_loss_and_authoritative_reconnect():
    class RecoveringClient(FakeClient):
        fail_snapshot = False

        async def snapshot_run(self, run_id, *, cursor=None):
            if self.fail_snapshot:
                raise RuntimeError("worker unavailable")
            return await super().snapshot_run(run_id, cursor=cursor)

    client = RecoveringClient()
    client.current_run = _quality_state_snapshot("streaming")
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        client.fail_snapshot = True
        await app._poll_run()
        assert "Disconnected" in str(app.query_one("#status").render())
        client.fail_snapshot = False
        await app._poll_run()
        assert "Reconnected" in str(app.query_one("#status").render())


@pytest.mark.anyio
async def test_tui_bounds_long_streams_and_coalesces_resize_storms():
    client = FakeClient()
    app = WorkbenchTui(client, workspace="/tmp/demo")

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        events = tuple(
            TimelineEvent(
                f"evt_{index}",
                "message_delta",
                "chunk",
                delta=f"{index}:" + "x" * 1024,
            )
            for index in range(1_000)
        )
        app._apply_run_snapshot(_run_snapshot(events=events))
        assert len(app.timeline) == 100
        assert len(str(app.query_one("#timeline").render())) <= 64_000

        client.snapshot = replace(
            client.snapshot,
            readiness=replace(client.snapshot.readiness, transport="native_terminal"),
        )
        app.snapshot = client.snapshot
        app._show_native_terminal(client.native_snapshot)
        await pilot.pause()
        screen = app.screen
        active = 0
        maximum_active = 0
        calls = 0

        async def slow_resize(process_id, *, rows, columns):
            nonlocal active, maximum_active, calls
            active += 1
            calls += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return replace(client.native_snapshot, output="")

        client.resize_native_terminal = slow_resize
        await asyncio.gather(*(screen._resize() for _ in range(50)))

        assert maximum_active == 1
        assert calls <= 2
