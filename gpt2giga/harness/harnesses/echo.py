"""Local echo harness for UI and registry smoke tests."""

from __future__ import annotations

from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class EchoHarness(BaseHarness):
    """Return the prompt without touching the network."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="echo",
            title="Echo",
            kind="test",
            description="Local echo harness for tests and UI smoke checks",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            tags=("local", "test"),
        )

    def availability(self) -> Availability:
        return Availability.available("local harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        model = request.model or context.default_model
        return HarnessResult(
            ok=True,
            text=request.prompt,
            raw={
                "model": model,
                "api_mode": request.api_mode.value,
                "capability": request.capability.value,
                "mode": request.mode,
            },
            command=(
                "giga",
                "harness",
                "run",
                "echo",
                "--api-mode",
                request.api_mode.value,
                "--prompt",
                request.prompt,
            ),
        )
