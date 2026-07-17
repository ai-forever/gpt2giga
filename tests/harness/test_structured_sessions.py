from dataclasses import replace
import json
import stat

import pytest

from gpt2giga_harness.execution import (
    EMPTY_EXTENSION_SNAPSHOT_HASH,
    ExecutionTransport,
    InteractionMode,
    ProviderRef,
    RouteRef,
    RuntimeOwnership,
    SnapshotEvidenceRef,
    create_execution_snapshot,
)
from gpt2giga_harness.structured_sessions import (
    AdapterCapabilitySnapshot,
    RecoveryState,
    SessionLinkConflict,
    SessionSnapshotMismatch,
    StructuredSessionConfigSnapshot,
    StructuredSessionCoordinator,
    StructuredSessionError,
    StructuredSessionLink,
    StructuredSessionLinkStore,
    StructuredSessionState,
    StructuredTurnInput,
    StructuredTurnResult,
    UnsupportedSessionCapability,
    capability_snapshot_from_dict,
    capability_snapshot_to_dict,
    config_snapshot_from_dict,
    config_snapshot_to_dict,
    migrate_structured_session_link_payload,
    structured_session_link_from_dict,
    structured_session_link_to_dict,
)


class _FakeStructuredDriver:
    def __init__(self, capabilities=None):
        self.capabilities = capabilities or _capabilities()
        self.calls = []
        self.session_number = 0

    def probe(self):
        self.calls.append(("probe",))
        return self.capabilities

    def open_or_resume(self, execution_snapshot, session_link):
        self.calls.append(
            (
                "open_or_resume",
                execution_snapshot.snapshot_hash,
                session_link.id if session_link else None,
            )
        )
        if session_link is not None:
            return StructuredSessionState(
                session_link.external_session_id,
                session_link.latest_external_turn_id,
            )
        self.session_number += 1
        return StructuredSessionState(f"external-session-{self.session_number}")

    def start_turn(self, turn_input, event_sink, approval_bridge):
        self.calls.append(("start_turn", turn_input.id, turn_input.content))
        event_sink({"type": "partial_output", "text": "ephemeral-output"})
        self.calls.append(("bridge", approval_bridge({"id": "approval-1"})))
        return StructuredTurnResult("external-turn-1", "completed")

    def respond_to_input(self, request_id, answer):
        self.calls.append(("respond_to_input", request_id, answer))

    def respond_to_approval(self, request_id, decision):
        self.calls.append(("respond_to_approval", request_id, decision))

    def interrupt(self, turn_id):
        self.calls.append(("interrupt", turn_id))

    def steer(self, turn_id, turn_input):
        self.calls.append(("steer", turn_id, turn_input.id, turn_input.content))

    def fork(self, session_link, turn_id):
        self.calls.append(("fork", session_link.id, turn_id))
        return StructuredSessionState("external-session-fork", turn_id)

    def recover(self, session_link):
        self.calls.append(("recover", session_link.id))
        return StructuredSessionState(
            session_link.external_session_id,
            session_link.latest_external_turn_id,
        )

    def open_in_provider(self):
        self.calls.append(("open_in_provider",))
        return "provider-window-1"

    def close(self):
        self.calls.append(("close",))


def test_capability_and_config_snapshots_round_trip_with_stable_hashes():
    capabilities = _capabilities(
        attachment_kinds=("image", "text"),
        attachment_transports=("inline", "path"),
    )
    config = _config()

    capabilities_payload = capability_snapshot_to_dict(capabilities)
    config_payload = config_snapshot_to_dict(config)

    assert capability_snapshot_from_dict(capabilities_payload) == capabilities
    assert config_snapshot_from_dict(config_payload) == config
    assert capabilities_payload["attachment_kinds"] == ["image", "text"]
    assert capabilities.supports_link_schema(1) is True

    changed = dict(config_payload)
    changed["managed_home_id"] = "managed-home-other"
    with pytest.raises(ValueError, match="config snapshot hash mismatch"):
        config_snapshot_from_dict(changed)

    future = dict(capabilities_payload)
    future["schema_version"] = 2
    with pytest.raises(ValueError, match="schema_version"):
        capability_snapshot_from_dict(future)


