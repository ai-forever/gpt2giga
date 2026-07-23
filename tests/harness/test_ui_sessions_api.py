import base64
import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobWorker
from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    InMemoryHarnessSessionStore,
)
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import utc_now
from gpt2giga_harness.types import (
    Availability,
    GigaChatApiMode,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    HarnessEventType,
)
from gpt2giga_harness.ui.app import create_app


def _sse_frames(text: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for block in text.split("\n\n"):
        lines = block.splitlines()
        event_id = next(
            (line.removeprefix("id: ") for line in lines if line.startswith("id: ")),
            None,
        )
        data = next(
            (
                json.loads(line.removeprefix("data: "))
                for line in lines
                if line.startswith("data: ")
            ),
            None,
        )
        if event_id is not None and isinstance(data, dict):
            frames.append({"id": event_id, "data": data})
    return frames


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


def test_session_navigation_api_binds_revision_and_replays_idempotently():
    client = _client()
    created = client.post(
        "/api/sessions",
        json={"title": "Bound session", "harness_id": "echo"},
    ).json()["session"]
    session_id = created["id"]
    store = client.app.state.harness_session_store
    store.update_session(
        session_id,
        metadata={
            "project_id": "project-bound",
            "native_session_reference": {
                "authority": "codex",
                "native_id": "thread-bound",
                "operation": "resume",
                "revision": 7,
            },
        },
    )
    summary = client.get(f"/api/sessions/{session_id}/navigation-preview").json()[
        "session"
    ]
    binding = {
        "session_revision": summary["session_revision"],
        "session_generation": summary["session_generation"],
        "session_lease": summary["session_lease"],
        "idempotency_key": "rename-bound-once",
    }

    first = client.post(
        f"/api/sessions/{session_id}/navigation-update",
        json={**binding, "title": "Renamed once"},
    )
    replay = client.post(
        f"/api/sessions/{session_id}/navigation-update",
        json={**binding, "title": "Different retry payload"},
    )
    stale = client.post(
        f"/api/sessions/{session_id}/navigation-update",
        json={**binding, "idempotency_key": "stale-binding", "title": "Lost"},
    )

    assert first.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["session"]["native_session_reference"] == {
        "authority": "codex",
        "native_id": "thread-bound",
        "operation": "resume",
        "revision": 7,
    }
    assert stale.status_code == 409
    assert "resnapshot" in stale.json()["detail"]


def test_session_navigation_export_never_derives_paths_from_request_data(tmp_path):
    data_dir = tmp_path / "data"
    client = _client(config=HarnessConfig(data_dir=str(data_dir)))
    created = client.post(
        "/api/sessions",
        json={"title": "Safe export", "harness_id": "echo"},
    ).json()["session"]
    session_id = created["id"]
    summary = client.get(f"/api/sessions/{session_id}/navigation-preview").json()[
        "session"
    ]
    binding = {
        "session_revision": summary["session_revision"],
        "session_generation": summary["session_generation"],
        "session_lease": summary["session_lease"],
        "idempotency_key": "../../outside-export",
    }

    response = client.post(
        f"/api/sessions/{session_id}/navigation-export", json=binding
    )
    replay = client.post(f"/api/sessions/{session_id}/navigation-export", json=binding)

    assert response.status_code == 200
    assert replay.json() == response.json()
    path = Path(response.json()["export"]["path"])
    assert path.parent == data_dir / "exports"
    assert path.name.startswith("session-")
    assert path.suffix == ".md"
    assert path.is_file()
    assert not (tmp_path / "outside-export").exists()


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


def test_interactive_run_actions_reject_stale_binding_and_missing_owner():
    client = _client()
    completed = client.post(
        "/api/sessions/run",
        json={"harness_id": "echo", "prompt": "binding"},
    ).json()
    run_id = completed["run"]["id"]
    session_id = completed["session"]["id"]
    projection = client.get(f"/api/cockpit/runs/{run_id}").json()
    binding = {
        "run_id": run_id,
        "session_id": session_id,
        "revision": projection["snapshot_revision"],
        "generation": 1,
        "idempotency_key": "tui_action_1",
    }

    stale = client.post(
        f"/api/runs/{run_id}/steer",
        json={**binding, "revision": "0" * 64, "content": "stale"},
    )
    owner_lost = client.post(
        f"/api/runs/{run_id}/steer",
        json={**binding, "content": "continue"},
    )
    unsupported_input = client.post(
        f"/api/runs/{run_id}/input",
        json={**binding, "input_id": "input_1", "answer": "yes"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "Run revision changed"
    assert owner_lost.status_code == 409
    assert "owner is unavailable" in owner_lost.json()["detail"]
    assert unsupported_input.status_code == 409
    assert "does not expose" in unsupported_input.json()["detail"]


def test_session_update_stream_replays_title_revision_and_closes_on_delete():
    store = _ObservedSessionUpdateStore()
    session = store.create_session()
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="title",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
    )
    updated = store.update_session(session.id, title="Generated title")
    store.append_event(
        HarnessStoredEvent(
            id="evt-title",
            session_id=session.id,
            run_id=run.id,
            type="session.updated",
            message="Session title revision stored.",
            payload={
                "session_id": session.id,
                "revision": updated.updated_at,
                "changed_fields": ["title"],
            },
            created_at=utc_now(),
        )
    )
    client = _client(store=store)
    result: dict[str, object] = {}

    def consume() -> None:
        with client.stream(
            "GET",
            f"/api/cockpit/sessions/{session.id}/updates/stream?tail_only=false",
        ) as response:
            result["status"] = response.status_code
            result["text"] = "".join(response.iter_text())

    thread = threading.Thread(target=consume)
    thread.start()
    assert store.title_revision_read.wait(timeout=2)
    store.delete_session(session.id)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert result["status"] == 200
    frames = _sse_frames(str(result["text"]))
    assert [frame["data"]["type"] for frame in frames] == [
        "session.snapshot",
        "session.updated",
    ]
    assert frames[0]["data"]["payload"]["session"]["title"] == "Generated title"
    assert "title" not in frames[1]["data"]["payload"]


def test_sessions_api_start_run_returns_stream_urls_and_sse_replay():
    client = _client()

    started = client.post(
        "/api/sessions/run/start",
        json={"harness_id": "echo", "prompt": "hello", "stream": True},
    )

    assert started.status_code == 200
    body = started.json()
    assert body["run"]["id"].startswith("run_")
    assert body["run"]["metadata"]["execution_transport"] == "one_shot"
    assert body["stream_url"] == f"/api/runs/{body['run']['id']}/events/stream"
    assert body["cancel_url"] == f"/api/runs/{body['run']['id']}/cancel"

    with client.stream("GET", body["stream_url"]) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    assert "run_started" in text
    assert "run_finished" in text


def test_headless_run_uses_title_model_from_settings(tmp_path, monkeypatch):
    captured = {}
    requested = threading.Event()

    def request_json(method, url, *, payload, api_key, timeout):
        captured["model"] = payload["model"]
        requested.set()
        return {"choices": [{"message": {"content": "Generated title"}}]}

    monkeypatch.setattr(
        "gpt2giga_harness.session_runner.proxy.request_json",
        request_json,
    )
    client = _client(
        config=HarnessConfig(
            default_model="ConfiguredChatModel",
            data_dir=str(tmp_path / "data"),
        )
    )
    saved = client.patch(
        "/api/settings/defaults",
        json={"defaults": {"default_title_model": "SelectedTitleModel"}},
    )
    assert saved.status_code == 200
    session = client.post("/api/sessions", json={"harness_id": "echo"}).json()[
        "session"
    ]

    started = client.post(
        f"/api/sessions/{session['id']}/run/start",
        json={
            "harness_id": "echo",
            "prompt": "Generate a selected title",
            "extra": {"generate_session_title": True},
        },
    )

    assert started.status_code == 200
    assert requested.wait(timeout=2)
    assert captured["model"] == "SelectedTitleModel"


def test_sessions_api_marks_durable_ui_turns_interactive(tmp_path):
    data_dir = tmp_path / "data"
    config = HarnessConfig(data_dir=str(data_dir))
    store = FilesystemHarnessSessionStore(data_dir)
    runtime = RuntimeCoordinationStore(data_dir)
    client = TestClient(
        create_app(
            config,
            registry=create_default_registry(include_entry_points=False),
            store=store,
            runtime_store=runtime,
        )
    )
    session = client.post(
        "/api/sessions",
        json={"title": "Queued chat", "harness_id": "echo"},
    ).json()["session"]

    started = client.post(
        f"/api/sessions/{session['id']}/run/start",
        json={"harness_id": "echo", "prompt": "first"},
    )

    assert started.status_code == 200
    job = runtime.find_job_for_run(started.json()["run"]["id"])
    assert job is not None
    assert job.origin == "interactive"


def test_run_event_stream_synthesizes_terminal_event_for_legacy_run():
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Legacy terminal run")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="succeeded",
    )
    client = _client(store=store)

    with client.stream("GET", f"/api/runs/{run.id}/events/stream") as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    assert '"type": "run_finished"' in text
    assert '"status": "succeeded"' in text
    assert '"synthetic": true' in text


def test_run_event_stream_tail_only_skips_history_and_closes_with_terminal():
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Bounded live tail")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="succeeded",
    )
    store.append_event(
        HarnessStoredEvent(
            id="evt-retained-terminal",
            session_id=session.id,
            run_id=run.id,
            type=HarnessEventType.RUN_FINISHED.value,
            message="retained terminal",
            payload={"status": "succeeded"},
            created_at=utc_now(),
        )
    )
    client = _client(store=store)

    with client.stream(
        "GET",
        f"/api/runs/{run.id}/events/stream?tail_only=true",
    ) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    frames = _sse_frames(text)
    assert [frame["data"]["id"] for frame in frames] == [f"evt_terminal_{run.id}"]
    assert frames[0]["data"]["payload"]["synthetic"] is True


