"""Bounded capability probes for supported external agent CLIs."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import subprocess
import tempfile
import threading
from typing import Any, Mapping

from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.types import Availability, redact_secrets

PROBE_TIMEOUT_SECONDS = 5.0
PROBE_OUTPUT_CHARS = 8000
_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+\.\d+(?:\.\d+)?(?:[-+._A-Za-z0-9]*)?)")
_PROBE_CACHE: dict[tuple[str, tuple[str, ...], str], "CliCapabilitySnapshot"] = {}
_PROBE_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class CliProbeContract:
    """Describe the side-effect-free help probes required by one adapter."""

    harness_id: str
    display_name: str
    help_argv: tuple[str, ...]
    required_tokens: tuple[str, ...]
    optional_tokens: tuple[str, ...] = ()
    event_schema: str = "unknown"
    history_schema: str = "unknown"


@dataclass(frozen=True)
class CliCapabilitySnapshot:
    """Redaction-safe compatibility evidence for one resolved CLI command."""

    harness_id: str
    status: str
    version: str | None
    parsed_version: str | None
    command: tuple[str, ...]
    capabilities: Mapping[str, bool]
    event_schema: str
    history_schema: str
    warning: str | None = None
    evidence: str | None = None

    @property
    def compatible(self) -> bool:
        """Return whether the required adapter contract was proven."""
        return self.status == "supported"


CLI_PROBE_CONTRACTS = {
    "codex-cli": CliProbeContract(
        harness_id="codex-cli",
        display_name="Codex CLI",
        help_argv=("exec", "--help"),
        required_tokens=("--json", "--sandbox", "--ephemeral"),
        optional_tokens=("--image", "--config", "--strict-config"),
        event_schema="codex-exec-jsonl-v1",
        history_schema="codex-session-jsonl-v1",
    ),
    "claude-code": CliProbeContract(
        harness_id="claude-code",
        display_name="Claude Code",
        help_argv=("--help",),
        required_tokens=(
            "--output-format",
            "stream-json",
            "--permission-mode",
            "--no-session-persistence",
        ),
        optional_tokens=(
            "--include-partial-messages",
            "--resume",
            "--effort",
            "--allowedTools",
            "--disallowedTools",
        ),
        event_schema="claude-stream-json-v1",
        history_schema="claude-project-jsonl-v1",
    ),
    "gemini-cli": CliProbeContract(
        harness_id="gemini-cli",
        display_name="Gemini CLI",
        help_argv=("--help",),
        required_tokens=(
            "--output-format",
            "stream-json",
            "--approval-mode",
            "--skip-trust",
        ),
        optional_tokens=("--prompt-interactive", "--list-sessions", "--resume"),
        event_schema="gemini-stream-json-v1",
        history_schema="gemini-checkpoint-jsonl-v1",
    ),
}


def probe_cli_capabilities(
    resolution: ExecutableResolution,
    harness_id: str,
) -> CliCapabilitySnapshot:
    """Probe version and help output without reading user-owned CLI state."""
    contract = CLI_PROBE_CONTRACTS[harness_id]
    command = resolution.command
    if resolution.error is not None:
        return _snapshot(
            contract,
            status="error",
            command=command,
            warning=resolution.error,
        )
    if not command:
        return _snapshot(
            contract,
            status="missing",
            command=(),
            warning=f"{contract.display_name} executable was not found.",
        )

    version_run = _run_probe(command + ("--version",), harness_id)
    if version_run[0] != "ok":
        return _snapshot(
            contract,
            status="error",
            command=command,
            warning=f"{contract.display_name} version probe failed: {version_run[1]}",
        )
    version = _first_line(version_run[1]) or "unknown"
    cache_key = (harness_id, command, version)
    with _PROBE_CACHE_LOCK:
        cached = _PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    help_run = _run_probe(command + contract.help_argv, harness_id)
    if help_run[0] != "ok":
        snapshot = _snapshot(
            contract,
            status="error",
            command=command,
            version=version,
            warning=f"{contract.display_name} capability probe failed: {help_run[1]}",
        )
    else:
        output = help_run[1]
        capabilities = {
            token: token in output
            for token in (*contract.required_tokens, *contract.optional_tokens)
        }
        if harness_id == "codex-cli":
            app_server_run = _run_probe(command + ("app-server", "--help"), harness_id)
            app_server_output = app_server_run[1] if app_server_run[0] == "ok" else ""
            capabilities["app-server"] = (
                app_server_run[0] == "ok"
                and "stdio://" in app_server_output
                and "generate-json-schema" in app_server_output
            )
        missing = [
            token for token in contract.required_tokens if not capabilities[token]
        ]
        warning = None
        status = "supported"
        if missing:
            status = "unsupported"
            warning = (
                f"{contract.display_name} {version} is missing required adapter "
                f"capabilities: {', '.join(missing)}."
            )
        snapshot = _snapshot(
            contract,
            status=status,
            command=command,
            version=version,
            capabilities=capabilities,
            warning=warning,
            evidence="bounded --version and --help probes",
        )
    with _PROBE_CACHE_LOCK:
        _PROBE_CACHE[cache_key] = snapshot
    return snapshot


def invalidate_cli_probe_cache() -> None:
    """Explicitly invalidate all cached external CLI capability evidence."""
    with _PROBE_CACHE_LOCK:
        _PROBE_CACHE.clear()


def cli_capability_snapshot_to_dict(
    snapshot: CliCapabilitySnapshot,
) -> dict[str, Any]:
    """Serialize a capability snapshot without exposing secrets or full env."""
    return {
        "status": snapshot.status,
        "compatible": snapshot.compatible,
        "version": snapshot.version,
        "parsed_version": snapshot.parsed_version,
        "command": list(_redacted_command(snapshot.command)),
        "capabilities": dict(snapshot.capabilities),
        "event_schema": snapshot.event_schema,
        "history_schema": snapshot.history_schema,
        "warning": snapshot.warning,
        "evidence": snapshot.evidence,
    }


def cli_probe_availability(
    snapshot: CliCapabilitySnapshot,
    *,
    install_hint: str,
) -> Availability:
    """Translate proven CLI compatibility into truthful adapter availability."""
    if snapshot.status == "missing":
        return Availability.missing(
            snapshot.warning or "executable not found", install_hint
        )
    if not snapshot.compatible:
        return Availability.error(
            snapshot.warning or "external CLI is not adapter-compatible",
            snapshot.evidence,
        )
    command = snapshot.command[0] if snapshot.command else "external CLI"
    return Availability.available(
        f"compatible {snapshot.version or 'unknown version'} at {command}"
    )


def _snapshot(
    contract: CliProbeContract,
    *,
    status: str,
    command: tuple[str, ...],
    version: str | None = None,
    capabilities: Mapping[str, bool] | None = None,
    warning: str | None = None,
    evidence: str | None = None,
) -> CliCapabilitySnapshot:
    match = _VERSION_PATTERN.search(version or "")
    return CliCapabilitySnapshot(
        harness_id=contract.harness_id,
        status=status,
        version=version,
        parsed_version=match.group(1) if match else None,
        command=command,
        capabilities=dict(capabilities or {}),
        event_schema=contract.event_schema,
        history_schema=contract.history_schema,
        warning=str(redact_secrets(warning)) if warning else None,
        evidence=evidence,
    )


def _run_probe(command: tuple[str, ...], harness_id: str) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="gpt2giga-cli-probe-") as home:
        env = {
            key: value
            for key in ("PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
            if (value := os.environ.get(key)) is not None
        }
        env["HOME"] = home
        if harness_id == "codex-cli":
            env["CODEX_HOME"] = os.path.join(home, ".codex")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
                env=env,
            )
        except OSError as exc:
            return "error", str(redact_secrets(str(exc)))
        except subprocess.TimeoutExpired:
            return "error", f"timed out after {PROBE_TIMEOUT_SECONDS:g} seconds"
    output = f"{completed.stdout}\n{completed.stderr}"[-PROBE_OUTPUT_CHARS:]
    output = str(redact_secrets(output)).strip()
    if completed.returncode != 0:
        return "error", _first_line(output) or f"exit status {completed.returncode}"
    return "ok", output


def _first_line(value: str) -> str | None:
    lines = value.strip().splitlines()
    return lines[0][:200] if lines else None


def _redacted_command(command: tuple[str, ...]) -> tuple[str, ...]:
    if not command:
        return ()
    return (str(redact_secrets(command[0])), *("<arg>" for _ in command[1:]))
