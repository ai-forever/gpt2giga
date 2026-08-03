"""Hermetic cross-provider conformance-runner contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt2giga.protocols.normalized.loss_matrix import (
    PublicProtocol,
    UpstreamProvider,
)
from gpt2giga.protocols.normalized.models import (
    NormalizedChatRequest,
    NormalizedResponse,
    NormalizedStreamEvent,
)
from conformance_runner import (
    BridgeConformanceCase,
    BridgeConformanceRunner,
    ConformanceObservation,
    FakeProviderCancelled,
    FakeProviderProtocolError,
    FakeProviderScript,
    ScriptedFakeProvider,
)


CORPUS = Path(__file__).parent / "v1"


class FixtureProviderAdapter:
    """Project the same normalized fake-provider facts for one provider kind."""

    def __init__(self, provider: UpstreamProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        case: BridgeConformanceCase,
        provider: ScriptedFakeProvider,
    ) -> ConformanceObservation:
        try:
            if not case.request.stream:
                response = await provider.complete(case.request)
                choice = response.choices[0]
                message = choice.message
                usage = response.usage
                return ConformanceObservation(
                    public_response={
                        "output_text": message.content if message is not None else None,
                        "status": "completed",
                        "usage": (
                            usage.model_dump(
                                mode="json",
                                exclude_none=True,
                                exclude={"provider_metadata", "raw_extensions"},
                            )
                            if usage is not None
                            else None
                        ),
                    }
                )

            events: list[str] = []
            output: list[str] = []
            async for event in provider.stream(case.request):
                events.append(event.type)
                if event.content_delta:
                    output.append(event.content_delta)
            return ConformanceObservation(
                public_response={
                    "events": events,
                    "output_text": "".join(output),
                    "status": "completed" if events[-1] == "message_end" else "failed",
                }
            )
        except FakeProviderProtocolError:
            return ConformanceObservation(error_code="provider_protocol_error")
        except FakeProviderCancelled:
            return ConformanceObservation(error_code="client_disconnected")


class DoubleDispatchAdapter(FixtureProviderAdapter):
    async def execute(
        self,
        case: BridgeConformanceCase,
        provider: ScriptedFakeProvider,
    ) -> ConformanceObservation:
        await provider.complete(case.request)
        return await super().execute(case, provider)


def _load_cases() -> list[tuple[BridgeConformanceCase, FakeProviderScript]]:
    payload = json.loads(
        (CORPUS / "provider_conformance_cases.json").read_text(encoding="utf-8")
    )
    result: list[tuple[BridgeConformanceCase, FakeProviderScript]] = []
    for raw in payload["cases"]:
        script_payload = raw["script"]
        script = FakeProviderScript(
            response=(
                NormalizedResponse.model_validate(script_payload["response"])
                if "response" in script_payload
                else None
            ),
            events=tuple(
                NormalizedStreamEvent.model_validate(event)
                for event in script_payload.get("events", [])
            ),
            latency_seconds=script_payload.get("latency_seconds", 0.0),
            malformed_at_event=script_payload.get("malformed_at_event"),
            cancel_after_events=script_payload.get("cancel_after_events"),
        )
        result.append(
            (
                BridgeConformanceCase(
                    case_id=raw["id"],
                    public_protocol=PublicProtocol(raw["public_protocol"]),
                    request=NormalizedChatRequest.model_validate(raw["request"]),
                    expected_public_response=raw.get("expected_public_response"),
                    expected_error_code=raw.get("expected_error_code"),
                    expected_network_attempts=raw["expected_network_attempts"],
                ),
                script,
            )
        )
    return result


def _adapters() -> dict[UpstreamProvider, FixtureProviderAdapter]:
    return {provider: FixtureProviderAdapter(provider) for provider in UpstreamProvider}


async def test_same_corpus_runs_across_every_provider_without_network() -> None:
    injected_delays: list[float] = []

    async def record_delay(seconds: float) -> None:
        injected_delays.append(seconds)

    runner = BridgeConformanceRunner(sleep=record_delay)
    results = []
    for case, script in _load_cases():
        results.extend(await runner.run_across_providers(case, _adapters(), script))

    assert len(results) == len(_load_cases()) * len(UpstreamProvider)
    assert {result.provider for result in results} == set(UpstreamProvider)
    assert all(result.network_attempts == 1 for result in results)
    assert injected_delays == [0.025] * len(UpstreamProvider)


async def test_runner_requires_a_complete_provider_adapter_set() -> None:
    case, script = _load_cases()[0]
    adapters = _adapters()
    adapters.pop(UpstreamProvider.GEMINI)

    with pytest.raises(ValueError, match="provider adapter set must be complete"):
        await BridgeConformanceRunner().run_across_providers(case, adapters, script)


async def test_runner_detects_hidden_retry_or_fallback_attempts() -> None:
    case, script = _load_cases()[0]

    with pytest.raises(AssertionError, match="expected 1 network attempts, got 2"):
        await BridgeConformanceRunner().run_case(
            case,
            DoubleDispatchAdapter(UpstreamProvider.GIGACHAT),
            script,
        )


async def test_runner_rejects_credential_shaped_case_before_dispatch() -> None:
    case, script = _load_cases()[0]
    unsafe = BridgeConformanceCase(
        case_id="unsafe-credential",
        public_protocol=case.public_protocol,
        request=case.request.model_copy(
            update={"provider_metadata": {"api_key": "fixture-secret"}}
        ),
        expected_public_response=case.expected_public_response,
    )

    with pytest.raises(ValueError, match="credential-shaped field"):
        await BridgeConformanceRunner().run_case(
            unsafe,
            FixtureProviderAdapter(UpstreamProvider.GIGACHAT),
            script,
        )


async def test_runner_detects_public_golden_drift() -> None:
    case, script = _load_cases()[0]
    drifted = BridgeConformanceCase(
        case_id="golden-drift",
        public_protocol=case.public_protocol,
        request=case.request,
        expected_public_response={"output_text": "different"},
    )

    with pytest.raises(AssertionError, match="public golden mismatch"):
        await BridgeConformanceRunner().run_case(
            drifted,
            FixtureProviderAdapter(UpstreamProvider.GIGACHAT),
            script,
        )
