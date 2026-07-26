"""Generated public matrices for adapter and agent-surface contracts."""

from __future__ import annotations

from typing import Any, Mapping

from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.types import (
    AdapterSupportLevel,
    HeadlessContinuationStrategy,
    spec_to_dict,
)

CAPABILITY_MATRIX_SCHEMA_VERSION = 1
CAPABILITY_MATRIX_SOURCE = "HarnessSpec.adapter_capabilities"
AGENT_SURFACE_MATRIX_SOURCE = (
    "HarnessSpec+HarnessSpec.adapter_capabilities+agent_surface_contracts_v1"
)
AGENT_SURFACE_IDS = (
    "direct-chat",
    "codex-cli",
    "claude-code",
    "gemini-cli",
)
AGENT_SURFACE_CAPABILITIES = (
    "execution_route",
    "provider_authentication",
    "session_continuity",
    "cancellation",
    "harness_and_provider_approvals",
    "managed_mcp",
    "skills_and_plugins",
    "gigachat_builtin_tools",
    "isolated_edit_delivery",
    "multi_agent_delivery",
    "usage_and_monetary_cost",
    "structured_evidence",
    "cross_provider_session_transfer",
    "hidden_reasoning_transfer",
)


def build_adapter_capability_matrix(registry: HarnessRegistry) -> dict[str, Any]:
    """Build a deterministic matrix from declared adapter capability contracts."""
    adapters: list[dict[str, Any]] = []
    capability_ids: set[str] = set()

    for harness in sorted(registry.list(), key=lambda item: item.spec().id):
        spec = spec_to_dict(harness.spec())
        claims = spec["adapter_capabilities"]
        if not claims:
            continue
        capability_ids.update(claims)
        adapters.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "protocol_capability_scope": spec["protocol_capability_scope"],
                "claims": claims,
            }
        )

    capabilities = []
    for capability_id in sorted(capability_ids):
        capabilities.append(
            {
                "id": capability_id,
                "support": {
                    adapter["id"]: adapter["claims"].get(capability_id)
                    for adapter in adapters
                },
            }
        )

    return {
        "schema_version": CAPABILITY_MATRIX_SCHEMA_VERSION,
        "generated_from": CAPABILITY_MATRIX_SOURCE,
        "built_in_only": True,
        "adapters": [
            {
                "id": adapter["id"],
                "title": adapter["title"],
                "protocol_capability_scope": adapter["protocol_capability_scope"],
            }
            for adapter in adapters
        ],
        "capabilities": capabilities,
    }


def render_adapter_capability_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    """Render a reviewable Markdown view without creating a second source of truth."""
    adapters = list(matrix.get("adapters", ()))
    capabilities = list(matrix.get("capabilities", ()))
    lines = [
        "# Harness adapter capability matrix",
        "",
        (
            "> Generated from `HarnessSpec.adapter_capabilities`; regenerate this "
            "output instead of editing it."
        ),
        "",
        "| Capability | "
        + " | ".join(_markdown_text(adapter["title"]) for adapter in adapters)
        + " |",
        "| --- | " + " | ".join("---" for _ in adapters) + " |",
    ]
    for capability in capabilities:
        support = capability["support"]
        lines.append(
            "| `"
            + _markdown_text(capability["id"])
            + "` | "
            + " | ".join(
                _claim_status(support.get(adapter["id"])) for adapter in adapters
            )
            + " |"
        )

    lines.extend(["", "## Contract evidence", ""])
    for capability in capabilities:
        lines.extend([f"### `{_markdown_text(capability['id'])}`", ""])
        support = capability["support"]
        for adapter in adapters:
            claim = support.get(adapter["id"])
            if not isinstance(claim, Mapping):
                lines.append(f"- **{_markdown_text(adapter['title'])}:** undeclared")
                continue
            lines.append(
                f"- **{_markdown_text(adapter['title'])}:** "
                f"{_markdown_text(claim.get('status', 'undeclared'))} — "
                f"{_markdown_text(claim.get('detail', ''))}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_agent_surface_capability_matrix(
    registry: HarnessRegistry,
) -> dict[str, Any]:
    """Build the user-facing Direct Chat and coding-agent capability matrix."""
    surfaces: list[dict[str, Any]] = []
    for harness_id in AGENT_SURFACE_IDS:
        spec = spec_to_dict(registry.get(harness_id).spec())
        surfaces.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "kind": spec["kind"],
                "support": _agent_surface_support(spec),
            }
        )

    return {
        "schema_version": CAPABILITY_MATRIX_SCHEMA_VERSION,
        "generated_from": AGENT_SURFACE_MATRIX_SOURCE,
        "built_in_only": True,
        "surfaces": [
            {
                "id": surface["id"],
                "title": surface["title"],
                "kind": surface["kind"],
            }
            for surface in surfaces
        ],
        "capabilities": [
            {
                "id": capability_id,
                "support": {
                    surface["id"]: surface["support"][capability_id]
                    for surface in surfaces
                },
            }
            for capability_id in AGENT_SURFACE_CAPABILITIES
        ],
    }


