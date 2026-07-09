import time

from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.project import project_id_for_root
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry
from gpt2giga.harness.sessions import InMemoryHarnessSessionStore
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


def _client(
    *,
    registry: HarnessRegistry | None = None,
    store: InMemoryHarnessSessionStore | None = None,
) -> TestClient:
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
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
