from gpt2giga.core.redaction import (
    build_redaction_keys,
    is_sensitive_key,
    redact_traffic_payload,
)
from gpt2giga.models.config import ProxySettings


def test_traffic_log_redaction_settings_default_on():
    settings = ProxySettings()

    assert settings.traffic_log_redact_sensitive is True
    assert settings.traffic_log_redact_extra_keys == []


def test_traffic_log_redaction_settings_parse_extra_keys(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS",
        '["session_id", "tenant-secret"]',
    )

    settings = ProxySettings()

    assert settings.traffic_log_redact_extra_keys == ["session_id", "tenant-secret"]


def test_traffic_redaction_redacts_nested_dicts_and_lists():
    payload = {
        "headers": {
            "Authorization": "Bearer secret-token",
            "cookie": "session=secret",
            "x-goog-api-key": "google-secret",
            "x-request-id": "req-1",
        },
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "metadata": {
                    "api_key": "sk-secret",
                    "items": [{"set-cookie": "session=rotated"}],
                },
            }
        ],
        "key": "gemini-query-secret",
        "token": "plain-token",
    }

    redacted = redact_traffic_payload(payload)

    assert redacted["headers"]["Authorization"] == "***"
    assert redacted["headers"]["cookie"] == "***"
    assert redacted["headers"]["x-goog-api-key"] == "***"
    assert redacted["headers"]["x-request-id"] == "req-1"
    assert redacted["messages"][0]["content"] == "hello"
    assert redacted["messages"][0]["metadata"]["api_key"] == "***"
    assert redacted["messages"][0]["metadata"]["items"][0]["set-cookie"] == "***"
    assert redacted["key"] == "***"
    assert redacted["token"] == "***"
    assert payload["headers"]["Authorization"] == "Bearer secret-token"


def test_traffic_redaction_redacts_token_like_strings():
    payload = {
        "query": "api_key=sk-secret&key=gemini-secret&model=GigaChat",
    }

    redacted = redact_traffic_payload(payload)

    assert redacted["query"] == "api_key=***&key=***&model=GigaChat"


def test_traffic_redaction_supports_extra_keys():
    payload = {"tenant_secret": "secret", "nested": {"Session-ID": "session"}}

    redacted = redact_traffic_payload(
        payload, extra_keys=["tenant_secret", "session-id"]
    )

    assert redacted["tenant_secret"] == "***"
    assert redacted["nested"]["Session-ID"] == "***"


def test_traffic_redaction_can_be_disabled():
    payload = {"authorization": "Bearer secret"}

    redacted = redact_traffic_payload(payload, enabled=False)

    assert redacted is payload
    assert redacted["authorization"] == "Bearer secret"


def test_traffic_redaction_key_matching_is_case_and_separator_insensitive():
    keys = build_redaction_keys(["custom-token"])

    assert is_sensitive_key("X-API-KEY", keys)
    assert is_sensitive_key("x_api_key", keys)
    assert is_sensitive_key("Custom_Token", keys)
    assert not is_sensitive_key("x-request-id", keys)
