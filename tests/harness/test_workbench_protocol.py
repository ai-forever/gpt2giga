from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.tui.client import (
    AttachedWorkbenchClient,
    InProcessWorkbenchClient,
)
from gpt2giga_harness.ui import create_app
from gpt2giga_harness.workbench_protocol import (
    ArtifactReference,
    ResnapshotRequired,
    WorkbenchAction,
    WorkbenchActionKind,
    WorkbenchActionRegistry,
    WorkbenchBackbone,
    WorkbenchEventDraft,
    WorkbenchProtocolError,
    reduce_workbench_event,
    workbench_state_page_from_dict,
    workbench_state_page_to_dict,
)


def _draft(
    index: int,
    *,
    payload_type: str = "transcript.item",
    payload: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> WorkbenchEventDraft:
    return WorkbenchEventDraft(
        payload_type=payload_type,
        payload=payload or {"kind": "message", "text": f"item {index}"},
        provider="codex",
        session_id="session_1",
        workspace_id="workspace_1",
        source="provider_decoder",
        correlation_id=f"correlation_{index}",
        idempotency_key=idempotency_key,
    )


def test_backbone_reduces_shared_projections_and_raw_terminal_separately():
    backbone = WorkbenchBackbone(max_snapshot_events=2)
    backbone.publish(_draft(1, payload_type="command.catalog", payload={"items": []}))
    backbone.publish(
        _draft(2, payload_type="runtime.controls", payload={"provider": "codex"})
    )
    backbone.publish(_draft(3))
    backbone.publish(
        _draft(
            4,
            payload_type="raw-terminal-v1",
            payload={"process_id": "process_1", "chunk": "plain output"},
        )
    )

    snapshot = backbone.snapshot
    assert snapshot.revision == snapshot.sequence == 4
    assert snapshot.projections.command_catalog == {"items": ()}
    assert snapshot.projections.runtime_controls == {"provider": "codex"}
    assert snapshot.projections.transcript_items == (
        {"kind": "message", "text": "item 3"},
    )
    assert snapshot.projections.raw_terminal_frames == (
        {"process_id": "process_1", "chunk": "plain output"},
    )


def test_backbone_exposes_all_provider_neutral_projection_families():
    backbone = WorkbenchBackbone()
    backbone.publish(
        _draft(
            1,
            payload_type="sessions.snapshot",
            payload={"items": [{"id": "session_1", "status": "ready"}]},
        )
    )
    backbone.publish(
        _draft(
            2,
            payload_type="tasks_processes.snapshot",
            payload={"items": [{"id": "task_1", "kind": "task"}]},
        )
    )
    backbone.publish(
        _draft(
            3,
            payload_type="usage.limits",
            payload={"remaining_units": 100},
        )
    )
    backbone.publish(
        _draft(4, payload_type="preferences.snapshot", payload={"locale": "ru"})
    )

    projections = backbone.snapshot.projections
    assert projections.sessions == ({"id": "session_1", "status": "ready"},)
    assert projections.tasks_processes == ({"id": "task_1", "kind": "task"},)
    assert projections.usage_limits == {"remaining_units": 100}
    assert projections.preferences == {"locale": "ru"}


def test_reducer_is_exactly_once_and_fails_closed_on_sequence_revision_and_generation():
    backbone = WorkbenchBackbone()
    first = backbone.publish(_draft(1))
    snapshot = backbone.snapshot

    assert reduce_workbench_event(snapshot, first) is snapshot
    with pytest.raises(ResnapshotRequired, match="sequence gap"):
        reduce_workbench_event(
            snapshot,
            replace(first, id="wbe_1_3", sequence=3, revision=2),
        )
    with pytest.raises(ResnapshotRequired, match="revision gap"):
        reduce_workbench_event(
            snapshot,
            replace(first, id="wbe_1_2", sequence=2, revision=3),
        )
    with pytest.raises(ResnapshotRequired, match="generation changed"):
        reduce_workbench_event(
            snapshot,
            replace(first, id="wbe_2_2", sequence=2, revision=2, generation=2),
        )


def test_backbone_deduplicates_events_and_redacts_before_projection():
    backbone = WorkbenchBackbone()
    draft = _draft(
        1,
        payload={"text": "token=very-secret-value"},
        idempotency_key="provider_event_1",
    )

    first = backbone.publish(draft)
    duplicate = backbone.publish(draft)

    assert duplicate is first
    assert backbone.snapshot.sequence == 1
    assert "very-secret-value" not in str(first.payload)
    with pytest.raises(WorkbenchProtocolError, match="another correlation"):
        backbone.publish(replace(draft, correlation_id="correlation_2"))


def test_provider_decoder_boundary_retains_only_normalized_artifact_reference():
    class Decoder:
        def decode(self, raw_event):
            assert raw_event["provider_only_field"] == "not-for-widgets"
            return replace(
                _draft(1, payload={"kind": "tool", "status": "completed"}),
                artifacts=(
                    ArtifactReference(
                        id="artifact_1",
                        kind="stdout",
                        media_type="text/plain",
                        byte_count=2048,
                        truncated=True,
                    ),
                ),
            )

    event = WorkbenchBackbone().publish_provider_event(
        Decoder(), {"provider_only_field": "not-for-widgets"}
    )

    assert "provider_only_field" not in event.payload
    assert event.artifacts[0].byte_count == 2048
    assert event.artifacts[0].truncated is True


def test_bounded_delta_cursor_resnapshots_slow_consumers_and_pages_new_events():
    backbone = WorkbenchBackbone(max_deltas=2)
    initial = backbone.read().cursor
    for index in range(1, 5):
        backbone.publish(_draft(index))

    stale = backbone.read(initial)
    assert stale.resnapshot_reason == "slow_consumer"
    assert stale.deltas == ()
    page = backbone.read("wb1.1.2.2", limit=1)
    assert [event.sequence for event in page.deltas] == [3]
    assert page.cursor == "wb1.1.3.3"
    assert page.has_more is True
    assert backbone.read("invalid").resnapshot_reason == "cursor_gap"
    assert backbone.read("wb1.1.2.1").resnapshot_reason == "cursor_gap"
    assert backbone.read("wb1.2.0.0").resnapshot_reason == "generation_changed"


def test_action_registry_enforces_idempotency_and_cancellation():
    action = WorkbenchAction(
        id="action_1",
        idempotency_key="turn_1",
        kind=WorkbenchActionKind.TURN_SUBMIT,
        generation=1,
        expected_revision=0,
        session_id="session_1",
        workspace_id="workspace_1",
        payload={"content": "hello"},
    )
    registry = WorkbenchActionRegistry(max_receipts=2)

    first = registry.begin(action)
    assert registry.begin(action) is first
    canceled = registry.cancel(action.id)
    assert canceled.status == "canceled"
    assert registry.cancellation_requested(action.id) is True
    with pytest.raises(WorkbenchProtocolError, match="another action"):
        registry.begin(replace(action, id="action_2"))


def test_backbone_rejects_stale_actions_before_application_side_effects():
    backbone = WorkbenchBackbone()
    action = WorkbenchAction(
        id="action_1",
        idempotency_key="turn_1",
        kind=WorkbenchActionKind.TURN_SUBMIT,
        generation=1,
        expected_revision=0,
        session_id="session_1",
        payload={"content": "hello"},
    )
    assert backbone.accept_action(action).status == "accepted"
    assert backbone.cancel_action(action.id).status == "canceled"
    backbone.publish(_draft(1))
    with pytest.raises(ResnapshotRequired, match="action revision changed"):
        backbone.accept_action(replace(action, id="action_2", idempotency_key="turn_2"))
    with pytest.raises(ResnapshotRequired, match="action generation changed"):
        backbone.accept_action(
            replace(
                action,
                id="action_3",
                idempotency_key="turn_3",
                generation=2,
                expected_revision=1,
            )
        )


def test_state_page_round_trip_preserves_revision_deltas_and_artifacts():
    backbone = WorkbenchBackbone()
    cursor = backbone.read().cursor
    backbone.publish(
        replace(
            _draft(1),
            artifacts=(
                ArtifactReference(
                    id="artifact_1",
                    kind="diff",
                    media_type="text/x-diff",
                    byte_count=42,
                ),
            ),
        )
    )
    page = backbone.read(cursor)

    parsed = workbench_state_page_from_dict(workbench_state_page_to_dict(page))

    assert parsed == page


async def test_in_process_and_attach_clients_use_matching_state_contract(tmp_path):
    config = HarnessConfig(data_dir=tmp_path / "data")
    in_process = InProcessWorkbenchClient(config)
    in_process.workbench_backbone.publish(_draft(1))
    expected = await in_process.workbench_state(cursor="wb1.1.0.0")

    attached = AttachedWorkbenchClient("http://127.0.0.1:8000")

    async def request(method, path, payload=None):
        assert method == "GET"
        assert path == "/api/workbench/state?limit=32&cursor=wb1.1.0.0"
        assert payload is None
        return workbench_state_page_to_dict(expected)

    attached._request = request
    actual = await attached.workbench_state(cursor="wb1.1.0.0")

    assert actual == expected


def test_workbench_api_is_bounded_and_uses_app_backbone(tmp_path):
    config = HarnessConfig(data_dir=tmp_path / "data")
    app = create_app(config=config)
    app.state.harness_workbench_backbone.publish(_draft(1))

    with TestClient(app) as client:
        response = client.get(
            "/api/workbench/state",
            params={"cursor": "wb1.1.0.0", "limit": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["revision"] == 1
    assert payload["deltas"][0]["payload_type"] == "transcript.item"
    assert payload["cursor"] == "wb1.1.1.1"
