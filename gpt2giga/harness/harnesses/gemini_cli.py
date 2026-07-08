"""Gemini CLI harness for running Gemini through local gpt2giga."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from gpt2giga.harness.harnesses.agent_cli import (
    build_safe_env,
    executable_availability,
    prepare_proxy_for_agent,
    run_command,
    with_events,
    workspace_error,
)
from gpt2giga.harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    attachment_warning_events,
    cli_args_from_attachments,
    prompt_with_attachments,
)
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.native import HarnessInvocationMode
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    redact_secrets,
)

MODE_TO_APPROVAL = {
    "plan": "--approval-mode=plan",
    "read": "--approval-mode=plan",
}


class GeminiCliHarness(BaseHarness):
    """Run Gemini CLI in headless mode against gpt2giga."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="gemini-cli",
            title="Gemini CLI",
            kind="agent-cli",
            description="Run Gemini CLI against local gpt2giga proxy",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_workspace=True,
            supports_attachments=True,
            accepted_attachment_kinds=("text", "workspace_file", "document", "image"),
            attachment_transport=("at_file_reference", "prompt_path_reference"),
            supports_native_sessions=True,
            supports_external_history=True,
            default_invocation_mode=HarnessInvocationMode.NATIVE,
            tags=("gemini", "agent"),
        )

    def availability(self) -> Availability:
        executable = shutil.which("gemini")
        return executable_availability(
            executable=executable,
            executable_name="gemini",
            install_hint="Install Gemini CLI and ensure it is on PATH.",
            version_args=None,
        )

    def build_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> tuple[str, ...]:
        """Build the Gemini CLI command without executing it."""
        executable = shutil.which("gemini") or "gemini"
        model = request.model or context.default_model or "GigaChat"
        prompt = prompt_with_attachments(request)
        command = [
            executable,
            "-m",
            model,
            *cli_args_from_attachments(request),
            "-p",
            prompt,
            "--output-format",
            "json",
            "--skip-trust",
        ]
        approval = MODE_TO_APPROVAL.get(request.mode)
        if approval is not None:
            command.append(approval)
        return tuple(command)

    def build_env(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        home: str | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment for Gemini CLI."""
        model = request.model or context.default_model or "GigaChat"
        return build_safe_env(
            context,
            home=home,
            extra={
                "GOOGLE_GEMINI_BASE_URL": context.api_base_url(request.api_mode),
                "GEMINI_API_KEY": context.api_key or "0",
                "GEMINI_MODEL": model,
                "GEMINI_CLI_TRUST_WORKSPACE": "true",
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
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={
                    "env": redact_secrets(
                        self.build_env(request, context, home="<temp>")
                    ),
                    "workspace": request.workspace,
                    **attachment_raw_metadata(request),
                },
                events=attachment_warning_events(request),
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
        prepared_context, proxy_events, proxy_error = prepare_proxy_for_agent(
            request,
            context,
            command=command,
        )
        if proxy_error is not None:
            return proxy_error
        with tempfile.TemporaryDirectory(prefix="gpt2giga-gemini-") as temp_dir:
            _write_gemini_settings(Path(temp_dir))
            env = self.build_env(request, prepared_context, home=temp_dir)
            result = run_command(
                label="Gemini CLI",
                command=command,
                env=env,
                cwd=request.workspace,
                timeout_seconds=context.timeout_seconds,
            )
            return with_events(
                result,
                (*attachment_warning_events(request), *proxy_events),
            )


def _write_gemini_settings(home: Path) -> None:
    settings_path = home / ".gemini" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {"security": {"auth": {"selectedType": "gemini-api-key"}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
