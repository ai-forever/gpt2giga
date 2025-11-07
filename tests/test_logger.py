import logging

import loguru

from gpt2giga.logger import setup_logger


def test_init_logger_info_level():
    logger = setup_logger("info")
    assert isinstance(logger, loguru._logger.Logger)
    assert logger.level("INFO").no == logging.INFO


def test_init_logger_debug_level():
    logger = setup_logger("DEBUG")
    assert logger.level("DEBUG").no == logging.DEBUG
