"""Direct Chat Completions harness through the local gpt2giga proxy."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from gpt2giga_harness import proxy
from gpt2giga_harness.generated_files import (
    GeneratedFileError,
    generated_file_metadata,
    persist_generated_file,
)
from gpt2giga_harness.harnesses.attachment_plan import (
    attachment_raw_metadata,
    attachment_warning_events,
    request_render_plan,
)
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.gpt2giga_preset import (
    Gpt2GigaPresetUnavailableError,
    require_gpt2giga_preset,
)
from gpt2giga_harness.protocols.normalized import (
    NormalizedStreamEvent,
    NormalizedToolCall,
)
from gpt2giga_harness.types import (
    AttachmentTransportSupport,
    Availability,
    GIGACHAT_BUILTIN_TOOLS,
    HarnessChatMessage,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HarnessEventType,
    HeadlessContinuationStrategy,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    emit_event,
)
from gpt2giga_harness.protocols.openai.stream_accumulator import (
    OpenAIChatCompletionStreamAccumulator,
    openai_usage_to_normalized_usage,
    stream_tool_call_to_normalized_tool_call,
)


DEFAULT_MODEL = "GigaChat"
MESSAGE_DELTA_FLUSH_CHARS = 64
MESSAGE_DELTA_FLUSH_SECONDS = 0.08


class DirectChatHarness(BaseHarness):
    """Call /v1 or /v2 Chat Completions on the local proxy."""

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="direct-chat",
            title="Direct Chat Completions",
            kind="built-in",
            description=("Direct OpenAI-style Chat Completions through gpt2giga"),
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_model_selection=True,
            supports_api_mode_selection=True,
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
            supports_attachments=True,
            accepted_attachment_kinds=("image", "text", "workspace_file"),
            attachment_transport=("openai_content_parts", "inline_text"),
            attachment_capabilities={
                "image": AttachmentTransportSupport(
                    headless=("openai_content_parts",),
                    rich=True,
                    detail="Stored images are sent as OpenAI-style image content parts.",
                ),
                "text": AttachmentTransportSupport(
                    headless=("inline_text",),
                    detail="Small text attachments are inlined with a size limit.",
                ),
                "workspace_file": AttachmentTransportSupport(
                    headless=("prompt_path_reference",),
                    detail="Workspace files remain contained path references.",
                ),
            },
            supported_builtin_tools=GIGACHAT_BUILTIN_TOOLS,
            headless_continuation=HeadlessContinuationStrategy.STRUCTURED_REPLAY,
            tags=("chat", "proxy"),
        )

    def availability(self) -> Availability:
        return Availability.available("built-in harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        model = request.model or context.default_model or DEFAULT_MODEL
        url = proxy.build_chat_completions_url(context.proxy_url, request.api_mode)
        payload = {
            "model": model,
            "messages": _payload_messages(request),
            "stream": bool(request.stream),
        }
        adapter_options = request.extra.get("agent_adapter_options")
        reasoning_effort = (
            adapter_options.get("reasoning_effort")
            if isinstance(adapter_options, Mapping)
            else None
        )
        if reasoning_effort in {"low", "medium", "high"}:
            payload["reasoning_effort"] = reasoning_effort
        if request.builtin_tools:
            payload["tools"] = [{"type": tool.value} for tool in request.builtin_tools]
        api_key = context.api_key or proxy.cached_sidecar_api_key(context.proxy_url)
        cli_command = (
            "giga",
            "chat",
            "--api-mode",
            request.api_mode.value,
            "--model",
            model,
            request.prompt,
        )
        curl_command = _curl_command(url, payload, bool(api_key))
        if request.extra.get("dry_run"):
            return HarnessResult(
                ok=True,
                text="dry run",
                raw={
                    "url": url,
                    "payload": payload,
                    "curl_command": curl_command,
                    **attachment_raw_metadata(request),
                },
                events=attachment_warning_events(request),
                command=cli_command,
            )
        events = attachment_warning_events(request)
        if context.auto_start_proxy:
            startup = proxy.ensure_proxy_available(context, request.api_mode)
            api_key = startup.api_key or api_key
            curl_command = _curl_command(url, payload, bool(api_key))
            if not startup.ok:
                return HarnessResult(
                    ok=False,
                    text="",
                    raw={
                        "url": url,
                        "payload": payload,
                        "curl_command": curl_command,
                        **attachment_raw_metadata(request),
                        "proxy_start": {
                            "started": startup.started,
                            "detail": startup.detail,
                            "error": startup.error,
                        },
                    },
                    command=cli_command,
                    error=startup.error or "proxy is not reachable",
                )
            if startup.started:
                events = (
                    *events,
                    HarnessEvent(
                        type="proxy_sidecar",
                        message="Started local gpt2giga proxy sidecar.",
                        payload={
                            "proxy_url": context.proxy_url,
                            "pid": startup.pid,
                        },
                    ),
                )
        try:
            if request.stream:
                return self._run_stream(
                    request=request,
                    context=context,
                    url=url,
                    payload=payload,
                    api_key=api_key,
                    cli_command=cli_command,
                    curl_command=curl_command,
                    events=events,
                )
            data = proxy.request_json(
                "POST",
                url,
                payload=payload,
                api_key=api_key,
                timeout=context.timeout_seconds,
            )
        except proxy.ProxyRequestError as exc:
            return HarnessResult(
                ok=False,
                text="",
                raw={
                    "url": url,
                    "payload": payload,
                    "curl_command": curl_command,
                    **attachment_raw_metadata(request),
                },
                command=cli_command,
                events=events,
                error=str(exc),
            )
        events = list(events)
        provider_trace = _ProviderToolTrace()
        provider_trace.register_payload(data)
        for event in provider_trace.drain_events():
            _emit_or_collect(request, events, event)
        for event in _builtin_tool_execution_events(data, final=True):
            _emit_or_collect(request, events, event)
        for event in _generated_file_events(data, request=request, context=context):
            _emit_or_collect(request, events, event)
        usage_event = _usage_event(data.get("usage"))
        if usage_event is not None:
            _emit_or_collect(request, events, usage_event)
        return HarnessResult(
            ok=True,
            text=proxy.extract_text(data),
            raw={
                **proxy.safe_raw(data),
                "url": url,
                "curl_command": curl_command,
                **attachment_raw_metadata(request),
            },
            events=tuple(events),
            command=cli_command,
        )

    def _run_stream(
        self,
        *,
        request: HarnessRequest,
        context: HarnessContext,
        url: str,
        payload: dict[str, Any],
        api_key: str | None,
        cli_command: tuple[str, ...],
        curl_command: tuple[str, ...],
        events: tuple[HarnessEvent, ...],
    ) -> HarnessResult:
        pending_events: list[HarnessEvent] = []
        for event in events:
            _emit_or_collect(request, pending_events, event)
        accumulator = OpenAIChatCompletionStreamAccumulator()
        provider_trace = _ProviderToolTrace()
        builtin_tools_seen: set[str] = set()
        generated_files_seen: set[str] = set()
        message_deltas = _TextDeltaCoalescer(
            request,
            pending_events,
            event_type=HarnessEventType.MESSAGE_DELTA.value,
            payload_key="delta",
            event_message="Assistant message delta.",
        )
        reasoning_deltas = _TextDeltaCoalescer(
            request,
            pending_events,
            event_type=HarnessEventType.REASONING_DELTA.value,
            payload_key="delta",
            event_message="Assistant reasoning delta.",
        )

        def flush_due_deltas() -> None:
            message_deltas.flush_if_due()
            reasoning_deltas.flush_if_due()

        chunk_count = 0
        last_payload: Mapping[str, Any] = {}
        try:
            for stream_payload in proxy.stream_sse_json(
                "POST",
                url,
                payload=payload,
                api_key=api_key,
                timeout=context.timeout_seconds,
                cancel_event=request.cancel_event,
                idle_callback=flush_due_deltas,
            ):
                chunk_count += 1
                last_payload = stream_payload
                provider_trace.register_payload(stream_payload)
                for event in _builtin_tool_execution_events(
                    stream_payload,
                    seen=builtin_tools_seen,
                ):
                    message_deltas.flush()
                    reasoning_deltas.flush()
                    _emit_or_collect(request, pending_events, event)
                for event in _generated_file_events(
                    stream_payload,
                    request=request,
                    context=context,
                    seen=generated_files_seen,
                ):
                    message_deltas.flush()
                    reasoning_deltas.flush()
                    _emit_or_collect(request, pending_events, event)
                for normalized_event in accumulator.observe_payload(stream_payload):
                    if normalized_event.type == "content_delta":
                        reasoning_deltas.flush()
                        message_deltas.push(normalized_event)
                        continue
                    if normalized_event.type == "reasoning_delta":
                        message_deltas.flush()
                        reasoning_deltas.push(normalized_event)
                        continue
                    message_deltas.flush()
                    reasoning_deltas.flush()
                    event = _normalized_harness_event(normalized_event)
                    if event is not None:
                        event = provider_trace.enrich_event(event)
                        _emit_or_collect(request, pending_events, event)
                for event in provider_trace.drain_events():
                    message_deltas.flush()
                    reasoning_deltas.flush()
                    _emit_or_collect(request, pending_events, event)
        except proxy.ProxyRequestError as exc:
            message_deltas.flush()
            reasoning_deltas.flush()
            return HarnessResult(
                ok=False,
                text="",
                raw={
                    "url": url,
                    "payload": payload,
                    "curl_command": curl_command,
                    "stream": True,
                    "chunk_count": chunk_count,
                    **attachment_raw_metadata(request),
                },
                command=cli_command,
                events=tuple(pending_events),
                error=str(exc),
            )

        message_deltas.flush()
        reasoning_deltas.flush()
        response = accumulator.to_normalized_response()
        for index, raw_tool_call in sorted(accumulator.tool_calls.items()):
            tool_call = stream_tool_call_to_normalized_tool_call(raw_tool_call)
            tool_call.raw_extensions["index"] = index
            if provider_trace.is_finished(tool_call.id):
                continue
            event = provider_trace.enrich_event(
                HarnessEvent(
                    type=HarnessEventType.TOOL_CALL_FINISHED.value,
                    message=f"Tool call {tool_call.name or tool_call.id or index} assembled.",
                    payload={
                        **_tool_call_payload(tool_call),
                        "status": "requested",
                        "source": "direct-chat",
                    },
                )
            )
            _emit_or_collect(
                request,
                pending_events,
                event,
            )
        error = response.error.message if response.error is not None else None
        return HarnessResult(
            ok=error is None,
            text="".join(accumulator.content_parts),
            raw={
                "url": url,
                "curl_command": curl_command,
                "stream": True,
                "chunk_count": chunk_count,
                "last_payload": proxy.safe_raw(dict(last_payload)),
                "response": response.to_json_dict(),
                **attachment_raw_metadata(request),
            },
            events=tuple(pending_events),
            command=cli_command,
            error=error,
        )


def _curl_command(
    url: str,
    payload: dict[str, object],
    include_auth: bool,
) -> tuple[str, ...]:
    command = ["curl", "-sS", url, "-H", "Content-Type: application/json"]
    if include_auth:
        command.extend(["-H", "Authorization: Bearer <redacted>"])
    command.extend(["-d", json.dumps(payload, ensure_ascii=False)])
    return tuple(command)


def _request_messages(request: HarnessRequest) -> tuple[HarnessChatMessage, ...]:
    if request.messages:
        return request.messages
    return (HarnessChatMessage(role="user", content=request.prompt),)


def _payload_messages(request: HarnessRequest) -> list[dict[str, Any]]:
    messages = [
        {"role": message.role, "content": message.content}
        for message in _request_messages(request)
    ]
    plan = request_render_plan(request)
    if not plan:
        return messages
    messages[-1]["content"] = _content_with_attachments(request, plan)
    return messages


def _content_with_attachments(
    request: HarnessRequest,
    plan: Mapping[str, Any],
) -> str | list[Mapping[str, Any]]:
    content_parts = [
        dict(part)
        for part in plan.get("content_parts", ())
        if isinstance(part, Mapping)
    ]
    prompt_prefix = str(plan.get("prompt_prefix") or "").strip()
    prompt_suffix = str(plan.get("prompt_suffix") or "").strip()
    if content_parts:
        merged_parts: list[Mapping[str, Any]] = []
        merged_text = False
        for part in content_parts:
            if part.get("type") == "text" and not merged_text:
                merged_parts.append(
                    {
                        **part,
                        "text": _join_text(
                            prompt_prefix,
                            str(part.get("text") or request.prompt),
                            prompt_suffix,
                        ),
                    }
                )
                merged_text = True
            else:
                merged_parts.append(part)
        if not merged_text and (prompt_prefix or prompt_suffix):
            merged_parts.insert(
                0,
                {
                    "type": "text",
                    "text": _join_text(prompt_prefix, request.prompt, prompt_suffix),
                },
            )
        return merged_parts
    return _join_text(prompt_prefix, request.prompt, prompt_suffix)


def _join_text(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _emit_or_collect(
    request: HarnessRequest,
    events: list[HarnessEvent],
    event: HarnessEvent,
) -> None:
    if not emit_event(request, event):
        events.append(event)


class _TextDeltaCoalescer:
    """Batch tiny text deltas before hitting the persistent session event store."""

    def __init__(
        self,
        request: HarnessRequest,
        events: list[HarnessEvent],
        *,
        event_type: str,
        payload_key: str,
        event_message: str,
    ) -> None:
        self._request = request
        self._events = events
        self._event_type = event_type
        self._payload_key = payload_key
        self._event_message = event_message
        self._parts: list[str] = []
        self._character_count = 0
        self._started_at: float | None = None
        self._last_sequence: int | None = None

    def push(self, event: NormalizedStreamEvent) -> None:
        """Add one content delta and flush when the size/time budget is reached."""
        delta = (
            event.reasoning_delta
            if self._event_type == HarnessEventType.REASONING_DELTA.value
            else event.content_delta
        )
        if not delta:
            return
        now = time.monotonic()
        if (
            self._parts
            and self._started_at is not None
            and now - self._started_at >= MESSAGE_DELTA_FLUSH_SECONDS
        ):
            self.flush()
        if not self._parts:
            self._started_at = now
        self._parts.append(delta)
        self._character_count += len(delta)
        self._last_sequence = event.sequence
        if self._character_count >= MESSAGE_DELTA_FLUSH_CHARS:
            self.flush()

    def flush(self) -> None:
        """Publish the buffered text as one normalized message event."""
        if not self._parts:
            return
        payload: dict[str, Any] = {
            self._payload_key: "".join(self._parts),
            "source": "direct-chat",
        }
        if self._last_sequence is not None:
            payload["sequence"] = self._last_sequence
        _emit_or_collect(
            self._request,
            self._events,
            HarnessEvent(
                type=self._event_type,
                message=self._event_message,
                payload=payload,
            ),
        )
        self._parts.clear()
        self._character_count = 0
        self._started_at = None
        self._last_sequence = None

    def flush_if_due(self) -> None:
        """Publish pending text once its latency budget has elapsed."""
        if (
            self._parts
            and self._started_at is not None
            and time.monotonic() - self._started_at >= MESSAGE_DELTA_FLUSH_SECONDS
        ):
            self.flush()


def _normalized_harness_event(event: NormalizedStreamEvent) -> HarnessEvent | None:
    if event.type == "content_delta" and event.content_delta:
        return HarnessEvent(
            type=HarnessEventType.MESSAGE_DELTA.value,
            message="Assistant message delta.",
            payload={
                "delta": event.content_delta,
                "sequence": event.sequence,
                "source": "direct-chat",
            },
        )
    if event.type == "reasoning_delta" and event.reasoning_delta:
        return HarnessEvent(
            type=HarnessEventType.REASONING_DELTA.value,
            message="Assistant reasoning delta.",
            payload={
                "delta": event.reasoning_delta,
                "kind": "model",
                "sequence": event.sequence,
                "source": "direct-chat",
            },
        )
    if event.type in {"tool_call_start", "tool_call_delta"}:
        tool_call = event.tool_call
        if tool_call is None:
            return None
        payload = {
            **_tool_call_payload(tool_call),
            "source": "direct-chat",
        }
        arguments_delta = tool_call.raw_extensions.get("arguments_delta")
        if arguments_delta is not None:
            payload["arguments_delta"] = arguments_delta
        return HarnessEvent(
            type=(
                HarnessEventType.TOOL_CALL_STARTED.value
                if event.type == "tool_call_start"
                else HarnessEventType.TOOL_CALL_DELTA.value
            ),
            message=(
                f"Tool call {tool_call.name or tool_call.id or 'tool'} started."
                if event.type == "tool_call_start"
                else f"Tool call {tool_call.name or tool_call.id or 'tool'} updated."
            ),
            payload=payload,
        )
    if event.type == "usage" and event.usage is not None:
        return HarnessEvent(
            type=HarnessEventType.USAGE.value,
            message="Token usage updated.",
            payload=_usage_payload(event.usage),
        )
    if event.type == "error" and event.error is not None:
        return HarnessEvent(
            type=HarnessEventType.ERROR.value,
            message=event.error.message or "Direct chat stream failed.",
            payload={
                "type": event.error.type,
                "code": event.error.code,
                "source": "direct-chat",
            },
        )
    return None


def _usage_event(value: Any) -> HarnessEvent | None:
    usage = openai_usage_to_normalized_usage(value)
    if usage is None:
        return None
    return HarnessEvent(
        type=HarnessEventType.USAGE.value,
        message="Token usage updated.",
        payload=_usage_payload(usage),
    )


class _ProviderToolTrace:
    """Rebuild provider-internal tool nesting from response metadata."""

    def __init__(self) -> None:
        self._calls: dict[str, dict[str, Any]] = {}
        self._call_order: list[str] = []
        self._started: set[str] = set()
        self._provider_finished: set[str] = set()
        self._active_agents: list[str] = []
        self._visible_ids: dict[str, str] = {}
        self._pending_calls: list[str] = []
        self._pending_results: list[dict[str, Any]] = []

    def register_payload(self, payload: Mapping[str, Any]) -> None:
        result_items = _provider_metadata_items(payload, "gigachat_tool_results")
        result_ids = {
            identifier
            for item in result_items
            if (identifier := _provider_tool_identifier(item)) is not None
        }
        current_ids = _payload_tool_call_ids(payload)
        for identifier in current_ids:
            self._visible_ids[_canonical_tool_id(identifier)] = identifier

        call_items = _current_provider_call_items(
            _provider_metadata_items(payload, "gigachat_called_tools"),
            current_ids=current_ids,
            result_ids=result_ids,
            known_ids=set(self._calls),
        )
        for item in call_items:
            identifier = _provider_tool_identifier(item)
            name = _provider_tool_name(item)
            if identifier is None or name is None:
                continue
            key = _canonical_tool_id(identifier)
            explicit_parent = _provider_parent_identifier(item)
            parent_key = (
                _canonical_tool_id(explicit_parent)
                if explicit_parent is not None
                else self._active_agents[-1]
                if self._active_agents and self._active_agents[-1] != key
                else None
            )
            record = self._calls.setdefault(
                key,
                {
                    "id": identifier,
                    "name": name,
                    "parent_key": parent_key,
                },
            )
            record.update(
                {
                    "id": identifier,
                    "name": name,
                    "arguments": item.get("arguments"),
                    "parent_key": parent_key or record.get("parent_key"),
                }
            )
            if key not in self._call_order:
                self._call_order.append(key)
            if key not in self._started and key not in self._pending_calls:
                self._pending_calls.append(key)
            if name == "invoke_agent" and key not in self._active_agents:
                self._active_agents.append(key)

        self._pending_results.extend(result_items)

    def enrich_event(self, event: HarnessEvent) -> HarnessEvent:
        identifier = _provider_tool_identifier(event.payload)
        if identifier is None:
            return event
        key = _canonical_tool_id(identifier)
        self._visible_ids[key] = identifier
        record = self._calls.get(key)
        payload = dict(event.payload)
        if record is not None:
            if record.get("name") is not None:
                payload.setdefault("name", record["name"])
            if record.get("arguments") is not None:
                payload.setdefault("arguments", record["arguments"])
            parent_id = self._parent_visible_id(record.get("parent_key"))
            if parent_id is not None:
                payload["parent_tool_call_id"] = parent_id
        if event.type in {
            HarnessEventType.TOOL_CALL_STARTED.value,
            HarnessEventType.TOOL_CALL_DELTA.value,
        }:
            self._started.add(key)
            if key in self._pending_calls:
                self._pending_calls.remove(key)
        return HarnessEvent(type=event.type, message=event.message, payload=payload)

    def drain_events(self) -> tuple[HarnessEvent, ...]:
        events: list[HarnessEvent] = []
        for key in self._pending_calls:
            if key in self._started:
                continue
            events.append(self._started_event(key))
            self._started.add(key)
        self._pending_calls.clear()

        for result in self._pending_results:
            key = self._result_key(result)
            if key is None or key in self._provider_finished:
                continue
            if key not in self._started:
                events.append(self._started_event(key))
                self._started.add(key)
            record = self._calls[key]
            status = str(result.get("status") or "completed")
            payload = {
                "tool_call_id": self._visible_ids.get(key, str(record["id"])),
                "name": record["name"],
                "arguments": record.get("arguments"),
                "result": result.get("result"),
                "status": status,
                "source": "direct-chat-provider",
            }
            parent_id = self._parent_visible_id(record.get("parent_key"))
            if parent_id is not None:
                payload["parent_tool_call_id"] = parent_id
            events.append(
                HarnessEvent(
                    type=HarnessEventType.TOOL_CALL_FINISHED.value,
                    message=f"Tool call {record['name']} {status}.",
                    payload={
                        key: value
                        for key, value in payload.items()
                        if value is not None
                    },
                )
            )
            self._provider_finished.add(key)
            self._close_agent(key)
        self._pending_results.clear()
        return tuple(events)

    def is_finished(self, identifier: Any) -> bool:
        return (
            isinstance(identifier, str)
            and _canonical_tool_id(identifier) in self._provider_finished
        )

    def _result_key(self, result: Mapping[str, Any]) -> str | None:
        identifier = _provider_tool_identifier(result)
        if identifier is not None:
            key = _canonical_tool_id(identifier)
            if key not in self._calls:
                name = _provider_tool_name(result) or "tool"
                parent_id = _provider_parent_identifier(result)
                parent_key = (
                    _canonical_tool_id(parent_id)
                    if parent_id is not None
                    else self._active_agents[-1]
                    if self._active_agents and name != "invoke_agent"
                    else None
                )
                self._calls[key] = {
                    "id": identifier,
                    "name": name,
                    "parent_key": parent_key,
                }
                self._call_order.append(key)
            return key
        name = _provider_tool_name(result)
        if name is None:
            return None
        return next(
            (
                key
                for key in reversed(self._call_order)
                if self._calls[key].get("name") == name
                and key not in self._provider_finished
            ),
            None,
        )

    def _started_event(self, key: str) -> HarnessEvent:
        record = self._calls[key]
        payload = {
            "tool_call_id": self._visible_ids.get(key, str(record["id"])),
            "name": record["name"],
            "arguments": record.get("arguments"),
            "status": "running",
            "source": "direct-chat-provider",
        }
        parent_id = self._parent_visible_id(record.get("parent_key"))
        if parent_id is not None:
            payload["parent_tool_call_id"] = parent_id
        return HarnessEvent(
            type=HarnessEventType.TOOL_CALL_STARTED.value,
            message=f"Tool call {record['name']} started.",
            payload={key: value for key, value in payload.items() if value is not None},
        )

    def _parent_visible_id(self, parent_key: Any) -> str | None:
        if not isinstance(parent_key, str):
            return None
        parent = self._calls.get(parent_key)
        fallback = str(parent["id"]) if parent is not None else parent_key
        return self._visible_ids.get(parent_key, fallback)

    def _close_agent(self, key: str) -> None:
        if key not in self._active_agents:
            return
        index = self._active_agents.index(key)
        del self._active_agents[index:]


def _provider_metadata_items(
    payload: Mapping[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    raw_items = metadata.get(key)
    if not isinstance(raw_items, str) or not raw_items:
        return []
    try:
        decoded = json.loads(raw_items)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [dict(item) for item in decoded if isinstance(item, Mapping)]


def _payload_tool_call_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    identifiers: list[str] = []
    for choice in payload.get("choices") or ():
        if not isinstance(choice, Mapping):
            continue
        for message_key in ("delta", "message"):
            message = choice.get(message_key)
            if not isinstance(message, Mapping):
                continue
            for tool_call in message.get("tool_calls") or ():
                if not isinstance(tool_call, Mapping):
                    continue
                identifier = _provider_tool_identifier(tool_call)
                if identifier is not None:
                    identifiers.append(identifier)
    return tuple(identifiers)


def _current_provider_call_items(
    items: list[dict[str, Any]],
    *,
    current_ids: tuple[str, ...],
    result_ids: set[str],
    known_ids: set[str],
) -> list[dict[str, Any]]:
    current_keys = {_canonical_tool_id(identifier) for identifier in current_ids}
    result_keys = {_canonical_tool_id(identifier) for identifier in result_ids}
    candidate_indexes = [
        index
        for index, item in enumerate(items)
        if (identifier := _provider_tool_identifier(item)) is not None
        and _canonical_tool_id(identifier) in current_keys | result_keys
    ]
    if candidate_indexes:
        start = min(candidate_indexes)
        if not current_keys:
            for index in range(start - 1, -1, -1):
                if _provider_tool_name(items[index]) == "invoke_agent":
                    start = index
                    break
        return items[start:]
    return [
        item
        for item in items
        if _provider_parent_identifier(item) is not None
        or (
            (identifier := _provider_tool_identifier(item)) is not None
            and _canonical_tool_id(identifier) in known_ids
        )
    ]


def _provider_tool_identifier(value: Mapping[str, Any]) -> str | None:
    for key in ("tools_state_id", "tool_call_id", "call_id", "id"):
        identifier = value.get(key)
        if isinstance(identifier, str) and identifier.strip():
            return identifier.strip()
    return None


def _provider_parent_identifier(value: Mapping[str, Any]) -> str | None:
    parent_id = value.get("parent_tool_call_id")
    return (
        parent_id.strip() if isinstance(parent_id, str) and parent_id.strip() else None
    )


def _provider_tool_name(value: Mapping[str, Any]) -> str | None:
    name = value.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _canonical_tool_id(identifier: str) -> str:
    for prefix in ("fc_", "call_"):
        if identifier.startswith(prefix) and len(identifier) > len(prefix):
            return identifier.removeprefix(prefix)
    return identifier


def _builtin_tool_execution_events(
    payload: Mapping[str, Any],
    *,
    seen: set[str] | None = None,
    final: bool = False,
) -> tuple[HarnessEvent, ...]:
    """Normalize GigaChat built-in tool metadata into Harness tool events."""
    seen = seen if seen is not None else set()
    events = []
    messages: list[Mapping[str, Any]] = []
    for choice in payload.get("choices") or ():
        if isinstance(choice, Mapping):
            messages.extend(
                message
                for message_key in ("delta", "message")
                if isinstance((message := choice.get(message_key)), Mapping)
            )
    messages.extend(
        message
        for message in payload.get("messages") or ()
        if isinstance(message, Mapping)
    )
    for message in messages:
        executions = list(message.get("tool_executions") or ())
        for part in message.get("content") or ():
            if isinstance(part, Mapping) and isinstance(
                part.get("tool_execution"), Mapping
            ):
                executions.append(part["tool_execution"])
        for execution in executions:
            if not isinstance(execution, Mapping):
                continue
            name = str(execution.get("name") or "").strip()
            if not name:
                continue
            tool_call_id = f"builtin:{name}"
            status = _builtin_tool_status(execution.get("status"), final=final)
            if status in {"completed", "failed"}:
                event_type = HarnessEventType.TOOL_CALL_FINISHED.value
            elif tool_call_id in seen:
                event_type = HarnessEventType.TOOL_CALL_DELTA.value
            else:
                event_type = HarnessEventType.TOOL_CALL_STARTED.value
            seen.add(tool_call_id)
            event_payload = {
                "tool_call_id": tool_call_id,
                "name": name,
                "type": "builtin",
                "status": status,
                "source": "direct-chat",
            }
            if execution.get("seconds_left") is not None:
                event_payload["seconds_left"] = execution["seconds_left"]
            events.append(
                HarnessEvent(
                    type=event_type,
                    message=f"Built-in tool {name} {status}.",
                    payload=event_payload,
                )
            )
    return tuple(events)


def _builtin_tool_status(value: Any, *, final: bool) -> str:
    status = str(value or "").lower()
    if status in {"success", "completed"}:
        return "completed"
    if status in {"failed", "error"}:
        return "failed"
    return "completed" if final else "running"


def _generated_file_events(
    payload: Mapping[str, Any],
    *,
    request: HarnessRequest,
    context: HarnessContext,
    seen: set[str] | None = None,
) -> tuple[HarnessEvent, ...]:
    """Fetch GigaChat-generated files and expose safe Harness file events."""
    seen = seen if seen is not None else set()
    events = []
    for file_data in _generated_file_items(payload):
        metadata = generated_file_metadata(file_data)
        if metadata is None:
            continue
        file_id, mime_type, target = metadata
        if file_id in seen:
            continue
        seen.add(file_id)
        try:
            generated = _fetch_generated_file(
                file_data,
                request=request,
                context=context,
                file_id=file_id,
                mime_type=mime_type,
                target=target,
            )
        except Exception as exc:
            events.append(
                HarnessEvent(
                    type=HarnessEventType.WARNING.value,
                    message="Generated file could not be fetched.",
                    payload={
                        "file_id": file_id,
                        "error_type": type(exc).__name__,
                        "source": "direct-chat",
                    },
                )
            )
            continue
        events.append(
            HarnessEvent(
                type=HarnessEventType.GENERATED_FILE.value,
                message="Generated file is ready.",
                payload={**generated, "source": "direct-chat"},
            )
        )
    return tuple(events)


def _generated_file_items(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    messages: list[Mapping[str, Any]] = []
    for choice in payload.get("choices") or ():
        if not isinstance(choice, Mapping):
            continue
        messages.extend(
            message
            for message_key in ("delta", "message")
            if isinstance((message := choice.get(message_key)), Mapping)
        )
    messages.extend(
        message
        for message in payload.get("messages") or ()
        if isinstance(message, Mapping)
    )
    files: list[Mapping[str, Any]] = []
    for message in messages:
        files.extend(
            item for item in message.get("files") or () if isinstance(item, Mapping)
        )
        for content_part in message.get("content") or ():
            if not isinstance(content_part, Mapping):
                continue
            files.extend(
                item
                for item in content_part.get("files") or ()
                if isinstance(item, Mapping)
            )
    return tuple(files)


def _fetch_generated_file(
    file_data: Mapping[str, Any],
    *,
    request: HarnessRequest,
    context: HarnessContext,
    file_id: str,
    mime_type: str,
    target: str,
) -> dict[str, Any]:
    if not context.data_dir or not request.run_id:
        raise GeneratedFileError("generated files require a managed Harness run")
    content = file_data.get("content")
    if not isinstance(content, str) or not content:
        content = (
            _download_gigachat_image(file_id)
            if target == "image"
            else _download_gigachat_file(file_id)
        )
    return persist_generated_file(
        context.data_dir,
        run_id=request.run_id,
        file_id=file_id,
        mime_type=mime_type,
        target=target,
        content_base64=content,
    )


def _download_gigachat_image(file_id: str) -> str:
    """Download a generated image with the same config as the local proxy."""
    return _download_gigachat_file(file_id)


def _download_gigachat_file(file_id: str) -> str:
    """Download generated bytes through the SDK file-content endpoint."""
    try:
        runtime = require_gpt2giga_preset()
    except Gpt2GigaPresetUnavailableError as exc:
        raise GeneratedFileError(str(exc)) from exc
    settings = runtime.load_config().gigachat_settings
    client = runtime.client_type(**settings.model_dump())
    try:
        # gigachat 0.2 exposes /files/{id}/content as get_image for every MIME type.
        file_response = client.get_image(file_id)
        content = getattr(file_response, "content", None)
        if not isinstance(content, str) or not content:
            raise GeneratedFileError("GigaChat returned empty generated file content")
        return content
    finally:
        client.close()


def _usage_payload(usage: Any) -> dict[str, Any]:
    payload = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "source": "direct-chat",
    }
    raw = dict(usage.raw_extensions)
    prompt_details = raw.get("prompt_tokens_details")
    completion_details = raw.get("completion_tokens_details")
    if isinstance(prompt_details, Mapping):
        payload["cached_input_tokens"] = prompt_details.get("cached_tokens")
    if isinstance(completion_details, Mapping):
        payload["reasoning_output_tokens"] = completion_details.get("reasoning_tokens")
    for key in ("cached_input_tokens", "reasoning_output_tokens"):
        if raw.get(key) is not None:
            payload[key] = raw[key]
    return {key: item for key, item in payload.items() if item is not None}


def _tool_call_payload(tool_call: NormalizedToolCall) -> dict[str, Any]:
    index = tool_call.raw_extensions.get("index")
    tool_call_id = tool_call.id or (f"tool_{index}" if index is not None else None)
    return {
        key: value
        for key, value in {
            "tool_call_id": tool_call_id,
            "name": tool_call.name,
            "type": tool_call.type,
            "arguments": tool_call.arguments,
        }.items()
        if value is not None
    }
