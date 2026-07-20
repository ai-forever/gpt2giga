from __future__ import annotations

import asyncio
from dataclasses import replace
import os
from pathlib import Path

import pytest

pytest.importorskip("textual")

from gpt2giga_harness.tui.app import WorkbenchTui
from gpt2giga_harness.tui.client import (
    ApprovalSummary,
    ArtifactSummary,
    AttachmentSummary,
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
    TimelineEvent,
)


class FakeClient:
    def __init__(self) -> None:
        self.created = 0
        self.remembered: list[str] = []
        self.submitted: list[str] = []
        self.submitted_attachments: list[tuple[str, ...]] = []
        self.decisions: list[str] = []
        self.native_calls: list[tuple[str, object]] = []
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
        )

    async def load(self, workspace, *, selected_session_id=None):
        selected = selected_session_id or self.snapshot.selected_session_id
        return replace(self.snapshot, selected_session_id=selected)

    async def create_session(self, workspace, *, title=None):
        self.created += 1
        created = SessionSummary(
            f"sess_{self.created + 1}",
            title or "Untitled session",
            "2026-07-20T00:00:01Z",
            workspace,
            "echo",
            "local",
            "plan",
        )
        self.snapshot = replace(
            self.snapshot,
            sessions=(created, *self.snapshot.sessions),
            selected_session_id=created.id,
        )
        return created

    async def remember_session(self, workspace, session_id):
        self.remembered.append(session_id)

    async def latest_run(self, session_id):
        return self.current_run

    async def submit_turn(
        self, session_id, content, *, idempotency_key, attachment_ids=()
    ):
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
    ):
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
            "#send-turn",
            "#actions",
            "#new-session",
            "#status",
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
        assert {"session-list", "composer", "send-turn", "new-session", "help"} <= (
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
