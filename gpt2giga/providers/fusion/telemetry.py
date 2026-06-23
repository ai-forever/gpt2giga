"""Safe Fusion observability and metrics helpers."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized.models import NormalizedUsage
from gpt2giga.providers.fusion.detection import FusionRequestConfig
from gpt2giga.providers.fusion.schemas import FusionRunResult
from gpt2giga.providers.fusion.usage import aggregate_usage
from gpt2giga.sinks.metrics.factory import (
    emit_metric_increment,
    emit_metric_observation,
)
from gpt2giga.sinks.observability.factory import emit_observability_event

FUSION_SPAN_NAME = "GigaFusion"
FUSION_REQUESTS_TOTAL = "gpt2giga_fusion_requests_total"
FUSION_PANEL_CALLS_TOTAL = "gpt2giga_fusion_panel_calls_total"
FUSION_LATENCY_SECONDS = "gpt2giga_fusion_latency_seconds"
FUSION_PANEL_LATENCY_SECONDS = "gpt2giga_fusion_panel_latency_seconds"
FUSION_JUDGE_LATENCY_SECONDS = "gpt2giga_fusion_judge_latency_seconds"
FUSION_TOKENS_TOTAL = "gpt2giga_fusion_tokens_total"
FUSION_FAILURES_TOTAL = "gpt2giga_fusion_failures_total"
FUSION_SELECTED_CANDIDATE_TOTAL = "gpt2giga_fusion_selected_candidate_total"
FUSION_REWRITE_TOTAL = "gpt2giga_fusion_rewrite_total"
FUSION_JUDGE_PARSE_ERRORS_TOTAL = "gpt2giga_fusion_judge_parse_errors_total"
FUSION_REPAIR_CALLS_TOTAL = "gpt2giga_fusion_repair_calls_total"
FUSION_FALLBACK_TOTAL = "gpt2giga_fusion_fallback_total"
FUSION_STAGE_LATENCY_SECONDS = "gpt2giga_fusion_stage_latency_seconds"
FUSION_STAGE_INPUT_TOKENS = "gpt2giga_fusion_stage_input_tokens"
FUSION_STAGE_OUTPUT_TOKENS = "gpt2giga_fusion_stage_output_tokens"
FUSION_PANEL_TRUNCATED_TOTAL = "gpt2giga_fusion_panel_truncated_total"


async def emit_fusion_telemetry(
    *,
    metrics_sink: Any,
    observability_sink: Any,
    run_result: FusionRunResult,
    fusion_config: FusionRequestConfig,
    context: RequestContext | None,
    logger: Any | None = None,
) -> None:
    """Emit safe Fusion observability and metrics without surfacing raw content."""
    await emit_fusion_observability(
        observability_sink,
        run_result=run_result,
        fusion_config=fusion_config,
        context=context,
        logger=logger,
    )
    await emit_fusion_metrics(
        metrics_sink,
        run_result=run_result,
        logger=logger,
    )


async def emit_fusion_observability(
    sink: Any,
    *,
    run_result: FusionRunResult,
    fusion_config: FusionRequestConfig,
    context: RequestContext | None,
    logger: Any | None = None,
) -> bool:
    """Emit one bounded Fusion span plus panel/judge lifecycle events."""
    return await emit_observability_event(
        sink,
        FUSION_SPAN_NAME,
        build_fusion_observability_attributes(run_result, fusion_config),
        context=context,
        events=build_fusion_span_events(run_result),
        logger=logger,
    )


async def emit_fusion_metrics(
    sink: Any,
    *,
    run_result: FusionRunResult,
    logger: Any | None = None,
) -> None:
    """Emit bounded Fusion metrics derived from a completed run."""
    request_labels = {
        "preset": run_result.preset,
        "status": run_result.status,
    }
    await emit_metric_increment(
        sink,
        FUSION_REQUESTS_TOTAL,
        1,
        request_labels,
        logger=logger,
    )
    if run_result.latency_ms is not None:
        await emit_metric_observation(
            sink,
            FUSION_LATENCY_SECONDS,
            run_result.latency_ms / 1000,
            request_labels,
            logger=logger,
        )
    if run_result.direct_latency_ms is not None:
        await _emit_stage_latency(
            sink,
            "direct",
            _direct_model(run_result),
            run_result.direct_latency_ms,
            logger=logger,
        )

    for panel in run_result.panel_results:
        panel_labels = {"model": panel.model, "status": panel.status}
        await emit_metric_increment(
            sink,
            FUSION_PANEL_CALLS_TOTAL,
            1,
            panel_labels,
            logger=logger,
        )
        if panel.latency_ms is not None:
            await emit_metric_observation(
                sink,
                FUSION_PANEL_LATENCY_SECONDS,
                panel.latency_ms / 1000,
                panel_labels,
                logger=logger,
            )
            await _emit_stage_latency(
                sink,
                "panel",
                panel.model,
                panel.latency_ms,
                logger=logger,
            )
        if panel.status != "ok":
            await _emit_failure(
                sink,
                _failure_reason(panel.error_type or panel.status),
                logger=logger,
            )
    for candidate in run_result.candidates:
        if candidate.truncated:
            await emit_metric_increment(
                sink,
                FUSION_PANEL_TRUNCATED_TOTAL,
                1,
                {"model": candidate.model, "role": candidate.role or ""},
                logger=logger,
            )

    if run_result.judge_latency_ms is not None:
        await emit_metric_observation(
            sink,
            FUSION_JUDGE_LATENCY_SECONDS,
            run_result.judge_latency_ms / 1000,
            {"model": run_result.judge_model, "status": run_result.status},
            logger=logger,
        )
        await _emit_stage_latency(
            sink,
            "judge",
            run_result.judge_model,
            run_result.judge_latency_ms,
            logger=logger,
        )
    if run_result.finalizer_latency_ms is not None:
        await _emit_stage_latency(
            sink,
            "finalizer",
            run_result.final_model or run_result.judge_model,
            run_result.finalizer_latency_ms,
            logger=logger,
        )

    await _emit_usage(sink, "panel", _panel_usage(run_result), logger=logger)
    await _emit_stage_usage(
        sink,
        "direct",
        _direct_model(run_result),
        _direct_usage(run_result),
        logger=logger,
    )
    for panel in run_result.panel_results:
        await _emit_stage_usage(
            sink,
            "panel",
            panel.model,
            panel.usage,
            logger=logger,
        )
    await _emit_usage(sink, "judge", run_result.judge_usage, logger=logger)
    await _emit_stage_usage(
        sink,
        "judge",
        run_result.judge_model,
        run_result.judge_usage,
        logger=logger,
    )
    await _emit_usage(sink, "finalizer", run_result.finalizer_usage, logger=logger)
    await _emit_stage_usage(
        sink,
        "finalizer",
        run_result.final_model or run_result.judge_model,
        run_result.finalizer_usage,
        logger=logger,
    )
    await _emit_usage(sink, "total", run_result.usage, logger=logger)

    if run_result.selected_candidate_id and run_result.selected_candidate_source:
        await emit_metric_increment(
            sink,
            FUSION_SELECTED_CANDIDATE_TOTAL,
            1,
            {
                "candidate_type": run_result.selected_candidate_source,
                "candidate_id": run_result.selected_candidate_id,
            },
            logger=logger,
        )
    if run_result.needs_rewrite:
        await emit_metric_increment(
            sink,
            FUSION_REWRITE_TOTAL,
            1,
            {"mode": run_result.decision_mode},
            logger=logger,
        )
    if run_result.judge_parse_error:
        await emit_metric_increment(
            sink,
            FUSION_JUDGE_PARSE_ERRORS_TOTAL,
            1,
            {},
            logger=logger,
        )
    if run_result.repair_used:
        await emit_metric_increment(
            sink,
            FUSION_REPAIR_CALLS_TOTAL,
            1,
            {},
            logger=logger,
        )
    if run_result.fallback_reason:
        await emit_metric_increment(
            sink,
            FUSION_FALLBACK_TOTAL,
            1,
            {"reason": _failure_reason(run_result.fallback_reason)},
            logger=logger,
        )
        await _emit_failure(
            sink,
            _failure_reason(run_result.fallback_reason),
            logger=logger,
        )


def build_fusion_observability_attributes(
    run_result: FusionRunResult,
    fusion_config: FusionRequestConfig,
) -> dict[str, Any]:
    """Build safe bounded attributes for one Fusion run."""
    successful_panels = len(run_result.panel_results) - len(run_result.failed_models)
    final_model = run_result.final_model or run_result.judge_model
    attributes: dict[str, Any] = {
        "openinference.span.kind": "LLM",
        "llm.provider": "fusion",
        "llm.model_name": run_result.requested_model,
        "llm.operation": "fusion",
        "llm.response.status": run_result.status,
        "status": run_result.status,
        "gpt2giga.provider": "fusion",
        "gpt2giga.fusion.preset": run_result.preset,
        "gpt2giga.fusion.analysis_model_count": len(run_result.analysis_models),
        "gpt2giga.fusion.successful_panel_count": successful_panels,
        "gpt2giga.fusion.failed_panel_count": len(run_result.failed_models),
        "gpt2giga.fusion.judge_model": run_result.judge_model,
        "gpt2giga.fusion.final_model": final_model,
        "gpt2giga.fusion.pipeline_mode": fusion_config.pipeline_mode,
        "gpt2giga.fusion.decision_mode": run_result.decision_mode,
        "gpt2giga.fusion.prompt_mode": run_result.prompt_mode,
        "gpt2giga.fusion.tools_mode": fusion_config.tools_mode,
        "gpt2giga.fusion.include_direct_candidate": (
            fusion_config.include_direct_candidate
        ),
        "gpt2giga.fusion.selected_candidate_id": run_result.selected_candidate_id,
        "gpt2giga.fusion.selected_candidate_source": (
            run_result.selected_candidate_source
        ),
        "gpt2giga.fusion.needs_rewrite": run_result.needs_rewrite,
        "gpt2giga.fusion.judge_parse_error": run_result.judge_parse_error,
        "gpt2giga.fusion.repair_used": run_result.repair_used,
        "gpt2giga.fusion.panel_truncated": run_result.panel_truncated,
        "gpt2giga.fusion.latency_ms": run_result.latency_ms,
        "gpt2giga.fusion.direct_latency_ms": run_result.direct_latency_ms,
        "gpt2giga.fusion.judge_latency_ms": run_result.judge_latency_ms,
        "gpt2giga.fusion.finalizer_latency_ms": run_result.finalizer_latency_ms,
    }
    if run_result.fallback_reason:
        attributes["gpt2giga.fusion.fallback_reason"] = _failure_reason(
            run_result.fallback_reason
        )
    if run_result.usage is not None:
        attributes.update(
            {
                "llm.token_count.prompt": run_result.usage.input_tokens,
                "llm.token_count.completion": run_result.usage.output_tokens,
                "llm.token_count.total": run_result.usage.total_tokens,
                "input_tokens": run_result.usage.input_tokens,
                "output_tokens": run_result.usage.output_tokens,
                "total_tokens": run_result.usage.total_tokens,
            }
        )
    return {key: value for key, value in attributes.items() if value is not None}


def build_fusion_span_events(run_result: FusionRunResult) -> list[dict[str, Any]]:
    """Build safe panel and judge span events without raw content."""
    events: list[dict[str, Any]] = []
    for index, panel in enumerate(run_result.panel_results):
        attributes = {
            "gpt2giga.fusion.phase": "panel",
            "gpt2giga.fusion.panel.index": index,
            "gpt2giga.fusion.panel.model": panel.model,
            "gpt2giga.fusion.panel.role": panel.role,
            "gpt2giga.fusion.panel.status": panel.status,
            "gpt2giga.fusion.panel.error_type": panel.error_type,
            "gpt2giga.fusion.panel.latency_ms": panel.latency_ms,
            "gpt2giga.fusion.panel.truncated": panel.truncated,
        }
        events.append(
            {
                "name": "fusion.panel",
                "attributes": {
                    key: value for key, value in attributes.items() if value is not None
                },
            }
        )
    if run_result.judge_latency_ms is not None:
        events.append(
            {
                "name": "fusion.judge",
                "attributes": {
                    "gpt2giga.fusion.phase": "judge",
                    "gpt2giga.fusion.judge.model": run_result.judge_model,
                    "gpt2giga.fusion.judge.status": run_result.status,
                    "gpt2giga.fusion.judge.latency_ms": run_result.judge_latency_ms,
                },
            }
        )
    if run_result.direct_latency_ms is not None:
        events.append(
            {
                "name": "fusion.direct",
                "attributes": {
                    "gpt2giga.fusion.phase": "direct",
                    "gpt2giga.fusion.direct.model": _direct_model(run_result),
                    "gpt2giga.fusion.direct.latency_ms": (run_result.direct_latency_ms),
                },
            }
        )
    if run_result.finalizer_latency_ms is not None:
        events.append(
            {
                "name": "fusion.finalizer",
                "attributes": {
                    "gpt2giga.fusion.phase": "finalizer",
                    "gpt2giga.fusion.finalizer.model": (
                        run_result.final_model or run_result.judge_model
                    ),
                    "gpt2giga.fusion.finalizer.latency_ms": (
                        run_result.finalizer_latency_ms
                    ),
                },
            }
        )
    return events


async def _emit_usage(
    sink: Any,
    phase: str,
    usage: NormalizedUsage | None,
    *,
    logger: Any | None,
) -> None:
    if usage is None:
        return
    token_values = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
    }
    for input_output, value in token_values.items():
        if value is None or value <= 0:
            continue
        await emit_metric_increment(
            sink,
            FUSION_TOKENS_TOTAL,
            int(value),
            {"phase": phase, "input_output": input_output},
            logger=logger,
        )


async def _emit_failure(
    sink: Any,
    reason: str,
    *,
    logger: Any | None,
) -> None:
    await emit_metric_increment(
        sink,
        FUSION_FAILURES_TOTAL,
        1,
        {"reason": reason},
        logger=logger,
    )


async def _emit_stage_latency(
    sink: Any,
    stage: str,
    model: str,
    latency_ms: int,
    *,
    logger: Any | None,
) -> None:
    await emit_metric_observation(
        sink,
        FUSION_STAGE_LATENCY_SECONDS,
        latency_ms / 1000,
        {"stage": stage, "model": model},
        logger=logger,
    )


async def _emit_stage_usage(
    sink: Any,
    stage: str,
    model: str,
    usage: NormalizedUsage | None,
    *,
    logger: Any | None,
) -> None:
    if usage is None:
        return
    if usage.input_tokens is not None and usage.input_tokens > 0:
        await emit_metric_increment(
            sink,
            FUSION_STAGE_INPUT_TOKENS,
            int(usage.input_tokens),
            {"stage": stage, "model": model},
            logger=logger,
        )
    if usage.output_tokens is not None and usage.output_tokens > 0:
        await emit_metric_increment(
            sink,
            FUSION_STAGE_OUTPUT_TOKENS,
            int(usage.output_tokens),
            {"stage": stage, "model": model},
            logger=logger,
        )


def _panel_usage(run_result: FusionRunResult) -> NormalizedUsage | None:
    return aggregate_usage(panel.usage for panel in run_result.panel_results)


def _direct_usage(run_result: FusionRunResult) -> NormalizedUsage | None:
    for candidate in run_result.candidates:
        if candidate.source == "direct":
            return candidate.usage
    return None


def _direct_model(run_result: FusionRunResult) -> str:
    for candidate in run_result.candidates:
        if candidate.source == "direct":
            return candidate.model
    return run_result.judge_model


def _failure_reason(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.split(":", 1)[0].strip().lower() or "unknown"