@pytest.mark.parametrize("api_mode", [GigaChatApiMode.V1, GigaChatApiMode.V2])
def test_run_event_stream_polls_cross_process_filesystem_appends(
    tmp_path,
    api_mode,
):
    config = HarnessConfig(data_dir=str(tmp_path))
    store = FilesystemHarnessSessionStore(tmp_path)
    external_store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(
        title="Cross process stream",
        default_api_mode=api_mode,
    )
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="running",
    )
    client = TestClient(create_app(config, store=store))

    def append_from_worker() -> None:
        time.sleep(0.15)
        external_store.append_event(
            HarnessStoredEvent(
                id="evt-cross-process-delta",
                session_id=session.id,
                run_id=run.id,
                type=HarnessEventType.MESSAGE_DELTA.value,
                message="delta",
                payload={"delta": "streamed"},
                created_at=utc_now(),
            )
        )
        external_store.update_run(run.id, status="succeeded", finished_at=utc_now())
        external_store.append_event(
            HarnessStoredEvent(
                id="evt-cross-process-finished",
                session_id=session.id,
                run_id=run.id,
                type=HarnessEventType.RUN_FINISHED.value,
                message="finished",
                payload={"status": "succeeded"},
                created_at=utc_now(),
            )
        )

    writer = threading.Thread(target=append_from_worker)
    started_at = time.monotonic()
    writer.start()
    with client.stream("GET", f"/api/runs/{run.id}/events/stream") as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())
    writer.join(timeout=1)

    assert time.monotonic() - started_at < 2
    assert [frame["data"]["id"] for frame in _sse_frames(text)] == [
        "evt-cross-process-delta",
        "evt-cross-process-finished",
    ]


