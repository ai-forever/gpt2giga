"""Core local GigaFusion provider adapter."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import ValidationError

from gpt2giga.core.context import RequestContext
from gpt2giga.models.config import FusionSettings
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedTool,
)
from gpt2giga.providers.fusion.detection import FusionRequestConfig
from gpt2giga.providers.fusion.prompts import (
    FUSION_JUDGE_SYSTEM_PROMPT,
    build_judge_user_prompt,
    build_panel_system_prompt,
)
from gpt2giga.providers.fusion.schemas import (
    FusionAnalysis,
    FusionPanelResult,
    FusionRunResult,
)
from gpt2giga.providers.fusion.tool_arbitration import (
    build_judge_tool_arbitration_prompt,
    build_panel_tool_reference,
    first_allowed_tool_call,
    tool_call_allowed,
    tool_choice_requires_tool,
)
from gpt2giga.providers.fusion.usage import aggregate_usage

DisconnectChecker = Callable[[], bool | Awaitable[bool]]


class FusionUpstreamProvider(Protocol):
    """Minimal normalized chat provider contract used by Fusion."""

    async def chat(
        self,
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None = None,
    ) -> NormalizedResponse:
        """Execute one normalized chat request."""


class FusionProviderAdapter:
    """Compose multiple normalized provider calls into one Fusion response."""

    name = "fusion"

    def __init__(
        self,
        *,
        settings: FusionSettings,
        upstream_provider: FusionUpstreamProvider,
    ) -> None:
        self.settings = settings
        self.upstream_provider = upstream_provider

    async def chat(
        self,
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None = None,
        fusion_config: FusionRequestConfig,
        is_disconnected: DisconnectChecker | None = None,
    ) -> NormalizedResponse:
        """Execute a compact Fusion panel plus judge/finalizer pipeline."""
        started = time.perf_counter()
        requested_model = fusion_config.requested_model or request.model or "fusion"

        await _raise_if_disconnected(is_disconnected)
        panel_results = await self._run_panels(
            request,
            context=context,
            fusion_config=fusion_config,
            is_disconnected=is_disconnected,
        )
        await _raise_if_disconnected(is_disconnected)

        successful_panels = [
            result for result in panel_results if result.status == "ok"
        ]
        failed_panels = [result for result in panel_results if result.status != "ok"]
        if len(successful_panels) < fusion_config.min_successful_panels:
            usage = aggregate_usage(result.usage for result in panel_results)
            run_result = self._build_run_result(
                status="error",
                requested_model=requested_model,
                fusion_config=fusion_config,
                panel_results=panel_results,
                failed_models=failed_panels,
                usage=usage,
                latency_ms=_elapsed_ms(started),
                fallback_reason="all_panels_failed",
            )
            return self._error_response(
                requested_model=requested_model,
                message="Fusion panel stage did not produce enough successful results",
                code="all_panels_failed",
                run_result=run_result,
                usage=usage,
            )

        judge_response: NormalizedResponse | None = None
        judge_error_reason: str | None = None
        try:
            judge_response = await self._run_judge(
                request,
                panel_results=panel_results,
                context=context,
                fusion_config=fusion_config,
                is_disconnected=is_disconnected,
            )
        except asyncio.TimeoutError:
            judge_error_reason = "judge_timeout"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            judge_error_reason = f"judge_failed:{type(exc).__name__}"

        analysis, parse_error_reason = _analysis_from_judge_response(
            judge_response,
            request_tools=request.tools,
            tools_mode=fusion_config.tools_mode,
            tool_choice=request.tool_choice,
            max_tool_calls=fusion_config.max_tool_calls,
        )
        fallback_reason = judge_error_reason or parse_error_reason
        usage = aggregate_usage(
            [
                *(result.usage for result in panel_results),
                judge_response.usage if judge_response is not None else None,
            ]
        )
        message, finish_reason = _final_message_from_analysis(
            analysis,
            request_tools=request.tools,
            tools_mode=fusion_config.tools_mode,
            tool_choice=request.tool_choice,
            max_tool_calls=fusion_config.max_tool_calls,
        )
        if _final_tool_call_is_required(
            message,
            request_tools=request.tools,
            tools_mode=fusion_config.tools_mode,
            tool_choice=request.tool_choice,
            max_tool_calls=fusion_config.max_tool_calls,
        ):
            run_result = self._build_run_result(
                status="error",
                requested_model=requested_model,
                fusion_config=fusion_config,
                panel_results=panel_results,
                failed_models=failed_panels,
                analysis=analysis,
                usage=usage,
                latency_ms=_elapsed_ms(started),
                fallback_reason=fallback_reason or "required_tool_call_missing",
            )
            return self._error_response(
                requested_model=requested_model,
                message="Fusion finalizer did not produce the required tool call",
                code="fusion_tool_required",
                run_result=run_result,
                usage=usage,
            )
        if message is None:
            fallback = _fallback_panel_message(successful_panels)
            if fallback is None:
                run_result = self._build_run_result(
                    status="error",
                    requested_model=requested_model,
                    fusion_config=fusion_config,
                    panel_results=panel_results,
                    failed_models=failed_panels,
                    analysis=analysis,
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    fallback_reason=fallback_reason or "empty_fusion_result",
                )
                return self._error_response(
                    requested_model=requested_model,
                    message="Fusion did not produce a final answer",
                    code="empty_fusion_result",
                    run_result=run_result,
                    usage=usage,
                )
            message = fallback
            finish_reason = "stop"
            fallback_reason = fallback_reason or "judge_empty_final"

        run_result = self._build_run_result(
            status="ok",
            requested_model=requested_model,
            fusion_config=fusion_config,
            panel_results=panel_results,
            failed_models=failed_panels,
            analysis=analysis,
            usage=usage,
            latency_ms=_elapsed_ms(started),
            fallback_reason=fallback_reason,
        )
        return NormalizedResponse(
            id=context.request_id if context is not None else None,
            model=requested_model,
            provider=self.name,
            choices=[
                NormalizedChoice(
                    index=0,
                    message=message,
                    finish_reason=finish_reason,
                )
            ],
            usage=usage,
            metadata=_public_metadata(run_result),
            provider_metadata={
                "fusion": _provider_metadata(
                    run_result,
                    settings=self.settings,
                )
            },
        )

    async def _run_panels(
        self,
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None,
        fusion_config: FusionRequestConfig,
        is_disconnected: DisconnectChecker | None,
    ) -> list[FusionPanelResult]:
        concurrency = min(
            self.settings.max_panel_concurrency,
            len(fusion_config.analysis_models),
        )
        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            asyncio.create_task(
                self._run_indexed_panel(
                    index,
                    model,
                    request,
                    semaphore=semaphore,
                    context=context,
                    fusion_config=fusion_config,
                    is_disconnected=is_disconnected,
                )
            )
            for index, model in enumerate(fusion_config.analysis_models)
        ]
        try:
            indexed_results = await _wait_for_indexed_results(
                tasks,
                is_disconnected=is_disconnected,
            )
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [
            result for _, result in sorted(indexed_results, key=lambda item: item[0])
        ]

    async def _run_indexed_panel(
        self,
        index: int,
        model: str,
        request: NormalizedChatRequest,
        *,
        semaphore: asyncio.Semaphore,
        context: RequestContext | None,
        fusion_config: FusionRequestConfig,
        is_disconnected: DisconnectChecker | None,
    ) -> tuple[int, FusionPanelResult]:
        role = _panel_role(fusion_config, index)
        async with semaphore:
            result = await self._run_panel(
                request,
                model=model,
                role=role,
                context=context,
                fusion_config=fusion_config,
                is_disconnected=is_disconnected,
            )
        return index, result

    async def _run_panel(
        self,
        request: NormalizedChatRequest,
        *,
        model: str,
        role: str | None,
        context: RequestContext | None,
        fusion_config: FusionRequestConfig,
        is_disconnected: DisconnectChecker | None,
    ) -> FusionPanelResult:
        started = time.perf_counter()
        panel_request = _build_panel_request(
            request,
            model=model,
            role=role,
            fusion_config=fusion_config,
        )
        try:
            await _raise_if_disconnected(is_disconnected)
            response = await asyncio.wait_for(
                self.upstream_provider.chat(panel_request, context=context),
                timeout=fusion_config.timeout_seconds,
            )
            if response.error is not None:
                return FusionPanelResult(
                    model=model,
                    role=role,
                    status="error",
                    usage=response.usage,
                    error_type=response.error.type,
                    error_message=response.error.message,
                    latency_ms=_elapsed_ms(started),
                )
            message = _first_message(response)
            if message is None:
                return FusionPanelResult(
                    model=model,
                    role=role,
                    status="error",
                    usage=response.usage,
                    error_type="empty_response",
                    latency_ms=_elapsed_ms(started),
                )
            content = _content_to_text(message.content)
            if not content and not message.tool_calls:
                return FusionPanelResult(
                    model=model,
                    role=role,
                    status="error",
                    usage=response.usage,
                    error_type="empty_response",
                    latency_ms=_elapsed_ms(started),
                )
            return FusionPanelResult(
                model=model,
                role=role,
                status="ok",
                content=content,
                tool_calls=list(message.tool_calls),
                usage=response.usage,
                latency_ms=_elapsed_ms(started),
            )
        except asyncio.TimeoutError:
            return FusionPanelResult(
                model=model,
                role=role,
                status="timeout",
                error_type="timeout",
                latency_ms=_elapsed_ms(started),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return FusionPanelResult(
                model=model,
                role=role,
                status="error",
                error_type=type(exc).__name__,
                error_message=str(exc),
                latency_ms=_elapsed_ms(started),
            )

    async def _run_judge(
        self,
        request: NormalizedChatRequest,
        *,
        panel_results: list[FusionPanelResult],
        context: RequestContext | None,
        fusion_config: FusionRequestConfig,
        is_disconnected: DisconnectChecker | None,
    ) -> NormalizedResponse:
        judge_request = _build_judge_request(
            request,
            panel_results=panel_results,
            fusion_config=fusion_config,
        )
        await _raise_if_disconnected(is_disconnected)
        return await asyncio.wait_for(
            self.upstream_provider.chat(judge_request, context=context),
            timeout=fusion_config.timeout_seconds,
        )

    def _build_run_result(
        self,
        *,
        status: str,
        requested_model: str,
        fusion_config: FusionRequestConfig,
        panel_results: list[FusionPanelResult],
        failed_models: list[FusionPanelResult],
        usage: Any = None,
        latency_ms: int | None = None,
        analysis: FusionAnalysis | None = None,
        fallback_reason: str | None = None,
    ) -> FusionRunResult:
        return FusionRunResult(
            status=status,
            requested_model=requested_model,
            preset=fusion_config.preset,
            analysis_models=list(fusion_config.analysis_models),
            judge_model=fusion_config.judge_model,
            final_model=fusion_config.final_model,
            panel_results=panel_results,
            failed_models=failed_models,
            analysis=analysis,
            fallback_reason=fallback_reason,
            usage=usage,
            latency_ms=latency_ms,
        )

    def _error_response(
        self,
        *,
        requested_model: str,
        message: str,
        code: str,
        run_result: FusionRunResult,
        usage: Any = None,
    ) -> NormalizedResponse:
        return NormalizedResponse(
            model=requested_model,
            provider=self.name,
            choices=[],
            usage=usage,
            error=NormalizedError(
                type="fusion_error",
                message=message,
                code=code,
            ),
            metadata=_public_metadata(run_result),
            provider_metadata={
                "fusion": _provider_metadata(
                    run_result,
                    settings=self.settings,
                )
            },
        )


def _build_panel_request(
    request: NormalizedChatRequest,
    *,
    model: str,
    role: str | None,
    fusion_config: FusionRequestConfig,
) -> NormalizedChatRequest:
    panel_request = request.model_copy(deep=True)
    panel_request.model = model
    panel_request.stream = False
    panel_request.response_format = None
    _apply_generation_overrides(panel_request, fusion_config)

    code_prompt = _is_code_preset(fusion_config)
    system_messages = [
        NormalizedMessage(
            role="system",
            content=build_panel_system_prompt(role, code=code_prompt),
        )
    ]
    tool_reference = build_panel_tool_reference(
        panel_request.tools, fusion_config.tools_mode
    )
    if tool_reference is not None:
        system_messages.append(NormalizedMessage(role="system", content=tool_reference))
    panel_request.messages = [*system_messages, *panel_request.messages]

    if fusion_config.tools_mode in {"off", "schema_only", "final_arbitration"}:
        panel_request.tools = []
        panel_request.tool_choice = None

    panel_request.metadata = {
        **panel_request.metadata,
        "gpt2giga_fusion_stage": "panel",
        "gpt2giga_fusion_role": role or "",
    }
    return panel_request


def _build_judge_request(
    request: NormalizedChatRequest,
    *,
    panel_results: list[FusionPanelResult],
    fusion_config: FusionRequestConfig,
) -> NormalizedChatRequest:
    judge_request = request.model_copy(deep=True)
    judge_request.model = fusion_config.judge_model
    judge_request.stream = False
    judge_request.response_format = None
    _apply_generation_overrides(judge_request, fusion_config)

    messages = [
        NormalizedMessage(role="system", content=FUSION_JUDGE_SYSTEM_PROMPT),
    ]
    tool_prompt = build_judge_tool_arbitration_prompt(
        tools=request.tools,
        panel_results=panel_results,
        tool_choice=request.tool_choice,
        tools_mode=fusion_config.tools_mode,
        max_tool_calls=fusion_config.max_tool_calls,
    )
    if tool_prompt is not None:
        messages.append(NormalizedMessage(role="system", content=tool_prompt))
    messages.extend(
        [
            *request.messages,
            NormalizedMessage(
                role="user",
                content=build_judge_user_prompt(panel_results),
            ),
        ]
    )
    judge_request.messages = messages
    if fusion_config.tools_mode == "off":
        judge_request.tools = []
        judge_request.tool_choice = None
    judge_request.metadata = {
        **judge_request.metadata,
        "gpt2giga_fusion_stage": "judge",
    }
    return judge_request


def _apply_generation_overrides(
    request: NormalizedChatRequest,
    fusion_config: FusionRequestConfig,
) -> None:
    if fusion_config.temperature is not None:
        request.generation_config.temperature = fusion_config.temperature
    if fusion_config.max_completion_tokens is not None:
        request.generation_config.max_tokens = fusion_config.max_completion_tokens


def _analysis_from_judge_response(
    response: NormalizedResponse | None,
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int,
) -> tuple[FusionAnalysis | None, str | None]:
    if response is None:
        return None, "judge_failed"
    if response.error is not None:
        return None, f"judge_error:{response.error.type}"
    message = _first_message(response)
    if message is None:
        return None, "judge_empty_response"
    direct_tool_call = first_allowed_tool_call(
        message.tool_calls,
        request_tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    )
    if direct_tool_call is not None and not _content_to_text(message.content):
        return FusionAnalysis(final_tool_call=direct_tool_call), None

    content = _content_to_text(message.content)
    if not content:
        return None, "judge_empty_response"
    try:
        payload = _load_json_object(content)
        analysis = FusionAnalysis.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        return None, "invalid_judge_json"

    if analysis.final_tool_call is not None and not tool_call_allowed(
        analysis.final_tool_call,
        request_tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    ):
        analysis.final_tool_call = None
        if not analysis.final_answer:
            return analysis, "invalid_final_tool_call"
    return analysis, None


def _final_message_from_analysis(
    analysis: FusionAnalysis | None,
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int,
) -> tuple[NormalizedMessage | None, str | None]:
    if analysis is None:
        return None, None
    if analysis.final_tool_call is not None and tool_call_allowed(
        analysis.final_tool_call,
        request_tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    ):
        return (
            NormalizedMessage(
                role="assistant",
                content=None,
                tool_calls=[analysis.final_tool_call],
            ),
            "tool_calls",
        )
    if analysis.final_answer:
        return (
            NormalizedMessage(role="assistant", content=analysis.final_answer),
            "stop",
        )
    return None, None


def _fallback_panel_message(
    panel_results: list[FusionPanelResult],
) -> NormalizedMessage | None:
    for result in panel_results:
        if result.content:
            return NormalizedMessage(role="assistant", content=result.content)
    return None


def _first_message(response: NormalizedResponse) -> NormalizedMessage | None:
    for choice in response.choices:
        if choice.message is not None:
            return choice.message
    return None


def _content_to_text(
    content: str | list[NormalizedContentPart] | None,
) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content.strip()
        return text or None
    parts: list[str] = []
    for part in content:
        if part.text:
            parts.append(part.text)
        elif part.data is not None:
            parts.append(json.dumps(part.data, ensure_ascii=True, sort_keys=True))
    text = "\n".join(parts).strip()
    return text or None


def _load_json_object(content: str) -> dict[str, Any]:
    text = _strip_code_fence(content)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Fusion judge response must be a JSON object")
    return value


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _final_tool_call_is_required(
    message: NormalizedMessage | None,
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int,
) -> bool:
    if not tool_choice_requires_tool(
        request_tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    ):
        return False
    return message is None or not message.tool_calls


def _public_metadata(run_result: FusionRunResult) -> dict[str, str]:
    metadata = {
        "gpt2giga_fusion": "true",
        "gpt2giga_fusion_preset": run_result.preset,
        "gpt2giga_fusion_requested_model": run_result.requested_model,
        "gpt2giga_fusion_analysis_models": ",".join(run_result.analysis_models),
        "gpt2giga_fusion_judge_model": run_result.judge_model,
        "gpt2giga_fusion_successful_panels": str(
            len(run_result.panel_results) - len(run_result.failed_models)
        ),
        "gpt2giga_fusion_failed_panels": str(len(run_result.failed_models)),
    }
    if run_result.final_model:
        metadata["gpt2giga_fusion_final_model"] = run_result.final_model
    if run_result.fallback_reason:
        metadata["gpt2giga_fusion_fallback_reason"] = run_result.fallback_reason
    return metadata


def _provider_metadata(
    run_result: FusionRunResult,
    *,
    settings: FusionSettings,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "status": run_result.status,
        "requested_model": run_result.requested_model,
        "preset": run_result.preset,
        "analysis_models": list(run_result.analysis_models),
        "judge_model": run_result.judge_model,
        "final_model": run_result.final_model,
        "fallback_reason": run_result.fallback_reason,
        "latency_ms": run_result.latency_ms,
        "panel_results": [
            _panel_metadata(result, expose_content=settings.expose_panel_responses)
            for result in run_result.panel_results
        ],
    }
    if settings.expose_analysis_metadata and run_result.analysis is not None:
        metadata["analysis"] = run_result.analysis.model_dump(
            mode="json",
            exclude_none=True,
        )
    return metadata


def _panel_metadata(
    result: FusionPanelResult,
    *,
    expose_content: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "model": result.model,
        "role": result.role,
        "status": result.status,
        "error_type": result.error_type,
        "latency_ms": result.latency_ms,
        "usage": result.usage.to_json_dict() if result.usage is not None else None,
    }
    if expose_content:
        metadata["content"] = result.content
        metadata["tool_calls"] = [
            tool_call.to_json_dict() for tool_call in result.tool_calls
        ]
        metadata["error_message"] = result.error_message
    return metadata


async def _wait_for_indexed_results(
    tasks: list[asyncio.Task[tuple[int, FusionPanelResult]]],
    *,
    is_disconnected: DisconnectChecker | None,
) -> list[tuple[int, FusionPanelResult]]:
    pending = set(tasks)
    results: list[tuple[int, FusionPanelResult]] = []
    while pending:
        done, pending = await asyncio.wait(
            pending,
            timeout=0.05,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            results.append(await task)
        if pending and await _is_disconnected(is_disconnected):
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise asyncio.CancelledError
    return results


async def _raise_if_disconnected(
    is_disconnected: DisconnectChecker | None,
) -> None:
    if await _is_disconnected(is_disconnected):
        raise asyncio.CancelledError


async def _is_disconnected(is_disconnected: DisconnectChecker | None) -> bool:
    if is_disconnected is None:
        return False
    result = is_disconnected()
    if inspect.isawaitable(result):
        result = await result
    return bool(result)


def _panel_role(
    fusion_config: FusionRequestConfig,
    index: int,
) -> str | None:
    if index < len(fusion_config.panel_roles):
        return fusion_config.panel_roles[index]
    return None


def _is_code_preset(fusion_config: FusionRequestConfig) -> bool:
    text = " ".join(
        value
        for value in [
            fusion_config.preset,
            fusion_config.requested_model or "",
        ]
        if value
    ).lower()
    return "code" in text


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
