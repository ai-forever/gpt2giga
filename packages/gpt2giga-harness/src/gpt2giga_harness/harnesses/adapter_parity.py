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
        "cli_capability_probe": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Uses bounded isolated --version and --help probes, caches evidence by "
            "command and version, and rejects binaries missing required adapter flags.",
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
            AdapterSupportLevel.SUPPORTED,
            "Persists owner leases, heartbeats, cancellation, timeouts, bounded terminal "
            "cursors, and explicit non-adopting recovery after owner restart.",
        ),
        "native_terminal_transport": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Provides authenticated cursor-based streaming, reconnect, bounded polling "
            "fallback, terminal resize, stdin, and stop for owned native processes.",
        ),
        "managed_mcp_native": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Reviewed managed MCP configuration can be applied to the project native home.",
        ),
        "managed_mcp_headless": _claim(
            AdapterSupportLevel.SUPPORTED,
            "Freezes selected trusted project MCP descriptors into an immutable "
            "redaction-safe snapshot, resolves secret references only at subprocess "
            "construction, and materializes it into the active temporary CLI home.",
        ),
        "attachment_transport": _claim(
            AdapterSupportLevel.PARTIAL,
            "Attachment delivery is exposed per kind and invocation mode; path-only "
            "delivery remains explicit when no richer CLI capability is proven.",
        ),
        "interactive_approvals": _claim(
            AdapterSupportLevel.DELEGATED,
            "Interactive approval prompts remain owned by the external CLI terminal.",
        ),
        "external_history": _claim(
            AdapterSupportLevel.PARTIAL,
            "Discovery and import remain heuristic and use coarse project identity, while "
            "supported shapes are frozen in versioned additive-field-tolerant fixtures.",
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
                AdapterSupportLevel.SUPPORTED,
                "Uses a supervised Codex app-server thread for repeated turns when the "
                "capability probe succeeds; codex exec history replay remains an "
                "explicit degraded fallback.",
            ),
            "structured_app_server": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Maps Harness sessions, turns, forks, cancellation, and reconnect to "
                "the version-probed Codex app-server JSON-RPC protocol.",
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
            "agent_profile_options": _claim(
                AdapterSupportLevel.PARTIAL,
                "Applies model, mode, route, workspace, durable timeout/retry budgets, "
                "capability-proven reasoning effort, and managed MCP tool ids; token "
                "limits remain unsupported before queueing.",
            ),
            "attachment_transport": _claim(
                AdapterSupportLevel.SUPPORTED,
                "Images use the version-probed --image flag for one-shot and native "
                "CLI runs; other files remain path references and structured "
                "app-server image transport is not claimed.",
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
            "agent_profile_options": _claim(
                AdapterSupportLevel.PARTIAL,
                "Applies model, mode, route, workspace, durable timeout/retry budgets, "
                "capability-proven effort, allowed/disallowed tool restrictions, and "
                "managed MCP tool ids; token limits remain unsupported before queueing.",
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
            "agent_profile_options": _claim(
                AdapterSupportLevel.PARTIAL,
                "Applies model, mode, route, workspace, durable timeout/retry budgets, "
                "and managed MCP tool ids; reasoning effort and token limits are "
                "reported unsupported before queueing.",
            ),
        }
    )
    return contract