def test_structured_link_round_trip_is_content_free_and_snapshot_bound():
    canary = "secret-canary-transcript-value"
    link = _link()

    payload = structured_session_link_to_dict(link)
    serialized = json.dumps(payload, sort_keys=True)

    assert structured_session_link_from_dict(payload) == link
    assert canary not in serialized
    assert "prompt" not in serialized
    assert "transcript" not in serialized
    assert payload["execution_snapshot"]["provider"]["id"] == "provider-main"
    assert payload["execution_snapshot"]["route"]["id"] == "coding"
    assert (
        payload["execution_snapshot"]["snapshot_hash"]
        == link.execution_snapshot.snapshot_hash
    )
    assert (
        payload["config_snapshot"]["snapshot_hash"]
        == link.config_snapshot.snapshot_hash
    )

    with pytest.raises(SessionSnapshotMismatch, match="fork or start a new"):
        link.require_continuation_snapshots(
            replace(link.execution_snapshot, permission_profile="read-only"),
            link.config_snapshot,
        )

    value_bearing = json.loads(json.dumps(payload))
    value_bearing["api_key"] = canary
    with pytest.raises(ValueError, match="unknown structured session link fields"):
        structured_session_link_from_dict(value_bearing)

    transcript_bearing = json.loads(json.dumps(payload))
    transcript_bearing["config_snapshot"]["prompt"] = canary
    with pytest.raises(ValueError, match="unknown config snapshot fields"):
        structured_session_link_from_dict(transcript_bearing)

    changed = json.loads(json.dumps(payload))
    changed["heartbeat_at"] = "2026-07-17T11:00:00+00:00"
    with pytest.raises(ValueError, match="link hash mismatch"):
        structured_session_link_from_dict(changed)

    future = dict(payload)
    future["schema_version"] = 2
    with pytest.raises(ValueError, match="schema_version"):
        structured_session_link_from_dict(future)


def test_reviewed_v0_link_migrates_to_hashed_v1_without_new_authority():
    payload = structured_session_link_to_dict(_link())
    legacy = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "link_hash",
            "recovery_state",
            "degradation_evidence",
            "forked_from_link_id",
            "forked_from_external_turn_id",
        }
    }
    legacy["schema_version"] = 0

    migrated = migrate_structured_session_link_payload(legacy)
    link = structured_session_link_from_dict(migrated)

    assert migrated["schema_version"] == 1
    assert migrated["recovery_state"] == "active"
    assert migrated["degradation_evidence"] == []
    assert link.recovery_state is RecoveryState.ACTIVE

    legacy["credential"] = "must-not-migrate"
    with pytest.raises(ValueError, match="unknown structured session link v0 fields"):
        migrate_structured_session_link_payload(legacy)


