import json
import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

rquid_context: ContextVar[str | None] = ContextVar("rquid", default=None)


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter with contextual rquid support."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "rquid": rquid_context.get(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps({k: v for k, v in log_data.items() if v is not None})


def init_logger(
    name: str = "gpt2giga",
    log_level: str = "INFO",
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Initialize a JSON logger with contextual request ID support.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = JSONFormatter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    # Silence noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger.debug("Logger initialized with contextual rquid support.")
    return logger
