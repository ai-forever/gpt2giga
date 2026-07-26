import json
from pathlib import Path

import pytest

from gpt2giga_harness.product_capabilities import (
    AdmissionStatus,
    AuthorityLevel,
    CapabilityRequest,
    IntegrationLifecycle,
    ProductCapabilityError,
    TaskIntent,
    TitleProvenance,
    ToolCapability,
    TransportCapability,
    admit_capability_request,
    capability_manifest,
    legacy_mode_compatibility_receipt,
    migrate_legacy_capability_request,
)

FIXTURES = Path(__file__).parent / "fixtures" / "product_capabilities"


def test_manifest_is_versioned_and_keeps_transport_out_of_task_vocabulary():
    manifest = capability_manifest()

    assert manifest["schema_version"] == 1
    assert manifest["task_intents"] == ["ask", "review", "change"]
    assert manifest["authority_levels"] == ["read_only", "workspace_write"]
    assert "native_structured" not in manifest["task_intents"]
    assert set(manifest["title_provenance"]) == {item.value for item in TitleProvenance}
    assert set(manifest["integration_lifecycle"]) == {
        item.value for item in IntegrationLifecycle
    }
    assert [item["value"] for item in manifest["legacy_mode_receipts"]] == [
        "plan",
        "read",
        "edit",
    ]


@pytest.mark.parametrize(
    ("mode", "intent", "authority"),
    [
        ("plan", TaskIntent.ASK, AuthorityLevel.READ_ONLY),
        ("read", TaskIntent.REVIEW, AuthorityLevel.READ_ONLY),
        ("edit", TaskIntent.CHANGE, AuthorityLevel.WORKSPACE_WRITE),
    ],
)
def test_legacy_modes_have_explicit_compatibility_mappings(
    mode,
    intent,
    authority,
):
    request = migrate_legacy_capability_request(
        {
            "mode": mode,
            "execution_transport": "native_structured",
            "stream": True,
        }
    )

    assert request.intent is intent
    assert request.authority is authority
    assert request.required_transports == {
        TransportCapability.STRUCTURED_SESSION,
        TransportCapability.STREAMING_EVENTS,
    }
    assert request.compatibility_notes


def test_headless_does_not_guess_a_transport_and_unknown_values_fail_closed():
    with pytest.raises(
        ProductCapabilityError,
        match="does not prove an execution transport",
    ):
        migrate_legacy_capability_request(
            {"mode": "read", "invocation_mode": "headless"}
        )
    with pytest.raises(ProductCapabilityError, match="unknown legacy"):
        migrate_legacy_capability_request({"mode": "act"})
    with pytest.raises(ProductCapabilityError, match="unknown legacy"):
        migrate_legacy_capability_request(
            {"mode": "read", "execution_transport": "future_transport"}
        )
    with pytest.raises(ProductCapabilityError, match="must be a boolean"):
        migrate_legacy_capability_request({"mode": "read", "stream": "false"})


def test_legacy_mode_receipts_keep_intent_distinct_and_unknown_authority_safe():
    plan = legacy_mode_compatibility_receipt("plan")
    review = legacy_mode_compatibility_receipt("read")
    unknown = legacy_mode_compatibility_receipt("act")

    assert plan["authority"] == review["authority"] == "read_only"
    assert plan["artifacts"] == ["plan"]
    assert review["artifacts"] == ["review_findings"]
    assert unknown["status"] == "ambiguous"
    assert unknown["intent"] == "ask"
    assert unknown["authority"] == "read_only"
    assert unknown["warning"] == "legacy_mode_unmapped_read_only"
    assert unknown["removal"] == {
        "earliest_version": "1.0.0",
        "condition": (
            "one_released_schema_v1_window_and_zero_tracked_callers_or_saved_state"
        ),
    }


def test_legacy_mode_request_receipts_match_golden_fixtures():
    fixtures = json.loads(
        (FIXTURES / "legacy_mode_aliases.json").read_text(encoding="utf-8")
    )

    assert [
        legacy_mode_compatibility_receipt(item["request"]["mode"]) for item in fixtures
    ] == [item["receipt"] for item in fixtures]


def test_read_only_authority_rejects_write_tool_before_admission():
    with pytest.raises(ProductCapabilityError, match="workspace-write"):
        CapabilityRequest(
            intent=TaskIntent.REVIEW,
            authority=AuthorityLevel.READ_ONLY,
            required_tools=frozenset({ToolCapability.FILESYSTEM_WRITE}),
        )


def test_admission_reports_available_degraded_and_blocked_truthfully():
    request = CapabilityRequest(
        intent=TaskIntent.CHANGE,
        authority=AuthorityLevel.WORKSPACE_WRITE,
        required_transports=frozenset(
            {
                TransportCapability.STRUCTURED_SESSION,
                TransportCapability.STREAMING_EVENTS,
            }
        ),
        required_tools=frozenset(
            {ToolCapability.FILESYSTEM_WRITE, ToolCapability.NETWORK}
        ),
    )

    available = admit_capability_request(
        request,
        available_transports=request.required_transports,
        available_tools=request.required_tools,
    )
    assert available.status is AdmissionStatus.AVAILABLE
    assert available.to_dict() == {
        "schema_version": 1,
        "available": True,
        "degraded": False,
        "blocked": False,
        "why": ["capabilities_admitted"],
        "recovery": [],
        "diagnostics": {},
    }

    degraded = admit_capability_request(
        request,
        available_transports={TransportCapability.STRUCTURED_SESSION},
        degraded_transports={TransportCapability.STREAMING_EVENTS},
        available_tools={ToolCapability.FILESYSTEM_WRITE},
        degraded_tools={ToolCapability.NETWORK},
    )
    assert degraded.degraded is True
    assert degraded.why == (
        "tool_degraded:network",
        "transport_degraded:streaming_events",
    )

    blocked = admit_capability_request(
        request,
        available_transports={TransportCapability.STRUCTURED_SESSION},
        available_tools={ToolCapability.FILESYSTEM_WRITE},
        diagnostics={"provider": "codex", "evidence": "missing"},
    )
    assert blocked.blocked is True
    assert blocked.why == (
        "tool_unavailable:network",
        "transport_unavailable:streaming_events",
    )
    assert blocked.to_dict()["diagnostics"] == {
        "provider": "codex",
        "evidence": "missing",
    }


def test_unknown_evidence_values_are_never_treated_as_supported():
    request = CapabilityRequest(
        intent=TaskIntent.ASK,
        authority=AuthorityLevel.READ_ONLY,
    )

    with pytest.raises(ProductCapabilityError, match="transport capability"):
        admit_capability_request(
            request,
            available_transports={"future_transport"},
            available_tools=(),
        )
