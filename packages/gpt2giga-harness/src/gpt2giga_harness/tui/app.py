"""Textual shell for project and session navigation."""

from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from gpt2giga_harness.tui.client import (
    NavigationSnapshot,
    ProjectSummary,
    RunSnapshot,
    SessionSummary,
    TimelineEvent,
    WorkbenchClient,
)
from gpt2giga_harness.tui.i18n import translator


class NavigationItem(ListItem):
    """List item that retains one opaque navigation identity."""

    def __init__(self, label: str, value: str) -> None:
        super().__init__(Label(label, markup=False))
        self.value = value


class TextPrompt(ModalScreen[str | None]):
    """Keyboard-first bounded text prompt."""

    CSS = """
    TextPrompt {
        align: center middle;
    }
    #prompt-dialog {
        width: 72;
        max-width: 92%;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #prompt-actions {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    #prompt-actions Button {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, prompt: str, confirm: str, cancel: str) -> None:
        super().__init__()
        self.prompt = prompt
        self.confirm = confirm
        self.cancel = cancel

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-dialog"):
            yield Label(self.prompt, markup=False)
            yield Input(id="prompt-input")
            with Horizontal(id="prompt-actions"):
                yield Button(self.cancel, id="cancel")
                yield Button(self.confirm, variant="primary", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted)
    def submit_input(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value.strip())

    @on(Button.Pressed, "#confirm")
    def confirm_prompt(self) -> None:
        value = self.query_one("#prompt-input", Input).value.strip()
        self.dismiss(value)

    @on(Button.Pressed, "#cancel")
    def cancel_prompt(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    """Discoverable keyboard help."""

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-dialog {
        width: 68;
        max-width: 92%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("enter", "close", "Close", show=False),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.help_title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label(self.help_title, classes="dialog-title", markup=False)
            yield Static(self.body, markup=False)

    def action_close(self) -> None:
        self.dismiss(None)


class WorkbenchTui(App[None]):
    """Thin optional shell over the authoritative Harness application."""

    TITLE = "GigaLoom"
    CSS = """
    Screen {
        layout: vertical;
        overflow-x: hidden;
    }
    Header {
        height: 1;
    }
    #body {
        height: 1fr;
        min-height: 8;
        layout: horizontal;
        overflow-x: hidden;
    }
    .nav-pane {
        width: 28;
        min-width: 18;
        border-right: solid $primary-background;
        overflow-x: hidden;
    }
    #sessions-pane {
        width: 34;
    }
    .pane-title {
        height: 2;
        padding: 0 1;
        text-style: bold;
        color: $text-muted;
    }
    ListView {
        height: 1fr;
        overflow-x: hidden;
    }
    ListItem {
        height: 2;
        padding: 0 1;
    }
    #detail-pane {
        width: 1fr;
        min-width: 20;
        padding: 0 2;
        overflow: auto hidden;
    }
    #detail-title {
        height: auto;
        min-height: 2;
        text-style: bold;
        margin-bottom: 1;
    }
    #readiness {
        height: auto;
        max-height: 9;
    }
    #timeline {
        height: 1fr;
        min-height: 4;
        margin-top: 1;
        padding: 0 1;
        border: round $primary-background;
        overflow: auto hidden;
    }
    #interaction-actions {
        height: 3;
        align-vertical: middle;
        overflow-x: hidden;
    }
    #interaction-actions Button {
        min-width: 8;
        margin-right: 1;
    }
    #composer-row {
        height: 3;
        align-vertical: middle;
    }
    #composer {
        width: 1fr;
    }
    #send-turn {
        min-width: 10;
        margin-left: 1;
    }
    #actions {
        height: 3;
        padding: 0 1;
        align-vertical: middle;
        overflow-x: hidden;
    }
    #actions Button {
        min-width: 10;
        margin-right: 1;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #body.narrow {
        layout: vertical;
    }
    #body.narrow #projects-pane {
        display: none;
    }
    #body.narrow #sessions-pane {
        width: 100%;
        height: 42%;
        min-height: 5;
        border-right: none;
        border-bottom: solid $primary-background;
    }
    #body.narrow #detail-pane {
        width: 100%;
        height: 1fr;
        min-height: 4;
        padding: 0 1;
    }
    #body.narrow #readiness {
        display: none;
    }
    #body.narrow #timeline {
        margin-top: 0;
        min-height: 3;
    }
    #body.narrow #interaction-actions Button {
        min-width: 3;
        width: 1fr;
        margin-right: 0;
    }
    #body.narrow .pane-title {
        height: 1;
    }
    #body.narrow #actions Button {
        min-width: 3;
        width: 1fr;
        margin-right: 0;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "choose_project", "Project"),
        Binding("n", "new_session", "New session"),
        Binding("?", "help", "Help"),
    ]

    def __init__(
        self,
        client: WorkbenchClient,
        *,
        workspace: str | None = None,
        session_id: str | None = None,
        locale: str | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.workspace = workspace
        self.selected_session_id = session_id
        self.snapshot: NavigationSnapshot | None = None
        self.run_snapshot: RunSnapshot | None = None
        self.run_cursor: str | None = None
        self.timeline: list[TimelineEvent] = []
        self._polling = False
        self.t = translator(locale)
        self.sub_title = self.t("app.subtitle")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="projects-pane", classes="nav-pane"):
                yield Label(self.t("pane.projects"), classes="pane-title", markup=False)
                yield ListView(id="project-list")
            with Vertical(id="sessions-pane", classes="nav-pane"):
                yield Label(self.t("pane.sessions"), classes="pane-title", markup=False)
                yield ListView(id="session-list")
            with Vertical(id="detail-pane"):
                yield Label(self.t("pane.readiness"), id="detail-title", markup=False)
                yield Static(self.t("detail.empty"), id="readiness", markup=False)
                yield Static(self.t("timeline.empty"), id="timeline", markup=False)
                with Horizontal(id="interaction-actions"):
                    yield Button(self.t("button.approve"), id="approve")
                    yield Button(self.t("button.deny"), id="deny")
                    yield Button(self.t("button.answer"), id="answer")
                    yield Button(self.t("button.cancel_run"), id="cancel-run")
                    yield Button(self.t("button.fork"), id="fork-run")
                with Horizontal(id="composer-row"):
                    yield Input(
                        placeholder=self.t("composer.placeholder"),
                        id="composer",
                    )
                    yield Button(
                        self.t("button.send"),
                        id="send-turn",
                        variant="primary",
                    )
        with Horizontal(id="actions"):
            yield Button(self.t("button.new_project"), id="project")
            yield Button(
                self.t("button.new_session"), id="new-session", variant="primary"
            )
            yield Button(self.t("button.refresh"), id="refresh")
            yield Button(self.t("button.help"), id="help")
        yield Static(self.t("status.loading"), id="status", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        self._set_narrow(self.size.width)
        await self._reload()
        self.set_interval(0.15, self._poll_run)
        self.query_one("#session-list", ListView).focus()

    def on_resize(self, event: events.Resize) -> None:
        self._set_narrow(event.size.width)

    @on(ListView.Selected, "#project-list")
    async def select_project(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, NavigationItem) or self.snapshot is None:
            return
        selected = next(
            (project for project in self.snapshot.projects if project.id == item.value),
            None,
        )
        if selected is None or selected.root == self.workspace:
            return
        self.workspace = selected.root
        self.selected_session_id = None
        await self._reload()

    @on(ListView.Selected, "#session-list")
    async def select_session(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, NavigationItem):
            return
        self.selected_session_id = item.value
        self._reset_run()
        if self.snapshot is not None:
            await self.client.remember_session(self.snapshot.project.root, item.value)
        await self._reload()

    @on(Button.Pressed, "#project")
    def press_project(self) -> None:
        self.action_choose_project()

    @on(Button.Pressed, "#new-session")
    def press_new_session(self) -> None:
        self.action_new_session()

    @on(Button.Pressed, "#refresh")
    async def press_refresh(self) -> None:
        await self._reload()

    @on(Button.Pressed, "#help")
    def press_help(self) -> None:
        self.action_help()

    @on(Input.Submitted, "#composer")
    async def submit_composer(self, event: Input.Submitted) -> None:
        event.stop()
        await self._submit_content(event.value)

    @on(Button.Pressed, "#send-turn")
    async def press_send_turn(self) -> None:
        composer = self.query_one("#composer", Input)
        await self._submit_content(composer.value)

    @on(Button.Pressed, "#approve")
    async def press_approve(self) -> None:
        await self._decide_approval("allow_once")

    @on(Button.Pressed, "#deny")
    async def press_deny(self) -> None:
        await self._decide_approval("deny")

    @on(Button.Pressed, "#cancel-run")
    async def press_cancel_run(self) -> None:
        if self.run_snapshot is None:
            return
        try:
            snapshot = await self.client.cancel_run(self.run_snapshot.binding)
        except Exception as exc:
            self._show_error(exc)
            return
        self._apply_run_snapshot(snapshot)

    @on(Button.Pressed, "#fork-run")
    async def press_fork_run(self) -> None:
        if self.run_snapshot is None:
            return
        try:
            session = await self.client.fork_run(self.run_snapshot.binding)
        except Exception as exc:
            self._show_error(exc)
            return
        self.selected_session_id = session.id
        self._reset_run()
        await self._reload()

    @on(Button.Pressed, "#answer")
    def press_answer(self) -> None:
        if self._pending_input_id() is None:
            return
        self.push_screen(
            TextPrompt(
                self.t("dialog.input_answer"),
                self.t("dialog.confirm"),
                self.t("dialog.cancel"),
            ),
            self._input_answered,
        )

    async def action_refresh(self) -> None:
        await self._reload()

    def action_choose_project(self) -> None:
        self.push_screen(
            TextPrompt(
                self.t("dialog.project_path"),
                self.t("dialog.confirm"),
                self.t("dialog.cancel"),
            ),
            self._project_chosen,
        )

    def action_new_session(self) -> None:
        self.push_screen(
            TextPrompt(
                self.t("dialog.session_title"),
                self.t("dialog.confirm"),
                self.t("dialog.cancel"),
            ),
            self._session_title_chosen,
        )

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.t("help.title"), self.t("help.body")))

    async def _project_chosen(self, value: str | None) -> None:
        if not value:
            return
        self.workspace = value
        self.selected_session_id = None
        self._reset_run()
        await self._reload()

    async def _session_title_chosen(self, value: str | None) -> None:
        if value is None or self.snapshot is None:
            return
        try:
            created = await self.client.create_session(
                self.snapshot.project.root,
                title=value or None,
            )
        except Exception as exc:
            self._show_error(exc)
            return
        self.selected_session_id = created.id
        self._reset_run()
        self._set_status(self.t("session.created"))
        await self._reload()

    async def _reload(self) -> None:
        self._set_status(self.t("status.loading"))
        try:
            snapshot = await self.client.load(
                self.workspace,
                selected_session_id=self.selected_session_id,
            )
        except Exception as exc:
            self._show_error(exc)
            return
        self.snapshot = snapshot
        self.workspace = snapshot.project.root
        self.selected_session_id = snapshot.selected_session_id
        await self._render_projects(snapshot.projects, snapshot.project.id)
        await self._render_sessions(snapshot.sessions, snapshot.selected_session_id)
        self._render_readiness(snapshot)
        await self._reconnect_selected_run()
        mode_key = (
            "status.attach"
            if snapshot.transport_mode == "attach"
            else "status.in_process"
        )
        self._set_status(f"{self.t('status.ready')} · {self.t(mode_key)}")

    async def _submit_content(self, value: str) -> None:
        content = value.strip()
        if not content or self.selected_session_id is None:
            return
        self.query_one("#composer", Input).value = ""
        key = f"tui-{uuid4().hex}"
        try:
            if self.run_snapshot is not None and not self.run_snapshot.terminal:
                snapshot = await self.client.steer_run(
                    self.run_snapshot.binding,
                    content,
                    idempotency_key=key,
                )
            else:
                snapshot = await self.client.submit_turn(
                    self.selected_session_id,
                    content,
                    idempotency_key=key,
                )
        except Exception as exc:
            self._show_error(exc)
            return
        self._reset_run()
        self._apply_run_snapshot(snapshot)
        self._set_status(self.t("status.running"))

    async def _poll_run(self) -> None:
        if self._polling or self.run_snapshot is None or self.run_snapshot.terminal:
            return
        self._polling = True
        try:
            snapshot = await self.client.snapshot_run(
                self.run_snapshot.binding.run_id,
                cursor=self.run_cursor,
            )
            self._apply_run_snapshot(snapshot)
        except Exception as exc:
            self._show_error(exc)
        finally:
            self._polling = False

    async def _reconnect_selected_run(self) -> None:
        if self.selected_session_id is None:
            self._reset_run()
            return
        if (
            self.run_snapshot is not None
            and self.run_snapshot.binding.session_id == self.selected_session_id
        ):
            return
        try:
            snapshot = await self.client.latest_run(self.selected_session_id)
        except Exception as exc:
            self._show_error(exc)
            return
        self._reset_run()
        if snapshot is not None:
            self._apply_run_snapshot(snapshot)

    def _apply_run_snapshot(self, snapshot: RunSnapshot) -> None:
        if (
            self.run_snapshot is None
            or self.run_snapshot.binding.run_id != snapshot.binding.run_id
            or snapshot.resnapshot_reason in {"cursor_gap", "generation_changed"}
        ):
            self.timeline.clear()
        known = {event.id for event in self.timeline}
        self.timeline.extend(
            event for event in snapshot.events if event.id not in known
        )
        self.timeline = self.timeline[-100:]
        self.run_snapshot = snapshot
        self.run_cursor = snapshot.cursor
        self._render_timeline()
        self._update_interaction_actions()
        if snapshot.terminal:
            self._set_status(f"{self.t('status.finished')}: {snapshot.status}")
        elif snapshot.resnapshot_reason:
            self._set_status(
                f"{self.t('status.resnapshot')}: {snapshot.resnapshot_reason}"
            )

    def _render_timeline(self) -> None:
        lines: list[str] = []
        for event in self.timeline:
            if event.type == "message_delta" and event.delta:
                lines.append(event.delta)
            elif event.type == "reasoning_delta" and event.delta:
                lines.append(f"· {event.delta}")
            elif event.type.startswith("tool_call"):
                lines.append(f"⚙ {event.tool_name or event.message}")
            elif event.type == "approval_requested":
                lines.append(f"! {event.message}")
            elif event.input_id is not None or event.type in {
                "input_requested",
                "user_input_requested",
            }:
                lines.append(f"? {event.message}")
            elif event.type in {
                "run_started",
                "run_finished",
                "run_canceled",
                "error",
                "warning",
            }:
                lines.append(event.message)
        content = "\n".join(lines)[-64_000:] or self.t("timeline.empty")
        self.query_one("#timeline", Static).update(content)

    def _update_interaction_actions(self) -> None:
        snapshot = self.run_snapshot
        pending = bool(snapshot and snapshot.pending_approvals)
        self.query_one("#approve", Button).disabled = not pending
        self.query_one("#deny", Button).disabled = not pending
        self.query_one("#answer", Button).disabled = self._pending_input_id() is None
        self.query_one("#cancel-run", Button).disabled = (
            not snapshot or snapshot.terminal
        )
        self.query_one("#fork-run", Button).disabled = snapshot is None

    async def _decide_approval(self, decision: str) -> None:
        if self.run_snapshot is None or not self.run_snapshot.pending_approvals:
            return
        approval = self.run_snapshot.pending_approvals[0]
        try:
            snapshot = await self.client.decide_approval(
                self.run_snapshot.binding,
                approval.id,
                decision,
            )
        except Exception as exc:
            self._show_error(exc)
            return
        self._apply_run_snapshot(snapshot)

    async def _input_answered(self, answer: str | None) -> None:
        input_id = self._pending_input_id()
        if not answer or input_id is None or self.run_snapshot is None:
            return
        try:
            snapshot = await self.client.answer_input(
                self.run_snapshot.binding,
                input_id,
                answer,
            )
        except Exception as exc:
            self._show_error(exc)
            return
        self._apply_run_snapshot(snapshot)

    def _pending_input_id(self) -> str | None:
        return next(
            (event.input_id for event in reversed(self.timeline) if event.input_id),
            None,
        )

    def _reset_run(self) -> None:
        self.run_snapshot = None
        self.run_cursor = None
        self.timeline.clear()
        if self.is_mounted:
            self._render_timeline()
            self._update_interaction_actions()

    async def _render_projects(
        self,
        projects: tuple[ProjectSummary, ...],
        selected_id: str,
    ) -> None:
        view = self.query_one("#project-list", ListView)
        await view.clear()
        await view.extend(
            NavigationItem(
                f"{project.name}  ({project.session_count})",
                project.id,
            )
            for project in projects
        )
        view.index = next(
            (index for index, item in enumerate(projects) if item.id == selected_id),
            0 if projects else None,
        )

    async def _render_sessions(
        self,
        sessions: tuple[SessionSummary, ...],
        selected_id: str | None,
    ) -> None:
        view = self.query_one("#session-list", ListView)
        await view.clear()
        await view.extend(
            NavigationItem(
                f"{session.title} · {session.harness_id}",
                session.id,
            )
            for session in sessions
        )
        view.index = next(
            (index for index, item in enumerate(sessions) if item.id == selected_id),
            0 if sessions else None,
        )

    def _render_readiness(self, snapshot: NavigationSnapshot) -> None:
        readiness = snapshot.readiness
        model = readiness.model or "—"
        findings = ", ".join(readiness.findings) or "—"
        content = "\n".join(
            (
                f"{snapshot.project.name}",
                f"{self.t('label.provider')}: {readiness.provider} [{readiness.provider_status}]",
                f"{self.t('label.harness')}: {readiness.harness_id} [{readiness.harness_status}]",
                f"{self.t('label.model')}: {model}",
                f"{self.t('label.transport')}: {readiness.transport}",
                f"{self.t('label.readiness')}: {readiness.status}",
                f"Findings: {findings}",
            )
        )
        self.query_one("#readiness", Static).update(content)

    def _set_narrow(self, width: int) -> None:
        self.query_one("#body").set_class(width < 84, "narrow")

    def _show_error(self, exc: Exception) -> None:
        message = str(exc).strip() or type(exc).__name__
        self._set_status(f"{self.t('status.error')}: {message[:240]}")

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)
