#!/usr/bin/env python3
"""Measure hermetic normalized bridge overhead with reproducible workloads."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
import math
from pathlib import Path
import platform
import sys
from time import perf_counter_ns
from typing import Any, NamedTuple

from starlette.responses import JSONResponse

from gpt2giga.protocols.normalized import (
    BRIDGE_LOSS_MATRIX_V1,
    BridgeFeature,
    BridgeSemantic,
    DownstreamProtocol,
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedTokenLimits,
    NormalizedUsage,
    ProtocolBridgeAdmission,
    PublicProtocol,
    UpstreamProvider,
    admit_bridge_route,
    bridge_loss_matrix_json,
)
from gpt2giga.protocols.openai import OpenAIProtocolAdapter, ResponsesStreamProjector
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_responses,
)
from gpt2giga.providers.anthropic import (
    ANTHROPIC_IMPLEMENTED_FEATURES_V1,
    anthropic_profile,
    anthropic_response_to_normalized,
    normalized_chat_to_anthropic_payload,
)
from gpt2giga.providers.gemini import (
    gemini_response_to_normalized,
    gemini_upstream_profile,
    normalized_chat_to_gemini_payload,
)
from gpt2giga.providers.openai_compatible import (
    normalized_chat_to_openai_compatible_payload,
    openai_compatible_profile,
    openai_compatible_response_to_normalized,
)
from gpt2giga.providers.profiles import (
    LoadedProviderProfileSet,
    ProviderMachineContracts,
    ProviderProfileConfig,
    ProviderRegistry,
)


REPORT_SCHEMA_VERSION = "gpt2giga.bridge-performance.v1"
DEFAULT_SAMPLES = 25
DEFAULT_ITERATIONS = 10
DEFAULT_WARMUPS = 5
WORKLOAD_NAMES = (
    "responses_nonstream",
    "responses_stream_first_event",
    "responses_stream_total",
    "alias_profile_admission",
    "openai_fake_adapter",
    "anthropic_fake_adapter",
    "gemini_fake_adapter",
    "models_endpoint",
    "capabilities_endpoint",
)


class Workload(NamedTuple):
    """One timed callable plus its untimed correctness check."""

    name: str
    mechanism: str
    run: Callable[[], Any]
    check: Callable[[Any], None]


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return the nearest-rank percentile for a non-empty sample."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 < fraction <= 1:
        raise ValueError("percentile fraction must be in (0, 1]")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def measure_workload(
    workload: Workload,
    *,
    samples: int,
    iterations: int,
    warmups: int,
) -> dict[str, Any]:
    """Measure one workload and return per-operation p50/p95 in microseconds."""
    if samples < 1 or iterations < 1 or warmups < 0:
        raise ValueError("samples/iterations must be positive and warmups non-negative")
    result: Any = None
    for _ in range(warmups):
        result = workload.run()
    workload.check(result)

    timings_us: list[float] = []
    for _ in range(samples):
        started = perf_counter_ns()
        for _ in range(iterations):
            result = workload.run()
        elapsed_ns = perf_counter_ns() - started
        timings_us.append(elapsed_ns / iterations / 1_000)
    workload.check(result)
    return {
        "name": workload.name,
        "mechanism": workload.mechanism,
        "p50_us": round(percentile(timings_us, 0.50), 3),
        "p95_us": round(percentile(timings_us, 0.95), 3),
        "min_us": round(min(timings_us), 3),
        "max_us": round(max(timings_us), 3),
    }


def run_benchmarks(
    *,
    samples: int = DEFAULT_SAMPLES,
    iterations: int = DEFAULT_ITERATIONS,
    warmups: int = DEFAULT_WARMUPS,
    workload_names: Sequence[str] = (),
    label: str = "working-tree",
) -> dict[str, Any]:
    """Run all or selected bridge workloads without provider or network access."""
    selected = tuple(workload_names) or WORKLOAD_NAMES
    unknown = sorted(set(selected) - set(WORKLOAD_NAMES))
    if unknown:
        raise ValueError(f"unknown workloads: {', '.join(unknown)}")
    workloads = {workload.name: workload for workload in build_workloads()}
    results = [
        measure_workload(
            workloads[name],
            samples=samples,
            iterations=iterations,
            warmups=warmups,
        )
        for name in selected
    ]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "label": label,
        "environment": {
            "implementation": platform.python_implementation(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "parameters": {
            "samples": samples,
            "iterations": iterations,
            "warmups": warmups,
        },
        "workloads": results,
    }


def compare_reports(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Compare matching workloads; negative percentages are improvements."""
    _validate_report(baseline)
    _validate_report(candidate)
    baseline_by_name = {item["name"]: item for item in baseline["workloads"]}
    comparisons: list[dict[str, Any]] = []
    for current in candidate["workloads"]:
        previous = baseline_by_name.get(current["name"])
        if previous is None:
            continue
        comparisons.append(
            {
                "name": current["name"],
                "p50_change_percent": _percentage_change(
                    previous["p50_us"], current["p50_us"]
                ),
                "p95_change_percent": _percentage_change(
                    previous["p95_us"], current["p95_us"]
                ),
            }
        )
    return comparisons


