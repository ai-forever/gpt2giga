# logger.py
import contextvars
import json
import sys

from loguru import logger

from .constants import _JSON_KV_RE, _KV_EQ_RE, _BEARER_RE

# Context variable for rquid
rquid_context = contextvars.ContextVar("rquid", default="-")


def redact_sensitive(message: str) -> str:
    """Replace values of sensitive keys in a log message with '***'."""
    message = _JSON_KV_RE.sub(r"\1\2\1: \3***\3", message)
    message = _KV_EQ_RE.sub(r"\1=***", message)
    message = _BEARER_RE.sub(r"\1***", message)
    return message


def get_rquid() -> str:
    """Retrieve current request's RQUID from contextvar."""
    return rquid_context.get()


def _format_structured_extra(extra: dict) -> str:
    """Format structured extra fields into a compact suffix string.

    Skips internal keys (``rquid``) so that only user-bound fields appear.
    Returns an empty string when there are no extra fields to show.

    Note: Curly braces in the JSON output are escaped (doubled) to prevent
    Loguru's format_map from interpreting them as format placeholders.
    """
    filtered = {k: v for k, v in extra.items() if k != "rquid" and v is not None}
    if not filtered:
        return ""
    try:
        json_str = json.dumps(filtered, ensure_ascii=False, default=str)
        # Escape curly braces to prevent Loguru format_map interpretation
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
    logger.remove()  # Remove default logger
    log_level = log_level.upper()

    # Custom format that includes rquid and optional structured extra fields.
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
        rotation=max_bytes,  # rotate by size
        retention="7 days",
        enqueue=True,
        format=_format,
    )

    _do_redact = enable_redaction

    class RquidAndRedactPatcher:
        """Bind rquid context and optionally redact sensitive data."""

        def __call__(self, record):
            record["extra"]["rquid"] = get_rquid()
            if _do_redact:
                record["message"] = redact_sensitive(record["message"])

    logger.configure(patcher=RquidAndRedactPatcher())
    return logger
