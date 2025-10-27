import logging
import sys


def init_logger(log_level: str) -> logging.Logger:
    """Initialize a simple console logger."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger("gpt2giga")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
