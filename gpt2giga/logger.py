import logging


def init_logger(name: str) -> logging.Logger:
    """The main purpose of this function is to ensure that loggers are
    retrieved in such a way that we can be sure the root vllm logger has
    already been configured."""

    logger = logging.getLogger(name)

    return logger

logger = init_logger("gpt2giga")