def test_run_event_stream_reconnects_from_opaque_cursor_without_gap_or_duplicate():
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Reconnect")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="running",
    )
    for event_id, event_type in (
        ("evt-one", HarnessEventType.RUN_STARTED.value),
        ("evt-two", HarnessEventType.MESSAGE_COMPLETED.value),
        ("evt-three", HarnessEventType.RUN_FINISHED.value),
    ):
        store.append_event(
            HarnessStoredEvent(
                id=event_id,
                session_id=session.id,
                run_id=run.id,
                type=event_type,
                message=event_id,
                payload={"status": "succeeded"},
                created_at=utc_now(),
            )
        )
    store.update_run(run.id, status="succeeded")
    client = _client(store=store)

    with client.stream("GET", f"/api/runs/{run.id}/events/stream") as response:
        first_text = "".join(response.iter_text())

    first_frames = _sse_frames(first_text)
    assert [frame["data"]["id"] for frame in first_frames] == [
        "evt-one",
        "evt-two",
        "evt-three",
    ]
    assert all(frame["id"].startswith("hc1.") for frame in first_frames)

    with client.stream(
        "GET",
        f"/api/runs/{run.id}/events/stream",
        headers={"Last-Event-ID": first_frames[0]["id"]},
    ) as response:
        replay_text = "".join(response.iter_text())

    assert [frame["data"]["id"] for frame in _sse_frames(replay_text)] == [
        "evt-two",
        "evt-three",
    ]


