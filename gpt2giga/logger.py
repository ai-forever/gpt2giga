# logger.py
import sys
from loguru import logger
import contextvars

# Context variable for rquid
rquid_context = contextvars.ContextVar("rquid", default="-")


def get_rquid() -> str:
    """Retrieve current request's RQUID from contextvar."""
    return rquid_context.get()


def setup_logger(log_level="INFO", log_file="app.log", max_bytes=10_000_000):
    """
    Configure Loguru logger with file rotation and contextual rquid.
    """
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

    # Patch to automatically bind rquid from contextvar
    class RquidFilter:
        def __call__(self, record):
            record["extra"]["rquid"] = get_rquid()
            return True

    logger.configure(patcher=RquidFilter())
    return logger
