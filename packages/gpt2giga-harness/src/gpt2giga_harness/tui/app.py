"""Textual shell for project and session navigation."""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar
from uuid import uuid4

from textual import events, on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding, BindingsMap
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
from textual.suggester import SuggestFromList

from gpt2giga_harness.terminal_dispatch import TuiLaunchIntent
from gpt2giga_harness.tui.client import (
    AttachmentSummary,
    FileCandidate,
    HandoffPreview,
    MAX_NATIVE_SCROLLBACK_CHARS,
    NativeTerminalSnapshot,
    NavigationSnapshot,
    ProjectSummary,
    RunInspection,
    RunSnapshot,
    SessionSummary,
    TimelineEvent,
    WorkbenchClient,
    neutralize_native_terminal_output,
)
from gpt2giga_harness.tui.i18n import translator
from gpt2giga_harness.tui.commands import (
    COMMAND_REGISTRY,
    RuntimeControlState,
    command_bindings,
    command_for_slash,
    slash_commands,
    visible_commands,
)


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


class FilePickerScreen(ModalScreen[FileCandidate | None]):
    """Bounded keyboard-first project file picker with safe preview."""

    CSS = """
    FilePickerScreen { align: center middle; }
    #file-dialog {
        width: 92%;
        height: 88%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #file-policy { height: auto; color: $text-muted; }
    #file-list { height: 40%; margin-top: 1; border: round $primary-background; }
    #file-preview { height: 1fr; margin-top: 1; overflow: auto hidden; }
    #file-actions { height: 3; align-horizontal: right; }
    #file-actions Button { margin-left: 1; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        candidates: tuple[FileCandidate, ...],
        *,
        title: str,
        policy: str,
        attach: str,
        cancel: str,
        empty: str,
    ) -> None:
        super().__init__()
        self.candidates = candidates
        self.dialog_title = title
        self.policy = policy
        self.attach_label = attach
        self.cancel_label = cancel
        self.empty = empty

    def compose(self) -> ComposeResult:
        with Vertical(id="file-dialog"):
            yield Label(self.dialog_title, classes="dialog-title", markup=False)
            yield Static(self.policy, id="file-policy", markup=False)
            yield ListView(
                *(
                    NavigationItem(
                        f"{item.path} · {item.kind} · {item.size_bytes} B",
                        item.path,
                    )
                    for item in self.candidates
                ),
                id="file-list",
            )
            yield Static(self.empty, id="file-preview", markup=False)
            with Horizontal(id="file-actions"):
                yield Button(self.cancel_label, id="file-cancel")
                yield Button(
                    self.attach_label,
                    id="file-attach",
                    variant="primary",
                    disabled=not self.candidates,
                )

    def on_mount(self) -> None:
        view = self.query_one("#file-list", ListView)
        if self.candidates:
            view.index = 0
            self._render_preview(0)
        view.focus()

    @on(ListView.Highlighted, "#file-list")
    def highlight_file(self, event: ListView.Highlighted) -> None:
        item = event.item
        if not isinstance(item, NavigationItem):
            return
        index = next(
            (
                index
                for index, candidate in enumerate(self.candidates)
                if candidate.path == item.value
            ),
            None,
        )
        if index is not None:
            self._render_preview(index)

    @on(ListView.Selected, "#file-list")
    def select_file(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, NavigationItem):
            self.dismiss(
                next(
                    candidate
                    for candidate in self.candidates
                    if candidate.path == item.value
                )
            )

    @on(Button.Pressed, "#file-attach")
    def attach_file(self) -> None:
        index = self.query_one("#file-list", ListView).index
        if index is not None and 0 <= index < len(self.candidates):
            self.dismiss(self.candidates[index])

    @on(Button.Pressed, "#file-cancel")
    def cancel_file(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _render_preview(self, index: int) -> None:
        candidate = self.candidates[index]
        header = (
            f"{candidate.path}\n{candidate.mime_type} · {candidate.preview_status}\n\n"
        )
        self.query_one("#file-preview", Static).update(header + candidate.preview)


class DetailScreen(ModalScreen[None]):
    """Bounded read-only inspection or handoff detail."""

    CSS = """
    DetailScreen { align: center middle; }
    #detail-dialog {
        width: 92%;
        height: 88%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #detail-body { height: 1fr; overflow: auto hidden; }
    #detail-close { dock: bottom; width: 12; align-horizontal: right; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("enter", "close", "Close", show=False),
    ]

    def __init__(self, title: str, body: str, close: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.body = body
        self.close_label = close

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-dialog"):
            yield Label(self.dialog_title, classes="dialog-title", markup=False)
            yield Static(self.body, id="detail-body", markup=False)
            yield Button(self.close_label, id="detail-close", variant="primary")

    @on(Button.Pressed, "#detail-close")
    def close_button(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class NativeTerminalScreen(ModalScreen[str | None]):
    """Contained, terminal-neutral view over application-owned native processes."""

    CSS = """
    NativeTerminalScreen { align: center middle; }
    #native-dialog {
        width: 96%;
        height: 94%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #native-header { height: auto; min-height: 2; }
    #native-output {
        height: 1fr;
        min-height: 4;
        margin-top: 1;
        padding: 0 1;
        border: round $primary-background;
        overflow: auto hidden;
    }
    #native-input-row { height: 3; align-vertical: middle; }
    #native-input { width: 1fr; }
    #native-send { min-width: 10; margin-left: 1; }
    #native-actions { height: 3; align-horizontal: right; }
    #native-actions Button { min-width: 10; margin-left: 1; }
    #native-status { height: 1; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "return_to_session", "Return", show=False),
        Binding("ctrl+c", "stop", "Stop", show=False),
    ]

    def __init__(
        self,
        client: WorkbenchClient,
        snapshot: NativeTerminalSnapshot,
        *,
        title: str,
        send: str,
        stop: str,
        return_to_session: str,
        handoff: str,
        fullscreen_blocked: str,
        disconnected: str,
        reconnected: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.snapshot = snapshot
        self.dialog_title = title
        self.send_label = send
        self.stop_label = stop
        self.return_label = return_to_session
        self.handoff_label = handoff
        self.fullscreen_blocked = fullscreen_blocked
        self.disconnected_label = disconnected
        self.reconnected_label = reconnected
        self.scrollback = ""
        self._polling = False
        self._resizing = False
        self._pending_dimensions: tuple[int, int] | None = None
        self._disconnected = False
        self._stopping_for_handoff = False

    def compose(self) -> ComposeResult:
        with Vertical(id="native-dialog"):
            yield Label(self.dialog_title, id="native-header", markup=False)
            yield Static("", id="native-output", markup=False)
            with Horizontal(id="native-input-row"):
                yield Input(id="native-input")
                yield Button(self.send_label, id="native-send", variant="primary")
            with Horizontal(id="native-actions"):
                yield Button(self.handoff_label, id="native-handoff")
                yield Button(self.stop_label, id="native-stop", variant="error")
                yield Button(self.return_label, id="native-return")
            yield Static("", id="native-status", markup=False)

    async def on_mount(self) -> None:
        self._apply_snapshot(self.snapshot)
        self.set_interval(0.1, self._poll)
        await self._resize()
        await self._enforce_fullscreen_boundary()
        self.query_one("#native-input", Input).focus()

    async def on_resize(self, _event: events.Resize) -> None:
        await self._resize()

    @on(Input.Submitted, "#native-input")
    async def submit_input(self, event: Input.Submitted) -> None:
        event.stop()
        await self._send(event.value)

    @on(Button.Pressed, "#native-send")
    async def press_send(self) -> None:
        await self._send(self.query_one("#native-input", Input).value)

    @on(Button.Pressed, "#native-stop")
    async def press_stop(self) -> None:
        await self.action_stop()

    @on(Button.Pressed, "#native-return")
    def press_return(self) -> None:
        self.action_return_to_session()

    @on(Button.Pressed, "#native-handoff")
    def press_handoff(self) -> None:
        self.dismiss("handoff")

    async def action_stop(self) -> None:
        if self.snapshot.terminal:
            return
        try:
            stopped = await self.client.stop_native_terminal(self.snapshot.process_id)
        except Exception as exc:
            self._show_error(exc)
            return
        self._apply_snapshot(stopped)

    def action_return_to_session(self) -> None:
        self.dismiss("return")

    async def _send(self, value: str) -> None:
        if not value or self.snapshot.terminal or self.snapshot.handoff_required:
            return
        try:
            updated = await self.client.send_native_terminal_input(
                self.snapshot.process_id,
                value,
                submit=True,
            )
        except Exception as exc:
            self._show_error(exc)
            return
        self.query_one("#native-input", Input).value = ""
        self._apply_snapshot(updated)

    async def _poll(self) -> None:
        if self._polling or not self.is_mounted or self.snapshot.terminal:
            return
        self._polling = True
        try:
            updated = await self.client.snapshot_native_terminal(
                self.snapshot.process_id,
                cursor=self.snapshot.cursor,
            )
            if not self.is_mounted:
                return
            self._apply_snapshot(updated)
            if self._disconnected:
                self._disconnected = False
                self.query_one("#native-status", Static).update(
                    f"{updated.harness_id} · {updated.transport} · "
                    f"{self.reconnected_label}"
                )
            await self._enforce_fullscreen_boundary()
        except Exception as exc:
            if self.is_mounted:
                self._disconnected = True
                self._show_error(exc, prefix=self.disconnected_label)
        finally:
            self._polling = False

    async def _resize(self) -> None:
        if not self.is_mounted or self.snapshot.terminal:
            return
        rows = max(2, min(200, self.size.height - 10))
        columns = max(20, min(500, self.size.width - 8))
        self._pending_dimensions = (rows, columns)
        if self._resizing:
            return
        self._resizing = True
        try:
            while self._pending_dimensions is not None:
                requested_rows, requested_columns = self._pending_dimensions
                self._pending_dimensions = None
                try:
                    updated = await self.client.resize_native_terminal(
                        self.snapshot.process_id,
                        rows=requested_rows,
                        columns=requested_columns,
                    )
                except Exception as exc:
                    self._disconnected = True
                    self._show_error(exc, prefix=self.disconnected_label)
                    return
                self._apply_snapshot(updated)
        finally:
            self._resizing = False

    async def _enforce_fullscreen_boundary(self) -> None:
        if (
            not self.snapshot.handoff_required
            or self.snapshot.terminal
            or self._stopping_for_handoff
        ):
            return
        self._stopping_for_handoff = True
        try:
            stopped = await self.client.stop_native_terminal(self.snapshot.process_id)
            self._apply_snapshot(replace(stopped, handoff_required=True))
        except Exception as exc:
            self._show_error(exc)
        finally:
            self._stopping_for_handoff = False

    def _apply_snapshot(self, snapshot: NativeTerminalSnapshot) -> None:
        safe = neutralize_native_terminal_output(snapshot.output)
        if safe:
            self.scrollback = (self.scrollback + safe)[-MAX_NATIVE_SCROLLBACK_CHARS:]
        self.snapshot = snapshot
        output = self.scrollback
        if snapshot.output_truncated:
            output = "[older output unavailable]\n" + output
        if snapshot.handoff_required:
            output += f"\n\n{self.fullscreen_blocked}"
        self.query_one("#native-output", Static).update(output)
        self.query_one("#native-status", Static).update(
            f"{snapshot.harness_id} · {snapshot.transport} · {snapshot.status}"
        )
        blocked = snapshot.terminal or snapshot.handoff_required
        self.query_one("#native-input", Input).disabled = blocked
        self.query_one("#native-send", Button).disabled = blocked
        self.query_one("#native-stop", Button).disabled = snapshot.terminal

    def _show_error(self, exc: Exception, *, prefix: str | None = None) -> None:
        message = str(exc).strip() or type(exc).__name__
        if prefix:
            message = f"{prefix}: {message}"
        self.query_one("#native-status", Static).update(message[:240])


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
    ListView:focus, Input:focus {
        border: tall $accent;
    }
    Button:focus {
        text-style: bold reverse underline;
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
    #attachment-status {
        height: 1;
        color: $text-muted;
    }
    #context-actions {
        height: 3;
        align-vertical: middle;
        overflow-x: hidden;
    }
    #context-actions Button {
        min-width: 8;
        width: 1fr;
        margin-right: 1;
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
    #runtime-status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        overflow-x: hidden;
    }
    #body.narrow {
        layout: vertical;
    }
    #body.narrow #projects-pane {
        display: none;
    }
    #body.narrow #sessions-pane {
        width: 100%;
        height: 4;
        min-height: 4;
        border-right: none;
        border-bottom: solid $primary-background;
    }
    #body.narrow ListItem {
        height: 1;
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
        min-height: 2;
    }
    #body.narrow #interaction-actions Button {
        min-width: 3;
        width: 1fr;
        margin-right: 0;
    }
    #body.narrow #context-actions Button {
        min-width: 3;
        margin-right: 0;
    }
    #body.narrow #context-actions {
        display: none;
    }
    #body.narrow .pane-title {
        height: 1;
    }
    #body.narrow #detail-title {
        display: none;
    }
    #body.narrow #actions Button {
        min-width: 3;
        width: 1fr;
        margin-right: 0;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = command_bindings(translator("en"))

    def __init__(
        self,
        client: WorkbenchClient,
        *,
        workspace: str | None = None,
        session_id: str | None = None,
        locale: str | None = None,
        launch_intent: TuiLaunchIntent | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.workspace = workspace
        self.selected_session_id = session_id
        self.launch_intent = launch_intent or TuiLaunchIntent(
            workspace=workspace,
            session_id=session_id,
        )
        self._launch_intent_applied = False
        self._launch_session_id: str | None = None
        self.snapshot: NavigationSnapshot | None = None
        self.run_snapshot: RunSnapshot | None = None
        self.run_cursor: str | None = None
        self.timeline: list[TimelineEvent] = []
        self.attachments: tuple[AttachmentSummary, ...] = ()
        self._polling = False
        self._disconnected = False
        self.t = translator(locale)
        localized_bindings = BindingsMap(command_bindings(self.t))
        self._bindings.key_to_bindings.update(localized_bindings.key_to_bindings)
        self._runtime_overrides: dict[str, str] = {}
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
                yield Static(
                    self.t("attachments.empty"), id="attachment-status", markup=False
                )
                with Horizontal(id="context-actions"):
                    yield Button(self.t("button.files"), id="files")
                    yield Button(self.t("button.evidence"), id="evidence")
                    yield Button(self.t("button.terminal"), id="native-terminal")
                    yield Button(self.t("button.provider"), id="provider-handoff")
                    yield Button(self.t("button.web"), id="web-handoff")
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
                        suggester=SuggestFromList(
                            slash_commands(), case_sensitive=False
                        ),
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
        yield Static("", id="runtime-status", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        self._set_narrow(self.size.width)
        await self._reload()
        await self._apply_launch_intent()
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
        self.attachments = ()
        await self._reload()

    @on(ListView.Selected, "#session-list")
    async def select_session(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, NavigationItem):
            return
        self.selected_session_id = item.value
        self.attachments = ()
        self._render_attachments()
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

    @on(Button.Pressed, "#files")
    def press_files(self) -> None:
        self.action_files()

    @on(Button.Pressed, "#evidence")
    async def press_evidence(self) -> None:
        await self.action_evidence()

    @on(Button.Pressed, "#native-terminal")
    async def press_native_terminal(self) -> None:
        await self.action_native_terminal()

    @on(Button.Pressed, "#provider-handoff")
    async def press_provider_handoff(self) -> None:
        await self.action_provider_handoff()

    @on(Button.Pressed, "#web-handoff")
    async def press_web_handoff(self) -> None:
        await self.action_web_handoff()

    @on(Input.Submitted, "#composer")
    async def submit_composer(self, event: Input.Submitted) -> None:
        event.stop()
        command = command_for_slash(event.value)
        if command is not None:
            event.input.value = ""
            await self._execute_registered_command(command.id)
            return
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
        commands = visible_commands(has_session=self.selected_session_id is not None)
        body = "\n".join(
            f"{_display_key(command.key) if command.key else command.slash}: "
            f"{self.t(command.title_key)}"
            for command in commands
        )
        self.push_screen(HelpScreen(self.t("help.title"), body))

    def get_system_commands(self, screen):
        """Populate Ctrl+P from the same registry used by slash and bindings."""
        del screen
        for command in visible_commands(
            has_session=self.selected_session_id is not None
        ):
            yield SystemCommand(
                self.t(command.title_key),
                f"{command.slash} · {self.t(command.description_key)}",
                lambda command_id=command.id: self.call_later(
                    self._execute_registered_command, command_id
                ),
            )

    async def action_status_view(self) -> None:
        self._show_detail(self.t("status.title"), self._status_detail())

    def action_runtime_control(self, control_id: str) -> None:
        control = self._runtime_controls()[control_id]
        if control.state != "ready":
            self._show_detail(
                self.t(f"control.{control_id}"),
                self._runtime_control_text(control),
            )
            return
        self.push_screen(
            TextPrompt(
                self.t("control.change_prompt").format(
                    control=self.t(f"control.{control_id}"),
                    scope=self.t(f"scope.{control.effect_scope}"),
                    current=control.current,
                ),
                self.t("dialog.confirm"),
                self.t("dialog.cancel"),
            ),
            lambda value: self._runtime_control_chosen(control_id, value),
        )

    def action_files(self) -> None:
        if self.selected_session_id is None:
            self._show_detail(self.t("files.title"), self.t("files.no_session"))
            return
        self.push_screen(
            TextPrompt(
                self.t("dialog.file_query"),
                self.t("dialog.confirm"),
                self.t("dialog.cancel"),
            ),
            self._file_query_chosen,
        )

    async def action_evidence(self) -> None:
        if self.run_snapshot is None:
            self._show_detail(self.t("evidence.title"), self.t("evidence.empty"))
            return
        self._set_status(self.t("status.loading_evidence"))
        try:
            inspection = await self.client.inspect_run(self.run_snapshot.binding.run_id)
        except Exception as exc:
            self._show_error(exc)
            return
        self._show_detail(self.t("evidence.title"), self._inspection_text(inspection))
        self._set_status(self.t("status.ready"))

    async def action_native_terminal(self) -> None:
        process_id = (
            self.run_snapshot.native_process_id
            if self.run_snapshot is not None
            else None
        )
        if process_id is None:
            self._show_detail(self.t("terminal.title"), self.t("terminal.no_process"))
            return
        try:
            await self.client.status_native_terminal(process_id)
            snapshot = await self.client.snapshot_native_terminal(process_id)
        except Exception as exc:
            self._show_error(exc)
            return
        self._show_native_terminal(snapshot)

    async def action_provider_handoff(self) -> None:
        await self._show_handoff("provider")

    async def action_web_handoff(self) -> None:
        await self._show_handoff("web")

    async def _project_chosen(self, value: str | None) -> None:
        if not value:
            return
        self.workspace = value
        self.selected_session_id = None
        self.attachments = ()
        self._render_attachments()
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

    async def _file_query_chosen(self, value: str | None) -> None:
        if value is None or self.selected_session_id is None:
            return
        self._set_status(self.t("status.loading_files"))
        try:
            candidates = await self.client.search_files(self.selected_session_id, value)
        except Exception as exc:
            self._show_error(exc)
            return
        self.push_screen(
            FilePickerScreen(
                candidates,
                title=self.t("files.title"),
                policy=self.t("files.policy"),
                attach=self.t("files.attach"),
                cancel=self.t("dialog.cancel"),
                empty=self.t("files.empty"),
            ),
            self._file_chosen,
        )
        self._set_status(self.t("status.ready"))

    async def _file_chosen(self, candidate: FileCandidate | None) -> None:
        if candidate is None or self.selected_session_id is None:
            return
        try:
            attachment = await self.client.attach_file(
                self.selected_session_id, candidate.path
            )
        except Exception as exc:
            self._show_error(exc)
            return
        if attachment.id not in {item.id for item in self.attachments}:
            self.attachments = (*self.attachments, attachment)
        self._render_attachments()
        self._set_status(self.t("files.attached"))

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

    async def _apply_launch_intent(self) -> None:
        if self._launch_intent_applied or self.snapshot is None:
            return
        self._launch_intent_applied = True
        intent = self.launch_intent
        if intent.create_session:
            try:
                created = await self.client.create_session(
                    intent.workspace or self.snapshot.project.root,
                    title=intent.title,
                    harness_id=intent.harness_id,
                    model=intent.model,
                    api_mode=intent.api_mode,
                    mode=intent.mode,
                )
            except Exception as exc:
                self._show_error(exc)
                return
            self.selected_session_id = created.id
            self._launch_session_id = created.id
            await self._reload()
        if intent.prompt and self.selected_session_id is not None:
            await self._submit_content(intent.prompt, launch_intent=intent)

    async def _submit_content(
        self,
        value: str,
        *,
        launch_intent: TuiLaunchIntent | None = None,
    ) -> None:
        content = value.strip()
        if not content or self.selected_session_id is None:
            return
        if (
            launch_intent is None
            and self.selected_session_id == self._launch_session_id
        ):
            launch_intent = self.launch_intent
        self.query_one("#composer", Input).value = ""
        key = f"tui-{uuid4().hex}"
        intent_arguments = (
            {
                "harness_id": launch_intent.harness_id,
                "model": launch_intent.model,
                "api_mode": launch_intent.api_mode,
                "mode": launch_intent.mode,
            }
            if launch_intent is not None
            else {}
        )
        for field in ("model", "mode"):
            if field in self._runtime_overrides:
                intent_arguments[field] = self._runtime_overrides[field]
        if launch_intent is not None and launch_intent.native_session_selector:
            intent_arguments["native_session_id"] = (
                launch_intent.native_session_selector
            )
            intent_arguments["native_session_operation"] = (
                launch_intent.session_operation
            )
        try:
            if (
                launch_intent is not None
                and launch_intent.execution_transport == "native_terminal"
            ) or self._native_terminal_selected():
                process_id = (
                    self.run_snapshot.native_process_id
                    if self.run_snapshot is not None and not self.run_snapshot.terminal
                    else None
                )
                if process_id is None:
                    terminal = await self.client.start_native_terminal(
                        self.selected_session_id,
                        content,
                        idempotency_key=key,
                        attachment_ids=tuple(item.id for item in self.attachments),
                        **intent_arguments,
                    )
                else:
                    terminal = await self.client.send_native_terminal_input(
                        process_id,
                        content,
                        submit=True,
                    )
                self.attachments = ()
                self._render_attachments()
                self._show_native_terminal(terminal)
                self._set_status(self.t("status.native_terminal"))
                return
            if self.run_snapshot is not None and not self.run_snapshot.terminal:
                snapshot = await self.client.steer_run(
                    self.run_snapshot.binding,
                    content,
                    idempotency_key=key,
                )
            else:
                turn_intent_arguments = dict(intent_arguments)
                if launch_intent is not None:
                    turn_intent_arguments.update(
                        capability=launch_intent.capability,
                        execution_transport=launch_intent.execution_transport,
                    )
                snapshot = await self.client.submit_turn(
                    self.selected_session_id,
                    content,
                    idempotency_key=key,
                    attachment_ids=tuple(item.id for item in self.attachments),
                    **turn_intent_arguments,
                )
                self._launch_session_id = None
        except Exception as exc:
            self._show_error(exc)
            return
        self._reset_run()
        self._apply_run_snapshot(snapshot)
        self.attachments = ()
        self._render_attachments()
        self._set_status(self.t("status.running"))
        self._runtime_overrides.clear()
        self._render_runtime_status()

    def _native_terminal_selected(self) -> bool:
        if (
            self.run_snapshot is not None
            and self.run_snapshot.execution_transport == "native_terminal"
        ):
            return True
        return bool(
            self.snapshot is not None
            and self.snapshot.readiness.transport == "native_terminal"
        )

    async def _poll_run(self) -> None:
        if (
            self._polling
            or len(self.screen_stack) > 1
            or not any(self.query("#timeline"))
            or self.run_snapshot is None
            or self.run_snapshot.terminal
        ):
            return
        self._polling = True
        try:
            snapshot = await self.client.snapshot_run(
                self.run_snapshot.binding.run_id,
                cursor=self.run_cursor,
            )
            if len(self.screen_stack) > 1 or not any(self.query("#timeline")):
                return
            self._apply_run_snapshot(snapshot)
            if self._disconnected:
                self._disconnected = False
                self._set_status(self.t("status.reconnected"))
        except Exception as exc:
            if any(self.query("#status")):
                self._disconnected = True
                self._set_status(
                    f"{self.t('status.disconnected')}: "
                    f"{(str(exc).strip() or type(exc).__name__)[:180]}"
                )
        finally:
            self._polling = False

    async def _reconnect_selected_run(self, *, force: bool = False) -> None:
        if self.selected_session_id is None:
            self._reset_run()
            return
        if (
            not force
            and self.run_snapshot is not None
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
                lines.append(f"[{self.t('timeline.reasoning')}] {event.delta}")
            elif event.type.startswith("tool_call"):
                lines.append(
                    f"[{self.t('timeline.tool')}] {event.tool_name or event.message}"
                )
            elif event.type == "approval_requested":
                lines.append(f"[{self.t('timeline.approval')}] {event.message}")
            elif event.input_id is not None or event.type in {
                "input_requested",
                "user_input_requested",
            }:
                lines.append(f"[{self.t('timeline.question')}] {event.message}")
            elif event.type in {
                "run_started",
                "run_finished",
                "run_canceled",
                "error",
                "warning",
            }:
                label = (
                    self.t("timeline.error")
                    if event.type == "error"
                    else self.t("timeline.warning")
                    if event.type == "warning"
                    else self.t("timeline.status")
                )
                lines.append(f"[{label}] {event.message}")
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
        self.query_one("#native-terminal", Button).disabled = not bool(
            snapshot and snapshot.native_process_id
        )

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

    async def _show_handoff(self, kind: str) -> None:
        if self.selected_session_id is None:
            self._show_detail(self.t("handoff.title"), self.t("handoff.no_session"))
            return
        self._set_status(self.t("status.loading_handoff"))
        try:
            preview = (
                await self.client.provider_handoff(self.selected_session_id)
                if kind == "provider"
                else await self.client.web_handoff(self.selected_session_id)
            )
        except Exception as exc:
            self._show_error(exc)
            return
        self._show_detail(self.t("handoff.title"), self._handoff_text(preview))
        self._set_status(self.t("status.ready"))

    def _show_native_terminal(self, snapshot: NativeTerminalSnapshot) -> None:
        self.push_screen(
            NativeTerminalScreen(
                self.client,
                snapshot,
                title=self.t("terminal.title"),
                send=self.t("button.send"),
                stop=self.t("terminal.stop"),
                return_to_session=self.t("terminal.return"),
                handoff=self.t("button.provider"),
                fullscreen_blocked=self.t("terminal.fullscreen_blocked"),
                disconnected=self.t("status.disconnected"),
                reconnected=self.t("status.reconnected"),
            ),
            self._native_terminal_closed,
        )

    async def _native_terminal_closed(self, result: str | None) -> None:
        await self._reconnect_selected_run(force=True)
        if result == "handoff":
            await self.action_provider_handoff()

    def _show_detail(self, title: str, body: str) -> None:
        self.push_screen(DetailScreen(title, body, self.t("dialog.close")))

    def _inspection_text(self, inspection: RunInspection) -> str:
        artifacts = ", ".join(item.type for item in inspection.artifacts) or "—"
        changed = ", ".join(inspection.changed_files) or "—"
        untracked = ", ".join(inspection.untracked_files) or "—"
        diff = inspection.diff or self.t("evidence.no_diff")
        if inspection.diff_truncated:
            diff += f"\n\n{self.t('evidence.truncated')}"
        return "\n".join(
            (
                f"State: ready · revision {inspection.revision[:12]}",
                f"Run: {inspection.run_id} [{inspection.status}]",
                f"Provider continuity: {inspection.provider_continuity}",
                f"Harness / integration: {inspection.harness_status}",
                f"Recovery: {inspection.recovery}",
                f"Artifacts: {artifacts}",
                f"Changed: {changed}",
                f"Untracked: {untracked}",
                "Environment: deferred to Phase N6",
                "",
                "Evidence:",
                *(f"- {item}" for item in inspection.evidence),
                "",
                "Diff:",
                diff,
            )
        )

    def _handoff_text(self, preview: HandoffPreview) -> str:
        command = " ".join(preview.command) or "—"
        return "\n".join(
            (
                f"Status: {preview.status}",
                f"Exact target: {preview.target}",
                f"Continuity: {preview.continuity}",
                f"Command: {command}",
                "Observability boundary:",
                *(f"- {item}" for item in preview.observability),
                "",
                preview.instruction,
            )
        )

    def _render_attachments(self) -> None:
        content = (
            f"{self.t('attachments.selected')}: "
            + ", ".join(item.path for item in self.attachments)
            if self.attachments
            else self.t("attachments.empty")
        )
        self.query_one("#attachment-status", Static).update(content)

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
                (
                    "Integrations: "
                    f"{snapshot.integrations.status} · "
                    f"catalog {snapshot.integrations.catalog_count} · "
                    f"flows {snapshot.integrations.flow_count} · "
                    f"verified {snapshot.integrations.verified_count}"
                ),
                "Environment: deferred to Phase N6",
                f"Findings: {findings}",
            )
        )
        self.query_one("#readiness", Static).update(content)
        self._render_runtime_status()

    def _set_narrow(self, width: int) -> None:
        self.query_one("#body").set_class(width < 84, "narrow")
        if self.is_mounted:
            self._render_runtime_status()

    def _show_error(self, exc: Exception) -> None:
        message = str(exc).strip() or type(exc).__name__
        self._set_status(f"{self.t('status.error')}: {message[:240]}")

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    async def _execute_registered_command(self, command_id: str) -> None:
        command = next(item for item in COMMAND_REGISTRY if item.id == command_id)
        if command.requires_session and self.selected_session_id is None:
            self._set_status(self.t("command.session_required"))
            return
        if command.control_id is not None:
            self.action_runtime_control(command.control_id)
            return
        callback = getattr(self, f"action_{command.action}")
        result = callback()
        if hasattr(result, "__await__"):
            await result

    async def _runtime_control_chosen(self, control_id: str, value: str | None) -> None:
        if not value or self.snapshot is None:
            return
        if control_id == "harness":
            available = {
                item.id
                for item in self.snapshot.harnesses
                if item.availability != "unavailable"
            }
            if value not in available:
                self._set_status(self.t("control.invalid_harness"))
                return
            try:
                created = await self.client.create_session(
                    self.snapshot.project.root, harness_id=value
                )
            except Exception as exc:
                self._show_error(exc)
                return
            self.selected_session_id = created.id
            self._reset_run()
            await self._reload()
            return
        self._runtime_overrides[control_id] = value
        self._set_status(
            self.t("control.queued").format(
                control=self.t(f"control.{control_id}"),
                scope=self.t(
                    f"scope.{self._runtime_controls()[control_id].effect_scope}"
                ),
            )
        )
        self._render_runtime_status()

    def _runtime_controls(self) -> dict[str, RuntimeControlState]:
        readiness = self.snapshot.readiness if self.snapshot is not None else None
        intent = self.launch_intent
        selected_session = (
            next(
                (
                    item
                    for item in self.snapshot.sessions
                    if item.id == self.selected_session_id
                ),
                None,
            )
            if self.snapshot is not None
            else None
        )
        current = {
            "harness": readiness.harness_id if readiness else intent.harness_id or "—",
            "model": self._runtime_overrides.get(
                "model",
                readiness.model
                if readiness and readiness.model
                else intent.model or "—",
            ),
            "effort": intent.effort or "—",
            "mode": self._runtime_overrides.get(
                "mode",
                selected_session.mode
                if selected_session is not None
                else intent.mode or "—",
            ),
            "permission": intent.permission_mode or "—",
            "policy": intent.policy or "—",
            "sandbox": intent.sandbox or "—",
        }
        ready = {
            "harness": ("new_session",),
            "model": ("next_run",),
            "mode": ("next_run",),
        }
        states: dict[str, RuntimeControlState] = {}
        for control_id in current:
            if control_id in {"model", "mode"} and self.selected_session_id is None:
                states[control_id] = RuntimeControlState(
                    control_id,
                    current[control_id],
                    ready[control_id][0],
                    "blocked",
                    self.t("control.session_required"),
                    self.t("control.session_remediation"),
                )
            elif control_id in ready:
                states[control_id] = RuntimeControlState(
                    control_id, current[control_id], ready[control_id][0], "ready"
                )
            else:
                states[control_id] = RuntimeControlState(
                    control_id,
                    current[control_id],
                    "next_run" if control_id == "effort" else "next_turn",
                    "handoff",
                    self.t("control.provider_owned"),
                    self.t("control.handoff_remediation"),
                )
        return states

    def _runtime_control_text(self, control: RuntimeControlState) -> str:
        return "\n".join(
            part
            for part in (
                f"{self.t('status.current')}: {control.current}",
                f"{self.t('status.effect_scope')}: {self.t(f'scope.{control.effect_scope}')}",
                f"{self.t('status.control_state')}: {self.t(f'control.state.{control.state}')}",
                control.limitation,
                (
                    f"{self.t('status.remediation')}: {control.remediation}"
                    if control.remediation
                    else None
                ),
            )
            if part
        )

    def _route_status(self) -> tuple[str, str, str, int]:
        intent = self.launch_intent
        transport = (
            self.run_snapshot.execution_transport
            if self.run_snapshot and self.run_snapshot.execution_transport
            else intent.provider_transport
            or (self.snapshot.readiness.transport if self.snapshot else "unknown")
        )
        if intent.provider_namespace and intent.provider_transport:
            level, owner = "L2", "harness"
        elif intent.provider_namespace:
            level, owner = "L1", "provider"
        else:
            level, owner = "Harness", "harness"
        generation = self.run_snapshot.binding.generation if self.run_snapshot else 1
        return level, transport, owner, generation

    def _render_runtime_status(self) -> None:
        if not any(self.query("#runtime-status")) or self.snapshot is None:
            return
        level, transport, owner, generation = self._route_status()
        controls = self._runtime_controls()
        width = self.size.width
        if width < 72:
            value = f"{level} · {controls['harness'].current} · {self.snapshot.readiness.status}"
        elif width < 100:
            value = (
                f"{level} · {transport} · {controls['harness'].current} · "
                f"{controls['model'].current}"
            )
        else:
            value = (
                f"{level} · {transport} · {owner} · gen {generation} · "
                f"{controls['harness'].current} · {controls['model'].current} · "
                f"{controls['mode'].current}"
            )
        self.query_one("#runtime-status", Static).update(value)

    def _status_detail(self) -> str:
        if self.snapshot is None:
            return self.t("status.loading")
        readiness = self.snapshot.readiness
        level, transport, owner, generation = self._route_status()
        controls = self._runtime_controls()
        lines = [
            f"{self.t('label.provider')}: {readiness.provider} [{readiness.provider_status}]",
            f"{self.t('status.route_level')}: {level}",
            f"{self.t('label.transport')}: {transport}",
            f"{self.t('status.process_owner')}: {owner}",
            f"{self.t('status.generation')}: {generation}",
            f"{self.t('status.client_transport')}: {self.snapshot.transport_mode}",
            f"{self.t('label.readiness')}: {readiness.status}",
            "",
        ]
        lines.extend(
            f"{self.t(f'control.{control.id}')}: {control.current} · "
            f"{self.t(f'control.state.{control.state}')} · "
            f"{self.t(f'scope.{control.effect_scope}')}"
            + (f" · {control.remediation}" if control.remediation else "")
            for control in controls.values()
        )
        if readiness.findings:
            lines.extend(
                ("", f"{self.t('status.findings')}: {', '.join(readiness.findings)}")
            )
        return "\n".join(lines)


def _display_key(key: str) -> str:
    """Render a compact human-facing key chord."""
    return "+".join(
        part.title() if len(part) > 1 else part.upper() for part in key.split("+")
    )
