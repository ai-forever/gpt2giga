from types import SimpleNamespace
from unittest.mock import MagicMock

from gpt2giga.common.debug_logging import log_debug_payload


def test_payload_serialization_is_skipped_when_debug_logging_is_disabled():
    payload = MagicMock()
    payload.model_dump.side_effect = AssertionError("payload must stay lazy")
    logger = MagicMock()
    config = SimpleNamespace(
        proxy_settings=SimpleNamespace(mode="DEV", log_level="INFO")
    )

    log_debug_payload(
        logger,
        config,
        event="request",
        message="Request payload",
        payload_key="payload",
        payload=payload,
    )

    logger.bind.assert_not_called()


def test_payload_serialization_runs_when_debug_logging_is_enabled():
    logger = MagicMock()
    bound_logger = logger.bind.return_value
    config = SimpleNamespace(
        proxy_settings=SimpleNamespace(mode="DEV", log_level="DEBUG")
    )

    log_debug_payload(
        logger,
        config,
        event="request",
        message="Request payload",
        payload_key="payload",
        payload={"message": "hello"},
    )

    logger.bind.assert_called_once_with(
        event="request",
        payload={"message": "hello"},
    )
    bound_logger.debug.assert_called_once_with("Request payload")
