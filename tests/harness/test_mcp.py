import json
import sys

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.mcp import (
    MCPProbeHistoryStore,
    MCPProbeStatus,
    build_mcp_inventory,
    descriptor_from_profile,
    mcp_descriptor_to_dict,
    mcp_probe_to_dict,
    probe_mcp_server,
)
from gpt2giga_harness.project import ProjectToolProfile
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.runtime.policy import ApprovalDecision, MCP_SERVER_PROBE_OWNER
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.tools import CompositeSecretResolver, EnvironmentSecretResolver


_FAKE_STDIO = r"""
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}, "resources": {}, "prompts": {}}, "serverInfo": {"name": "fake", "version": "1.0"}, "instructions": "Safe fake server"}
    elif method == "tools/list":
        result = {"tools": [{"name": "read_issue", "description": "Read one issue", "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}}, "annotations": {"readOnlyHint": True}}]}
    elif method == "resources/list":
        result = {"resources": [{"name": "issues", "uri": "issues://all", "mimeType": "application/json"}]}
    else:
        result = {"prompts": [{"name": "triage", "description": "Triage issue"}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
"""


def test_descriptor_accepts_timeout_longer_than_60_seconds():
    profile = ProjectToolProfile(
        enabled=True,
        config={
            "transport": "stdio",
            "command": "server",
            "timeout_seconds": 300,
        },
    )

    descriptor = descriptor_from_profile("long-running", profile)

    assert descriptor.timeout_seconds == 300


def test_stdio_descriptor_discovers_without_invoking_tools(tmp_path):
    profile = ProjectToolProfile(
        enabled=True,
        title="Fake MCP",
        config={
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", _FAKE_STDIO],
            "env": {"TOKEN": {"kind": "environment", "name": "MCP_TEST_TOKEN"}},
            "tool_policy": {"fake:read_issue": "allow"},
        },
    )
    descriptor = descriptor_from_profile("fake", profile)
    resolver = CompositeSecretResolver(
        (EnvironmentSecretResolver({"MCP_TEST_TOKEN": "do-not-persist"}),)
    )

    result = probe_mcp_server(descriptor, resolver)
    payload = mcp_probe_to_dict(result)
    history = MCPProbeHistoryStore(tmp_path)
    history.append(result)

    assert result.status is MCPProbeStatus.HEALTHY
    assert result.server_name == "fake"
    assert [tool.title for tool in result.tools] == ["read_issue"]
    assert result.tools[0].risk.value == "low"
    assert payload["resources"][0]["uri"] == "issues://all"
    assert "do-not-persist" not in json.dumps(payload)
    assert history.list("fake")[0]["status"] == "healthy"


def test_descriptor_requires_secret_references_for_sensitive_headers():
    profile = ProjectToolProfile(
        enabled=True,
        config={
            "transport": "streamable_http",
            "url": "https://mcp.example.test",
            "headers": {"Authorization": "Bearer literal-secret"},
        },
    )

    descriptors, errors = build_mcp_inventory({"remote": profile})

    assert descriptors == ()
    assert errors[0]["server_id"] == "remote"
    assert "must use secret_ref" in errors[0]["error"]

    unsafe_env = ProjectToolProfile(
        enabled=True,
        config={
            "transport": "stdio",
            "command": "server",
            "env": {"ACCESS_TOKEN": "literal-secret"},
        },
    )
    unsafe_args = ProjectToolProfile(
        enabled=True,
        config={
            "transport": "stdio",
            "command": "server",
            "args": ["--api-key=literal-secret"],
        },
    )

    assert build_mcp_inventory({"env": unsafe_env})[0] == ()
    assert build_mcp_inventory({"args": unsafe_args})[0] == ()


