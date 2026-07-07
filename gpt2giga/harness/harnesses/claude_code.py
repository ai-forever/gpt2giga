"""Claude Code harness scaffold."""

from __future__ import annotations

import shutil

from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class ClaudeCodeHarness(BaseHarness):
    """Detect Claude Code and expose a safe scaffold."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="claude-code",
            title="Claude Code",
            kind="agent-cli",
            description="Claude Code adapter scaffold; executable detection only",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_workspace=True,
            tags=("claude", "agent", "scaffold"),
        )

    def availability(self) -> Availability:
        executable = shutil.which("claude")
        if executable is None:
            return Availability.missing(
                "claude executable not found",
                "Install Claude Code and ensure it is on PATH.",
            )
        return Availability.available(f"claude executable found: {executable}")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(
            ok=False,
            text="",
            raw={"api_mode": request.api_mode.value, "proxy_url": context.proxy_url},
            error=(
                "Claude Code command execution is not implemented in this MVP. "
                "The harness is registered for availability and UI scaffolding."
            ),
        )
