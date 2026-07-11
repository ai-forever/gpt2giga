"""Registry for native harness history connectors."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from gpt2giga_harness.config import DEFAULT_HARNESS_DATA_DIR
from gpt2giga_harness.native.base import (
    NativeDiscoveryError,
    NativeDiscoveryResult,
    NativeHistoryConnector,
)
from gpt2giga_harness.types import redact_secrets


class UnknownNativeHistoryConnectorError(KeyError):
    """Raised when a native history connector is not registered."""


class NativeHistoryConnectorRegistry:
    """Store and invoke native history connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, NativeHistoryConnector] = {}

    def register(self, connector: NativeHistoryConnector) -> None:
        """Register one connector instance."""
        self._connectors[connector.harness_id] = connector

    def register_many(self, connectors: Iterable[NativeHistoryConnector]) -> None:
        """Register multiple connector instances."""
        for connector in connectors:
            self.register(connector)

    def get(self, harness_id: str) -> NativeHistoryConnector:
        """Return a connector by harness id."""
        try:
            return self._connectors[harness_id]
        except KeyError as exc:
            raise UnknownNativeHistoryConnectorError(harness_id) from exc

    def list(self) -> tuple[NativeHistoryConnector, ...]:
        """Return connectors in registration order."""
        return tuple(self._connectors.values())

    def ids(self) -> tuple[str, ...]:
        """Return registered connector harness ids."""
        return tuple(sorted(self._connectors))

    def discover(
        self,
        *,
        harness_id: str | None = None,
        workspace: str | None = None,
        include_external: bool = False,
    ) -> NativeDiscoveryResult:
        """Discover native sessions and return connector failures as data."""
        connectors = self._connectors_for_discovery(harness_id)
        sessions = []
        errors = []
        for connector in connectors:
            try:
                sessions.extend(
                    connector.discover(
                        workspace=workspace,
                        include_external=include_external,
                    )
                )
            except Exception as exc:
                errors.append(_connector_error(connector.harness_id, exc))
        if harness_id is not None and not connectors:
            errors.append(
                NativeDiscoveryError(
                    harness_id=harness_id,
                    code="unknown_connector",
                    message=f"Native history connector is not registered: {harness_id}",
                )
            )
        return NativeDiscoveryResult(sessions=tuple(sessions), errors=tuple(errors))

    def _connectors_for_discovery(
        self,
        harness_id: str | None,
    ) -> tuple[NativeHistoryConnector, ...]:
        if harness_id is None:
            return self.list()
        connector = self._connectors.get(harness_id)
        return (connector,) if connector is not None else ()


def _connector_error(
    harness_id: str,
    exc: Exception,
) -> NativeDiscoveryError:
    return NativeDiscoveryError(
        harness_id=harness_id,
        code="connector_error",
        message=str(redact_secrets(str(exc))),
        detail=type(exc).__name__,
    )


def create_default_native_registry(
    *,
    data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
) -> NativeHistoryConnectorRegistry:
    """Create a registry with built-in native history connectors."""
    from gpt2giga_harness.native.claude import ClaudeNativeHistoryConnector
    from gpt2giga_harness.native.codex import CodexNativeHistoryConnector
    from gpt2giga_harness.native.gemini import GeminiNativeHistoryConnector

    registry = NativeHistoryConnectorRegistry()
    registry.register_many(
        (
            CodexNativeHistoryConnector(data_dir=data_dir),
            ClaudeNativeHistoryConnector(data_dir=data_dir),
            GeminiNativeHistoryConnector(data_dir=data_dir),
        )
    )
    return registry
