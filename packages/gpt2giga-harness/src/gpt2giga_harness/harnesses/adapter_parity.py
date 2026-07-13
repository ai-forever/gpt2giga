"""Truthful capability contracts for built-in external CLI adapters."""

from __future__ import annotations

from gpt2giga_harness.types import (
    AdapterCapabilitySupport,
    AdapterSupportLevel,
)


def _claim(status: AdapterSupportLevel, detail: str) -> AdapterCapabilitySupport:
    return AdapterCapabilitySupport(status=status, detail=detail)


def _common_contract() -> dict[str, AdapterCapabilitySupport]:
    return {
        "headless_one_shot": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Runs one bounded CLI process with the normalized prompt, model, route, "
            "mode, stream, workspace, and attachment request fields.",
        ),
        "headless_structured_events": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Consumes the CLI JSON or JSONL surface and emits normalized Harness events.",
        ),
        "native_workspace": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Native process spawn passes through shared policy and edit mode uses an "
            "isolated Git worktree under the safe auto or worktree policy.",
        ),
        "native_route_snapshot": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Managed starts persist route, model, home, workspace, permission, and tool "
            "configuration identity through discovery and resume; legacy refs require "
            "an explicit reviewed route override.",
        ),
        "native_durable_lifecycle": _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "Native process ownership is in memory and cannot be truthfully recovered "
            "after owner restart.",
        ),
        "native_terminal_transport": _claim(
            AdapterSupportLevel.PARTIAL,
            "Provides PTY or pipes, stdin, polling output, and stop without durable "
            "cursor reconnect or resize.",
        ),
        "managed_mcp_native": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Reviewed managed MCP configuration can be applied to the project native home.",
        ),
        "managed_mcp_headless": _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "Headless execution creates a fresh temporary home and does not materialize "
            "the selected managed MCP snapshot into it.",
        ),
        "interactive_approvals": _claim(
            AdapterSupportLevel.DELEGATED,
            "Interactive approval prompts remain owned by the external CLI terminal.",
        ),
        "external_history": _claim(
            AdapterSupportLevel.PARTIAL,
            "Discovery and import are defensive but rely on heuristic, unversioned native "
            "history formats and coarse project identity.",
        ),
        "structured_app_server": _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "No supervised structured app-server transport is currently active.",
        ),
    }


def codex_adapter_capabilities() -> dict[str, AdapterCapabilitySupport]:
    """Return the current Codex CLI adapter contract."""
    contract = _common_contract()
    contract.update(
        {
            "headless_continuity": _claim(
                AdapterSupportLevel.PARTIAL,
                "Replays normalized history into a fresh codex exec --ephemeral prompt; "
                "native_session_id is not consumed and this is not native continuity.",
            ),
            "native_initial_prompt": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Delivers the composed prompt and attachment arguments in native argv.",
            ),
            "native_permission_mode": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Maps plan and read to read-only and edit to workspace-write sandbox "
                "argv; interactive approvals remain delegated to Codex.",
            ),
            "native_resume": _claim(
                AdapterSupportLevel.PARTIAL,
                "Managed resume works after history discovery reconciles a native session "
                "id; the execution snapshot is preserved once that id is reconciled.",
            ),
        }
    )
    return contract


def claude_adapter_capabilities() -> dict[str, AdapterCapabilitySupport]:
    """Return the current Claude Code adapter contract."""
    contract = _common_contract()
    contract.update(
        {
            "headless_continuity": _claim(
                AdapterSupportLevel.UNSUPPORTED,
                "Headless execution consumes only the current prompt; native_session_id "
                "and normalized history are not consumed.",
            ),
            "native_initial_prompt": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Delivers the composed prompt and attachment references in native argv.",
            ),
            "native_permission_mode": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Maps plan and read to Claude plan mode and edit to default permission "
                "mode; interactive approvals remain delegated to Claude Code.",
            ),
            "native_resume": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Uses a deterministic managed session name and preserves its immutable "
                "execution snapshot for immediate native resume.",
            ),
        }
    )
    return contract


def gemini_adapter_capabilities() -> dict[str, AdapterCapabilitySupport]:
    """Return the current Gemini CLI adapter contract."""
    contract = _common_contract()
    contract.update(
        {
            "headless_continuity": _claim(
                AdapterSupportLevel.UNSUPPORTED,
                "Headless execution consumes only the current prompt; native_session_id "
                "and normalized history are not consumed.",
            ),
            "native_initial_prompt": _claim(
                AdapterSupportLevel.SUPPORTED,
                "A capability-probed --prompt-interactive invocation delivers the "
                "composed prompt once and records a redaction-safe outcome.",
            ),
            "native_permission_mode": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Maps plan and read to Gemini plan approval mode and edit to default "
                "approval mode; interactive approvals remain delegated to Gemini CLI.",
            ),
            "native_resume": _claim(
                AdapterSupportLevel.PARTIAL,
                "Managed resume works after history discovery reconciles a native session "
                "id; the execution snapshot is preserved once that id is reconciled.",
            ),
        }
    )
    return contract
