import logging

import loguru

from gpt2giga.logger import setup_logger, redact_sensitive


def test_init_logger_info_level():
    logger = setup_logger("info")
    assert isinstance(logger, loguru._logger.Logger)
    assert logger.level("INFO").no == logging.INFO


def test_init_logger_debug_level():
    logger = setup_logger("DEBUG")
    assert logger.level("DEBUG").no == logging.DEBUG


# --- redact_sensitive tests ---


def test_redact_json_kv_double_quotes():
    msg = '{"api_key": "sk-secret123", "model": "gpt-4"}'
    result = redact_sensitive(msg)
    assert "sk-secret123" not in result
    assert '"api_key": "***"' in result
    assert '"model": "gpt-4"' in result


def test_redact_json_kv_single_quotes():
    msg = "{'password': 'P@ssw0rd!'}"
    result = redact_sensitive(msg)
    assert "P@ssw0rd!" not in result
    assert "'password': '***'" in result


def test_redact_multiple_keys():
    msg = '{"token": "tok_abc", "credentials": "cred_xyz", "host": "example.com"}'
    result = redact_sensitive(msg)
    assert "tok_abc" not in result
    assert "cred_xyz" not in result
    assert "example.com" in result


def test_redact_kv_eq_style():
    msg = "Connecting with api_key=sk-abc123&host=example.com"
    result = redact_sensitive(msg)
    assert "sk-abc123" not in result
    assert "api_key=***" in result
    assert "host=example.com" in result


def test_redact_bearer_token():
    msg = "Header: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
    result = redact_sensitive(msg)
    assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in result
    assert "Bearer ***" in result


def test_redact_authorization_header():
    msg = '{"authorization": "Bearer tok123"}'
    result = redact_sensitive(msg)
    assert "tok123" not in result
    assert '"authorization": "***"' in result


def test_redact_access_token():
    msg = '{"access_token": "at_secret"}'
    result = redact_sensitive(msg)
    assert "at_secret" not in result


def test_redact_no_sensitive_data():
    msg = "Processing 5 messages for model gpt-4"
    result = redact_sensitive(msg)
    assert result == msg


def test_redact_case_insensitive():
    msg = "API_KEY=mykey123"
    result = redact_sensitive(msg)
    assert "mykey123" not in result


def test_setup_logger_with_redaction_enabled(tmp_path):
    log_file = str(tmp_path / "test.log")
    logger = setup_logger("DEBUG", log_file=log_file, enable_redaction=True)
    assert isinstance(logger, loguru._logger.Logger)


def test_setup_logger_with_redaction_disabled(tmp_path):
    log_file = str(tmp_path / "test.log")
    logger = setup_logger("DEBUG", log_file=log_file, enable_redaction=False)
    assert isinstance(logger, loguru._logger.Logger)
