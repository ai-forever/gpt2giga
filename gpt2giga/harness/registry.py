"""Harness registry and plugin discovery."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Iterable

from gpt2giga.harness.harnesses import (
    ClaudeCodeHarness,
    CodexCliHarness,
    DirectChatHarness,
    EchoHarness,
    GeminiCliHarness,
)
from gpt2giga.harness.harnesses.base import BaseHarness

ENTRY_POINT_GROUP = "gpt2giga.harnesses"
BUILTIN_HARNESSES = (
    DirectChatHarness,
    CodexCliHarness,
    ClaudeCodeHarness,
    GeminiCliHarness,
    EchoHarness,
)


class UnknownHarnessError(KeyError):
    """Raised when a harness id is not registered."""


class HarnessRegistry:
    """Store and discover harness implementations."""

    def __init__(self) -> None:
        self._harnesses: dict[str, BaseHarness] = {}
        self.discovery_errors: list[str] = []

    def register(self, harness: BaseHarness) -> None:
        """Register one harness instance."""
        spec = harness.spec()
        self._harnesses[spec.id] = harness

    def get(self, harness_id: str) -> BaseHarness:
        """Return a registered harness by id."""
        try:
            return self._harnesses[harness_id]
        except KeyError as exc:
            raise UnknownHarnessError(harness_id) from exc

    def list(self) -> tuple[BaseHarness, ...]:
        """Return registered harnesses in registration order."""
        return tuple(self._harnesses.values())

    def ids(self) -> tuple[str, ...]:
        """Return registered harness ids."""
        return tuple(sorted(self._harnesses))

    @classmethod
    def with_builtins(cls) -> "HarnessRegistry":
        """Create a registry with built-in harnesses."""
        registry = cls()
        registry.register_many(harness_class() for harness_class in BUILTIN_HARNESSES)
        return registry

    def register_many(self, harnesses: Iterable[BaseHarness]) -> None:
        """Register multiple harness instances."""
        for harness in harnesses:
            self.register(harness)

    def load_entry_points(self) -> None:
        """Load third-party harnesses from package entry points."""
        try:
            selected = _select_entry_points()
        except Exception as exc:  # pragma: no cover - defensive importlib path
            self.discovery_errors.append(str(exc))
            return
        for entry_point in selected:
            try:
                harness_class = entry_point.load()
                harness = harness_class()
                self.register(harness)
            except Exception as exc:  # pragma: no cover - plugin failure path
                self.discovery_errors.append(f"{entry_point.name}: {exc}")


def create_default_registry(*, include_entry_points: bool = True) -> HarnessRegistry:
    """Create the default registry used by CLI and UI."""
    registry = HarnessRegistry.with_builtins()
    if include_entry_points:
        registry.load_entry_points()
    return registry


def _select_entry_points():
    all_entry_points = entry_points()
    if hasattr(all_entry_points, "select"):
        return all_entry_points.select(group=ENTRY_POINT_GROUP)
    return all_entry_points.get(ENTRY_POINT_GROUP, ())