def test_streamable_http_discovery_accepts_json_and_session_header(monkeypatch):
    calls = []

    class Headers(dict):
        def get_content_type(self):
            return "application/json"

    class Response:
        def __init__(self, body, session_id=None):
            self.body = json.dumps(body).encode()
            self.headers = Headers()
            if session_id:
                self.headers["Mcp-Session-Id"] = session_id

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return self.body

    def fake_urlopen(request, timeout):
        if request.get_method() == "DELETE":
            calls.append(({"method": "DELETE"}, dict(request.header_items()), timeout))
            return Response({})
        payload = json.loads(request.data)
        calls.append((payload, dict(request.header_items()), timeout))
        if "id" not in payload:
            return Response({})
        results = {
            1: {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "remote-fake", "version": "2"},
            },
            2: {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]},
            3: {"resources": []},
            4: {"prompts": []},
        }
        return Response(
            {"jsonrpc": "2.0", "id": payload["id"], "result": results[payload["id"]]},
            session_id="session-1" if payload["id"] == 1 else None,
        )

    monkeypatch.setattr("gpt2giga_harness.mcp._open_http", fake_urlopen)
    descriptor = descriptor_from_profile(
        "remote",
        ProjectToolProfile(
            enabled=True,
            config={
                "transport": "streamable_http",
                "url": "https://mcp.example.test/rpc",
            },
        ),
    )

    result = probe_mcp_server(descriptor, CompositeSecretResolver())

    assert result.status is MCPProbeStatus.HEALTHY
    assert result.server_name == "remote-fake"
    assert result.tools[0].title == "search"
    assert len(calls) == 6
    assert calls[1][0]["method"] == "notifications/initialized"
    assert calls[2][1]["Mcp-session-id"] == "session-1"
    assert calls[2][1]["Mcp-protocol-version"] == "2025-11-25"
    assert calls[-1][0]["method"] == "DELETE"


def test_missing_secret_blocks_probe_without_leaking_reference_value():
    profile = ProjectToolProfile(
        enabled=True,
        config={
            "transport": "streamable_http",
            "url": "https://mcp.example.test",
            "headers": {
                "Authorization": {
                    "secret_ref": {"kind": "environment", "name": "MISSING_TOKEN"}
                }
            },
        },
    )
    descriptor = descriptor_from_profile("remote", profile)

    result = probe_mcp_server(
        descriptor,
        CompositeSecretResolver((EnvironmentSecretResolver({}),)),
    )

    assert result.status is MCPProbeStatus.BLOCKED
    assert result.error == "environment reference is missing: MISSING_TOKEN"
    assert "Authorization" not in json.dumps(mcp_probe_to_dict(result))
    safe = mcp_descriptor_to_dict(descriptor)
    assert safe["headers"]["Authorization"]["secret_ref"]["name"] == "MISSING_TOKEN"


def test_tools_api_lists_compatibility_and_policy_gates_untrusted_probe(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir(parents=True)
    escaped_script = json.dumps(_FAKE_STDIO)
    config_path.write_text(
        f"""
[project]
name = "mcp-api"

[tools.fake]
enabled = true
title = "Fake MCP"
harnesses = ["echo", "missing-harness"]
transport = "stdio"
command = {json.dumps(sys.executable)}
args = ["-c", {escaped_script}]
""",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    runtime = RuntimeCoordinationStore(data_dir)
    app = create_app(
        HarnessConfig(data_dir=str(data_dir)),
        registry=create_default_registry(include_entry_points=False),
        store=FilesystemHarnessSessionStore(data_dir),
        runtime_store=runtime,
    )
    client = TestClient(app)

    listed = client.get("/api/tool-servers", params={"workspace": str(tmp_path)})
    gated = client.post(
        "/api/tool-servers/fake/probe", json={"workspace": str(tmp_path)}
    )

    assert listed.status_code == 200
    row = listed.json()["servers"][0]
    assert row["descriptor"]["transport"] == "stdio"
    assert {item["status"] for item in row["compatibility"]} >= {
        "available",
        "missing",
    }
    assert gated.status_code == 202
    approval = gated.json()["approval"]
    assert approval["action"] == "mcp.server.start"
    assert approval["enforcement_owner"] == MCP_SERVER_PROBE_OWNER

    runtime.decide_approval_request(
        approval["id"],
        ApprovalDecision.ALLOW_PROJECT,
        project_expiry_seconds=3600,
    )
    probed = client.post(
        "/api/tool-servers/fake/probe", json={"workspace": str(tmp_path)}
    )

    assert probed.status_code == 200
    assert probed.json()["probe"]["status"] == "healthy"
    refreshed = client.get(
        "/api/tool-servers", params={"workspace": str(tmp_path)}
    ).json()
    assert refreshed["servers"][0]["latest_probe"]["server_name"] == "fake"
