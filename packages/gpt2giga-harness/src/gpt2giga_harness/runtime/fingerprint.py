"""Worker capability fingerprinting for safe durable job claims."""

from __future__ import annotations

from importlib import metadata
import platform
import shutil
import subprocess
from typing import Any

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
        harnesses[spec.id] = {
            "available": availability.status is AvailabilityStatus.AVAILABLE,
            "kind": spec.kind,
            "distribution": str(spec.metadata.get("distribution") or "builtin"),
            "binary": binary,
            "binary_version": _binary_version(binary) if binary else None,
            "features": {
                "structured_events": capabilities.structured_events,
                "streaming": capabilities.streaming,
                "cancellation": capabilities.cancellation,
                "synchronous_fallback": capabilities.synchronous_fallback,
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


def _binary_version(binary: str) -> str | None:
    path = shutil.which(binary)
    if path is None:
        return None
    try:
        completed = subprocess.run(
            (path, "--version"),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    line = (completed.stdout or completed.stderr).strip().splitlines()
    return line[0][:200] if line else "unknown"


def _distribution_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "source-checkout"
