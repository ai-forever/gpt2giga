"""Shared helpers for external agent CLI harnesses."""

from __future__ import annotations

from dataclasses import replace
import os
import subprocess
from pathlib import Path
from typing import Mapping

from gpt2giga.harness import proxy
from gpt2giga.harness.types import (
    REDACTED,
    Availability,
    HarnessContext,
    HarnessEvent,
    HarnessRequest,
    HarnessResult,
)

SAFE_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SHELL", "LANG", "LC_ALL")
SECRET_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GPT2GIGA_API_KEY",
    "OPENAI_API_KEY",
)


def build_safe_env(
    context: HarnessContext,
    *,
    extra: Mapping[str, str] | None = None,
    home: str | None = None,
) -> dict[str, str]:
    """Build a minimal environment that excludes upstream GigaChat secrets."""
    env: dict[str, str] = {
        key: value
        for key in SAFE_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    env.update(context.extra_env)
    if home is not None:
        env["HOME"] = home
    if extra is not None:
        env.update(extra)
    return env


def workspace_error(value: str | None) -> str | None:
    """Return a user-facing workspace validation error, if any."""
    if value is None:
        return None
    path = Path(value)
    if not path.exists():
        return f"Workspace does not exist: {value}"
    if not path.is_dir():
        return f"Workspace is not a directory: {value}"
    return None


def prepare_proxy_for_agent(
    request: HarnessRequest,
    context: HarnessContext,
    *,
    command: tuple[str, ...],
) -> tuple[HarnessContext, tuple[HarnessEvent, ...], HarnessResult | None]:
    """Ensure the local proxy is ready before launching an external agent CLI."""
    startup = proxy.ensure_proxy_available(context, request.api_mode)
    if not startup.ok:
        return (
            context,
            (),
            HarnessResult(
                ok=False,
                text="",
                raw={
                    "proxy_url": context.proxy_url,
                    "auto_start_proxy": context.auto_start_proxy,
                },
                command=command,
                error=startup.error or "proxy is not reachable",
            ),
        )

    prepared_context = replace(context, api_key=startup.api_key or context.api_key)
    events: tuple[HarnessEvent, ...] = ()
    if startup.started:
        events = (
            HarnessEvent(
                type="proxy_sidecar",
                message="Started local gpt2giga proxy sidecar.",
                payload={
                    "proxy_url": context.proxy_url,
                    "pid": startup.pid,
                    "detail": startup.detail,
                },
            ),
        )
    return prepared_context, events, None


def with_events(
    result: HarnessResult,
    events: tuple[HarnessEvent, ...],
) -> HarnessResult:
    """Return a result with prepended events."""
    if not events:
        return result
    return HarnessResult(
        ok=result.ok,
        text=result.text,
        raw=result.raw,
        events=(*events, *result.events),
        command=result.command,
        error=result.error,
    )


def run_command(
    *,
    label: str,
    command: tuple[str, ...],
    env: Mapping[str, str],
    cwd: str | None,
    timeout_seconds: float,
) -> HarnessResult:
    """Run a command and normalize the captured result."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return HarnessResult(
            ok=False,
            text="",
            raw={"timeout_seconds": timeout_seconds},
            command=command,
            error=f"{label} timed out after {exc.timeout} seconds",
        )
    except OSError as exc:
        return HarnessResult(
            ok=False,
            text="",
            raw={},
            command=command,
            error=f"{label} failed to start: {exc}",
        )

    stdout = _redact_known_secret_values(completed.stdout, env)
    stderr = _redact_known_secret_values(completed.stderr, env)
    text = stdout.strip() or stderr.strip()
    return HarnessResult(
        ok=completed.returncode == 0,
        text=text,
        raw={
            "exit_code": completed.returncode,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        },
        command=command,
        error=None if completed.returncode == 0 else text,
    )


def executable_availability(
    *,
    executable: str | None,
    executable_name: str,
    install_hint: str,
    version_args: tuple[str, ...] | None = ("--version",),
) -> Availability:
    """Return availability for an executable, optionally probing startup."""
    if executable is None:
        return Availability.missing(
            f"{executable_name} executable not found",
            install_hint,
        )
    if version_args is None:
        return Availability.available(
            f"{executable_name} executable found: {executable}"
        )
    try:
        completed = subprocess.run(
            (executable, *version_args),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Availability.error(
            f"{executable_name} executable failed to run",
            str(exc),
        )
    detail = (completed.stdout or completed.stderr).strip().splitlines()
    version = detail[0] if detail else None
    if completed.returncode != 0:
        return Availability.error(
            f"{executable_name} executable failed to run",
            version,
        )
    suffix = f" ({version})" if version else ""
    return Availability.available(
        f"{executable_name} executable found: {executable}{suffix}"
    )


def _redact_known_secret_values(text: str, env: Mapping[str, str]) -> str:
    redacted = text
    for key in SECRET_ENV_KEYS:
        value = env.get(key)
        if value and value != "0":
            redacted = redacted.replace(value, REDACTED)
    return redacted
