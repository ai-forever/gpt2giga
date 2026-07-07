"""Codex CLI harness for running Codex through local gpt2giga."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from gpt2giga.harness.harnesses.agent_cli import run_command, workspace_error
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
        workspace_validation_error = workspace_error(request.workspace)
        if workspace_validation_error is not None:
            return HarnessResult(
                ok=False,
                text="",
                raw={},
                command=command,
                error=workspace_validation_error,
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
            return run_command(
                label="Codex CLI",
                command=command,
                env=env,
                cwd=request.workspace or None,
                timeout_seconds=context.timeout_seconds,
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
