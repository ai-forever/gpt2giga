"""Generated public matrix for adapter parity contracts."""

from __future__ import annotations

from typing import Any, Mapping

from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.types import spec_to_dict

CAPABILITY_MATRIX_SCHEMA_VERSION = 1
CAPABILITY_MATRIX_SOURCE = "HarnessSpec.adapter_capabilities"


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


def _claim_status(claim: Any) -> str:
    if not isinstance(claim, Mapping):
        return "undeclared"
    return _markdown_text(claim.get("status", "undeclared"))


def _markdown_text(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
