"""Reusable hermetic conformance runner for normalized provider adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol

from gpt2giga.protocols.normalized.loss_matrix import (
    PublicProtocol,
    UpstreamProvider,
)
from gpt2giga.protocols.normalized.models import (
    NormalizedChatRequest,
    NormalizedResponse,
    NormalizedStreamEvent,
)


class FakeProviderProtocolError(RuntimeError):
    """Raised when a scripted provider emits one malformed stream frame."""


class FakeProviderCancelled(RuntimeError):
    """Raised when cancellation reaches the exact scripted provider request."""


@dataclass(frozen=True)
class FakeProviderScript:
    """Deterministic response, stream, failure, and latency instructions."""

    response: NormalizedResponse | None = None
    events: tuple[NormalizedStreamEvent, ...] = ()
    latency_seconds: float = 0.0
    malformed_at_event: int | None = None
    cancel_after_events: int | None = None

    def __post_init__(self) -> None:
        if self.latency_seconds < 0:
            raise ValueError("latency_seconds must be non-negative")
        if self.malformed_at_event is not None and self.malformed_at_event < 0:
            raise ValueError("malformed_at_event must be non-negative")
        if self.cancel_after_events is not None and self.cancel_after_events < 0:
            raise ValueError("cancel_after_events must be non-negative")


class ScriptedFakeProvider:
    """In-memory provider boundary with observable network-attempt semantics."""

    def __init__(
        self,
        provider: UpstreamProvider,
        script: FakeProviderScript,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.provider = provider
        self.script = script
        self.network_attempts = 0
        self._sleep = sleep
        self._cancelled = False

    def cancel(self) -> None:
        """Cancel the currently scripted operation without starting another."""
        self._cancelled = True

    async def complete(self, _request: NormalizedChatRequest) -> NormalizedResponse:
        """Return one copied normalized response after injected latency."""
        self.network_attempts += 1
        await self._delay()
        self._raise_if_cancelled()
        if self.script.response is None:
            raise FakeProviderProtocolError("script has no non-stream response")
        return self.script.response.model_copy(deep=True)

    async def stream(
        self,
        _request: NormalizedChatRequest,
    ) -> AsyncIterator[NormalizedStreamEvent]:
        """Yield copied normalized events and inject exact failure boundaries."""
        self.network_attempts += 1
        for index, event in enumerate(self.script.events):
            await self._delay()
            self._raise_if_cancelled()
            if self.script.malformed_at_event == index:
                raise FakeProviderProtocolError(
                    f"malformed scripted frame at event {index}"
                )
            yield event.model_copy(deep=True)
            if self.script.cancel_after_events == index + 1:
                self.cancel()
        self._raise_if_cancelled()

    async def _delay(self) -> None:
        if self.script.latency_seconds:
            await self._sleep(self.script.latency_seconds)

    def _raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise FakeProviderCancelled("scripted provider operation cancelled")


@dataclass(frozen=True)
class BridgeConformanceCase:
    """One normalized input and exact public-protocol golden outcome."""

    case_id: str
    public_protocol: PublicProtocol
    request: NormalizedChatRequest
    expected_public_response: Mapping[str, Any] | None = None
    expected_error_code: str | None = None
    expected_network_attempts: int = 1

    def __post_init__(self) -> None:
        if (self.expected_public_response is None) == (
            self.expected_error_code is None
        ):
            raise ValueError("case must expect exactly one response or error")
        if self.expected_network_attempts < 0:
            raise ValueError("expected_network_attempts must be non-negative")


@dataclass(frozen=True)
class ConformanceObservation:
    """Public adapter observation returned to the conformance runner."""

    public_response: Mapping[str, Any] | None = None
    error_code: str | None = None


class ProviderConformanceAdapter(Protocol):
    """Minimal adapter hook implemented by every provider conformance lane."""

    provider: UpstreamProvider

    async def execute(
        self,
        case: BridgeConformanceCase,
        provider: ScriptedFakeProvider,
    ) -> ConformanceObservation:
        """Execute one case and project it to the selected public protocol."""


@dataclass(frozen=True)
class BridgeConformanceResult:
    """Bounded result retained after exact golden and attempt assertions."""

    case_id: str
    provider: UpstreamProvider
    public_protocol: PublicProtocol
    network_attempts: int
    error_code: str | None


class BridgeConformanceRunner:
    """Run identical normalized cases across a complete provider adapter set."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sleep = sleep

    async def run_case(
        self,
        case: BridgeConformanceCase,
        adapter: ProviderConformanceAdapter,
        script: FakeProviderScript,
    ) -> BridgeConformanceResult:
        """Assert one adapter's golden output and exact network-attempt count."""
        _assert_no_live_credentials(case.request.model_dump(mode="json"))
        _assert_no_live_credentials(_script_payload(script))
        provider = ScriptedFakeProvider(
            adapter.provider,
            script,
            sleep=self._sleep,
        )
        observation = await adapter.execute(case, provider)
        if _canonical(observation.public_response) != _canonical(
            case.expected_public_response
        ):
            raise AssertionError(
                f"{case.case_id}/{adapter.provider.value}: public golden mismatch"
            )
        if observation.error_code != case.expected_error_code:
            raise AssertionError(
                f"{case.case_id}/{adapter.provider.value}: error code mismatch"
            )
        if provider.network_attempts != case.expected_network_attempts:
            raise AssertionError(
                f"{case.case_id}/{adapter.provider.value}: expected "
                f"{case.expected_network_attempts} network attempts, got "
                f"{provider.network_attempts}"
            )
        return BridgeConformanceResult(
            case_id=case.case_id,
            provider=adapter.provider,
            public_protocol=case.public_protocol,
            network_attempts=provider.network_attempts,
            error_code=observation.error_code,
        )

    async def run_across_providers(
        self,
        case: BridgeConformanceCase,
        adapters: Mapping[UpstreamProvider, ProviderConformanceAdapter],
        script: FakeProviderScript,
    ) -> tuple[BridgeConformanceResult, ...]:
        """Run a case once for each exact provider kind in lexical order."""
        if set(adapters) != set(UpstreamProvider):
            missing = set(UpstreamProvider) - set(adapters)
            extra = set(adapters) - set(UpstreamProvider)
            raise ValueError(
                "provider adapter set must be complete; "
                f"missing={sorted(item.value for item in missing)}, "
                f"extra={sorted(str(item) for item in extra)}"
            )
        return tuple(
            [
                await self.run_case(case, adapters[provider], script)
                for provider in sorted(UpstreamProvider, key=lambda item: item.value)
            ]
        )


def _script_payload(script: FakeProviderScript) -> dict[str, Any]:
    return {
        "response": (
            script.response.model_dump(mode="json")
            if script.response is not None
            else None
        ),
        "events": [event.model_dump(mode="json") for event in script.events],
    }


def _canonical(value: Mapping[str, Any] | None) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _assert_no_live_credentials(value: Any) -> None:
    forbidden_keys = {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "refresh_token",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise ValueError(f"credential-shaped field is forbidden: {key}")
            _assert_no_live_credentials(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_live_credentials(item)
        return
    if isinstance(value, str) and (
        value.lower().startswith("bearer ") or value.startswith("sk-")
    ):
        raise ValueError("credential-shaped value is forbidden")
