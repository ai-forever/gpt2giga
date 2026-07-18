from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

sdk = pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (  # noqa: E402
    ClaudeSDKClient,
    DeferredToolUse,
    HookMatcher,
    PermissionResultAllow,
    ResultMessage,
    Transport,
)

from gpt2giga_harness.claude_agent_sdk_poc import (  # noqa: E402
    ClaudeAgentSdkPocError,
    ClaudeSdkAuthMode,
    build_claude_agent_sdk_options,
    normalize_claude_sdk_message,
    permission_binding,
    probe_installed_claude_agent_sdk,
    review_claude_agent_sdk_surface,
)


FIXTURE = Path("tests/fixtures/harness_cli/claude/2.1.212/agent_sdk_surface.json")
_CLOSED = object()


def _surface_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


class _ScriptedSdkTransport(Transport):
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        self.writes: list[dict[str, Any]] = []
        self.permission_response: dict[str, Any] | None = None
        self.hook_response: dict[str, Any] | None = None
        self.hook_callback_id: str | None = None
        self.query_count = 0
        self.ready = False

    async def connect(self) -> None:
        self.ready = True

    async def write(self, data: str) -> None:
        for line in data.splitlines():
            if not line:
                continue
            message = json.loads(line)
            self.writes.append(message)
            if message.get("type") == "control_request":
                await self._handle_client_control(message)
            elif message.get("type") == "control_response":
                await self._handle_callback_response(message)
            elif message.get("type") == "user":
                await self._handle_query()

    def read_messages(self):
        return self._read_messages()

    async def _read_messages(self):
        while True:
            message = await self.incoming.get()
            if message is _CLOSED:
                return
            yield message

    async def close(self) -> None:
        if self.ready:
            self.ready = False
            await self.incoming.put(_CLOSED)

    def is_ready(self) -> bool:
        return self.ready

    async def end_input(self) -> None:
        return None

    async def _handle_client_control(self, message: dict[str, Any]) -> None:
        request = message["request"]
        subtype = request["subtype"]
        response: dict[str, Any] = {}
        if subtype == "initialize":
            hooks = request["hooks"]["PreToolUse"]
            self.hook_callback_id = hooks[0]["hookCallbackIds"][0]
            response = {"commands": [], "output_style": "fixture"}
        elif subtype == "mcp_status":
            response = {
                "mcpServers": [
                    {"name": "fixture", "status": "connected"},
                ]
            }
        await self.incoming.put(
            {
                "type": "control_response",
                "response": {
                    "subtype": "success",
                    "request_id": message["request_id"],
                    "response": response,
                },
            }
        )

    async def _handle_query(self) -> None:
        self.query_count += 1
        if self.query_count == 1:
            await self._complete_turn("fixture first turn")
            return
        await self.incoming.put(
            {
                "type": "control_request",
                "request_id": "provider-permission-2",
                "request": {
                    "subtype": "can_use_tool",
                    "tool_name": "Bash",
                    "input": {"command": "permission-raw-canary"},
                    "tool_use_id": "tool-2",
                },
            }
        )

    async def _handle_callback_response(self, message: dict[str, Any]) -> None:
        request_id = message["response"]["request_id"]
        if request_id == "provider-permission-2":
            self.permission_response = message
            assert self.hook_callback_id is not None
            await self.incoming.put(
                {
                    "type": "control_request",
                    "request_id": "provider-hook-2",
                    "request": {
                        "subtype": "hook_callback",
                        "callback_id": self.hook_callback_id,
                        "input": {
                            "hook_event_name": "PreToolUse",
                            "tool_name": "Bash",
                            "tool_input": {"command": "hook-raw-canary"},
                        },
                        "tool_use_id": "tool-2",
                    },
                }
            )
        elif request_id == "provider-hook-2":
            self.hook_response = message
            await self._complete_turn("fixture second turn", include_tool=True)

    async def _complete_turn(self, text: str, *, include_tool: bool = False) -> None:
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if include_tool:
            content.append(
                {
                    "type": "tool_use",
                    "id": "tool-2",
                    "name": "Bash",
                    "input": {"command": "message-raw-canary"},
                }
            )
        await self.incoming.put(
            {
                "type": "assistant",
                "message": {"model": "fixture", "content": content},
                "session_id": "11111111-1111-4111-8111-111111111111",
            }
        )
        await self.incoming.put(
            {
                "type": "result",
                "subtype": "success",
                "duration_ms": 1,
                "duration_api_ms": 1,
                "is_error": False,
                "num_turns": 1,
                "session_id": "11111111-1111-4111-8111-111111111111",
                "stop_reason": "end_turn",
                "result": "result-raw-canary",
            }
        )