def render_agent_surface_capability_matrix_markdown(
    matrix: Mapping[str, Any],
) -> str:
    """Render the source-derived agent surface matrix as reviewable Markdown."""
    surfaces = list(matrix.get("surfaces", ()))
    capabilities = list(matrix.get("capabilities", ()))
    lines = [
        "# GigaLoom agent surface capability matrix",
        "",
        (
            "> Generated by `giga harness capabilities --agents` from built-in "
            "`HarnessSpec` and adapter contracts. Regenerate this file instead of "
            "editing capability cells."
        ),
        "",
        "| Capability | "
        + " | ".join(_markdown_text(surface["title"]) for surface in surfaces)
        + " |",
        "| --- | " + " | ".join("---" for _ in surfaces) + " |",
    ]
    for capability in capabilities:
        support = capability["support"]
        lines.append(
            "| `"
            + _markdown_text(capability["id"])
            + "` | "
            + " | ".join(
                _claim_status(support.get(surface["id"])) for surface in surfaces
            )
            + " |"
        )

    lines.extend(["", "## Contract evidence", ""])
    for capability in capabilities:
        lines.extend([f"### `{_markdown_text(capability['id'])}`", ""])
        support = capability["support"]
        for surface in surfaces:
            claim = support.get(surface["id"])
            lines.append(
                f"- **{_markdown_text(surface['title'])}:** "
                f"{_claim_status(claim)} — "
                f"{_markdown_text(_claim_detail(claim))}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _agent_surface_support(spec: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    harness_id = str(spec["id"])
    is_direct = harness_id == "direct-chat"
    adapter_claims = _mapping(spec.get("adapter_capabilities"))
    supported_tools = tuple(spec.get("supported_builtin_tools") or ())

    continuity = _continuity_claim(spec, adapter_claims, is_direct=is_direct)
    cancellation = _boolean_claim(
        bool(spec.get("supports_cancellation")),
        supported=(
            "Harness exposes cooperative cancellation for the admitted route; "
            "already-completed provider side effects are not rolled back."
        ),
        unsupported="This surface has no admitted cancellation contract.",
    )
    structured_evidence = _structured_evidence_claim(
        spec,
        adapter_claims,
        is_direct=is_direct,
    )

    if is_direct:
        execution_route = _claim(
            AdapterSupportLevel.SUPPORTED,
            "Calls GigaChat through the local gpt2giga Chat Completions route; "
            "it is a model conversation, not a repository coding-agent loop.",
        )
        authentication = _claim(
            AdapterSupportLevel.DELEGATED,
            "The gateway owns its SecretRef or local proxy credential boundary. "
            "GigaLoom does not turn this into a native provider account login.",
        )
        managed_mcp = _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "Direct Chat does not project managed MCP descriptors as GigaChat "
            "built-in tools.",
        )
        builtin_tools = _claim(
            AdapterSupportLevel.SUPPORTED,
            "The admitted GigaChat built-ins are: "
            + ", ".join(str(item) for item in supported_tools)
            + ".",
        )
        isolated_edits = _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "Direct Chat has no repository edit loop or isolated patch-delivery "
            "contract.",
        )
    else:
        execution_route = _claim(
            AdapterSupportLevel.SUPPORTED,
            "Starts the selected external coding-agent adapter; the provider CLI "
            "owns behavior inside its process.",
        )
        authentication = _claim(
            AdapterSupportLevel.DELEGATED,
            "The native provider CLI owns login, refresh, credential storage, "
            "logout, and revocation. An installed executable is not proof of a "
            "ready account.",
        )
        managed_mcp = _combined_adapter_claim(
            adapter_claims,
            ("managed_mcp_headless", "managed_mcp_native"),
            fallback=(
                "Managed MCP support is undeclared for this coding-agent adapter."
            ),
        )
        builtin_tools = _claim(
            AdapterSupportLevel.DELEGATED,
            "Provider-native tools remain owned by the external CLI; GigaChat "
            "built-in tool names are not projected as equivalent capabilities.",
        )
        isolated_edits = _adapter_claim(
            adapter_claims,
            "native_workspace",
            fallback=(
                "No isolated workspace delivery contract is declared for this "
                "coding-agent adapter."
            ),
        )

    return {
        "execution_route": execution_route,
        "provider_authentication": authentication,
        "session_continuity": continuity,
        "cancellation": cancellation,
        "harness_and_provider_approvals": _claim(
            AdapterSupportLevel.PARTIAL,
            "Harness approvals cover Harness-owned actions such as process spawn "
            "or patch apply. Provider-internal approval prompts remain provider-"
            "owned and cannot be inferred from the outer receipt.",
        ),
        "managed_mcp": managed_mcp,
        "skills_and_plugins": _claim(
            AdapterSupportLevel.PARTIAL,
            "GigaLoom can discover and manage reviewed integrations, but catalog "
            "presence never grants execution authority or proves automatic "
            "prompt/tool injection for this surface.",
        ),
        "gigachat_builtin_tools": builtin_tools,
        "isolated_edit_delivery": isolated_edits,
        "multi_agent_delivery": _claim(
            AdapterSupportLevel.PARTIAL,
            "GigaLoom can coordinate independent Arena or workflow runs and pass "
            "bounded summaries/artifact references. That is not native subagent "
            "state or private reasoning transfer.",
        ),
        "usage_and_monetary_cost": _claim(
            AdapterSupportLevel.PARTIAL,
            "Provider-emitted usage may be retained when available; monetary cost "
            "remains unknown unless the provider returns explicit cost evidence.",
        ),
        "structured_evidence": structured_evidence,
        "cross_provider_session_transfer": _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "A retained Harness summary or handoff capsule does not transfer a "
            "provider-native session identity to another provider or adapter.",
        ),
        "hidden_reasoning_transfer": _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "Only visible summaries, messages, events, and retained artifacts may "
            "cross a boundary; hidden reasoning is neither requested nor claimed.",
        ),
    }


