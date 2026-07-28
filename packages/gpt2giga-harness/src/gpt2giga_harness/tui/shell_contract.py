"""Semantic contract for the minimal chat-first TUI shell."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any


TUI_SHELL_SCHEMA_VERSION = 1

DEFAULT_SHELL_REGIONS = (
    "compact_context",
    "transcript",
    "contextual_decision",
    "composer",
)

CONTEXT_DRAWER_SURFACES = (
    "tasks",
    "processes",
    "preferences",
    "environment",
    "integrations",
    "diagnostics",
    "advanced_transport",
)

G2_JOURNEY_DISPOSITIONS = MappingProxyType(
    {
        "ask-question": "default_shell",
        "review-repository": "default_shell",
        "make-isolated-change": "default_shell_with_evidence_and_approval",
        "connect-or-disable-mcp": "integration_context_handoff",
        "run-or-author-automation": "external_surface_not_claimed",
        "provider-login-guidance": "provider_owned_handoff_not_claimed",
        "request-network-or-github-grant": "contextual_decision",
        "recover-disconnect": "default_shell_with_authoritative_resnapshot",
    }
)


def minimal_shell_contract() -> dict[str, Any]:
    """Return a copy-safe, source-derived information architecture contract."""
    return {
        "schema_version": TUI_SHELL_SCHEMA_VERSION,
        "default_regions": list(DEFAULT_SHELL_REGIONS),
        "context_drawer": list(CONTEXT_DRAWER_SURFACES),
        "journey_dispositions": dict(G2_JOURNEY_DISPOSITIONS),
        "claims": {
            "authority_owner": "existing_application_services",
            "second_frontend": False,
            "event_delivery_changed": False,
            "differential_rendering_changed": False,
        },
    }
