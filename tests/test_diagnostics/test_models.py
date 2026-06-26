import pytest
from pydantic import ValidationError

from gpt2giga.diagnostics import (
    ADMIN_COMPAT_ANALYZE_ROUTE,
    CompatibilityAnalysis,
    ProtocolDiagnosticWarning,
    build_empty_analysis,
)
from gpt2giga.diagnostics.fields import build_field_compatibility
from gpt2giga.diagnostics.tools import build_builtin_tool_mapping
from gpt2giga.diagnostics.tools import build_tool_decision


def test_build_empty_analysis_defaults_are_safe():
    analysis = build_empty_analysis(
        protocol="openai",
        route="/v2/chat/completions",
        operation="chat_completions",
        backend_mode="gigachat_v2",
    )

    payload = analysis.to_json_dict()

    assert payload == {
        "protocol": "openai",
        "route": "/v2/chat/completions",
        "operation": "chat_completions",
        "backend_mode": "gigachat_v2",
        "model": {"pass_model": False},
        "fields": {
            "supported": [],
            "accepted_ignored": [],
            "accepted_diagnostic_only": [],
            "approximated": [],
            "rejected": [],
        },
        "tools": {
            "user_functions": [],
            "mapped_builtin_tools": [],
            "unsupported_tools": [],
            "accepted_ignored": [],
            "rejected": [],
            "details": [],
        },
        "security": {
            "headers_redacted": [],
            "query_redacted": [],
            "body_fields_redacted": [],
        },
        "warnings": [],
    }


def test_compatibility_analysis_serializes_tool_aliases_and_warnings():
    analysis = CompatibilityAnalysis(
        protocol="gemini",
        route="/v1beta/models/gemini-pro:generateContent",
        operation="generate_content",
        backend_mode="gigachat_v2",
        fields=build_field_compatibility(
            supported=["contents", "tools", "contents"],
            accepted_ignored=["safetySettings"],
            approximated=["countTokens"],
        ),
        tools={
            "user_functions": ["search_docs"],
            "mapped_builtin_tools": [
                build_builtin_tool_mapping(
                    from_name="googleSearch",
                    to_name="web_search",
                    reason="provider_alias",
                )
            ],
            "unsupported_tools": ["fileSearch"],
            "details": [
                build_tool_decision(
                    source="gemini.tools",
                    category="provider_builtin",
                    decision="mapped",
                    name="googleSearch",
                    target="web_search",
                    reason="provider_alias",
                    field="tools[0].googleSearch",
                )
            ],
            "mapping_disabled": False,
        },
        security={
            "headers_redacted": ["x-goog-api-key"],
            "query_redacted": ["key"],
        },
        warnings=[
            ProtocolDiagnosticWarning(
                code="unsupported_tool",
                field="tools[1]",
                message="fileSearch is accepted for diagnostics only",
            )
        ],
    )

    payload = analysis.to_json_dict()

    assert payload["fields"]["supported"] == ["contents", "tools"]
    assert payload["tools"]["mapped_builtin_tools"] == [
        {
            "from": "googleSearch",
            "to": "web_search",
            "reason": "provider_alias",
        }
    ]
    assert payload["tools"]["details"] == [
        {
            "source": "gemini.tools",
            "category": "provider_builtin",
            "decision": "mapped",
            "name": "googleSearch",
            "target": "web_search",
            "reason": "provider_alias",
            "field": "tools[0].googleSearch",
        }
    ]
    assert payload["warnings"] == [
        {
            "code": "unsupported_tool",
            "message": "fileSearch is accepted for diagnostics only",
            "severity": "warning",
            "field": "tools[1]",
        }
    ]
    assert "content" not in payload


def test_compatibility_analysis_rejects_unknown_extra_fields():
    with pytest.raises(ValidationError):
        CompatibilityAnalysis(
            protocol="openai",
            route="/responses",
            operation="responses",
            prompt="raw secret content",
        )


def test_admin_compat_route_constant():
    assert ADMIN_COMPAT_ANALYZE_ROUTE == "/_admin/compat/analyze"
