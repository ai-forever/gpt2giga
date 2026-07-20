from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("textual")

from gpt2giga_harness.tui.app import WorkbenchTui
from gpt2giga_harness.tui.client import (
    HarnessSummary,
    NavigationSnapshot,
    ProjectSummary,
    ReadinessSummary,
    SessionSummary,
)


class FakeClient:
    def __init__(self) -> None:
        self.created = 0
        self.remembered: list[str] = []
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
        for widget in app.screen.query("#body, #sessions-pane, #detail-pane, #actions"):
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
