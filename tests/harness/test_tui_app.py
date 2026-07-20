from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("textual")

from gpt2giga_harness.tui.app import WorkbenchTui
from gpt2giga_harness.tui.client import (
    ApprovalSummary,
    HarnessSummary,
    NavigationSnapshot,
    ProjectSummary,
    ReadinessSummary,
    RunActionBinding,
    RunSnapshot,
    SessionSummary,
    TimelineEvent,
)


class FakeClient:
    def __init__(self) -> None:
        self.created = 0
        self.remembered: list[str] = []
        self.submitted: list[str] = []
        self.decisions: list[str] = []
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

    async def submit_turn(self, session_id, content, *, idempotency_key):
        self.submitted.append(content)
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
