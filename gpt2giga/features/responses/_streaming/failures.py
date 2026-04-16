"""Failure helpers shared by Responses streaming flows."""

from __future__ import annotations

from typing import Any

from gpt2giga.features.responses._streaming.events import (
    ResponsesStreamEventSequencer,
)
from gpt2giga.providers.gigachat.streaming import report_stream_failure


def emit_stream_failure_event(
    *,
    request: Any,
    exc: Exception,
    emitter: ResponsesStreamEventSequencer,
    logger: Any = None,
    rquid: str | None = None,
) -> str:
    """Report a stream failure and format the public SSE error event."""
    failure = report_stream_failure(
        request,
        exc,
        logger=logger,
        rquid=rquid,
    )
    return emitter.emit(
        "error",
        {
            "code": failure.code,
            "message": failure.message,
            "param": None,
        },
    )
