"""Codex CLI harness for running Codex through local gpt2giga."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    redact_secrets,
)

MODE_TO_SANDBOX = {
    "plan": "read-only",
    "read": "read-only",
    "edit": "workspace-write",
}
SAFE_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SHELL", "LANG", "LC_ALL")


class CodexCliHarness(BaseHarness):
    """Run Codex CLI in non-interactive mode against gpt2giga."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Codex CLI",
            kind="agent-cli",
            description="Run Codex CLI against local gpt2giga proxy",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_workspace=True,
            tags=("codex", "agent"),
        )

    def availability(self) -> Availability:
        executable = shutil.which("codex")
        if executable is None:
            return Availability.missing(
                "codex executable not found",
                "Install OpenAI Codex CLI and ensure it is on PATH.",
            )
        return Availability.available(f"codex executable found: {executable}")

    def build_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> tuple[str, ...]:
        """Build the Codex command without executing it."""
        executable = shutil.which("codex") or "codex"
        sandbox = MODE_TO_SANDBOX.get(request.mode, MODE_TO_SANDBOX["plan"])
        model = request.model or context.default_model or "GigaChat"
        return (
            executable,
            "--ask-for-approval",
            "on-request",
            "exec",
            "--sandbox",
            sandbox,
            "--ephemeral",
            "-m",
            model,
            request.prompt,
        )

    def build_env(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        codex_home: str | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment for the external CLI."""
        env: dict[str, str] = {
            key: value
            for key in SAFE_ENV_KEYS
            if (value := os.environ.get(key)) is not None
        }
        env.update(context.extra_env)
        env["GPT2GIGA_API_KEY"] = context.api_key or "0"
        env["GPT2GIGA_HARNESS_PROXY_URL"] = context.proxy_url
        env["GPT2GIGA_HARNESS_API_MODE"] = request.api_mode.value
        if codex_home is not None:
            env["CODEX_HOME"] = codex_home
        return env

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        command = self.build_command(request, context)
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={
                    "env": redact_secrets(
                        self.build_env(request, context, codex_home="<temp>")
                    ),
                    "workspace": request.workspace,
                },
                command=command,
            )
        workspace_error = _workspace_error(request.workspace)
        if workspace_error is not None:
            return HarnessResult(
                ok=False,
                text="",
                raw={},
                command=command,
                error=workspace_error,
            )
        availability = self.availability()
        if availability.status.value != "available":
            return HarnessResult(
                ok=False,
                text="",
                raw={},
                command=command,
                error=availability.reason,
            )
        with tempfile.TemporaryDirectory(prefix="gpt2giga-codex-") as temp_dir:
            codex_home = str(Path(temp_dir) / ".codex")
            Path(codex_home).mkdir(parents=True, exist_ok=True)
            _write_codex_config(Path(codex_home), request, context)
            env = self.build_env(request, context, codex_home=codex_home)
            try:
                completed = subprocess.run(
                    command,
                    cwd=request.workspace or None,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=context.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return HarnessResult(
                    ok=False,
                    text="",
                    raw={"timeout_seconds": context.timeout_seconds},
                    command=command,
                    error=f"Codex CLI timed out after {exc.timeout} seconds",
                )
        text = completed.stdout.strip() or completed.stderr.strip()
        return HarnessResult(
            ok=completed.returncode == 0,
            text=text,
            raw=redact_secrets(
                {
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout[-4000:],
                    "stderr": completed.stderr[-4000:],
                }
            ),
            command=command,
            error=None if completed.returncode == 0 else text,
        )


def _write_codex_config(
    codex_home: Path,
    request: HarnessRequest,
    context: HarnessContext,
) -> None:
    model = request.model or context.default_model or "GigaChat"
    base_url = context.api_base_url(request.api_mode)
    config = (
        f'model = "{_toml_escape(model)}"\n'
        'model_provider = "gpt2giga_harness"\n'
        'model_reasoning_effort = "none"\n\n'
        "[model_providers.gpt2giga_harness]\n"
        'name = "gpt2giga_harness"\n'
        f'base_url = "{_toml_escape(base_url)}"\n'
        'env_key = "GPT2GIGA_API_KEY"\n'
        'wire_api = "responses"\n'
        "supports_websockets = false\n"
    )
    (codex_home / "config.toml").write_text(config, encoding="utf-8")


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _workspace_error(value: str | None) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if not path.exists():
        return f"Workspace does not exist: {value}"
    if not path.is_dir():
        return f"Workspace is not a directory: {value}"
    return None
