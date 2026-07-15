import pytest

from gpt2giga_harness.gigachat_compatibility import (
    GIGACHAT_COMPATIBILITY_SCHEMA,
    gigachat_compatibility_evidence,
    gigachat_gateway_ready_event,
)
from gpt2giga_harness.provenance import build_run_provenance, run_provenance_to_dict
from gpt2giga_harness.runtime.models import RunStatus
from gpt2giga_harness.sessions.models import HarnessRun, HarnessStoredEvent
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability, HarnessRequest


def test_route_event_is_content_free_and_bound_to_selected_wire() -> None:
    event = gigachat_gateway_ready_event(
        HarnessRequest(
            prompt="secret prompt",
            model="GigaChat-2-Max",
            api_mode=GigaChatApiMode.V1,
            stream=True,
        ),
        harness_id="claude-code",
        sidecar_started=False,
    )

    assert event.type == "gigachat_gateway_ready"
    assert event.payload == {
        "schema": "gpt2giga-harness/gigachat-route-ready-v1",
        "gateway": "gpt2giga",
        "harness_id": "claude-code",
        "wire": "anthropic-messages",
        "api_mode": "v1",
        "requested_model": "GigaChat-2-Max",
        "stream_requested": True,
        "sidecar_started": False,
    }
    assert "secret prompt" not in str(event.payload)


def test_provenance_reports_only_observed_gigachat_semantics() -> None:
    run = _run()
    events = (
        _event(
            "route",
            "gigachat_gateway_ready",
            {
                "schema": "gpt2giga-harness/gigachat-route-ready-v1",
                "gateway": "gpt2giga",
                "harness_id": "codex-cli",
                "wire": "openai-responses",
                "api_mode": "v2",
                "requested_model": "GigaChat-2-Max",
                "stream_requested": True,
                "sidecar_started": True,
                "ignored_secret": "must-not-be-copied",
            },
        ),
        _event("delta", "message_delta", {"delta": "private response"}),
        _event("tool", "tool_call_started", {"arguments": "private arguments"}),
        _event("usage", "usage", {"total_tokens": 12}),
        _event("finished", "run_finished", {"status": "succeeded"}),
    )

    evidence = gigachat_compatibility_evidence(run, events)

    assert evidence is not None
    assert evidence["schema"] == GIGACHAT_COMPATIBILITY_SCHEMA
    assert evidence["route"] == {
        "gateway": "gpt2giga",
        "wire": "openai-responses",
        "api_mode": "v2",
        "requested_model": "GigaChat-2-Max",
        "readiness": "observed",
        "sidecar_started": True,
    }
    assert evidence["outcome"]["stream_observed"] is True
    assert evidence["outcome"]["tool_lifecycle_observed"] is True
    assert evidence["outcome"]["usage_observed"] is True
    assert evidence["outcome"]["error_observed"] is False
    assert len(evidence["manifest_sha256"]) == 64
    assert "private response" not in str(evidence)
    assert "private arguments" not in str(evidence)
    assert "must-not-be-copied" not in str(evidence)

    provenance = run_provenance_to_dict(build_run_provenance(run, events=events))
    assert provenance["gigachat_compatibility"] == evidence


@pytest.mark.parametrize(
    ("changed", "message"),
    (
        ({"api_mode": "v1"}, "api_mode"),
        ({"requested_model": "other-model"}, "requested_model"),
        ({"wire": "openai-chat"}, "wire"),
    ),
)
def test_gigachat_evidence_rejects_rebound_route_identity(changed, message) -> None:
    payload = {
        "schema": "gpt2giga-harness/gigachat-route-ready-v1",
        "gateway": "gpt2giga",
        "harness_id": "codex-cli",
        "wire": "openai-responses",
        "api_mode": "v2",
        "requested_model": "GigaChat-2-Max",
        "stream_requested": False,
        "sidecar_started": False,
        **changed,
    }

    with pytest.raises(ValueError, match=message):
        gigachat_compatibility_evidence(
            _run(),
            (_event("route", "gigachat_gateway_ready", payload),),
        )


def test_gigachat_evidence_is_absent_without_measured_route_event() -> None:
    assert gigachat_compatibility_evidence(_run(), ()) is None


def _run() -> HarnessRun:
    return HarnessRun(
        id="run_compat",
        session_id="session_compat",
        harness_id="codex-cli",
        status=RunStatus.SUCCEEDED,
        prompt="private prompt",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="plan",
        workspace=None,
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:01Z",
        started_at="2026-07-15T00:00:00Z",
        finished_at="2026-07-15T00:00:01Z",
    )


def _event(event_id: str, event_type: str, payload: dict) -> HarnessStoredEvent:
    return HarnessStoredEvent(
        id=event_id,
        session_id="session_compat",
        run_id="run_compat",
        type=event_type,
        message="private event message",
        payload=payload,
        created_at="2026-07-15T00:00:00Z",
    )
