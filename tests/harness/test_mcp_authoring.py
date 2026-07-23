from __future__ import annotations

import pytest

from gpt2giga_harness.mcp_authoring import (
    MCPAuthoringTransport,
    mcp_authoring_configuration_from_dict,
)


def _secret_ref(name: str, *, kind: str = "environment") -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": kind,
        "name": name,
        "service": None,
        "account": None,
        "expires_at": None,
        "cache_ttl_seconds": 0,
    }


def test_stdio_authoring_uses_explicit_argv_relative_cwd_and_secret_refs():
    configuration = mcp_authoring_configuration_from_dict(
        {
            "schema_version": 1,
            "transport": "stdio",
            "stdio": {
                "executable": "fixture-mcp",
                "argv": ["--stdio", "--quiet"],
                "cwd": "tools/server",
                "environment": {"MCP_TOKEN": _secret_ref("MCP_TOKEN")},
            },
        },
        target_id="codex-mcp",
    )

    assert configuration.transport is MCPAuthoringTransport.STDIO
    assert configuration.executable == "fixture-mcp"
    assert configuration.argv == ("--stdio", "--quiet")
    assert configuration.cwd == "tools/server"
    assert configuration.environment["MCP_TOKEN"].name == "MCP_TOKEN"


def test_remote_authoring_preserves_path_query_and_separates_authorization():
    configuration = mcp_authoring_configuration_from_dict(
        {
            "schema_version": 1,
            "transport": "streamable_http",
            "remote": {
                "url": "https://MCP.EXAMPLE:8443/v1/tools?tenant=fixture&mode=full",
                "headers": {"X-Tenant": _secret_ref("TENANT_ID")},
                "authorization": _secret_ref("MCP_AUTHORIZATION"),
            },
        },
        target_id="gemini-mcp",
    )

    assert configuration.url == (
        "https://mcp.example:8443/v1/tools?tenant=fixture&mode=full"
    )
    assert configuration.headers["Authorization"].name == "MCP_AUTHORIZATION"
    assert configuration.headers["X-Tenant"].name == "TENANT_ID"
    assert "secret-value" not in str(configuration.to_dict())


@pytest.mark.parametrize(
    ("target_id", "transport"),
    [
        ("codex-mcp", "sse"),
        ("claude-mcp", "sse"),
        ("harness-managed-mcp", "sse"),
    ],
)
def test_unsupported_sse_transport_fails_before_preview(target_id, transport):
    with pytest.raises(ValueError, match="does not support sse"):
        mcp_authoring_configuration_from_dict(
            {
                "schema_version": 1,
                "transport": transport,
                "remote": {"url": "https://mcp.example/sse", "headers": {}},
            },
            target_id=target_id,
        )


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        (
            {
                "schema_version": 1,
                "transport": "streamable_http",
                "remote": {"url": "http://mcp.example", "headers": {}},
            },
            "credential-free HTTPS",
        ),
        (
            {
                "schema_version": 1,
                "transport": "streamable_http",
                "remote": {"url": "https://user:pass@mcp.example", "headers": {}},
            },
            "credential-free HTTPS",
        ),
        (
            {
                "schema_version": 1,
                "transport": "stdio",
                "stdio": {
                    "executable": "sh",
                    "argv": ["-c", "curl https://example.invalid"],
                    "cwd": None,
                    "environment": {},
                },
            },
            "shell command strings",
        ),
        (
            {
                "schema_version": 1,
                "transport": "stdio",
                "stdio": {
                    "executable": "fixture-mcp",
                    "argv": [],
                    "cwd": "../outside",
                    "environment": {},
                },
            },
            "safe relative path",
        ),
    ],
)
def test_unsafe_authoring_input_fails_closed(configuration, message):
    with pytest.raises(ValueError, match=message):
        mcp_authoring_configuration_from_dict(
            configuration,
            target_id="codex-mcp",
        )


def test_native_targets_reject_non_environment_secret_backends():
    with pytest.raises(ValueError, match="environment-backed"):
        mcp_authoring_configuration_from_dict(
            {
                "schema_version": 1,
                "transport": "streamable_http",
                "remote": {
                    "url": "https://mcp.example",
                    "headers": {"Authorization": _secret_ref("MCP_KEY", kind="test")},
                },
            },
            target_id="claude-mcp",
        )


def test_remote_authoring_rejects_duplicate_headers_and_literal_secrets():
    with pytest.raises(ValueError, match="names contain duplicates"):
        mcp_authoring_configuration_from_dict(
            {
                "schema_version": 1,
                "transport": "streamable_http",
                "remote": {
                    "url": "https://mcp.example",
                    "headers": {
                        "X-Tenant": _secret_ref("TENANT_ID"),
                        "x-tenant": _secret_ref("OTHER_TENANT_ID"),
                    },
                },
            },
            target_id="codex-mcp",
        )

    with pytest.raises(ValueError, match="must use a secret reference"):
        mcp_authoring_configuration_from_dict(
            {
                "schema_version": 1,
                "transport": "streamable_http",
                "remote": {
                    "url": "https://mcp.example",
                    "headers": {"Authorization": "literal-secret"},
                },
            },
            target_id="codex-mcp",
        )


def test_claude_rejects_unrepresentable_stdio_cwd():
    with pytest.raises(ValueError, match="does not support an MCP stdio cwd"):
        mcp_authoring_configuration_from_dict(
            {
                "schema_version": 1,
                "transport": "stdio",
                "stdio": {
                    "executable": "fixture-mcp",
                    "argv": [],
                    "cwd": "tools/server",
                    "environment": {},
                },
            },
            target_id="claude-mcp",
        )
