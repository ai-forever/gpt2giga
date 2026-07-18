from __future__ import annotations

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions.models import HarnessMessage, HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.routers import cockpit as cockpit_router


def _app(tmp_path):
    return create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )


def _run(store, session_id: str, *, metadata=None):
    return store.create_run(
        session_id=session_id,
        harness_id="echo",
        prompt="bounded read model",
        model="GigaChat",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        metadata=metadata,
    )


def test_cockpit_session_pages_are_indexed_cursor_bound_and_etagged(
    tmp_path, monkeypatch
):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    sessions = [store.create_session(title=f"session {index}") for index in range(3)]
    run = _run(store, sessions[0].id)

    def full_bundle_forbidden(_session_id):
        raise AssertionError("Cockpit reads must not load a complete session bundle")

    monkeypatch.setattr(store, "get_session_bundle", full_bundle_forbidden)
    with TestClient(app) as client:
        first = client.get("/api/cockpit/sessions?limit=2")
        assert first.status_code == 200
        body = first.json()
        assert len(body["sessions"]) == 2
        assert body["has_more"] is True
        assert body["next_cursor"]
        assert body["order"] == "pinned_desc_updated_at_desc_id_desc"
        assert first.headers["etag"] == f'"{body["snapshot_revision"]}"'
        assert (
            client.get(
                "/api/cockpit/sessions?limit=2",
                headers={"If-None-Match": first.headers["etag"]},
            ).status_code
            == 304
        )
        monkeypatch.setattr(cockpit_router, "_REVISION_NAMESPACE", "restarted")
        after_restart = client.get(
            "/api/cockpit/sessions?limit=2",
            headers={"If-None-Match": first.headers["etag"]},
        )
        assert after_restart.status_code == 200
        assert after_restart.headers["etag"] != first.headers["etag"]

        second = client.get(
            "/api/cockpit/sessions",
            params={"limit": 2, "cursor": body["next_cursor"]},
        )
        assert second.status_code == 200
        assert len(second.json()["sessions"]) == 1
        assert {
            item["id"] for item in body["sessions"] + second.json()["sessions"]
        } == {item.id for item in sessions}

        overview = client.get(f"/api/cockpit/sessions/{sessions[0].id}")
        assert overview.status_code == 200
        assert overview.json()["projections"]["messages"].endswith("/messages")

    def session_run_scan_forbidden(_session_id):
        raise AssertionError("direct run lookup must use the read index")

    monkeypatch.setattr(store, "list_runs", session_run_scan_forbidden)
    assert store.get_run(run.id).id == run.id


def test_runs_center_generation_advances_for_session_and_run_projections(tmp_path):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    initial = store.runs_center_generation()
    session = store.create_session(title="revision")
    after_session = store.runs_center_generation()
    run = _run(store, session.id)
    after_run = store.runs_center_generation()
    store.update_run(run.id, status="running")

    assert after_session[0] > initial[0]
    assert after_run[1] > after_session[1]
    assert store.runs_center_generation()[1] > after_run[1]


def test_cockpit_record_pages_enforce_item_byte_bounds_and_stale_snapshots(tmp_path):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    session = store.create_session(title="large history")
    run = _run(store, session.id)
    for index in range(12):
        store.append_message(
            HarnessMessage(
                id=f"msg_{index:03d}",
                session_id=session.id,
                run_id=run.id,
                role="assistant",
                content=(f"message {index} " + ("x" * 900)),
                created_at=utc_now(),
            )
        )

    with TestClient(app) as client:
        first = client.get(
            f"/api/cockpit/sessions/{session.id}/messages",
            params={"limit": 5, "max_bytes": 4096},
        )
        assert first.status_code == 200
        body = first.json()
        assert 1 <= len(body["messages"]) <= 5
        assert body["byte_count"] <= 4096
        assert body["has_more"] is True
        assert body["next_cursor"]
        assert body["messages"][0]["content"]["byte_count"] > 0
        assert body["order"] == "append_created_at_asc_id_asc"

        second = client.get(
            f"/api/cockpit/sessions/{session.id}/messages",
            params={"cursor": body["next_cursor"], "limit": 5, "max_bytes": 4096},
        )
        assert second.status_code == 200
        assert second.json()["messages"][0]["id"] != body["messages"][0]["id"]

        store.append_message(
            HarnessMessage(
                id="msg_later",
                session_id=session.id,
                run_id=run.id,
                role="assistant",
                content="later",
                created_at=utc_now(),
            )
        )
        stale = client.get(
            f"/api/cockpit/sessions/{session.id}/messages",
            params={"cursor": body["next_cursor"]},
        )
        assert stale.status_code == 409
        assert "snapshot is stale" in stale.json()["detail"]


def test_cockpit_message_projection_exposes_bounded_reasoning_and_usage(tmp_path):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    session = store.create_session(title="reasoning")
    run = _run(store, session.id)
    store.append_message(
        HarnessMessage(
            id="msg_reasoning",
            session_id=session.id,
            run_id=run.id,
            role="assistant",
            content="answer",
            created_at=utc_now(),
            metadata={
                "reasoning": "Inspecting the repository",
                "usage": {
                    "input_tokens": 21,
                    "output_tokens": 8,
                    "source": "hidden",
                    "token": "secret",
                },
            },
        )
    )

    with TestClient(app) as client:
        response = client.get(f"/api/cockpit/sessions/{session.id}/messages")

    assert response.status_code == 200
    projected = response.json()["messages"][0]
    assert projected["reasoning"]["text"] == "Inspecting the repository"
    assert projected["usage"] == {"input_tokens": 21, "output_tokens": 8}