def test_reviewed_surface_selects_system_cli_and_blocks_embedded_driver():
    evidence = _surface_fixture()
    probe = review_claude_agent_sdk_surface(
        adapter_version="0.1.0b1",
        **evidence,
    )

    assert probe.sdk_version == "0.2.122"
    assert probe.system_cli_version == "2.1.212"
    assert probe.bundled_cli_version == "2.1.214 (Claude Code)"
    assert probe.selected_cli_source == "explicit_system_cli_path"
    assert probe.python_defer_shape is True
    assert probe.capability_snapshot.live_approvals is True
    assert probe.capability_snapshot.durable_approval is False
    assert probe.capability_snapshot.resume is True
    assert probe.capability_snapshot.fork is True
    assert probe.capability_snapshot.dynamic_mcp is True
    assert probe.capability_snapshot.provider_ui_handoff is False
    assert probe.exit_decision.embedded_driver_ready is False
    assert probe.exit_decision.subscription_embedding_allowed is False
    assert probe.exit_decision.blockers == ("python_durable_approval_not_documented",)

    incomplete = dict(evidence)
    incomplete["client_members"] = ["connect"]
    with pytest.raises(ClaudeAgentSdkPocError, match="reviewed surface is missing"):
        review_claude_agent_sdk_surface(
            adapter_version="0.1.0b1",
            **incomplete,
        )


def test_installed_optional_sdk_contains_bundled_cli_without_selecting_it():
    bundled = Path(sdk.__file__).resolve().parent / "_bundled" / "claude"
    probe = probe_installed_claude_agent_sdk(
        system_cli_path=bundled,
        adapter_version="0.1.0b1",
        python_durable_defer_documented=False,
    )

    assert probe.sdk_version == "0.2.122"
    assert probe.system_cli_version == "2.1.214"
    assert probe.bundled_cli_version == "2.1.214 (Claude Code)"
    assert probe.selected_cli_source == "explicit_system_cli_path"


def test_options_isolate_auth_and_bind_resume_fork_to_system_cli(tmp_path):
    options = build_claude_agent_sdk_options(
        system_cli_path="/fixture/system/claude",
        cwd=tmp_path,
        managed_config_dir=tmp_path / "managed",
        auth_mode=ClaudeSdkAuthMode.API_KEY,
        api_key="api-key-raw-canary",
        resume="11111111-1111-4111-8111-111111111111",
        fork_session=True,
        mcp_servers={"fixture": {"type": "http", "url": "https://fixture"}},
    )

    assert options.cli_path == Path("/fixture/system/claude")
    assert options.resume == "11111111-1111-4111-8111-111111111111"
    assert options.fork_session is True
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.extra_args == {"bare": None}
    assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert options.env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "managed")
    assert options.env["ANTHROPIC_API_KEY"] == "api-key-raw-canary"

    with pytest.raises(ClaudeAgentSdkPocError, match="prior provider approval"):
        build_claude_agent_sdk_options(
            system_cli_path="/fixture/system/claude",
            cwd=tmp_path,
            managed_config_dir=tmp_path / "managed",
            auth_mode=ClaudeSdkAuthMode.CLAUDE_AI_SUBSCRIPTION,
        )
    with pytest.raises(ClaudeAgentSdkPocError, match="OAuth tokens"):
        build_claude_agent_sdk_options(
            system_cli_path="/fixture/system/claude",
            cwd=tmp_path,
            managed_config_dir=tmp_path / "managed",
            auth_mode=ClaudeSdkAuthMode.BEDROCK,
            provider_env={
                "CLAUDE_CODE_USE_BEDROCK": "1",
                "CLAUDE_CODE_OAUTH_TOKEN": "oauth-raw-canary",
            },
        )


