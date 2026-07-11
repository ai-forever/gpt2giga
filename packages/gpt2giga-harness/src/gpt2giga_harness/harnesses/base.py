"""Abstract base class for Unified Harness implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from gpt2giga_harness.types import (
    Availability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class BaseHarness(ABC):
    """Base class for all Unified Harness implementations."""

    @classmethod
    @abstractmethod
    def spec(cls) -> HarnessSpec:
        """Return static harness metadata."""

    @abstractmethod
    def availability(self) -> Availability:
        """Return availability in the current environment."""

    @abstractmethod
    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        """Run a normalized harness request."""
