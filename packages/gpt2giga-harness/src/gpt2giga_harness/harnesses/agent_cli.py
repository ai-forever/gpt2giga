"""Shared helpers for external agent CLI harnesses."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from queue import Empty, Full, Queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, Any, Callable, Mapping

from gpt2giga_harness import proxy
from gpt2giga_harness.gigachat_compatibility import (
    gigachat_gateway_ready_event,
)
from gpt2giga_harness.types import (
    REDACTED,
    Availability,
    HarnessContext,
    HarnessEvent,
    HarnessRequest,
    HarnessResult,
    redact_secrets,
)

SAFE_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SHELL", "LANG", "LC_ALL")
SECRET_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "GEMINI_API_KEY",
    "GPT2GIGA_API_KEY",
    "OPENAI_API_KEY",
)
RAW_CAPTURE_CHARS = 4000
STREAM_POLL_SECONDS = 0.05
STREAM_QUEUE_MAX_ITEMS = 256
STREAM_EVENT_BATCH_CHARS = 256
STREAM_EVENT_BATCH_SECONDS = 0.08
PROCESS_STOP_TIMEOUT_SECONDS = 2.0
PROCESS_GROUP_GRACE_SECONDS = 0.2
PROCESS_STREAM_DRAIN_TIMEOUT_SECONDS = 1.0
PROCESS_READER_JOIN_TIMEOUT_SECONDS = 0.5
TERMINAL_ERROR_CHARS = 1000

StreamPayloadParser = Callable[[Mapping[str, Any]], tuple[HarnessEvent, ...]]


@dataclass(frozen=True)
class StreamTerminalOutcome:
    """Describe the terminal status reported by a structured CLI stream."""

    ok: bool
    error: str | None = None


def stream_terminal_failure(
    value: Any,
    *,
    fallback: str,
) -> StreamTerminalOutcome:
    """Build a concise redacted failure reported by a structured CLI stream."""
    return StreamTerminalOutcome(
        ok=False,
        error=_concise_stream_error(value, fallback=fallback),
    )


def build_safe_env(
    context: HarnessContext,
    *,
    extra: Mapping[str, str] | None = None,
    home: str | None = None,
) -> dict[str, str]:
    """Build a minimal environment that excludes upstream GigaChat secrets."""
    env: dict[str, str] = {
        key: value
        for key in SAFE_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    env.update(context.extra_env)
    if home is not None:
        env["HOME"] = home
    if extra is not None:
        env.update(extra)
    return env


def workspace_error(value: str | None) -> str | None:
    """Return a user-facing workspace validation error, if any."""
    if value is None:
        return None
    path = Path(value)
    if not path.exists():
        return f"Workspace does not exist: {value}"
    if not path.is_dir():
        return f"Workspace is not a directory: {value}"
    return None


def prepare_proxy_for_agent(
    request: HarnessRequest,
    context: HarnessContext,
    *,
    harness_id: str,
    command: tuple[str, ...],
) -> tuple[HarnessContext, tuple[HarnessEvent, ...], HarnessResult | None]:
    """Ensure the local proxy is ready before launching an external agent CLI."""
    startup = proxy.ensure_proxy_available(context, request.api_mode)
    if not startup.ok:
        return (
            context,
            (),
            HarnessResult(
                ok=False,
                text="",
                raw={
                    "proxy_url": context.proxy_url,
                    "auto_start_proxy": context.auto_start_proxy,
                },
                command=command,
                error=startup.error or "proxy is not reachable",
            ),
        )

    prepared_context = replace(context, api_key=startup.api_key or context.api_key)
    events: tuple[HarnessEvent, ...] = ()
    if startup.started:
        events = (
            HarnessEvent(
                type="proxy_sidecar",
                message="Started local gpt2giga proxy sidecar.",
                payload={
                    "proxy_url": context.proxy_url,
                    "pid": startup.pid,
                    "detail": startup.detail,
                },
            ),
        )
    events = (
        *events,
        gigachat_gateway_ready_event(
            request,
            harness_id=harness_id,
            sidecar_started=startup.started,
        ),
    )
    return prepared_context, events, None


def with_events(
    result: HarnessResult,
    events: tuple[HarnessEvent, ...],
) -> HarnessResult:
    """Return a result with prepended events."""
    if not events:
        return result
    return HarnessResult(
        ok=result.ok,
        text=result.text,
        raw=result.raw,
        events=(*events, *result.events),
        command=result.command,
        error=result.error,
    )


def with_raw_metadata(
    result: HarnessResult,
    metadata: Mapping[str, Any] | None,
) -> HarnessResult:
    """Return a result with additional redaction-safe execution evidence."""
    if not metadata:
        return result
    return HarnessResult(
        ok=result.ok,
        text=result.text,
        raw={**dict(result.raw), **dict(metadata)},
        events=result.events,
        command=result.command,
        error=result.error,
    )


def run_command(
    *,
    label: str,
    command: tuple[str, ...],
    env: Mapping[str, str],
    cwd: str | None,
    timeout_seconds: float,
) -> HarnessResult:
    """Run a command and normalize the captured result."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return HarnessResult(
            ok=False,
            text="",
            raw={"timeout_seconds": timeout_seconds},
            command=command,
            error=f"{label} timed out after {exc.timeout} seconds",
        )
    except OSError as exc:
        return HarnessResult(
            ok=False,
            text="",
            raw={},
            command=command,
            error=f"{label} failed to start: {exc}",
        )

    stdout = _redact_known_secret_values(completed.stdout, env)
    stderr = _redact_known_secret_values(completed.stderr, env)
    payload = _load_json_object(stdout)
    normalized_usage = (
        normalize_usage(payload.get("usage") or payload.get("stats"))
        if payload is not None
        else None
    )
    normalized_usage_event = usage_event(normalized_usage)
    text = _extract_machine_readable_text(stdout) or stdout.strip() or stderr.strip()
    raw = {
        "exit_code": completed.returncode,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }
    if normalized_usage is not None:
        raw["usage"] = normalized_usage
    return HarnessResult(
        ok=completed.returncode == 0,
        text=text,
        raw=raw,
        events=(normalized_usage_event,) if normalized_usage_event is not None else (),
        command=command,
        error=None if completed.returncode == 0 else text,
    )


