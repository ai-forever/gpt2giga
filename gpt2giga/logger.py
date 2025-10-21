import logging
import sys


def init_logger(verbose: bool = False) -> logging.Logger:
    """Initialize a simple console logger."""
    level = logging.DEBUG if verbose else logging.INFO

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