def build_workloads() -> tuple[Workload, ...]:
    """Build the fixed, content-bounded bridge workload set."""
    normalized_request = OpenAIProtocolAdapter().responses_to_normalized(
        _responses_request_payload()
    )
    adapter_request = normalized_request.model_copy(update={"metadata": {}})
    normalized_response = NormalizedResponse(
        id="fixture-response",
        model="fixture-model",
        provider="fixture-provider",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(role="assistant", content="pong"),
                finish_reason="stop",
                stop_reason="stop",
            )
        ],
        usage=NormalizedUsage(
            input_tokens=32,
            output_tokens=2,
            total_tokens=34,
        ),
    )
    registry = _provider_registry()
    contracts = ProviderMachineContracts(registry)
    matrix_manifest = bridge_loss_matrix_json()
    admission = ProtocolBridgeAdmission(
        downstream=DownstreamProtocol.OPENAI,
        upstream_profile="fixture@r1",
        required_features=(),
    )
    limits = NormalizedTokenLimits(
        context_window=8192,
        max_input_tokens=6144,
        max_output_tokens=2048,
    )
    openai_profile = openai_compatible_profile(
        profile_id="openai-fixture",
        revision="r1",
        config_revision=f"sha256:{'1' * 64}",
        public_alias="openai/fixture",
        base_url="https://openai.invalid/v1",
        model="fixture-model",
        capability_profile="fixture@r1",
        loss_matrix_revision=f"sha256:{'2' * 64}",
        features=frozenset(BridgeFeature),
        limits=limits,
        network_policy_ref="egress:fixture",
    )
    anthropic_profile_value = anthropic_profile(
        profile_id="anthropic-fixture",
        revision="r1",
        base_url="https://anthropic.invalid",
        model="fixture-model",
        features=ANTHROPIC_IMPLEMENTED_FEATURES_V1,
        limits=limits,
        network_policy_ref="egress:fixture",
        default_max_tokens=256,
    )
    gemini_profile = gemini_upstream_profile(
        profile_id="gemini-fixture",
        revision="r1",
        base_url="https://gemini.invalid/v1beta",
        model="fixture-model",
        features=frozenset(BridgeFeature),
        limits=limits,
        network_policy_ref="egress:fixture",
    )

    def responses_nonstream() -> tuple[int, str]:
        request = OpenAIProtocolAdapter().responses_to_normalized(
            _responses_request_payload()
        )
        projected = normalized_chat_response_to_responses(
            normalized_response,
            request_payload=_responses_request_payload(),
            requested_model="bridge/codex-test",
            response_id="fixture",
        )
        return len(request.messages), projected["status"]

    def responses_first_event() -> str:
        projector = _stream_projector()
        return projector.project(
            NormalizedStreamEvent(type="message_start", sequence=0)
        )[0]

    stream_events = _stream_events()

    def responses_stream_total() -> tuple[int, bool]:
        projector = _stream_projector()
        byte_count = 0
        for event in stream_events:
            byte_count += sum(len(frame) for frame in projector.project(event))
        projector.finish()
        return byte_count, projector.terminal

    def alias_profile_admission() -> tuple[str, str]:
        route = registry.resolve("giga/max")
        decision = admit_bridge_route(
            public_protocol=PublicProtocol.OPENAI_CHAT_COMPLETIONS,
            public_alias=route.public_alias,
            upstream_provider=UpstreamProvider.GIGACHAT,
            profile_id=route.profile_id,
            config_revision=route.config_revision,
            capability_profile_revision=route.capability_profile,
            requested_semantics={
                BridgeSemantic.ROLES: "messages",
                BridgeSemantic.TOOL_DEFINITIONS_AND_CALL_IDS: "tools",
            },
        )
        return route.upstream_model, decision.loss_matrix_revision

    def openai_fake_adapter() -> tuple[str, str]:
        payload = normalized_chat_to_openai_compatible_payload(adapter_request)
        response = openai_compatible_response_to_normalized(
            _openai_response(),
            profile=openai_profile,
            admission=admission,
        )
        return payload["model"], response.choices[0].message.content

    def anthropic_fake_adapter() -> tuple[str, str]:
        payload = normalized_chat_to_anthropic_payload(
            adapter_request,
            profile=anthropic_profile_value,
        )
        response = anthropic_response_to_normalized(
            _anthropic_response(),
            profile=anthropic_profile_value,
            admission=admission,
        )
        content = response.choices[0].message.content
        return payload["model"], content[0].text

    def gemini_fake_adapter() -> tuple[str, str]:
        payload = normalized_chat_to_gemini_payload(
            adapter_request,
            profile=gemini_profile,
        )
        response = gemini_response_to_normalized(
            _gemini_response(),
            profile=gemini_profile,
            admission=admission,
        )
        return payload["contents"][0]["role"], response.choices[0].message.content

    def models_endpoint() -> bytes:
        return JSONResponse(contracts.models_manifest()).body

    def capabilities_endpoint() -> bytes:
        return JSONResponse(contracts.capabilities_manifest(matrix_manifest)).body

    return (
        Workload(
            "responses_nonstream",
            "Responses decode plus normalized non-stream projection",
            responses_nonstream,
            lambda value: _require(value == (17, "completed")),
        ),
        Workload(
            "responses_stream_first_event",
            "Fresh projector through response.created SSE serialization",
            responses_first_event,
            lambda value: _require(value.startswith("event: response.created")),
        ),
        Workload(
            "responses_stream_total",
            "256 text deltas through terminal Responses SSE projection",
            responses_stream_total,
            lambda value: _require(value[0] > 0 and value[1] is True),
        ),
        Workload(
            "alias_profile_admission",
            "Exact alias resolution plus matrix admission before I/O",
            alias_profile_admission,
            lambda value: _require(
                value == ("GigaChat-Pro", BRIDGE_LOSS_MATRIX_V1.revision)
            ),
        ),
        Workload(
            "openai_fake_adapter",
            "Normalized request/response round-trip without network",
            openai_fake_adapter,
            lambda value: _require(value == ("bridge/codex-test", "pong")),
        ),
        Workload(
            "anthropic_fake_adapter",
            "Normalized Anthropic payload/response round-trip without network",
            anthropic_fake_adapter,
            lambda value: _require(value == ("fixture-model", "pong")),
        ),
        Workload(
            "gemini_fake_adapter",
            "Normalized Gemini payload/response round-trip without network",
            gemini_fake_adapter,
            lambda value: _require(value == ("user", "pong")),
        ),
        Workload(
            "models_endpoint",
            "Content-free models manifest plus JSON response serialization",
            models_endpoint,
            lambda value: _require(b'"models"' in value),
        ),
        Workload(
            "capabilities_endpoint",
            "16-cell capability manifest plus JSON response serialization",
            capabilities_endpoint,
            lambda value: _require(b'"cells"' in value),
        ),
    )