def run_streaming_command(
    *,
    label: str,
    command: tuple[str, ...],
    env: Mapping[str, str],
    cwd: str | None,
    timeout_seconds: float,
    request: HarnessRequest,
    parse_payload: StreamPayloadParser,
) -> HarnessResult:
    """Run a JSONL command while emitting normalized events as output arrives."""
    if _cancel_requested(request):
        return HarnessResult(
            ok=False,
            text="",
            raw={"usage": {}, "tool_calls": []},
            command=command,
            error=f"{label} canceled",
        )
    process_group_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        process_group_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **process_group_kwargs,
        )
    except OSError as exc:
        return HarnessResult(
            ok=False,
            text="",
            raw={"usage": {}, "tool_calls": []},
            command=command,
            error=f"{label} failed to start: {exc}",
        )

    if request.process_sink is not None:
        try:
            request.process_sink(
                {
                    "process_id": process.pid,
                    "process_group_id": (
                        os.getpgid(process.pid) if os.name == "posix" else None
                    ),
                }
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            # Process reporting is best-effort and must not abort the harness run.
            pass

    output_queue: Queue[tuple[str, str | None]] = Queue(maxsize=STREAM_QUEUE_MAX_ITEMS)
    reader_stop = threading.Event()
    readers = (
        _start_stream_reader(process.stdout, "stdout", output_queue, reader_stop),
        _start_stream_reader(process.stderr, "stderr", output_queue, reader_stop),
    )
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    finished_streams: set[str] = set()
    message_parts: list[str] = []
    usage: dict[str, int] = {}
    tool_calls: dict[str, dict[str, Any]] = {}
    pending_events: list[HarnessEvent] = []
    event_coalescer = _StreamEventCoalescer(request, pending_events)
    stdout = ""
    stderr = ""
    canceled = False
    timed_out = False
    stream_drain_deadline: float | None = None

    try:
        while process.poll() is None or len(finished_streams) < 2:
            now = time.monotonic()
            process_running = process.poll() is None
            if process_running:
                stream_drain_deadline = None
                if _cancel_requested(request):
                    canceled = True
                    _stop_process(process)
                elif now >= deadline:
                    timed_out = True
                    _stop_process(process)
            elif stream_drain_deadline is None:
                stream_drain_deadline = now + PROCESS_STREAM_DRAIN_TIMEOUT_SECONDS
            elif now >= stream_drain_deadline:
                _stop_process(process)
                break

            try:
                stream_name, line = output_queue.get(timeout=STREAM_POLL_SECONDS)
            except Empty:
                event_coalescer.flush_due()
                continue
            if process.poll() is not None:
                stream_drain_deadline = (
                    time.monotonic() + PROCESS_STREAM_DRAIN_TIMEOUT_SECONDS
                )
            if line is None:
                finished_streams.add(stream_name)
                continue

            clean_line = _redact_output_text(line, env)
            if stream_name == "stderr":
                stderr = _bounded_append(stderr, clean_line)
                _record_stream_event(
                    HarnessEvent(
                        type="stderr_delta",
                        message=f"{label} stderr delta.",
                        payload={"delta": clean_line},
                    ),
                    message_parts=message_parts,
                    usage=usage,
                    tool_calls=tool_calls,
                    event_coalescer=event_coalescer,
                )
                continue

            parsed = _load_json_object(clean_line)
            if parsed is None:
                stdout = _bounded_append(stdout, clean_line)
                _record_stream_event(
                    HarnessEvent(
                        type="stdout_delta",
                        message=f"{label} stdout delta.",
                        payload={"delta": clean_line},
                    ),
                    message_parts=message_parts,
                    usage=usage,
                    tool_calls=tool_calls,
                    event_coalescer=event_coalescer,
                )
                continue

            stdout = _bounded_append(stdout, _safe_json_line(parsed))
            try:
                events = parse_payload(parsed)
            except Exception:
                events = (
                    HarnessEvent(
                        type="stdout_delta",
                        message=f"{label} emitted an unrecognized JSON event.",
                        payload={"delta": _safe_json_line(parsed)},
                    ),
                )
            for event in events:
                _record_stream_event(
                    event,
                    message_parts=message_parts,
                    usage=usage,
                    tool_calls=tool_calls,
                    event_coalescer=event_coalescer,
                )
    finally:
        if process.poll() is None:
            _stop_process(process)
        reader_stop.set()
        for reader in readers:
            reader.join(timeout=PROCESS_READER_JOIN_TIMEOUT_SECONDS)
        _close_finished_process_pipes(process, readers)
        event_coalescer.flush()

    return_code = process.poll()
    if return_code is None:
        _stop_process(process)
        return_code = process.poll()
    exit_code = int(return_code if return_code is not None else -1)

    text = "".join(message_parts).strip()
    if not text:
        text = (
            _extract_machine_readable_text(stdout) or stdout.strip() or stderr.strip()
        )
    normalized_usage = _complete_usage(usage)
    normalized_tool_calls = list(tool_calls.values())
    raw = {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "usage": normalized_usage,
        "tool_calls": normalized_tool_calls,
    }
    if canceled:
        return HarnessResult(
            ok=False,
            text="",
            raw=raw,
            events=tuple(pending_events),
            command=command,
            error=f"{label} canceled",
        )
    if timed_out:
        return HarnessResult(
            ok=False,
            text="",
            raw={**raw, "timeout_seconds": timeout_seconds},
            events=tuple(pending_events),
            command=command,
            error=f"{label} timed out after {timeout_seconds} seconds",
        )
    terminal_outcome = _stream_terminal_outcome(parse_payload)
    terminal_error = (
        terminal_outcome.error
        if terminal_outcome is not None and not terminal_outcome.ok
        else None
    )
    ok = exit_code == 0 and terminal_error is None
    return HarnessResult(
        ok=ok,
        text=text,
        raw=raw,
        events=tuple(pending_events),
        command=command,
        error=None
        if ok
        else terminal_error or text or f"{label} exited with status {exit_code}",
    )


def normalize_usage(value: Any) -> dict[str, int] | None:
    """Normalize common Codex, Claude, and Gemini token usage shapes."""
    if not isinstance(value, Mapping):
        return None
    nested = value.get("tokens")
    source = nested if isinstance(nested, Mapping) else value
    input_tokens = _first_token_count(
        source,
        "input_tokens",
        "prompt_tokens",
        "prompt",
    )
    output_tokens = _first_token_count(
        source,
        "output_tokens",
        "completion_tokens",
        "candidates",
    )
    total_tokens = _first_token_count(source, "total_tokens", "total")
    prompt_details = _first_mapping(
        source,
        "input_tokens_details",
        "prompt_tokens_details",
    )
    completion_details = _first_mapping(
        source,
        "output_tokens_details",
        "completion_tokens_details",
    )
    cached_input_tokens = _first_token_count(
        source,
        "cached_input_tokens",
        "cached_tokens",
        "cache_read_input_tokens",
    )
    if cached_input_tokens is None:
        cached_input_tokens = _first_token_count(prompt_details, "cached_tokens")
    reasoning_output_tokens = _first_token_count(
        source,
        "reasoning_output_tokens",
        "reasoning_tokens",
        "thoughts_tokens",
    )
    if reasoning_output_tokens is None:
        reasoning_output_tokens = _first_token_count(
            completion_details,
            "reasoning_tokens",
            "thoughts_tokens",
        )
    tool_tokens = _first_token_count(source, "tool_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return {
        key: item
        for key, item in {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "tool_tokens": tool_tokens,
        }.items()
        if item is not None
    }


def usage_event(value: Any) -> HarnessEvent | None:
    """Build one normalized usage event when token counts are available."""
    usage = normalize_usage(value)
    if usage is None:
        return None
    return HarnessEvent(
        type="usage",
        message="Token usage updated.",
        payload=usage,
    )


def message_delta_event(delta: Any) -> HarnessEvent | None:
    """Build one assistant message delta event for non-empty text."""
    if not isinstance(delta, str) or not delta:
        return None
    return HarnessEvent(
        type="message_delta",
        message="Assistant message delta.",
        payload={"delta": delta},
    )


def tool_call_event(
    event_type: str,
    *,
    tool_call_id: Any,
    name: Any = None,
    arguments: Any = None,
    result: Any = None,
    status: Any = None,
    arguments_are_complete: bool = False,
) -> HarnessEvent:
    """Build a normalized tool-call lifecycle event."""
    payload = {
        "tool_call_id": str(tool_call_id or "tool-call"),
        "name": str(name) if name is not None else None,
        "status": str(status) if status is not None else None,
    }
    if event_type == "tool_call_delta":
        payload["arguments" if arguments_are_complete else "arguments_delta"] = (
            arguments
        )
        payload["output_delta"] = result
    else:
        payload["arguments"] = arguments
        payload["result"] = result
    message = {
        "tool_call_started": "Tool call started.",
        "tool_call_delta": "Tool call updated.",
        "tool_call_finished": "Tool call finished.",
    }.get(event_type, "Tool call updated.")
    return HarnessEvent(
        type=event_type,
        message=message,
        payload={key: item for key, item in payload.items() if item is not None},
    )


def executable_availability(
    *,
    executable: str | None,
    executable_name: str,
    install_hint: str,
    version_args: tuple[str, ...] | None = ("--version",),
    source: str | None = None,
) -> Availability:
    """Return availability for an executable, optionally probing startup."""
    if executable is None:
        return Availability.missing(
            f"{executable_name} executable not found",
            install_hint,
        )
    source_detail = f" via {source}" if source else ""
    if version_args is None:
        return Availability.available(
            f"{executable_name} executable found{source_detail}: {executable}"
        )
    try:
        completed = subprocess.run(
            (executable, *version_args),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Availability.error(
            f"{executable_name} executable failed to run",
            str(exc),
        )
    detail = (completed.stdout or completed.stderr).strip().splitlines()
    version = detail[0] if detail else None
    if completed.returncode != 0:
        return Availability.error(
            f"{executable_name} executable failed to run",
            version,
        )
    suffix = f" ({version})" if version else ""
    return Availability.available(
        f"{executable_name} executable found{source_detail}: {executable}{suffix}"
    )


def _redact_known_secret_values(text: str, env: Mapping[str, str]) -> str:
    redacted = text
    for key in SECRET_ENV_KEYS:
        value = env.get(key)
        if value and value != "0":
            redacted = redacted.replace(value, REDACTED)
    return redacted


def _redact_output_text(text: str, env: Mapping[str, str]) -> str:
    return str(redact_secrets(_redact_known_secret_values(text, env)))


def _safe_json_line(payload: Mapping[str, Any]) -> str:
    return json.dumps(redact_secrets(dict(payload)), ensure_ascii=False) + "\n"


def _bounded_append(current: str, value: str) -> str:
    return (current + value)[-RAW_CAPTURE_CHARS:]


def _start_stream_reader(
    stream: IO[str] | None,
    stream_name: str,
    output_queue: Queue[tuple[str, str | None]],
    stop_event: threading.Event,
) -> threading.Thread:
    def enqueue(item: tuple[str, str | None]) -> None:
        while not stop_event.is_set():
            try:
                output_queue.put(item, timeout=STREAM_POLL_SECONDS)
                return
            except Full:
                continue

    def read_stream() -> None:
        try:
            if stream is not None:
                for line in iter(stream.readline, ""):
                    enqueue((stream_name, line))
                    if stop_event.is_set():
                        break
        except (OSError, ValueError):
            # Shutdown may close the pipe while the daemon reader is draining it.
            pass
        finally:
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    # The process or another cleanup path may already own the pipe.
                    pass
            enqueue((stream_name, None))

    thread = threading.Thread(
        target=read_stream,
        name=f"gpt2giga-{stream_name}-reader",
        daemon=True,
    )
    thread.start()
    return thread


def _stop_process(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        _stop_posix_process_group(process)
        return
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        # The child may exit between poll() and terminate().
        pass
    if _wait_for_process(process, PROCESS_STOP_TIMEOUT_SECONDS):
        return
    try:
        process.kill()
    except OSError:
        # The child may exit before the forced-kill fallback runs.
        pass
    _wait_for_process(process, PROCESS_STOP_TIMEOUT_SECONDS)


def _wait_for_process(
    process: subprocess.Popen[str],
    timeout_seconds: float,
) -> bool:
    if process.poll() is not None:
        return True
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return process.poll() is not None
    return True


def _signal_process_group(process_group_id: int, sig: signal.Signals) -> bool:
    try:
        os.killpg(process_group_id, sig)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


def _stop_posix_process_group(process: subprocess.Popen[str]) -> None:
    process_group_id = process.pid
    signaled_group = _signal_process_group(process_group_id, signal.SIGTERM)
    if not signaled_group and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            # The direct child may exit while its process group is being stopped.
            pass

    # Reap the direct child with a bounded grace period. Descendants can keep the
    # inherited stdout/stderr descriptors open even after the direct child exits,
    # so always follow with a group-wide SIGKILL while that session still exists.
    _wait_for_process(process, PROCESS_STOP_TIMEOUT_SECONDS)
    group_deadline = time.monotonic() + PROCESS_GROUP_GRACE_SECONDS
    while _process_group_exists(process_group_id) and time.monotonic() < group_deadline:
        time.sleep(STREAM_POLL_SECONDS)
    if _process_group_exists(process_group_id):
        _signal_process_group(process_group_id, signal.SIGKILL)
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            # The direct child may exit after the group-wide signal.
            pass
        _wait_for_process(process, PROCESS_STOP_TIMEOUT_SECONDS)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _close_finished_process_pipes(
    process: subprocess.Popen[str],
    readers: tuple[threading.Thread, threading.Thread],
) -> None:
    for stream, reader in zip((process.stdout, process.stderr), readers, strict=True):
        # TextIOWrapper.close() may wait on the same lock held by a reader blocked
        # in readline(). Leaving that daemon reader to close its own pipe is safer
        # than making cancellation or timeout unbounded on platforms without
        # process-group signaling.
        if reader.is_alive():
            continue
        if stream is None or stream.closed:
            continue
        try:
            stream.close()
        except (OSError, ValueError):
            # Reader shutdown can close the pipe before this cleanup pass.
            pass


def _cancel_requested(request: HarnessRequest) -> bool:
    cancel_event = getattr(request, "cancel_event", None)
    is_set = getattr(cancel_event, "is_set", None)
    return bool(callable(is_set) and is_set())


class _StreamEventCoalescer:
    """Batch adjacent text deltas before invoking a persistence-backed sink."""

    def __init__(
        self,
        request: HarnessRequest,
        pending_events: list[HarnessEvent],
    ) -> None:
        self._request = request
        self._pending_events = pending_events
        self._pending: HarnessEvent | None = None
        self._pending_since = 0.0

    def record(self, event: HarnessEvent) -> None:
        now = time.monotonic()
        if not _coalescible_delta(event):
            self.flush()
            self._dispatch(event)
            return

        if self._pending is not None and _can_coalesce(self._pending, event):
            self._pending = _merge_delta_events(self._pending, event)
        else:
            self.flush()
            self._pending = event
            self._pending_since = now

        delta = _coalescible_delta(self._pending)
        if delta is not None and (
            len(delta) >= STREAM_EVENT_BATCH_CHARS
            or now - self._pending_since >= STREAM_EVENT_BATCH_SECONDS
        ):
            self.flush()

    def flush_due(self) -> None:
        if self._pending is None:
            return
        if time.monotonic() - self._pending_since >= STREAM_EVENT_BATCH_SECONDS:
            self.flush()

    def flush(self) -> None:
        if self._pending is None:
            return
        pending = self._pending
        self._pending = None
        self._pending_since = 0.0
        self._dispatch(pending)

    def _dispatch(self, event: HarnessEvent) -> None:
        event_sink = getattr(self._request, "event_sink", None)
        if callable(event_sink):
            event_sink(event)
        else:
            self._pending_events.append(event)


def _record_stream_event(
    event: HarnessEvent,
    *,
    message_parts: list[str],
    usage: dict[str, int],
    tool_calls: dict[str, dict[str, Any]],
    event_coalescer: _StreamEventCoalescer,
) -> None:
    safe_event = _safe_stream_event(event)
    payload = safe_event.payload
    if safe_event.type == "message_delta":
        delta = payload.get("delta")
        if isinstance(delta, str):
            message_parts.append(delta)
    elif safe_event.type == "usage":
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cached_input_tokens",
            "reasoning_output_tokens",
            "tool_tokens",
        ):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                usage[key] = value
    elif safe_event.type.startswith("tool_call_"):
        _update_tool_call(tool_calls, safe_event)
    event_coalescer.record(safe_event)


def _coalescible_delta(event: HarnessEvent) -> str | None:
    if event.type not in {"message_delta", "stdout_delta", "stderr_delta"}:
        return None
    delta = event.payload.get("delta")
    return delta if isinstance(delta, str) else None


def _can_coalesce(left: HarnessEvent, right: HarnessEvent) -> bool:
    if left.type != right.type or left.message != right.message:
        return False
    left_payload = {key: value for key, value in left.payload.items() if key != "delta"}
    right_payload = {
        key: value for key, value in right.payload.items() if key != "delta"
    }
    return left_payload == right_payload


def _merge_delta_events(left: HarnessEvent, right: HarnessEvent) -> HarnessEvent:
    left_delta = _coalescible_delta(left) or ""
    right_delta = _coalescible_delta(right) or ""
    return HarnessEvent(
        type=left.type,
        message=left.message,
        payload={**left.payload, "delta": left_delta + right_delta},
    )


def _safe_stream_event(event: HarnessEvent) -> HarnessEvent:
    return HarnessEvent(
        type=event.type,
        message=str(redact_secrets(event.message)),
        payload=dict(redact_secrets(dict(event.payload))),
    )


def _update_tool_call(
    tool_calls: dict[str, dict[str, Any]],
    event: HarnessEvent,
) -> None:
    payload = event.payload
    identifier = str(payload.get("tool_call_id") or f"tool-{len(tool_calls)}")
    tool_call = tool_calls.setdefault(identifier, {"tool_call_id": identifier})
    for key in ("name", "result", "status"):
        if payload.get(key) is not None:
            tool_call[key] = payload[key]
    output_delta = payload.get("output_delta")
    if isinstance(output_delta, str):
        previous_output = tool_call.get("result")
        tool_call["result"] = (
            previous_output + output_delta
            if isinstance(previous_output, str)
            else output_delta
        )
    arguments = (
        payload.get("arguments_delta")
        if event.type == "tool_call_delta"
        else payload.get("arguments")
    )
    if arguments is None:
        return
    if event.type == "tool_call_delta" and isinstance(arguments, str):
        previous = tool_call.get("arguments")
        tool_call["arguments"] = (
            previous + arguments if isinstance(previous, str) else arguments
        )
    else:
        tool_call["arguments"] = arguments


def _complete_usage(usage: Mapping[str, int]) -> dict[str, int]:
    completed = dict(usage)
    if (
        "total_tokens" not in completed
        and {
            "input_tokens",
            "output_tokens",
        }
        <= completed.keys()
    ):
        completed["total_tokens"] = (
            completed["input_tokens"] + completed["output_tokens"]
        )
    return completed


def _first_token_count(value: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool):
            return item
    return None


def _first_mapping(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        item = value.get(key)
        if isinstance(item, Mapping):
            return item
    return {}


def _stream_terminal_outcome(
    parse_payload: StreamPayloadParser,
) -> StreamTerminalOutcome | None:
    outcome = getattr(parse_payload, "terminal_outcome", None)
    if isinstance(outcome, StreamTerminalOutcome):
        return outcome
    recognized_payloads = getattr(parse_payload, "recognized_payloads", None)
    if recognized_payloads == 0:
        return stream_terminal_failure(
            None,
            fallback="Structured CLI output did not contain a recognized event contract",
        )
    return None


def _concise_stream_error(value: Any, *, fallback: str) -> str:
    safe_value = redact_secrets(value)
    text = _stream_error_text(safe_value)
    normalized = " ".join(text.split()) if text else ""
    return (normalized or fallback)[:TERMINAL_ERROR_CHARS]


def _stream_error_text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("message", "error", "detail", "reason"):
            if key in value and (text := _stream_error_text(value[key])):
                return text
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (list, tuple)):
        parts = [text for item in value if (text := _stream_error_text(item))]
        return "; ".join(parts[:3])
    if value is None:
        return ""
    return str(value)


def _extract_machine_readable_text(stdout: str) -> str:
    payload = _load_json_object(stdout)
    if payload is None:
        return ""
    for key in ("result", "response", "output_text", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _load_json_object(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, dict):
        return decoded
    return None
