import logging

from gpt2giga.logger import init_logger


def test_init_logger_info_level():
    logger = init_logger("info")
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.INFO


def test_init_logger_debug_level():
    logger = init_logger("DEBUG")
    assert logger.level == logging.DEBUG
