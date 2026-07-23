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
    minimum_version: str
    maximum_version_exclusive: str
    optional_tokens: tuple[str, ...] = ()
    event_schema: str = "unknown"
    history_schema: str = "unknown"
    native_event_schema: str = "raw-terminal-v1"
    native_structured_events: bool = False


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
    native_event_schema: str = "raw-terminal-v1"
    native_structured_events: bool = False
    warning: str | None = None
    evidence: str | None = None
    version_window_status: str = "not_probed"
    minimum_version: str | None = None
    maximum_version_exclusive: str | None = None

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
        minimum_version="0.144.0",
        maximum_version_exclusive="0.145.0",
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
            "--remote-control",
        ),
        minimum_version="2.1.0",
        maximum_version_exclusive="2.2.0",
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
        optional_tokens=(
            "--acp",
            "--experimental-acp",
            "--prompt-interactive",
            "--list-sessions",
            "--resume",
        ),
        minimum_version="0.46.0",
        maximum_version_exclusive="0.47.0",
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
        elif harness_id == "claude-code":
            remote_control_run = _run_probe(
                command + ("remote-control", "--help"), harness_id
            )
            capabilities["remote-control"] = (
                remote_control_run[0] == "ok"
                or remote_control_run[1]
                == "Error: You must be logged in to use Remote Control."
            )
        missing = [
            token for token in contract.required_tokens if not capabilities[token]
        ]
        version_window_status = _version_window_status(version, contract)
        warning = None
        status = "supported"
        if missing:
            status = "unsupported"
            warning = (
                f"{contract.display_name} {version} is missing required adapter "
                f"capabilities: {', '.join(missing)}."
            )
        elif version_window_status == "below_window":
            status = "unsupported"
            warning = (
                f"{contract.display_name} {version} is below the supported version "
                f"window {_format_version_window(contract)}."
            )
        elif version_window_status == "above_window":
            status = "degraded"
            warning = (
                f"{contract.display_name} {version} is newer than the validated "
                f"version window {_format_version_window(contract)}; required "
                "capabilities are present, but execution remains blocked until the "
                "window is reviewed."
            )
        elif version_window_status == "unparsed":
            status = "degraded"
            warning = (
                f"{contract.display_name} version could not be matched to the "
                f"supported version window {_format_version_window(contract)}; "
                "required capabilities are present, but execution remains blocked."
            )
        snapshot = _snapshot(
            contract,
            status=status,
            command=command,
            version=version,
            capabilities=capabilities,
            warning=warning,
            evidence=(
                "bounded --version and --help probes against the declared "
                "external CLI version window"
            ),
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
        "version_contract": {
            "status": snapshot.version_window_status,
            "minimum": snapshot.minimum_version,
            "maximum_exclusive": snapshot.maximum_version_exclusive,
        },
        "command": list(_redacted_command(snapshot.command)),
        "capabilities": dict(snapshot.capabilities),
        "event_schema": snapshot.event_schema,
        "history_schema": snapshot.history_schema,
        "native_event_schema": snapshot.native_event_schema,
        "native_structured_events": snapshot.native_structured_events,
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
    version_window_status = _version_window_status(version, contract)
    return CliCapabilitySnapshot(
        harness_id=contract.harness_id,
        status=status,
        version=version,
        parsed_version=match.group(1) if match else None,
        command=command,
        capabilities=dict(capabilities or {}),
        event_schema=contract.event_schema,
        history_schema=contract.history_schema,
        native_event_schema=contract.native_event_schema,
        native_structured_events=contract.native_structured_events,
        warning=str(redact_secrets(warning)) if warning else None,
        evidence=evidence,
        version_window_status=version_window_status,
        minimum_version=contract.minimum_version,
        maximum_version_exclusive=contract.maximum_version_exclusive,
    )


def _version_window_status(version: str | None, contract: CliProbeContract) -> str:
    if version is None:
        return "not_probed"
    parsed = _release_tuple(version)
    if parsed is None:
        return "unparsed"
    if parsed < _release_tuple_required(contract.minimum_version):
        return "below_window"
    if parsed >= _release_tuple_required(contract.maximum_version_exclusive):
        return "above_window"
    return "in_window"


def _release_tuple(version: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.search(version)
    if match is None:
        return None
    release = match.group(1).split("+", 1)[0].split("-", 1)[0]
    parts = release.split(".")
    numeric: list[int] = []
    for part in parts[:3]:
        match_part = re.match(r"\d+", part)
        if match_part is None:
            return None
        numeric.append(int(match_part.group(0)))
    numeric.extend(0 for _ in range(3 - len(numeric)))
    return numeric[0], numeric[1], numeric[2]


def _release_tuple_required(version: str) -> tuple[int, int, int]:
    parsed = _release_tuple(version)
    if parsed is None:  # pragma: no cover - static contracts are covered in tests
        raise ValueError(f"Invalid CLI version-window boundary: {version}")
    return parsed


def _format_version_window(contract: CliProbeContract) -> str:
    return f">={contract.minimum_version},<{contract.maximum_version_exclusive}"


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
