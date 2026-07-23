"""Pure, isolated capture plans for provider-native CLI evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from gpt2giga_harness.native_cli_contracts import WORKBENCH_INTEGRATION_SPECS

CAPTURE_TIMEOUT_SECONDS = 5.0
CAPTURE_OUTPUT_BYTES = 1_048_576
_INHERITED_ENV = ("PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TERM")


@dataclass(frozen=True)
class NativeCliCaptureInvocation:
    """One side-effect-free metadata query described but not executed."""

    label: str
    command_class: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class NativeCliCapturePlan:
    """Temporary-home capture plan carrying no execution authority."""

    namespace: str
    invocations: tuple[NativeCliCaptureInvocation, ...]
    environment: Mapping[str, str]
    timeout_seconds: float
    output_limit_bytes: int
    execution_authorized: bool = False
    network_authorized: bool = False
    mutation_authorized: bool = False


@dataclass(frozen=True)
class NativeCliCaptureDigest:
    """Content-free byte digest for one externally supplied capture result."""

    label: str
    command_class: str
    returncode: int
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str


def build_native_cli_capture_plan(
    namespace: str,
    executable: Sequence[str],
    temporary_home: str | Path,
    *,
    inherited_environment: Mapping[str, str] | None = None,
) -> NativeCliCapturePlan:
    """Describe bounded version/help probes rooted in an isolated home."""
    integration = WORKBENCH_INTEGRATION_SPECS[namespace]
    prefix = tuple(executable)
    if not prefix or any(not item or "\x00" in item for item in prefix):
        raise ValueError("capture executable must contain bounded NUL-free argv")
    home = Path(temporary_home)
    source_env = (
        inherited_environment if inherited_environment is not None else os.environ
    )
    environment = {
        name: value
        for name in _INHERITED_ENV
        if (value := source_env.get(name)) is not None
    }
    environment["HOME"] = str(home)
    for name in integration.isolated_variables:
        environment[name] = _isolated_variable_path(name, home)
    environment.update(
        {
            "CI": "1",
            "NO_COLOR": "1",
            "DO_NOT_TRACK": "1",
        }
    )
    invocations = [
        NativeCliCaptureInvocation(
            label="version",
            command_class="metadata.version",
            argv=(*prefix, "--version"),
        )
    ]
    invocations.extend(
        NativeCliCaptureInvocation(
            label="root-help" if not path else f"{'-'.join(path)}-help",
            command_class=(
                "metadata.root_help" if not path else f"metadata.{'.'.join(path)}_help"
            ),
            argv=(*prefix, *path, "--help"),
        )
        for path in integration.capture_help_paths
    )
    return NativeCliCapturePlan(
        namespace=namespace,
        invocations=tuple(invocations),
        environment=MappingProxyType(environment),
        timeout_seconds=CAPTURE_TIMEOUT_SECONDS,
        output_limit_bytes=CAPTURE_OUTPUT_BYTES,
    )


def digest_native_cli_capture(
    invocation: NativeCliCaptureInvocation,
    *,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
) -> NativeCliCaptureDigest:
    """Reduce supplied bytes to content-free evidence without executing a CLI."""
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        raise TypeError("capture output must be bytes")
    if len(stdout) > CAPTURE_OUTPUT_BYTES or len(stderr) > CAPTURE_OUTPUT_BYTES:
        raise ValueError("capture output exceeded the bounded evidence limit")
    return NativeCliCaptureDigest(
        label=invocation.label,
        command_class=invocation.command_class,
        returncode=int(returncode),
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
    )


def _isolated_variable_path(name: str, home: Path) -> str:
    suffixes = {
        "HOME": ".",
        "CODEX_HOME": ".codex",
        "CLAUDE_CONFIG_DIR": ".claude",
        "GEMINI_CLI_HOME": ".gemini",
    }
    return str(home / suffixes[name])


__all__ = [
    "CAPTURE_OUTPUT_BYTES",
    "CAPTURE_TIMEOUT_SECONDS",
    "NativeCliCaptureDigest",
    "NativeCliCaptureInvocation",
    "NativeCliCapturePlan",
    "build_native_cli_capture_plan",
    "digest_native_cli_capture",
]
