from gpt2giga_harness.native import (
    HarnessInvocationMode,
    NativeExecutionSnapshot,
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga_harness.native.models import (
    execution_snapshot_from_dict,
    execution_snapshot_to_dict,
)
from gpt2giga_harness.types import HarnessCapability, HarnessSpec, spec_to_dict


def test_harness_spec_defaults_to_headless_without_native_sessions():
    spec = HarnessSpec(
        id="fake",
        title="Fake",
        kind="test",
        description="test harness",
        capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
    )

    payload = spec_to_dict(spec)

    assert spec.default_invocation_mode is HarnessInvocationMode.HEADLESS
    assert payload["supports_native_sessions"] is False
    assert payload["supports_external_history"] is False
    assert payload["default_invocation_mode"] == "headless"


def test_harness_spec_serializes_native_session_support():
    spec = HarnessSpec(
        id="codex-cli",
        title="Codex CLI",
        kind="agent",
        description="Codex native harness",
        capabilities=(HarnessCapability.AGENT_CLI,),
        supports_native_sessions=True,
        supports_external_history=True,
        default_invocation_mode=HarnessInvocationMode.NATIVE,
    )

    payload = spec_to_dict(spec)

    assert payload["supports_native_sessions"] is True
    assert payload["supports_external_history"] is True
    assert payload["default_invocation_mode"] == "native"


def test_native_session_ref_defaults_metadata_and_resume_reason():
    ref = NativeSessionRef(
        id="native_codex_1",
        harness_id="codex-cli",
        native_session_id="abc123",
        title="Fix tests",
        workspace="/repo",
        source="~/.codex/sessions",
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        created_at="2026-07-08T10:00:00Z",
        updated_at="2026-07-08T10:05:00Z",
        message_count=4,
        can_preview=True,
        can_import=True,
        can_resume=False,
    )

    assert ref.resume_reason is None
    assert ref.metadata == {}
    assert ref.status.value == "external_native"


def test_native_transcript_message_defaults_metadata():
    message = NativeTranscriptMessage(role="assistant", content="done")

    assert message.created_at is None
    assert message.metadata == {}


def test_native_execution_snapshot_round_trips_public_identity():
    snapshot = NativeExecutionSnapshot(
        id="nexec_123",
        harness_id="codex-cli",
        api_mode="v1",
        model="GigaChat-2-Max",
        native_home="/managed/codex",
        workspace="/repo",
        project_id="proj_repo",
        permission_mode="edit",
        tool_config_hash="sha256-config",
        created_at="2026-07-13T10:00:00+00:00",
    )

    payload = execution_snapshot_to_dict(snapshot)

    assert execution_snapshot_from_dict(payload) == snapshot
    assert payload["route_known"] is True
    assert payload["warnings"] == []
