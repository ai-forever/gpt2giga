"""Logging setup and sanitization helpers."""

import contextvars
import json
import sys
from collections.abc import Mapping, Sequence

from loguru import logger

from gpt2giga.core.constants import _BEARER_RE, _JSON_KV_RE, _KV_EQ_RE

rquid_context = contextvars.ContextVar("rquid", default="-")


def redact_sensitive(message: str) -> str:
    """Replace values of sensitive keys in a log message with '***'."""
    message = _JSON_KV_RE.sub(r"\1\2\1: \3***\3", message)
    message = _KV_EQ_RE.sub(r"\1=***", message)
    message = _BEARER_RE.sub(r"\1***", message)
    return message


def sanitize_for_utf8(value):
    """Return a UTF-8-safe representation of ``value``."""
    if isinstance(value, str):
        return value.encode("utf-8", errors="backslashreplace").decode("utf-8")
    if isinstance(value, Mapping):
        return {
            sanitize_for_utf8(key): sanitize_for_utf8(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return type(value)(sanitize_for_utf8(item) for item in value)
    return value


def get_rquid() -> str:
    """Retrieve current request's RQUID from contextvar."""
    return rquid_context.get()


def _format_structured_extra(extra: dict) -> str:
    """Format structured extra fields into a compact suffix string."""
    filtered = {
        sanitize_for_utf8(key): sanitize_for_utf8(value)
        for key, value in extra.items()
        if key != "rquid" and value is not None
    }
    if not filtered:
        return ""
    try:
        json_str = json.dumps(filtered, ensure_ascii=False, default=str)
        json_str = json_str.replace("{", "{{").replace("}", "}}")
        return " | " + json_str
    except (TypeError, ValueError):
        return ""


def setup_logger(
    log_level="INFO",
    log_file="app.log",
    max_bytes=10_000_000,
    enable_redaction=True,
):
    """Configure Loguru logger with file rotation, contextual rquid, and redaction."""
    logger.remove()
    log_level = log_level.upper()

    def _format(record):
        extra_str = _format_structured_extra(record["extra"])
        return (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[rquid]}</cyan> | "
            "<level>{message}</level>" + extra_str + "\n"
        )

    logger.add(
        sys.stdout,
        level=log_level,
        format=_format,
        enqueue=True,
    )
    logger.add(
        log_file,
        level=log_level,
        rotation=max_bytes,
        retention="7 days",
        enqueue=True,
        format=_format,
    )

    do_redact = enable_redaction

    class RquidAndRedactPatcher:
        """Bind rquid context and optionally redact sensitive data."""

        def __call__(self, record):
            record["extra"]["rquid"] = get_rquid()
            record["message"] = sanitize_for_utf8(record["message"])
            if do_redact:
                record["message"] = redact_sensitive(record["message"])

    logger.configure(patcher=RquidAndRedactPatcher())
    return logger