def test_link_store_is_atomic_strict_and_revision_checked(tmp_path):
    store = StructuredSessionLinkStore(tmp_path)
    created = store.create(_link())
    path = next((tmp_path / "structured_sessions" / "links").glob("*.json"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.load(created.id) == created

    updated = store.replace(
        replace(created, latest_external_turn_id="external-turn-2"),
        expected_revision=created.revision,
    )
    assert updated.revision == 2
    assert store.load(created.id) == updated

    with pytest.raises(SessionLinkConflict, match="revision changed"):
        store.replace(
            replace(created, latest_external_turn_id="stale-turn"),
            expected_revision=created.revision,
        )

    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(StructuredSessionError, match="unreadable"):
        store.load(created.id)

    with pytest.raises(ValueError, match="link id is invalid"):
        store.load("../escape")


def test_coordinator_proves_start_turn_approval_interrupt_resume_fork_recovery(
    tmp_path,
):
    driver = _FakeStructuredDriver()
    store = StructuredSessionLinkStore(tmp_path)
    coordinator = StructuredSessionCoordinator(driver, store, owner_id="worker-1")
    execution = _execution()
    config = _config()

    link = coordinator.open_or_resume(
        link_id="link-main",
        harness_session_id="session-main",
        harness_run_id="run-1",
        execution_snapshot=execution,
        config_snapshot=config,
    )
    events = []
    link, result = coordinator.start_turn(
        link,
        StructuredTurnInput("input-1", "private prompt that is never persisted"),
        events.append,
        lambda request: "allow" if request["id"] == "approval-1" else "deny",
    )
    coordinator.respond_to_input(link, "input-request-1", "answer")
    coordinator.respond_to_approval(link, "approval-1", "allow")
    coordinator.interrupt(link, result.external_turn_id)
    coordinator.steer(
        link,
        result.external_turn_id,
        StructuredTurnInput("input-2", "steer content"),
    )
    assert coordinator.open_in_provider(link) == "provider-window-1"

    resumed = coordinator.open_or_resume(
        link_id=link.id,
        harness_session_id=link.harness_session_id,
        harness_run_id="run-2",
        execution_snapshot=execution,
        config_snapshot=config,
        existing_link=link,
    )
    forked = coordinator.fork(
        resumed,
        new_link_id="link-fork",
        harness_session_id="session-fork",
        harness_run_id="run-fork",
        turn_id=resumed.latest_external_turn_id,
    )
    owner_lost = store.replace(
        replace(forked, recovery_state=RecoveryState.OWNER_LOST),
        expected_revision=forked.revision,
    )
    recovered = coordinator.recover(owner_lost)
    closed = coordinator.close(recovered)

    assert result.status == "completed"
    assert events == [{"type": "partial_output", "text": "ephemeral-output"}]
    assert resumed.revision == 3
    assert forked.forked_from_link_id == resumed.id
    assert recovered.recovery_state is RecoveryState.RECOVERED
    assert closed.recovery_state is RecoveryState.CLOSED
    assert ("respond_to_approval", "approval-1", "allow") in driver.calls
    assert ("interrupt", "external-turn-1") in driver.calls
    assert ("recover", "link-fork") in driver.calls

    durable = json.dumps(
        structured_session_link_to_dict(store.load(link.id)),
        sort_keys=True,
    )
    assert "private prompt" not in durable
    assert "steer content" not in durable
    assert "ephemeral-output" not in durable
    assert "answer" not in durable


def test_coordinator_fails_closed_for_mismatch_and_unsupported_operations(tmp_path):
    capabilities = _capabilities(
        interactive_input=False,
        live_approvals=False,
        durable_approval=False,
        interrupt=False,
        steer=False,
        resume=False,
        fork=False,
        provider_ui_handoff=False,
        recovery_after_process_loss=False,
    )
    driver = _FakeStructuredDriver(capabilities)
    coordinator = StructuredSessionCoordinator(
        driver,
        StructuredSessionLinkStore(tmp_path),
        owner_id="worker-1",
    )
    link = coordinator.open_or_resume(
        link_id="link-limited",
        harness_session_id="session-limited",
        harness_run_id="run-limited",
        execution_snapshot=_execution(),
        config_snapshot=_config(),
    )

    with pytest.raises(UnsupportedSessionCapability, match="interactive input"):
        coordinator.respond_to_input(link, "request-1", "answer")
    with pytest.raises(UnsupportedSessionCapability, match="approval response"):
        coordinator.respond_to_approval(link, "approval-1", "allow")
    with pytest.raises(UnsupportedSessionCapability, match="interrupt"):
        coordinator.interrupt(link, "turn-1")
    with pytest.raises(UnsupportedSessionCapability, match="steer"):
        coordinator.steer(link, "turn-1", StructuredTurnInput("input-2", "text"))
    with pytest.raises(UnsupportedSessionCapability, match="fork"):
        coordinator.fork(
            link,
            new_link_id="link-fork",
            harness_session_id="session-fork",
            harness_run_id="run-fork",
        )
    with pytest.raises(UnsupportedSessionCapability, match="provider UI handoff"):
        coordinator.open_in_provider(link)
    with pytest.raises(UnsupportedSessionCapability, match="recovery"):
        coordinator.recover(link)
    with pytest.raises(UnsupportedSessionCapability, match="resume"):
        coordinator.open_or_resume(
            link_id=link.id,
            harness_session_id=link.harness_session_id,
            harness_run_id="run-resume",
            execution_snapshot=link.execution_snapshot,
            config_snapshot=link.config_snapshot,
            existing_link=link,
        )

    resume_capabilities = replace(capabilities, resume=True)
    driver.capabilities = resume_capabilities
    with pytest.raises(SessionSnapshotMismatch, match="fork or start a new"):
        coordinator.open_or_resume(
            link_id=link.id,
            harness_session_id=link.harness_session_id,
            harness_run_id="run-resume",
            execution_snapshot=replace(
                link.execution_snapshot,
                extension_snapshot_hash="a" * 64,
            ),
            config_snapshot=link.config_snapshot,
            existing_link=link,
        )

    assert [call[0] for call in driver.calls].count("open_or_resume") == 1


def test_coordinator_rejects_stale_link_before_driver_side_effect(tmp_path):
    driver = _FakeStructuredDriver()
    store = StructuredSessionLinkStore(tmp_path)
    coordinator = StructuredSessionCoordinator(driver, store, owner_id="worker-1")
    link = coordinator.open_or_resume(
        link_id="link-stale",
        harness_session_id="session-stale",
        harness_run_id="run-stale",
        execution_snapshot=_execution(),
        config_snapshot=_config(),
    )
    store.replace(
        replace(link, heartbeat_at="2026-07-17T11:00:00+00:00"),
        expected_revision=link.revision,
    )
    calls_before = list(driver.calls)

    with pytest.raises(SessionLinkConflict, match="revision changed"):
        coordinator.start_turn(
            link,
            StructuredTurnInput("input-stale", "must not run"),
            lambda event: None,
            lambda request: "deny",
        )

    assert driver.calls == calls_before


def _capabilities(**overrides):
    values = {
        "adapter_id": "codex-structured",
        "adapter_version": "1.0.0",
        "protocol": "codex-app-server",
        "protocol_version": "v2",
        "structured_events": True,
        "partial_output": True,
        "interactive_input": True,
        "live_approvals": True,
        "durable_approval": True,
        "interrupt": True,
        "steer": True,
        "resume": True,
        "fork": True,
        "session_list": True,
        "session_close": True,
        "native_auth": True,
        "provider_ui_handoff": True,
        "dynamic_model": False,
        "dynamic_mcp": False,
        "recovery_after_process_loss": True,
    }
    values.update(overrides)
    return AdapterCapabilitySnapshot(**values)


def _config():
    return StructuredSessionConfigSnapshot(
        adapter_id="codex-structured",
        adapter_version="1.0.0",
        protocol="codex-app-server",
        protocol_version="v2",
        cli_sdk_version="0.144.5",
        managed_home_id="managed-home-1",
    )


def _execution():
    provider = ProviderRef("provider-main", "7")
    return create_execution_snapshot(
        provider=provider,
        route=RouteRef("coding", "11", provider),
        harness_id="codex-structured",
        harness_version="1.0.0",
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        interaction_mode=InteractionMode.INTERACTIVE,
        runtime_ownership=RuntimeOwnership.DURABLE,
        workspace_id="workspace-main",
        worktree_id="worktree-run-1",
        permission_profile="workspace-write",
        extension_snapshot_hash=EMPTY_EXTENSION_SNAPSHOT_HASH,
        capability_evidence=(
            SnapshotEvidenceRef("structured-events", "1", "supported", "probe"),
        ),
    )


def _link():
    return StructuredSessionLink(
        id="link-main",
        harness_session_id="session-main",
        harness_run_id="run-main",
        execution_snapshot=_execution(),
        config_snapshot=_config(),
        capability_snapshot=_capabilities(),
        external_session_id="external-session-1",
        latest_external_turn_id="external-turn-1",
        supervisor_owner="worker-1",
        heartbeat_at="2026-07-17T10:00:00+00:00",
        degradation_evidence=(
            SnapshotEvidenceRef("handoff", "1", "degraded", "probe"),
        ),
        created_at="2026-07-17T10:00:00+00:00",
        updated_at="2026-07-17T10:00:00+00:00",
    )
