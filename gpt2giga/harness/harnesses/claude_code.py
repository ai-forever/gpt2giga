"""Claude Code harness for running Claude through local gpt2giga."""

from __future__ import annotations

import shutil

from gpt2giga.harness.harnesses.agent_cli import (
    build_safe_env,
    executable_availability,
    run_command,
    workspace_error,
)
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

MODE_TO_PERMISSION = {
    "plan": "plan",
    "read": "plan",
    "edit": "default",
}


class ClaudeCodeHarness(BaseHarness):
    """Run Claude Code in print mode against gpt2giga."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="claude-code",
            title="Claude Code",
            kind="agent-cli",
            description="Run Claude Code against local gpt2giga proxy",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_workspace=True,
            tags=("claude", "agent"),
        )

    def availability(self) -> Availability:
        executable = shutil.which("claude")
        return executable_availability(
            executable=executable,
            executable_name="claude",
            install_hint="Install Claude Code and ensure it is on PATH.",
            version_args=None,
        )

    def build_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> tuple[str, ...]:
        """Build the Claude Code command without executing it."""
        executable = shutil.which("claude") or "claude"
        model = request.model or context.default_model or "GigaChat"
        permission_mode = MODE_TO_PERMISSION.get(
            request.mode, MODE_TO_PERMISSION["plan"]
        )
        return (
            executable,
            "--bare",
            "--safe-mode",
            "-p",
            "--model",
            model,
            "--output-format",
            "json",
            "--no-session-persistence",
            "--permission-mode",
            permission_mode,
            request.prompt,
        )

    def build_env(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> dict[str, str]:
        """Build a sanitized environment for Claude Code."""
        return build_safe_env(
            context,
            extra={
                "ANTHROPIC_BASE_URL": context.api_base_url(request.api_mode),
                "ANTHROPIC_API_KEY": context.api_key or "0",
                "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
                "GPT2GIGA_HARNESS_API_MODE": request.api_mode.value,
            },
        )

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        command = self.build_command(request, context)
        env = self.build_env(request, context)
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={
                    "env": redact_secrets(env),
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
        return run_command(
            label="Claude Code",
            command=command,
            env=env,
            cwd=request.workspace,
            timeout_seconds=context.timeout_seconds,
        )
