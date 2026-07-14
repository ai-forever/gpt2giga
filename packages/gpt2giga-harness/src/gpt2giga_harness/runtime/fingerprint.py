"""Worker capability fingerprinting for safe durable job claims."""

from __future__ import annotations

from importlib import metadata
import platform
from typing import Any

from gpt2giga_harness.cli_capabilities import cli_capability_snapshot_to_dict
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.capabilities import negotiate_execution_capabilities
from gpt2giga_harness.types import AvailabilityStatus

_CLI_BINARIES = {
    "codex-cli": "codex",
    "claude-code": "claude",
    "gemini-cli": "gemini",
}


def build_worker_fingerprint(registry: HarnessRegistry) -> dict[str, Any]:
    """Return a redaction-safe snapshot used for claim compatibility."""
    harnesses: dict[str, Any] = {}
    for harness in registry.list():
        spec = harness.spec()
        availability = harness.availability()
        capabilities = negotiate_execution_capabilities(harness)
        binary = _CLI_BINARIES.get(spec.id)
        resolution = _executable_resolution(harness)
        binary_path = resolution.executable if resolution is not None else None
        probe = _capability_probe(harness)
        profile_features = _agent_profile_features(spec.id, probe)
        harnesses[spec.id] = {
            "available": availability.status is AvailabilityStatus.AVAILABLE,
            "kind": spec.kind,
            "distribution": str(spec.metadata.get("distribution") or "builtin"),
            "binary": binary,
            "binary_path": binary_path,
            "binary_source": resolution.source if resolution is not None else None,
            "binary_version": probe.version if probe is not None else None,
            "compatibility": (
                cli_capability_snapshot_to_dict(probe) if probe is not None else None
            ),
            "features": {
                "structured_events": capabilities.structured_events,
                "streaming": capabilities.streaming,
                "cancellation": capabilities.cancellation,
                "synchronous_fallback": capabilities.synchronous_fallback,
                **profile_features,
            },
        }
    return {
        "os": platform.system().lower(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "gpt2giga": _distribution_version("gpt2giga"),
        "gpt2giga_harness": _distribution_version("gpt2giga-harness"),
        "harnesses": harnesses,
    }


def _executable_resolution(harness: Any) -> Any | None:
    resolver = getattr(harness, "executable_resolution", None)
    return resolver() if callable(resolver) else None


def _capability_probe(harness: Any) -> Any | None:
    probe = getattr(harness, "capability_probe", None)
    return probe() if callable(probe) else None


def _agent_profile_features(harness_id: str, probe: Any | None) -> dict[str, bool]:
    capabilities = getattr(probe, "capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = dict(capabilities) if capabilities is not None else {}
    return {
        "agent_reasoning_effort": bool(
            capabilities.get("--config" if harness_id == "codex-cli" else "--effort")
            if harness_id in {"codex-cli", "claude-code"}
            else False
        ),
        "agent_allowed_tools": bool(
            harness_id == "claude-code" and capabilities.get("--allowedTools")
        ),
        "agent_disallowed_tools": bool(
            harness_id == "claude-code" and capabilities.get("--disallowedTools")
        ),
    }


def _distribution_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "source-checkout"
