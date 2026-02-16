# logger.py
import contextvars
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


def setup_logger(
    log_level="INFO",
    log_file="app.log",
    max_bytes=10_000_000,
    enable_redaction=True,
):
    """Configure Loguru logger with file rotation, contextual rquid, and redaction."""
    logger.remove()  # Remove default logger
    log_level = log_level.upper()
    # Custom format that automatically includes rquid
    format_str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[rquid]}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        level=log_level,
        format=format_str,
        enqueue=True,
    )

    logger.add(
        log_file,
        level=log_level,
        rotation=max_bytes,  # rotate by size
        retention="7 days",
        enqueue=True,
        format=format_str,
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