def _responses_request_payload() -> dict[str, Any]:
    inputs = [
        {
            "type": "message",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": [
                {
                    "type": "input_text" if index % 2 == 0 else "output_text",
                    "text": f"bounded fixture turn {index}",
                }
            ],
        }
        for index in range(16)
    ]
    return {
        "model": "bridge/codex-test",
        "instructions": "Be concise.",
        "input": inputs,
        "tools": [
            {
                "type": "function",
                "name": "lookup",
                "description": "Look up a value.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
        "tool_choice": "auto",
        "max_output_tokens": 128,
        "temperature": 0.2,
        "metadata": {"fixture": "bridge-v1"},
    }


def _stream_projector() -> ResponsesStreamProjector:
    return ResponsesStreamProjector(
        request_payload={"input": "hello", "model": "bridge/codex-test"},
        requested_model="bridge/codex-test",
        response_id="fixture",
        created_at=100,
    )


def _stream_events() -> tuple[NormalizedStreamEvent, ...]:
    events = [NormalizedStreamEvent(type="message_start", sequence=0)]
    events.extend(
        NormalizedStreamEvent(
            type="content_delta",
            sequence=index,
            content_delta="abcdefgh",
        )
        for index in range(1, 257)
    )
    events.append(
        NormalizedStreamEvent(
            type="message_end",
            sequence=257,
            finish_reason="stop",
            usage=NormalizedUsage(
                input_tokens=32,
                output_tokens=256,
                total_tokens=288,
            ),
        )
    )
    return tuple(events)


def _provider_registry() -> ProviderRegistry:
    profiles = []
    for provider, alias, upstream, status in (
        ("gigachat", "giga/max", "GigaChat-Pro", "stable"),
        ("openai_compatible", "openai/default", "fixture-model", "stable"),
        ("anthropic", "anthropic/default", "fixture-model", "technical_preview"),
        ("gemini", "gemini/default", "fixture-model", "technical_preview"),
    ):
        profiles.append(
            {
                "profile_id": f"{provider}-main".replace("_", "-"),
                "provider_kind": provider,
                "base_url": f"https://{provider.replace('_', '-')}.invalid/v1",
                "credential_env": f"{provider.upper()}_API_KEY",
                "network_policy_ref": "egress-fixture",
                "tls_policy_ref": "system-default",
                "models": [
                    {
                        "public_alias": alias,
                        "upstream_model": upstream,
                        "capability_profile": f"{provider}-v1",
                        "support_status": status,
                    }
                ],
            }
        )
    config = ProviderProfileConfig.model_validate({"profiles": profiles})
    loaded = LoadedProviderProfileSet(
        config=config,
        _credentials={profile["profile_id"]: "fixture" for profile in profiles},
    )
    return ProviderRegistry(
        loaded,
        loss_matrix_revision=BRIDGE_LOSS_MATRIX_V1.revision,
    )


def _openai_response() -> dict[str, Any]:
    return {
        "id": "chatcmpl-fixture",
        "created": 100,
        "model": "fixture-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "pong"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 32, "completion_tokens": 2, "total_tokens": 34},
    }


def _anthropic_response() -> dict[str, Any]:
    return {
        "id": "msg-fixture",
        "type": "message",
        "role": "assistant",
        "model": "fixture-model",
        "content": [{"type": "text", "text": "pong"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 32, "output_tokens": 2},
    }


def _gemini_response() -> dict[str, Any]:
    return {
        "responseId": "gemini-fixture",
        "modelVersion": "fixture-model",
        "candidates": [
            {
                "index": 0,
                "content": {"role": "model", "parts": [{"text": "pong"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 32,
            "candidatesTokenCount": 2,
            "totalTokenCount": 34,
        },
    }


def _require(condition: bool) -> None:
    if not condition:
        raise AssertionError("bridge benchmark mechanism check failed")


def _percentage_change(previous: float, current: float) -> float:
    if previous <= 0:
        raise ValueError("baseline timings must be positive")
    return round((current - previous) / previous * 100, 2)


def _validate_report(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("benchmark report schema is unsupported")
    workloads = report.get("workloads")
    if not isinstance(workloads, list):
        raise ValueError("benchmark report workloads must be a list")
    for workload in workloads:
        if not isinstance(workload, Mapping):
            raise ValueError("benchmark workload result must be an object")
        if not isinstance(workload.get("name"), str):
            raise ValueError("benchmark workload name is missing")
        for field in ("p50_us", "p95_us"):
            value = workload.get(field)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"benchmark workload {field} must be positive")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--workload", action="append", default=[])
    parser.add_argument("--label", default="working-tree")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark CLI and emit one JSON report."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = run_benchmarks(
            samples=args.samples,
            iterations=args.iterations,
            warmups=args.warmups,
            workload_names=args.workload,
            label=args.label,
        )
        if args.baseline is not None:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
            report["comparison"] = {
                "baseline_label": baseline.get("label"),
                "negative_is_improvement": True,
                "workloads": compare_reports(baseline, report),
            }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"bridge benchmark failed: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
