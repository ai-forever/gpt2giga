import subprocess
from pathlib import Path

import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.preflight import PreflightBlockedError
from gpt2giga_harness.project import project_id_for_root, resolve_project
from gpt2giga_harness.project_memory import FilesystemProjectMemoryStore
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.sessions.models import HarnessMessage
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.types import (
    Availability,
    GigaChatBuiltinTool,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    emit_event,
)


def test_session_runner_create_and_run_persists_success():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "hello",
            "api_mode": "v2",
            "mode": "plan",
        }
    )
    bundle = result.bundle

    assert result.result.ok is True
    assert bundle.session.title == "hello"
    assert [message.role for message in bundle.messages] == ["user", "assistant"]
    assert bundle.messages[-1].content == "answer: hello"
    assert bundle.runs[0].status == "succeeded"
    assert bundle.raw_requests
    assert bundle.raw_responses
    assert {event.type for event in bundle.events} >= {
        "run_started",
        "raw_request",
        "raw_response",
        "message_completed",
        "run_finished",
    }
    assert result.run.metadata["preflight"]["ok"] is True
    assert result.run.metadata["preflight"]["context_budget"]["prompt_chars"] == 5
    assert bundle.raw_requests[0].payload["preflight"]["ok"] is True


def test_session_runner_blocks_private_key_before_harness_invocation():
    harness = _CaptureHarness()
    runner = _runner(harness)
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    with pytest.raises(PreflightBlockedError) as exc_info:
        runner.create_and_run({"harness_id": "capture", "prompt": prompt})

    assert harness.last_request is None
    assert "private_key_material" in str(exc_info.value)


def test_session_runner_passes_and_records_selected_builtin_tools():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "search",
            "api_mode": "v2",
            "builtin_tools": ["web_search"],
        }
    )

    assert harness.last_request is not None
    assert harness.last_request.builtin_tools == (GigaChatBuiltinTool.WEB_SEARCH,)
    assert result.bundle.raw_requests[0].payload["builtin_tools"] == ["web_search"]
    assert result.run.metadata["builtin_tools"] == ["web_search"]


def test_session_runner_rejects_builtin_tools_for_v1():
    runner = _runner(_CaptureHarness())

    with pytest.raises(ValueError, match="/v2/chat/completions"):
        runner.create_and_run(
            {
                "harness_id": "capture",
                "prompt": "search",
                "api_mode": "v1",
                "builtin_tools": ["web_search"],
            }
        )


def test_managed_mcp_snapshot_is_bound_to_provenance_and_reused_for_replay(tmp_path):
    workspace = tmp_path / "project"
    config_path = workspace / ".giga" / "harness.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[tools.issues]