def test_run_event_stream_accepts_legacy_event_id_and_rejects_cross_run_cursor():
    store = InMemoryHarnessSessionStore()
    session = store.create_session(title="Legacy cursor")
    runs = [
        store.create_run(
            session_id=session.id,
            harness_id="echo",
            prompt=f"run {index}",
            model=None,
            api_mode=session.default_api_mode,
            capability=HarnessCapability.CHAT_COMPLETIONS,
            mode="plan",
            workspace=None,
            status="succeeded",
        )
        for index in range(2)
    ]
    for index, run in enumerate(runs):
        store.append_event(
            HarnessStoredEvent(
                id=f"evt-{index}",
                session_id=session.id,
                run_id=run.id,
                type=HarnessEventType.RUN_FINISHED.value,
                message="finished",
                payload={"status": "succeeded"},
                created_at=utc_now(),
            )
        )
    client = _client(store=store)

    with client.stream(
        "GET",
        f"/api/runs/{runs[0].id}/events/stream?after_id=evt-0",
    ) as response:
        assert response.status_code == 200
        assert "".join(response.iter_text()) == ""
    with client.stream("GET", f"/api/runs/{runs[0].id}/events/stream") as response:
        cursor = _sse_frames("".join(response.iter_text()))[0]["id"]

    rejected = client.get(
        f"/api/runs/{runs[1].id}/events/stream",
        headers={"Last-Event-ID": cursor},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "invalid or cross-run event cursor"


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
    assert preflight["readiness"]["plan"]["harness_id"] == "echo"
    assert preflight["readiness"]["plan"]["execution_transport"] == "one_shot"
    assert preflight["readiness"]["plan"]["delivery"] == "durable"
    assert {item["id"] for item in preflight["readiness"]["findings"]} == {
        "harness-echo",
        "invocation-mode",
        "delivery",
        "durable-worker",
    }
    assert preflight["readiness"]["summary"]["blocked"] == 0
    assert preflight["readiness"]["summary"]["degraded"] == 1
    simulation = preflight["permission_simulation"]
    assert simulation["side_effect_free"] is True
    assert simulation["content_free"] is True
    assert simulation["provider_safety_proven"] is False
    assert simulation["route_snapshot"]["harness_id"] == "echo"
    assert simulation["route_snapshot"]["execution_transport"] == "one_shot"
    assert simulation["block_run"] is False
    worker_finding = next(
        item
        for item in preflight["readiness"]["findings"]
        if item["id"] == "durable-worker"
    )
    assert worker_finding["remediation"][0]["command"] == "giga worker start"
    assert preflight["context_budget"]["attached_file_bytes"] == 1_000_001
    finding = next(
        item for item in preflight["findings"] if item["code"] == "large_attachment"
    )
    assert finding["severity"] == "warning"
    assert "continue" in finding["actions"]
    assert "exclude_attachment" in finding["actions"]


def test_preflight_api_blocks_an_explicit_action_denied_by_selected_policy():
    harness = _ArenaCaptureHarness("permission-preview")
    registry = HarnessRegistry()
    registry.register(harness)
    store = InMemoryHarnessSessionStore()
    client = _client(registry=registry, store=store)
    session = store.create_session(default_harness_id="permission-preview")

    response = client.post(
        "/api/preflight/run",
        json={
            "session_id": session.id,
            "harness_id": "permission-preview",
            "permission_profile": "unattended",
            "prompt": "preview only",
            "extra": {"required_permission_actions": ["git.push"]},
        },
    )

    assert response.status_code == 200
    preflight = response.json()["preflight"]
    assert preflight["hard_block"] is True
    assert preflight["permission_simulation"]["block_run"] is True
    assert preflight["permission_simulation"]["blocked_actions"] == ["git.push"]
    assert harness.requests == []
    assert store.list_runs(session.id) == ()


def test_preview_execution_does_not_invoke_harness_or_create_run():
    harness = _ArenaCaptureHarness("preview-capture")
    registry = HarnessRegistry()
    registry.register(harness)
    store = InMemoryHarnessSessionStore()
    client = _client(registry=registry, store=store)
    session = store.create_session(default_harness_id="preview-capture")

    response = client.post(
        "/api/preflight/run",
        json={
            "session_id": session.id,
            "harness_id": "preview-capture",
            "capability": "chat_completions",
            "dry_run": True,
            "invocation_mode": "headless",
            "prompt": "preview only",
        },
    )

    assert response.status_code == 200
    assert response.json()["preflight"]["ok"] is True
    assert harness.requests == []
    assert store.list_runs(session.id) == ()


def test_synchronous_route_preview_is_ready_with_not_checked_evidence(tmp_path):
    data_dir = tmp_path / "data"
    client = _client(
        config=HarnessConfig(data_dir=str(data_dir)),
        store=FilesystemHarnessSessionStore(data_dir),
    )

    response = client.post(
        "/api/preflight/run",
        json={
            "api_mode": "v2",
            "dry_run": True,
            "durable": False,
            "harness_id": "direct-chat",
            "invocation_mode": "headless",
            "mode": "plan",
            "prompt": "Readiness check",
            "workspace_policy": "auto",
        },
    )

    assert response.status_code == 200
    readiness = response.json()["preflight"]["readiness"]
    assert readiness["plan"]["delivery"] == "synchronous"
    assert readiness["status"] == "ready"
    assert readiness["evidence_status"] == "not_checked"
    assert readiness["summary"]["degraded"] == 0
    assert readiness["summary"]["blocked"] == 0
    route = next(
        finding for finding in readiness["findings"] if finding["id"] == "route-v2"
    )
    assert route["status"] == "not_checked"
    assert route["remediation"][0]["command"] == "giga doctor --json"


def test_evals_api_lists_and_runs_project_eval(tmp_path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    eval_path = workspace / ".giga" / "evals" / "smoke.yaml"
    eval_path.parent.mkdir(parents=True)
    eval_path.write_text(
        """
name: smoke
harnesses: [echo]
cases:
  - id: echo_contains
    prompt: "FastAPI gateway"
    checks:
      - type: contains
        value: "FastAPI"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    client = _client(
        config=HarnessConfig(data_dir=str(data_dir)),
        store=FilesystemHarnessSessionStore(data_dir),
    )

    listed = client.get("/api/evals", params={"workspace": str(workspace)})

    assert listed.status_code == 200
    assert listed.json()["specs"][0]["name"] == "smoke"
    assert listed.json()["specs"][0]["case_count"] == 1

    created = client.post(
        "/api/evals/smoke/runs",
        json={"workspace": str(workspace), "harness_ids": ["echo"]},
    )

    assert created.status_code == 200
    eval_run = created.json()["eval_run"]
    assert eval_run["status"] == "running"
    assert eval_run["results"][0]["status"] == "queued"
    assert eval_run["results"][0]["run_id"].startswith("run_")
    assert "session" in eval_run

    worker = DurableJobWorker(
        HarnessConfig(data_dir=str(data_dir)),
        registry=create_default_registry(include_entry_points=False),
        worker_id="worker_eval_api",
    )
    assert worker.run_once() is True

    fetched = client.get(f"/api/evals/runs/{eval_run['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["eval_run"]["id"] == eval_run["id"]
    assert fetched.json()["eval_run"]["status"] == "passed"
    assert fetched.json()["eval_run"]["summary"]["passed"] == 1
    assert "latency_seconds" in fetched.json()["eval_run"]["summary"]["metrics"]

    lab = client.get("/api/evaluate", params={"workspace": str(workspace)})
    assert lab.status_code == 200
    assert lab.json()["quality_specs"][0]["matrix"][0]["compatible"] is True
    assert "dimensions" in lab.json()["quality_specs"][0]
    assert lab.json()["protocol_matrix"][0]["fixture_id"] == "openai-chat"
    assert lab.json()["runs"][0]["baseline_delta"] is None

    pinned = client.post(
        f"/api/evaluate/runs/{eval_run['id']}/baseline",
        json={"workspace": str(workspace)},
    )
    assert pinned.status_code == 200
    assert pinned.json()["baseline"]["eval_run_id"] == eval_run["id"]

    refreshed = client.get("/api/evaluate", params={"workspace": str(workspace)})
    assert refreshed.json()["runs"][0]["baseline_delta"]["score_delta"] == 0.0

    queued = client.post(
        "/api/evals/smoke/runs",
        json={"workspace": str(workspace), "repetitions": 2},
    ).json()["eval_run"]
    canceled = client.post(f"/api/evaluate/runs/{queued['id']}/cancel")
    assert canceled.status_code == 200
    assert len(canceled.json()["cancel_requested"]) == 2


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


def test_cancel_does_not_overwrite_run_that_finished_during_lookup():
    store = _FinishDuringCancelLookupStore()
    session = store.create_session(title="Cancel race")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=session.default_api_mode,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="running",
    )
    store.finish_on_next_get(run.id)
    client = _client(store=store)

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 200
    assert response.json()["cancel_requested"] is False
    assert response.json()["run"]["status"] == "succeeded"
    assert store.get_run(run.id).status == "succeeded"
    assert store.list_events(session.id, run_id=run.id) == ()


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
    assert len(arena["review"]["task_sha256"]) == 64
    assert len(arena["review"]["candidate_set_sha256"]) == 64
    assert arena["review"]["verdict"] is None
    assert all(
        len(candidate["configuration_sha256"]) == 64
        for candidate in arena["review"]["candidates"]
    )
    assert all(
        candidate["cost"]["confidence"] == "unknown"
        for candidate in arena["review"]["candidates"]
    )
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


def test_arena_children_run_concurrently_and_follow_up_in_isolated_sessions(tmp_path):
    barrier = threading.Barrier(2)
    first = _ConcurrentArenaHarness("arena-concurrent-a", barrier)
    second = _ConcurrentArenaHarness("arena-concurrent-b", barrier)
    registry = HarnessRegistry()
    registry.register(first)
    registry.register(second)
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
        store=InMemoryHarnessSessionStore(),
    )

    created = client.post(
        "/api/arena/runs",
        json={
            "prompt": "compare concurrently",
            "harness_ids": ["arena-concurrent-a", "arena-concurrent-b"],
        },
    )

    assert created.status_code == 200
    arena = created.json()["arena"]
    child_session_ids = [child["session_id"] for child in arena["child_runs"]]
    assert len(set(child_session_ids)) == 2
    assert arena["session_id"] not in child_session_ids
    assert all(child["status"] == "succeeded" for child in arena["child_runs"])

    followed_up = client.post(
        f"/api/arena/runs/{arena['id']}/turns",
        json={"prompt": "shared follow-up", "model": "GigaChat-3-Pro"},
    )

    assert followed_up.status_code == 200
    updated = followed_up.json()["arena"]
    assert updated["model"] == "GigaChat-3-Pro"
    assert updated["metadata"]["turn_count"] == 1
    assert [request.prompt for request in first.requests] == [
        "compare concurrently",
        "shared follow-up",
    ]
    assert [request.prompt for request in second.requests] == [
        "compare concurrently",
        "shared follow-up",
    ]
    assert "arena-concurrent-a: compare concurrently" in [
        message.content for message in first.requests[1].messages
    ]
    assert "arena-concurrent-b: compare concurrently" not in [
        message.content for message in first.requests[1].messages
    ]
    assert all(child["bounded"] is True for child in updated["child_runs"])
    assert all(len(child["messages"]) == 4 for child in updated["child_runs"])
    assert first.requests[1].model == "GigaChat-3-Pro"
    assert second.requests[1].model == "GigaChat-3-Pro"

    retried = client.post(
        f"/api/arena/runs/{arena['id']}/children/0/retry",
    )

    assert (
        "/api/arena/runs/{arena_id}/verdict"
        in client.get("/openapi.json").json()["paths"]
    )
    assert retried.status_code == 200
    assert len(first.requests) == 3
    assert len(second.requests) == 2


def test_arena_verdict_binds_exact_candidates_and_selected_promotion(tmp_path):
    registry = HarnessRegistry()
    registry.register(_ArenaCaptureHarness("arena-reviewed-a"))
    registry.register(_ArenaCaptureHarness("arena-reviewed-b"))
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
        store=InMemoryHarnessSessionStore(),
    )
    created = client.post(
        "/api/arena/runs",
        json={
            "prompt": "review the same task",
            "harness_ids": ["arena-reviewed-a", "arena-reviewed-b"],
        },
    ).json()["arena"]
    review = created["review"]
    payload = {
        "candidate_set_sha256": review["candidate_set_sha256"],
        "selected_child_index": 1,
        "scores": [
            {"child_index": 0, "score": 0.75},
            {"child_index": 1, "score": 0.9},
        ],
    }

    stale = client.post(
        f"/api/arena/runs/{created['id']}/verdict",
        json={**payload, "candidate_set_sha256": "0" * 64},
    )
    decided = client.post(
        f"/api/arena/runs/{created['id']}/verdict",
        json=payload,
    )
    repeated = client.post(
        f"/api/arena/runs/{created['id']}/verdict",
        json=payload,
    )

    assert stale.status_code == 409
    assert decided.status_code == 200
    assert repeated.status_code == 200
    verdict = decided.json()["arena"]["review"]["verdict"]
    selected_run_id = created["child_runs"][1]["run_id"]
    assert verdict["current"] is True
    assert verdict["selected_run_id"] == selected_run_id
    assert len(verdict["verdict_sha256"]) == 64
    assert verdict["promotion"] == {
        "selected_run_id": selected_run_id,
        "configuration_preview_url": (
            f"/api/runs/{selected_run_id}/promotions/preview"
        ),
        "artifact_review_url": f"/api/runs/{selected_run_id}/diff",
        "run_url": f"/cockpit-v2/runs/{selected_run_id}",
        "automatic_apply": False,
    }
    assert (
        repeated.json()["arena"]["review"]["verdict"]["verdict_sha256"]
        == verdict["verdict_sha256"]
    )
    assert (
        client.post(
            f"/api/arena/runs/{created['id']}/turns",
            json={"prompt": "mutate the reviewed comparison"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/arena/runs/{created['id']}/children/0/retry",
        ).status_code
        == 409
    )


def test_arena_workspace_files_share_one_frozen_attachment_identity(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "brief.md").write_text("shared evidence\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    registry = HarnessRegistry()
    first = _ArenaCaptureHarness("arena-attachment-a")
    second = _ArenaCaptureHarness("arena-attachment-b")
    registry.register(first)
    registry.register(second)
    store = FilesystemHarnessSessionStore(data_dir)
    config = HarnessConfig(data_dir=str(data_dir))
    client = _client(
        config=config,
        registry=registry,
        store=store,
    )

    response = client.post(
        "/api/arena/runs",
        json={
            "prompt": "compare the brief",
            "harness_ids": ["arena-attachment-a", "arena-attachment-b"],
            "workspace": str(workspace),
            "workspace_paths": ["brief.md"],
        },
    )

    assert response.status_code == 200
    arena = response.json()["arena"]
    assert len(arena["attachment_ids"]) == 1
    attachment_id = arena["attachment_ids"][0]
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_arena_files")
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert first.requests[0].extra["attachment_ids"] == [attachment_id]
    assert second.requests[0].extra["attachment_ids"] == [attachment_id]
    assert (
        first.requests[0].extra["attachments"][0]["sha256"]
        == (second.requests[0].extra["attachments"][0]["sha256"])
    )


def test_arena_retry_queues_one_durable_child_and_rejects_active_source(tmp_path):
    data_dir = tmp_path / "data"
    config = HarnessConfig(data_dir=str(data_dir))
    store = FilesystemHarnessSessionStore(data_dir)
    runtime = RuntimeCoordinationStore(data_dir)
    registry = HarnessRegistry()
    registry.register(_ArenaCaptureHarness("arena-retry-a"))
    registry.register(_ArenaCaptureHarness("arena-retry-b"))
    client = TestClient(
        create_app(
            config,
            registry=registry,
            store=store,
            runtime_store=runtime,
        )
    )
    created = client.post(
        "/api/arena/runs",
        json={
            "prompt": "durable retry",
            "harness_ids": ["arena-retry-a", "arena-retry-b"],
        },
    )
    assert created.status_code == 200
    arena = created.json()["arena"]
    source_run_id = arena["child_runs"][0]["run_id"]

    active_retry = client.post(
        f"/api/arena/runs/{arena['id']}/children/0/retry",
    )
    assert active_retry.status_code == 400
    assert active_retry.json()["detail"] == "arena child is still active"

    store.update_run(source_run_id, status="succeeded", finished_at=utc_now())
    retried = client.post(
        f"/api/arena/runs/{arena['id']}/children/0/retry",
    )

    assert retried.status_code == 200
    retried_child = retried.json()["arena"]["child_runs"][0]
    assert retried_child["run_id"] != source_run_id
    assert retried_child["status"] == "queued"
    job = runtime.find_job_for_run(retried_child["run_id"])
    assert job is not None
    assert job.origin == "manual"


def test_arena_history_is_persisted_and_hidden_from_work_sessions(tmp_path):
    store = InMemoryHarnessSessionStore()
    registry = HarnessRegistry()
    registry.register(_ArenaCaptureHarness("arena-history"))
    client = _client(
        config=HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=registry,
        store=store,
    )
    normal = client.post(
        "/api/sessions",
        json={
            "title": "Keep in Work",
            "harness_id": "arena-history",
            "workspace": str(tmp_path),
        },
    ).json()["session"]
    created = client.post(
        "/api/arena/runs",
        json={
            "prompt": "keep this in arena",
            "harness_ids": ["arena-history"],
            "workspace": str(tmp_path),
        },
    ).json()["arena"]

    history = client.get(
        "/api/arena/runs",
        params={"workspace": str(tmp_path), "limit": 1},
    )
    work_sessions = client.get(
        "/api/sessions",
        params={"workspace": str(tmp_path), "include_archived": True},
    )
    all_sessions = client.get(
        "/api/sessions",
        params={
            "workspace": str(tmp_path),
            "include_archived": True,
            "include_arena": True,
        },
    )

    assert history.status_code == 200
    assert [item["id"] for item in history.json()["arenas"]] == [created["id"]]
    assert history.json()["arenas"][0]["prompt"] == ""
    assert "messages" not in history.json()["arenas"][0]["child_runs"][0]
    assert [item["id"] for item in work_sessions.json()["sessions"]] == [normal["id"]]
    assert {item["id"] for item in all_sessions.json()["sessions"]} == {
        normal["id"],
        created["session_id"],
    }


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
    config = HarnessConfig(
        default_model="ConfiguredModel",
        data_dir=str(tmp_path / "data"),
    )
    runtime = RuntimeCoordinationStore(config.data_dir)
    client = _client(
        config=config,
        registry=registry,
        runtime_store=runtime,
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

    assert applied.status_code == 202
    approval = applied.json()["approval"]
    approval_id = approval["id"]
    assert approval["preview"]["source_sha"] == _git_output(repo, "rev-parse", "HEAD")
    assert (
        approval["preview"]["patch_sha256"]
        == hashlib.sha256(diff_body["patch"].encode("utf-8")).hexdigest()
    )
    assert len(approval["preview"]["approval_binding_sha256"]) == 64
    broadened = client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"decision": "allow_run"},
    )
    assert broadened.status_code == 409
    decided = client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"decision": "allow_once"},
    )
    assert decided.status_code == 200
    applied = client.post(f"/api/runs/{run_id}/apply", json={})
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    assert applied.json()["diff"]["can_apply"] is False
    assert (
        applied.json()["diff"]["workspace_execution"]["approval_binding_sha256"]
        == approval["preview"]["approval_binding_sha256"]
    )
    assert (repo / "app.txt").read_text(encoding="utf-8") == "changed\n"
    audit = runtime.list_policy_audit_events(operation_id=approval_id)
    assert [event.phase.value for event in audit] == [
        "resolution",
        "decision",
        "enforcement",
    ]
    assert {event.enforcement_owner for event in audit} == {
        "reviewed_promotion.run_apply"
    }


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
    config = HarnessConfig(data_dir=str(tmp_path / "data"))
    runtime = RuntimeCoordinationStore(config.data_dir)
    client = _client(
        config=config,
        registry=registry,
        runtime_store=runtime,
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

    assert branched.status_code == 202
    approval_id = branched.json()["approval"]["id"]
    decided = client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"decision": "allow_once"},
    )
    assert decided.status_code == 200
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
    audit = runtime.list_policy_audit_events(operation_id=approval_id)
    assert [event.phase.value for event in audit] == [
        "resolution",
        "decision",
        "enforcement",
    ]
    assert {event.enforcement_owner for event in audit} == {
        "reviewed_promotion.branch_create"
    }


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
    runtime_store: RuntimeCoordinationStore | None = None,
) -> TestClient:
    app = create_app(
        config or HarnessConfig(default_model="ConfiguredModel"),
        registry=registry or create_default_registry(include_entry_points=False),
        store=store or InMemoryHarnessSessionStore(),
        runtime_store=runtime_store,
    )
    return TestClient(app)


class _ObservedSessionUpdateStore(InMemoryHarnessSessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.title_revision_read = threading.Event()

    def list_event_tail_page(self, session_id: str, **kwargs):
        page = super().list_event_tail_page(session_id, **kwargs)
        if any(item.event.type == "session.updated" for item in page.items):
            self.title_revision_read.set()
        return page


class _FinishDuringCancelLookupStore(InMemoryHarnessSessionStore):
    def __init__(self) -> None:
        super().__init__()
        self._finish_run_id: str | None = None

    def finish_on_next_get(self, run_id: str) -> None:
        self._finish_run_id = run_id

    def get_run(self, run_id: str):
        run = super().get_run(run_id)
        if self._finish_run_id == run_id:
            self._finish_run_id = None
            super().update_run(run_id, status="succeeded", finished_at=run.updated_at)
        return run


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
            supports_attachments=True,
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


class _ConcurrentArenaHarness(_ArenaCaptureHarness):
    def __init__(self, harness_id: str, barrier: threading.Barrier) -> None:
        super().__init__(harness_id)
        self.barrier = barrier

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.requests.append(request)
        if len(self.requests) <= 2:
            self.barrier.wait(timeout=2)
        return HarnessResult(ok=True, text=f"{self.harness_id}: {request.prompt}")


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