def _continuity_claim(
    spec: Mapping[str, Any],
    adapter_claims: Mapping[str, Any],
    *,
    is_direct: bool,
) -> dict[str, str]:
    strategy = str(spec.get("headless_continuation") or "")
    if is_direct:
        return _claim(
            AdapterSupportLevel.SUPPORTED,
            "Harness replays normalized visible chat history "
            f"({strategy or HeadlessContinuationStrategy.STRUCTURED_REPLAY.value}); "
            "there is no provider-native agent session to transfer.",
        )
    headless = _adapter_claim(
        adapter_claims,
        "headless_continuity",
        fallback="Headless continuity is undeclared.",
    )
    native = _adapter_claim(
        adapter_claims,
        "native_resume",
        fallback="Native resume is undeclared.",
    )
    statuses = {headless["status"], native["status"]}
    status = (
        AdapterSupportLevel.SUPPORTED
        if statuses == {AdapterSupportLevel.SUPPORTED.value}
        else AdapterSupportLevel.PARTIAL
    )
    return _claim(
        status,
        f"Headless: {headless['detail']} Native: {native['detail']}",
    )


def _structured_evidence_claim(
    spec: Mapping[str, Any],
    adapter_claims: Mapping[str, Any],
    *,
    is_direct: bool,
) -> dict[str, str]:
    if not bool(spec.get("supports_structured_events")):
        return _claim(
            AdapterSupportLevel.UNSUPPORTED,
            "This surface declares no structured event contract.",
        )
    if is_direct:
        return _claim(
            AdapterSupportLevel.SUPPORTED,
            "Direct Chat normalizes visible response, tool, usage, and completion "
            "events; it does not expose hidden reasoning.",
        )
    telemetry = _adapter_claim(
        adapter_claims,
        "native_telemetry",
        fallback="Native telemetry is undeclared.",
    )
    return _claim(
        AdapterSupportLevel.PARTIAL,
        "Version-probed headless or app-server routes emit normalized events. "
        f"Native terminal evidence: {telemetry['detail']}",
    )


def _combined_adapter_claim(
    claims: Mapping[str, Any],
    claim_ids: tuple[str, ...],
    *,
    fallback: str,
) -> dict[str, str]:
    selected = [
        _adapter_claim(claims, claim_id, fallback=fallback) for claim_id in claim_ids
    ]
    statuses = {item["status"] for item in selected}
    status = (
        AdapterSupportLevel.SUPPORTED
        if statuses == {AdapterSupportLevel.SUPPORTED.value}
        else AdapterSupportLevel.PARTIAL
    )
    return _claim(status, " ".join(item["detail"] for item in selected))


def _adapter_claim(
    claims: Mapping[str, Any],
    claim_id: str,
    *,
    fallback: str,
) -> dict[str, str]:
    claim = claims.get(claim_id)
    if not isinstance(claim, Mapping):
        return _claim(AdapterSupportLevel.UNSUPPORTED, fallback)
    try:
        status = AdapterSupportLevel(str(claim.get("status")))
    except ValueError:
        status = AdapterSupportLevel.UNSUPPORTED
    detail = str(claim.get("detail") or fallback)
    return _claim(status, detail)


def _boolean_claim(
    value: bool,
    *,
    supported: str,
    unsupported: str,
) -> dict[str, str]:
    return _claim(
        AdapterSupportLevel.SUPPORTED if value else AdapterSupportLevel.UNSUPPORTED,
        supported if value else unsupported,
    )


def _claim(status: AdapterSupportLevel, detail: str) -> dict[str, str]:
    return {"status": status.value, "detail": detail}


def _claim_status(claim: Any) -> str:
    if not isinstance(claim, Mapping):
        return "undeclared"
    return _markdown_text(claim.get("status", "undeclared"))


def _claim_detail(claim: Any) -> str:
    if not isinstance(claim, Mapping):
        return ""
    return str(claim.get("detail", ""))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _markdown_text(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