async def test_sdk_client_proves_multiturn_interrupt_permission_hooks_and_mcp(tmp_path):
    permission_bindings = []
    hook_bindings = []

    async def can_use_tool(tool_name, tool_input, context):
        permission_bindings.append(
            permission_binding(
                tool_name=tool_name,
                tool_input=tool_input,
                tool_use_id=context.tool_use_id,
            )
        )
        return PermissionResultAllow()

    async def pre_tool_hook(input_data, tool_use_id, context):
        del context
        hook_bindings.append(
            permission_binding(
                tool_name=input_data["tool_name"],
                tool_input=input_data["tool_input"],
                tool_use_id=tool_use_id,
            )
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

    options = build_claude_agent_sdk_options(
        system_cli_path="/fixture/system/claude",
        cwd=tmp_path,
        managed_config_dir=tmp_path / "managed",
        auth_mode=ClaudeSdkAuthMode.API_KEY,
        api_key="api-key-raw-canary",
        can_use_tool=can_use_tool,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[pre_tool_hook]),
            ]
        },
        mcp_servers={"fixture": {"type": "http", "url": "https://fixture"}},
    )
    transport = _ScriptedSdkTransport()
    client = ClaudeSDKClient(options=options, transport=transport)

    await client.connect()
    await client.query("first prompt raw canary")
    first = [message async for message in client.receive_response()]
    assert first[-1].session_id == "11111111-1111-4111-8111-111111111111"

    status = await client.get_mcp_status()
    assert status == {"mcpServers": [{"name": "fixture", "status": "connected"}]}
    await client.interrupt()

    await client.query("second prompt raw canary")
    second = [message async for message in client.receive_response()]
    normalized = [
        event for message in second for event in normalize_claude_sdk_message(message)
    ]
    await client.disconnect()

    assert len(permission_bindings) == 1
    assert permission_bindings[0].tool_use_id == "tool-2"
    assert len(hook_bindings) == 1
    assert transport.permission_response is not None
    assert transport.hook_response is not None
    assert transport.query_count == 2
    assert [event.type for event in normalized] == [
        "output_delta",
        "tool_approval_pending",
        "turn_completed",
    ]
    serialized = json.dumps(
        [dict(event.payload) for event in normalized], sort_keys=True
    )
    assert "message-raw-canary" not in serialized
    assert "result-raw-canary" not in serialized
    assert "input_hash" in serialized
    control_subtypes = {
        item["request"]["subtype"]
        for item in transport.writes
        if item.get("type") == "control_request"
    }
    assert {"initialize", "interrupt", "mcp_status"}.issubset(control_subtypes)


def test_deferred_result_normalization_is_content_free_but_not_durable_proof():
    message = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="11111111-1111-4111-8111-111111111111",
        stop_reason="tool_deferred",
        deferred_tool_use=DeferredToolUse(
            id="tool-3",
            name="AskUserQuestion",
            input={"question": "deferred-raw-canary"},
        ),
    )

    event = normalize_claude_sdk_message(message)[0]
    serialized = json.dumps(dict(event.payload), sort_keys=True)
    assert event.type == "turn_completed"
    assert event.payload["deferred_tool"]["tool_call_id"] == "tool-3"
    assert "deferred-raw-canary" not in serialized
    assert "input_hash" in serialized
