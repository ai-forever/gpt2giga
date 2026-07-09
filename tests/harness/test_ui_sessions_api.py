import base64
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.project import project_id_for_root
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry
from gpt2giga.harness.sessions import (
    FilesystemHarnessSessionStore,
    InMemoryHarnessSessionStore,
)
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga.harness.ui.app import create_app


def test_sessions_api_create_list_get_update_delete():
    client = _client()

    created = client.post(
        "/api/sessions",
        json={"title": "API smoke", "harness_id": "echo", "api_mode": "v2"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["id"]

    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["sessions"]] == [session_id]

    fetched = client.get(f"/api/sessions/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["session"]["title"] == "API smoke"

    patched = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "Renamed", "pinned": True},
    )
    assert patched.status_code == 200
    assert patched.json()["session"]["title"] == "Renamed"
    assert patched.json()["session"]["pinned"] is True

    deleted = client.delete(f"/api/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_sessions_api_filters_by_project_id(tmp_path):
    client = _client()
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    first = client.post(
        "/api/sessions",
        json={
            "title": "First project",
            "harness_id": "echo",
            "workspace": str(first_workspace),
        },
    )
    second = client.post(
        "/api/sessions",
        json={
            "title": "Second project",
            "harness_id": "echo",
            "workspace": str(second_workspace),
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get(
        "/api/sessions",
        params={"project_id": project_id_for_root(first_workspace)},
    )

    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert [session["id"] for session in sessions] == [first.json()["session"]["id"]]
    assert sessions[0]["project"]["id"] == project_id_for_root(first_workspace)


def test_sessions_api_create_and_run_echo_then_continue():
    client = _client()

    first = client.post(
        "/api/sessions/run",
        json={"harness_id": "echo", "prompt": "hello", "api_mode": "v2"},
    )
    assert first.status_code == 200
    body = first.json()
    session_id = body["session"]["id"]
    assert body["result"]["text"] == "hello"
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]

    second = client.post(
        f"/api/sessions/{session_id}/run",
        json={"prompt": "again", "harness_id": "echo"},
    )
    assert second.status_code == 200
    assert second.json()["result"]["text"] == "again"
    assert len(second.json()["messages"]) == 4


def test_sessions_api_events_polling_after_id():
    client = _client()
    first = client.post(
        "/api/sessions/run",
        json={"harness_id": "echo", "prompt": "hello"},
    ).json()
    session_id = first["session"]["id"]
    first_event_id = first["events"][0]["id"]

    response = client.get(
        f"/api/sessions/{session_id}/events?after_id={first_event_id}"
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["id"] != first_event_id


def test_sessions_api_start_run_returns_stream_urls_and_sse_replay():
    client = _client()

    started = client.post(
        "/api/sessions/run/start",
        json={"harness_id": "echo", "prompt": "hello", "stream": True},
    )

    assert started.status_code == 200
    body = started.json()
    assert body["run"]["id"].startswith("run_")
    assert body["stream_url"] == f"/api/runs/{body['run']['id']}/events/stream"
    assert body["cancel_url"] == f"/api/runs/{body['run']['id']}/cancel"

    with client.stream("GET", body["stream_url"]) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    assert "run_started" in text
    assert "run_finished" in text


def test_preflight_api_reports_large_attachment_warning(tmp_path):
    data_dir = tmp_path / "data"
    client = _client(
        config=HarnessConfig(data_dir=str(data_dir)),
        store=FilesystemHarnessSessionStore(data_dir),
    )
    created = client.post(
        "/api/sessions",
        json={"title": "Preflight", "harness_id": "echo"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["id"]
    payload = base64.b64encode(b"a" * 1_000_001).decode("ascii")
    attachment = client.post(
        f"/api/sessions/{session_id}/attachments",
        json={
            "filename": "large.txt",
            "mime_type": "text/plain",
            "data_base64": payload,
        },
    )
    assert attachment.status_code == 200
    attachment_id = attachment.json()["attachment"]["id"]

    response = client.post(
        "/api/preflight/run",
        json={
            "session_id": session_id,
            "harness_id": "echo",
            "prompt": "review",
            "attachment_ids": [attachment_id],
        },
    )

    assert response.status_code == 200
    preflight = response.json()["preflight"]
    assert preflight["hard_block"] is False
    assert preflight["context_budget"]["attached_file_bytes"] == 1_000_001
    finding = next(
        item for item in preflight["findings"] if item["code"] == "large_attachment"
    )
    assert finding["severity"] == "warning"
    assert "continue" in finding["actions"]
    assert "exclude_attachment" in finding["actions"]


def test_preflight_api_hard_blocks_private_key_prompt_without_echoing_secret():
    client = _client()
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    response = client.post(
        "/api/preflight/run",
        json={"harness_id": "echo", "prompt": prompt},
    )

    assert response.status_code == 200
    preflight = response.json()["preflight"]
    assert preflight["hard_block"] is True
    assert "private_key_material" in {
        finding["code"] for finding in preflight["findings"]
    }
    assert "not-real-secret" not in response.text


def test_sessions_api_blocks_private_key_prompt_before_run():
    client = _client()
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    response = client.post(
        "/api/sessions/run",
        json={"harness_id": "echo", "prompt": prompt},
    )

    assert response.status_code == 400
    assert "Preflight blocked" in response.json()["detail"]
    assert "not-real-secret" not in response.text


def test_sessions_api_cancel_active_headless_run():
    store = InMemoryHarnessSessionStore()
    registry = HarnessRegistry()
    registry.register(_CancellableHarness())
    client = _client(registry=registry, store=store)

    started = client.post(
        "/api/sessions/run/start",
        json={"harness_id": "slow", "prompt": "wait", "stream": True},
    )
    assert started.status_code == 200
    body = started.json()
    run_id = body["run"]["id"]
    session_id = body["session"]["id"]

    canceled = client.post(f"/api/runs/{run_id}/cancel")

    assert canceled.status_code == 200
    assert canceled.json()["cancel_requested"] is True
    for _ in range(100):
        bundle = client.get(f"/api/sessions/{session_id}").json()
        run = bundle["runs"][-1]
        if run["status"] == "canceled":
            break
        time.sleep(0.02)
    assert run["status"] == "canceled"
    event_types = {event["type"] for event in bundle["events"]}
    assert {"cancel_requested", "run_canceled", "run_finished"} <= event_types


def test_arena_api_creates_child_runs_without_shared_history(tmp_path):
    store = InMemoryHarnessSessionStore()
    first = _ArenaCaptureHarness("arena-first")
    second = _ArenaCaptureHarness("arena-second")
    registry = HarnessRegistry()
    registry.register(first)
    registry.register(second)
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
        store=store,
    )

    response = client.post(
        "/api/arena/runs",
        json={
            "prompt": "compare this",
            "harness_ids": ["arena-first", "arena-second"],
            "api_mode": "v2",
            "mode": "plan",
        },
    )

    assert response.status_code == 200
    arena = response.json()["arena"]
    assert arena["status"] == "succeeded"
    assert arena["session"]["id"] == arena["session_id"]
    assert [child["harness_id"] for child in arena["child_runs"]] == [
        "arena-first",
        "arena-second",
    ]
    assert all(child["run_id"].startswith("run_") for child in arena["child_runs"])
    assert [request.prompt for request in first.requests] == ["compare this"]
    assert [request.prompt for request in second.requests] == ["compare this"]
    assert [
        (message.role, message.content) for message in first.requests[0].messages
    ] == [("user", "compare this")]
    assert [
        (message.role, message.content) for message in second.requests[0].messages
    ] == [("user", "compare this")]

    fetched = client.get(f"/api/arena/runs/{arena['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["arena"]["id"] == arena["id"]


def test_arena_api_child_failure_does_not_stop_remaining_harnesses(tmp_path):
    store = InMemoryHarnessSessionStore()
    succeeding = _ArenaCaptureHarness("arena-ok")
    registry = HarnessRegistry()
    registry.register(_FailingArenaHarness())
    registry.register(succeeding)
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
        store=store,
    )

    response = client.post(
        "/api/arena/runs",
        json={
            "prompt": "compare failures",
            "harness_ids": ["arena-fail", "arena-ok"],
        },
    )

    assert response.status_code == 200
    arena = response.json()["arena"]
    assert arena["status"] == "partial"
    assert [child["status"] for child in arena["child_runs"]] == [
        "failed",
        "succeeded",
    ]
    assert succeeding.requests[0].prompt == "compare failures"


def test_arena_events_stream_replays_child_events(tmp_path):
    registry = HarnessRegistry()
    registry.register(_ArenaCaptureHarness("arena-stream"))
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
        store=InMemoryHarnessSessionStore(),
    )
    created = client.post(
        "/api/arena/runs",
        json={"prompt": "stream arena", "harness_ids": ["arena-stream"]},
    )
    assert created.status_code == 200
    arena_id = created.json()["arena"]["id"]

    with client.stream("GET", f"/api/arena/runs/{arena_id}/events/stream") as stream:
        assert stream.status_code == 200
        text = "".join(stream.iter_text())

    assert arena_id in text
    assert "arena-stream" in text
    assert "run_started" in text
    assert "run_finished" in text


def test_runs_api_diff_apply_and_open_worktree(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    registry = HarnessRegistry()
    registry.register(_FileEditHarness())
    client = _client(
        config=HarnessConfig(
            default_model="ConfiguredModel",
            data_dir=str(tmp_path / "data"),
        ),
        registry=registry,
    )

    response = client.post(
        "/api/sessions/run",
        json={
            "harness_id": "edit-file",
            "prompt": "change file",
            "mode": "edit",
            "workspace": str(repo),
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_id = body["run"]["id"]
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"

    diff = client.get(f"/api/runs/{run_id}/diff")

    assert diff.status_code == 200
    diff_body = diff.json()["diff"]
    assert diff_body["can_apply"] is True
    assert diff_body["workspace_execution"]["policy"] == "worktree"
    assert "app.txt" in diff_body["changed_files"]
    assert "diff --git a/app.txt b/app.txt" in diff_body["patch"]

    opened = client.post(f"/api/runs/{run_id}/open-worktree")
    assert opened.status_code == 200
    assert opened.json()["worktree"]["exists"] is True

    applied = client.post(f"/api/runs/{run_id}/apply", json={})

    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    assert applied.json()["diff"]["can_apply"] is False
    assert (repo / "app.txt").read_text(encoding="utf-8") == "changed\n"


def test_runs_api_discard_removes_worktree_without_touching_repo(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    registry = HarnessRegistry()
    registry.register(_FileEditHarness())
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
    )

    response = client.post(
        "/api/sessions/run",
        json={
            "harness_id": "edit-file",
            "prompt": "change file",
            "mode": "edit",
            "workspace": str(repo),
        },
    )
    assert response.status_code == 200
    run = response.json()["run"]
    worktree_path = Path(run["metadata"]["workspace_execution"]["worktree_path"])
    assert worktree_path.exists()

    discarded = client.post(f"/api/runs/{run['id']}/discard")

    assert discarded.status_code == 200
    assert discarded.json()["discarded"] is True
    assert discarded.json()["diff"]["can_discard"] is False
    assert not worktree_path.exists()
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"


def test_runs_api_pr_artifact_patch_and_branch_creation(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    registry = HarnessRegistry()
    registry.register(_FileEditHarness())
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
    )
    response = client.post(
        "/api/sessions/run",
        json={
            "harness_id": "edit-file",
            "prompt": "change file",
            "mode": "edit",
            "workspace": str(repo),
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run"]["id"]

    artifact = client.get(f"/api/runs/{run_id}/pr")

    assert artifact.status_code == 200
    pr_artifact = artifact.json()["pr_artifact"]
    assert pr_artifact["title"] == "Update app.txt"
    assert "edited" in pr_artifact["body"]
    assert pr_artifact["changed_files"] == ["app.txt"]
    assert "diff --git a/app.txt b/app.txt" in pr_artifact["patch"]

    patch = client.get(f"/api/runs/{run_id}/patch")
    assert patch.status_code == 200
    assert "diff --git a/app.txt b/app.txt" in patch.text

    branched = client.post(
        f"/api/runs/{run_id}/branch",
        json={"branch_name": "codex/pr-artifact-test"},
    )

    assert branched.status_code == 200
    assert branched.json()["branch_created"] is True
    assert branched.json()["branch_name"] == "codex/pr-artifact-test"
    assert branched.json()["pr_artifact"]["applied_branch"] == "codex/pr-artifact-test"
    assert _git_output(repo, "branch", "--show-current") == "codex/pr-artifact-test"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "changed\n"


def test_runs_api_provenance_replay_and_fork():
    client = _client()
    response = client.post(
        "/api/sessions/run",
        json={"harness_id": "echo", "prompt": "hello provenance"},
    )
    assert response.status_code == 200
    body = response.json()
    session_id = body["session"]["id"]
    run_id = body["run"]["id"]

    provenance = client.get(f"/api/runs/{run_id}/provenance")

    assert provenance.status_code == 200
    provenance_body = provenance.json()["provenance"]
    assert provenance_body["run_id"] == run_id
    assert provenance_body["request"]["prompt"] == "hello provenance"
    assert provenance_body["replay_request"]["prompt"] == "hello provenance"
    assert provenance_body["replay_request"]["extra"]["isolated_history"] is True

    replay = client.post(f"/api/runs/{run_id}/replay")

    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["source_run"]["id"] == run_id
    assert replay_body["result"]["text"] == "hello provenance"
    assert replay_body["run"]["metadata"]["provenance"]["request"]["prompt"] == (
        "hello provenance"
    )
    assert replay_body["session"]["id"] == session_id

    fork = client.post(f"/api/runs/{run_id}/fork")

    assert fork.status_code == 200
    fork_body = fork.json()
    assert fork_body["source_run"]["id"] == run_id
    assert fork_body["session"]["id"] != session_id
    assert fork_body["bundle"]["messages"][0]["content"] == "hello provenance"
    assert fork_body["bundle"]["session"]["metadata"]["forked_from_run_id"] == run_id


def _client(
    *,
    config: HarnessConfig | None = None,
    registry: HarnessRegistry | None = None,
    store: InMemoryHarnessSessionStore | None = None,
) -> TestClient:
    app = create_app(
        config or HarnessConfig(default_model="ConfiguredModel"),
        registry=registry or create_default_registry(include_entry_points=False),
        store=store or InMemoryHarnessSessionStore(),
    )
    return TestClient(app)


class _CancellableHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="slow",
            title="Slow",
            kind="test",
            description="Slow cancellable harness",
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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            cancel_event = request.cancel_event
            if cancel_event is not None and cancel_event.is_set():
                return HarnessResult(ok=False, text="", error="cancelled")
            time.sleep(0.01)
        return HarnessResult(ok=True, text="finished")


class _ArenaCaptureHarness(BaseHarness):
    def __init__(self, harness_id: str) -> None:
        self.harness_id = harness_id
        self.requests: list[HarnessRequest] = []

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=f"Arena {self.harness_id}",
            kind="test",
            description="Capture arena request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
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
            text=f"{self.harness_id}: {request.prompt}",
            raw={"harness_id": self.harness_id},
        )


class _FailingArenaHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="arena-fail",
            title="Arena Fail",
            kind="test",
            description="Fail arena request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=False, text="", error="arena boom")


class _FileEditHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="edit-file",
            title="Edit File",
            kind="agent-cli",
            description="Edit a file in the workspace",
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


def _git_output(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(cwd), *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
