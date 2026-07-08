from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.project import project_id_for_root
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.sessions import InMemoryHarnessSessionStore
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


def _client() -> TestClient:
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
        store=InMemoryHarnessSessionStore(),
    )
    return TestClient(app)