enabled = true
kind = "mcp"
transport = "stdio"
command = "issue-mcp-v1"
trusted = true
harnesses = ["codex-cli"]
""",
        encoding="utf-8",
    )
    harness = _ManagedCaptureHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")

    first = runner.create_and_run(
        {
            "harness_id": "codex-cli",
            "prompt": "inspect issues",
            "workspace": str(workspace),
            "extra": {"tool_ids": ["issues"]},
        }
    )
    first_ref = harness.requests[-1].extra["managed_mcp_snapshot"]
    replay_request = first.run.metadata["provenance"]["replay_request"]

    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("issue-mcp-v1", "issue-mcp-v2"),
        encoding="utf-8",
    )
    second = runner.run_in_session(first.session.id, replay_request)
    second_ref = harness.requests[-1].extra["managed_mcp_snapshot"]

    assert first_ref["snapshot_id"] == second_ref["snapshot_id"]
    assert first_ref["snapshot_hash"] == second_ref["snapshot_hash"]
    assert first.run.metadata["managed_mcp_snapshot"] == first_ref
    assert second.run.metadata["managed_mcp_snapshot"] == second_ref
    assert (
        second.run.metadata["provenance"]["execution"]["managed_mcp_snapshot"][
            "snapshot_id"
        ]
        == first_ref["snapshot_id"]
    )
    snapshot_path = (
        tmp_path
        / "data"
        / "tools"
        / "headless_mcp_snapshots"
        / f"{first_ref['snapshot_id']}.json"
    )
    snapshot_content = snapshot_path.read_text(encoding="utf-8")
    assert "issue-mcp-v1" in snapshot_content
    assert "issue-mcp-v2" not in snapshot_content


def test_session_runner_failed_harness_stores_error_message():
    runner = _runner(_FailingHarness())

    result = runner.create_and_run({"harness_id": "fail", "prompt": "hello"})

    assert result.run.status == "failed"
    assert result.bundle.messages[-1].role == "error"
    assert result.bundle.messages[-1].content == "boom"


def test_session_runner_deduplicates_live_usage_and_merges_partial_metadata():
    runner = _runner(_StreamingHarness())

    result = runner.create_and_run(
        {"harness_id": "streaming", "prompt": "hello", "stream": True}
    )

    usage_events = [event for event in result.bundle.events if event.type == "usage"]
    assert [event.payload for event in usage_events] == [
        {"input_tokens": 8, "source": "test"},
        {"output_tokens": 3, "source": "test"},
    ]
    expected_usage = {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
        "source": "test",
    }
    assert result.run.metadata["usage"] == expected_usage
    assert result.bundle.messages[-1].metadata["usage"] == expected_usage


def test_session_runner_updates_session_defaults_before_terminal_event():
    store = _TerminalOrderingStore()
    runner = _runner(_CaptureHarness(), store=store)
    session = runner.create_session(default_harness_id="echo")

    runner.run_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "hello", "stream": True},
    )

    assert store.harness_at_run_finished == "capture"


def test_session_runner_passes_previous_messages_to_chat_harness():
    harness = _CaptureHarness()
    runner = _runner(harness)
    first = runner.create_and_run({"harness_id": "capture", "prompt": "first"})

    runner.run_in_session(first.session.id, {"prompt": "second"})

    assert harness.last_request is not None
    assert [
        (message.role, message.content) for message in harness.last_request.messages
    ] == [
        ("user", "first"),
        ("assistant", "answer: first"),
        ("user", "second"),
    ]


def test_queued_turn_waits_for_preceding_assistant_in_request_history():
    store = InMemoryHarnessSessionStore()
    harness = _CaptureHarness()
    runner = _runner(harness, store=store)
    session = runner.create_session(default_harness_id="capture")
    first_run = store.create_run(
        session_id=session.id,
        harness_id="capture",
        prompt="first",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=session.workspace,
        status="running",
    )
    store.append_message(
        HarnessMessage(
            id=new_id("msg"),
            session_id=session.id,
            run_id=first_run.id,
            role="user",
            content="first",
            created_at=utc_now(),
        )
    )
    queued = runner.enqueue_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "second"},
        run_id=new_id("run"),
    )
    store.append_message(
        HarnessMessage(
            id=new_id("msg"),
            session_id=session.id,
            run_id=first_run.id,
            role="assistant",
            content="answer: first",
            created_at=utc_now(),
        )
    )

    runner.run_in_session(
        session.id,
        {"harness_id": "capture", "prompt": "second"},
        existing_run_id=queued.run.id,
        user_message_id=queued.user_message.id,
    )

    assert harness.last_request is not None
    assert [
        (message.role, message.content) for message in harness.last_request.messages
    ] == [
        ("user", "first"),
        ("assistant", "answer: first"),
        ("user", "second"),
    ]


def test_session_runner_create_session_records_project_metadata(tmp_path):
    runner = _runner(_CaptureHarness(), data_dir=tmp_path / "data")

    session = runner.create_session(workspace=str(tmp_path))

    assert session.workspace == str(tmp_path)
    assert session.metadata["project_id"] == project_id_for_root(tmp_path)
    assert session.metadata["project_root"] == str(tmp_path)
    assert session.metadata["project_name"] == tmp_path.name


def test_session_runner_updates_legacy_session_project_metadata(tmp_path):
    store = InMemoryHarnessSessionStore()
    legacy = store.create_session(title="legacy", default_harness_id="capture")
    runner = _runner(_CaptureHarness(), store=store, data_dir=tmp_path / "data")

    result = runner.run_in_session(
        legacy.id,
        {
            "prompt": "hello",
            "workspace": str(tmp_path),
        },
    )

    assert result.session.metadata["project_id"] == project_id_for_root(tmp_path)
    assert result.session.metadata["project_root"] == str(tmp_path)


def test_session_runner_persists_invocation_mode_metadata():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "hello",
            "invocation_mode": "native",
        }
    )

    assert harness.last_request is not None
    assert harness.last_request.invocation_mode is HarnessInvocationMode.NATIVE
    assert result.run.invocation_mode is HarnessInvocationMode.NATIVE
    assert result.run.metadata["invocation_mode"] == "native"
    assert result.bundle.runs[0].invocation_mode is HarnessInvocationMode.NATIVE
    assert result.bundle.raw_requests[0].payload["invocation_mode"] == "native"


def test_session_runner_injects_enabled_project_memory(tmp_path):
    harness = _CaptureHarness()
    data_dir = tmp_path / "data"
    project = resolve_project(tmp_path, data_dir=data_dir)
    memory_store = FilesystemProjectMemoryStore()
    enabled = memory_store.add(
        project,
        text="Use Alembic migrations",
        tags=("decision",),
    )
    disabled = memory_store.add(
        project,
        text="Do not include this",
        enabled=False,
    )
    runner = _runner(harness, data_dir=data_dir, memory_store=memory_store)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "plan database change",
            "workspace": str(tmp_path),
        }
    )

    assert harness.last_request is not None
    assert "Project memory to honor for this run" in harness.last_request.prompt
    assert "Use Alembic migrations" in harness.last_request.prompt
    assert "Do not include this" not in harness.last_request.prompt
    memory = result.run.metadata["project_memory"]
    assert memory["count"] == 1
    assert memory["entries"][0]["id"] == enabled.id
    assert disabled.id not in str(result.bundle.raw_requests[0].payload)
    assert result.bundle.raw_requests[0].payload["original_prompt"] == (
        "plan database change"
    )
    provenance = result.run.metadata["provenance"]
    assert provenance["request"]["prompt"] == "plan database change"
    assert provenance["request"]["prompt_was_augmented"] is True
    assert provenance["request"]["project_memory"]["count"] == 1
    assert provenance["replay_request"]["prompt"] == "plan database change"
    assert provenance["replay_request"]["extra"]["isolated_history"] is True
    assert provenance["project"]["id"] == project.id


def test_session_runner_defaults_agent_edit_to_isolated_worktree(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    harness = _WorkspaceEditHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")

    result = runner.create_and_run(
        {
            "harness_id": "edit-workspace",
            "prompt": "change it",
            "mode": "edit",
            "workspace": str(repo),
        }
    )

    assert harness.last_request is not None
    assert harness.last_request.workspace != str(repo)
    assert result.run.workspace == str(repo)
    workspace_execution = result.run.metadata["workspace_execution"]
    assert workspace_execution["requested_policy"] == "auto"
    assert workspace_execution["policy"] == "worktree"
    assert workspace_execution["source_git_root"] == str(repo)
    assert workspace_execution["effective_workspace"] == harness.last_request.workspace
    assert "app.txt" in workspace_execution["changed_files"]
    assert "diff --git a/app.txt b/app.txt" in workspace_execution["patch"]
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"


def test_session_runner_edit_fails_closed_for_non_git_workspace(tmp_path):
    workspace = tmp_path / "plain"
    workspace.mkdir()
    (workspace / "app.txt").write_text("base\n", encoding="utf-8")
    harness = _WorkspaceEditHarness()
    runner = _runner(harness, data_dir=tmp_path / "data")

    with pytest.raises(ValueError, match="requires a Git repository"):
        runner.create_and_run(
            {
                "harness_id": "edit-workspace",
                "prompt": "change it",
                "mode": "edit",
                "workspace": str(workspace),
            }
        )

    assert harness.last_request is None
    assert (workspace / "app.txt").read_text(encoding="utf-8") == "base\n"


def _runner(
    harness: BaseHarness,
    *,
    store: InMemoryHarnessSessionStore | None = None,
    data_dir=None,
    memory_store: FilesystemProjectMemoryStore | None = None,
) -> HarnessSessionRunner:
    registry = HarnessRegistry()
    registry.register(harness)
    return HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(data_dir) if data_dir is not None else "~/.gpt2giga/harness",
        ),
        store=store or InMemoryHarnessSessionStore(),
        memory_store=memory_store,
    )


class _CaptureHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture",
            title="Capture",
            kind="test",
            description="Capture request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supported_builtin_tools=(GigaChatBuiltinTool.WEB_SEARCH,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(
            ok=True,
            text=f"answer: {request.prompt}",
            raw={"request_id": "ok"},
            command=("capture", request.prompt),
        )


class _ManagedCaptureHarness(BaseHarness):
    def __init__(self) -> None:
        self.requests: list[HarnessRequest] = []

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Managed capture",
            kind="agent-cli",
            description="Capture managed MCP snapshots",
            capabilities=(HarnessCapability.AGENT_CLI,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.requests.append(request)
        return HarnessResult(
            ok=True,
            text="captured",
            raw={"managed_mcp_snapshot": request.extra["managed_mcp_snapshot"]},
            command=("capture-managed",),
        )


class _FailingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="fail",
            title="Fail",
            kind="test",
            description="Fail request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=False, text="", error="boom")


class _StreamingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="streaming",
            title="Streaming",
            kind="test",
            description="Emit live events",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_streaming=True,
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        events = (
            HarnessEvent(
                type="message_delta",
                message="Assistant message delta.",
                payload={"delta": "answer"},
            ),
            HarnessEvent(
                type="usage",
                message="Token usage updated.",
                payload={
                    "input_tokens": 8,
                    "source": "test",
                },
            ),
            HarnessEvent(
                type="usage",
                message="Token usage updated.",
                payload={
                    "output_tokens": 3,
                    "source": "test",
                },
            ),
        )
        for event in events:
            emit_event(request, event)
        return HarnessResult(ok=True, text="answer", events=events)


class _TerminalOrderingStore(InMemoryHarnessSessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.harness_at_run_finished: str | None = None

    def append_event(self, event):
        if event.type == "run_finished":
            self.harness_at_run_finished = self.get_session(
                event.session_id
            ).default_harness_id
        return super().append_event(event)


class _WorkspaceEditHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="edit-workspace",
            title="Edit Workspace",
            kind="agent-cli",
            description="Edit a workspace file",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        workspace = Path(request.workspace or "")
        (workspace / "app.txt").write_text("changed\n", encoding="utf-8")
        return HarnessResult(ok=True, text="edited")


def _git_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "app.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "app.txt")
    _git(path, "commit", "-m", "initial")
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-C", str(cwd), *args),
        check=True,
        capture_output=True,
        text=True,
    )