def test_cockpit_message_content_returns_complete_explicit_copy_payload(tmp_path):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    session = store.create_session(title="complete message")
    run = _run(store, session.id)
    full_content = f"prefix\n{'я' * 40_000}\nsuffix"
    store.append_message(
        HarnessMessage(
            id="msg_complete",
            session_id=session.id,
            run_id=run.id,
            role="assistant",
            content=full_content,
            created_at=utc_now(),
        )
    )

    with TestClient(app) as client:
        page = client.get(f"/api/cockpit/sessions/{session.id}/messages")
        complete = client.get(
            f"/api/cockpit/sessions/{session.id}/messages/msg_complete/content"
        )
        missing = client.get(
            f"/api/cockpit/sessions/{session.id}/messages/missing/content"
        )

    assert page.json()["messages"][0]["content"]["truncated"] is True
    assert complete.status_code == 200
    assert complete.headers["cache-control"] == "private, no-store"
    assert complete.json() == {
        "message_id": "msg_complete",
        "role": "assistant",
        "content": full_content,
        "byte_count": len(full_content.encode("utf-8")),
    }
    assert missing.status_code == 404


def test_cockpit_run_summary_exposes_bounded_native_and_provider_identity(tmp_path):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    session = store.create_session(title="native reconnect")
    run = _run(
        store,
        session.id,
        metadata={
            "execution_transport": "native_structured",
            "native_process": {
                "id": "native-process-1",
                "display_command": "codex --secret token",
            },
            "structured_session_link": {
                "id": "link-1",
                "external_session_id": "provider-session-1",
                "latest_external_turn_id": "provider-turn-1",
                "recovery_state": "active",
                "link_hash": "a" * 64,
                "supervisor_owner": "worker-secret-owner",
                "config_snapshot": {
                    "protocol": "codex-app-server-json-rpc-v2",
                    "protocol_version": "2",
                },
            },
        },
    )

    with TestClient(app) as client:
        response = client.get(f"/api/cockpit/sessions/{session.id}/runs")

    assert response.status_code == 200
    projected = response.json()["runs"][0]
    assert projected["id"] == run.id
    assert projected["native_process_id"] == "native-process-1"
    assert projected["execution_transport"] == "native_structured"
    assert projected["provider_session"] == {
        "link_id": "link-1",
        "external_session_id": "provider-session-1",
        "latest_external_turn_id": "provider-turn-1",
        "recovery_state": "active",
        "protocol": "codex-app-server-json-rpc-v2",
        "protocol_version": "2",
        "link_hash": "a" * 64,
        "content_free": True,
    }
    assert "display_command" not in response.text
    assert "secret" not in response.text
    assert "supervisor_owner" not in response.text


def test_cockpit_run_artifacts_and_heavy_evidence_are_lazy_and_bounded(tmp_path):
    app = _app(tmp_path)
    store = app.state.harness_session_store
    session = store.create_session(title="lazy evidence")
    patch = "diff --git a/app.py b/app.py\n" + ("+bounded\n" * 2000)
    run = _run(
        store,
        session.id,
        metadata={
            "workspace_execution": {
                "patch": patch,
                "changed_files": ["app.py"],
                "worktree_path": "/redacted/worktree",
            },
            "pr_artifact": {"title": "bounded", "body": "report " + ("y" * 8000)},
        },
    )
    store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=session.id,
            run_id=run.id,
            type="tool_result",
            message="retained event",
            payload={"large": "z" * 20_000},
            created_at=utc_now(),
        )
    )
    store.append_raw_request(
        session_id=session.id,
        run_id=run.id,
        payload={"prompt": "p" * 20_000},
    )
    store.append_raw_response(
        session_id=session.id,
        run_id=run.id,
        payload={"result": "r" * 20_000},
    )

    with TestClient(app) as client:
        overview = client.get(f"/api/cockpit/runs/{run.id}")
        assert overview.status_code == 200
        assert overview.json()["run"]["artifacts"] == [
            {
                "type": "diff",
                "byte_count": len(patch.encode()),
                "projection_url": f"/api/cockpit/runs/{run.id}/diff",
            },
            {"type": "worktree", "byte_count": None},
            {
                "type": "pr_report",
                "byte_count": len(
                    '{\n  "body": "report '
                    + ("y" * 8000)
                    + '",\n  "title": "bounded"\n}'
                ),
                "projection_url": f"/api/cockpit/runs/{run.id}/report",
            },
        ]

        events = client.get(f"/api/cockpit/sessions/{session.id}/events")
        assert events.status_code == 200
        assert "payload" not in events.json()["events"][0]
        assert events.json()["events"][0]["payload_url"].endswith(
            f"/events/{events.json()['events'][0]['id']}"
        )

        diff = client.get(
            f"/api/cockpit/runs/{run.id}/diff", params={"max_bytes": 4096}
        ).json()
        assert diff["patch"]["truncated"] is True
        assert len(diff["patch"]["text"].encode()) <= 4096 - 1024

        report = client.get(
            f"/api/cockpit/runs/{run.id}/report", params={"max_bytes": 4096}
        ).json()
        assert report["report"]["truncated"] is True

        raw = client.get(f"/api/cockpit/runs/{run.id}/raw", params={"max_bytes": 4096})
        assert raw.status_code == 200
        assert raw.json()["byte_count"] <= 4096
        assert {item["direction"] for item in raw.json()["records"]} == {
            "request",
            "response",
        }
