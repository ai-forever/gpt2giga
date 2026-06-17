import pytest

from gpt2giga.models.config import ProxyConfig, ProxySettings


def test_proxy_settings_defaults(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_HOST", raising=False)
    monkeypatch.delenv("GPT2GIGA_PASS_MODEL", raising=False)
    monkeypatch.delenv("GPT2GIGA_ENABLE_REASONING", raising=False)
    monkeypatch.delenv("GPT2GIGA_DISABLE_REASONING", raising=False)
    monkeypatch.delenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_GIGACHAT_API_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER", raising=False)
    monkeypatch.delenv("GPT2GIGA_NORMALIZATION_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_LEGACY_CHAT_FALLBACK", raising=False)
    monkeypatch.delenv("GPT2GIGA_TRAFFIC_LOG_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_TRAFFIC_LOG_SINK", raising=False)
    monkeypatch.delenv("GPT2GIGA_TRAFFIC_LOG_SINKS", raising=False)
    monkeypatch.delenv("GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_URL", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_USERNAME", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_PASSWORD", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_INDEX", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_DATA_STREAM", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_BULK_SIZE", raising=False)
    monkeypatch.delenv("GPT2GIGA_OPENSEARCH_FLUSH_INTERVAL_MS", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_BACKEND", raising=False)
    monkeypatch.delenv("GPT2GIGA_PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("GPT2GIGA_PHOENIX_PROJECT_NAME", raising=False)
    monkeypatch.delenv("GPT2GIGA_PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH", raising=False)
    monkeypatch.delenv("GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_METRICS_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_METRICS_PATH", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("GPT2GIGA_UI_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_DEBUG_TRANSLATE_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_ADMIN_API_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("GPT2GIGA_REPLAY_ENABLED", raising=False)
    monkeypatch.delenv("GPT2GIGA_DEFAULT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODEL_MAX_CONNECTIONS", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", raising=False)
    s = ProxySettings()
    assert s.mode == "DEV"
    assert s.host == "localhost"
    assert isinstance(s.port, int)
    assert isinstance(s.log_level, str)
    assert s.pass_model is True
    assert s.enable_reasoning is False
    assert s.disable_reasoning is False
    assert s.structured_output_mode == "function_call"
    assert s.gigachat_api_mode == "v1"
    assert s.experimental_normalized_layer is False
    assert s.normalization_mode == "off"
    assert s.legacy_chat_fallback is True
    assert s.conversation_stitching_enabled is False
    assert s.conversation_ttl_seconds == 3600
    assert s.conversation_max_messages == 40
    assert s.conversation_use_session_id is False
    assert s.conversation_on_divergence == "client_wins"
    assert s.traffic_log_enabled is False
    assert s.traffic_log_sink == "noop"
    assert s.traffic_log_sinks == []
    assert s.traffic_log_retention_days == 30
    assert s.traffic_log_purge_interval_seconds == 3600
    assert s.opensearch_url == "http://localhost:9200"
    assert s.opensearch_username is None
    assert s.opensearch_password is None
    assert s.opensearch_index == "gpt2giga-traffic"
    assert s.opensearch_data_stream is True
    assert s.opensearch_bulk_size == 500
    assert s.opensearch_flush_interval_ms == 2000
    assert s.observability_enabled is False
    assert s.observability_backend == "phoenix"
    assert s.phoenix_collector_endpoint == "http://localhost:4317"
    assert s.phoenix_project_name == "gpt2giga"
    assert s.phoenix_api_key is None
    assert s.observability_sample_rate == 1.0
    assert s.observability_capture_content is False
    assert s.observability_capture_messages is False
    assert s.observability_capture_tool_args is False
    assert s.observability_capture_responses is False
    assert s.observability_max_content_length == 8000
    assert s.observability_redaction_enabled is True
    assert s.metrics_enabled is False
    assert s.metrics_path == "/metrics"
    assert s.ui_enabled is False
    assert s.debug_translate_enabled is False
    assert s.admin_api_enabled is False
    assert s.admin_api_key is None
    assert s.replay_enabled is False
    assert s.max_audio_file_size_bytes == 35 * 1024 * 1024
    assert s.max_image_file_size_bytes == 15 * 1024 * 1024
    assert s.max_text_file_size_bytes == 40 * 1024 * 1024
    assert s.max_audio_image_total_size_bytes == 80 * 1024 * 1024
    assert s.default_max_tokens is None
    assert s.model_max_connections == {}
    assert s.model_max_connections_default is None
    assert s.model_max_connections_acquire_timeout is None


def test_proxy_config_instantiation():
    c = ProxyConfig()
    assert isinstance(c.proxy_settings, ProxySettings)


def test_proxy_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HOST", "127.0.0.1")
    s = ProxySettings()
    assert s.host == "127.0.0.1"


def test_proxy_settings_default_max_tokens_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_DEFAULT_MAX_TOKENS", "128000")

    s = ProxySettings()

    assert s.default_max_tokens == 128000


@pytest.mark.parametrize("env_value", ["0", "-1"])
def test_proxy_settings_default_max_tokens_must_be_positive(monkeypatch, env_value):
    monkeypatch.setenv("GPT2GIGA_DEFAULT_MAX_TOKENS", env_value)

    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_model_max_connections_from_env(monkeypatch):
    monkeypatch.setenv(
        "GPT2GIGA_MODEL_MAX_CONNECTIONS",
        '{"GigaChat":1,"GigaChat-Pro":2,"GigaChat-Max":5}',
    )
    monkeypatch.setenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", "3")
    monkeypatch.setenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", "30")

    s = ProxySettings()

    assert s.model_max_connections == {
        "GigaChat": 1,
        "GigaChat-Pro": 2,
        "GigaChat-Max": 5,
    }
    assert s.model_max_connections_default == 3
    assert s.model_max_connections_acquire_timeout == 30


def test_proxy_settings_model_max_connections_timeout_zero_is_valid(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", "0")

    s = ProxySettings()

    assert s.model_max_connections_acquire_timeout == 0


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS", '{"GigaChat":0}'),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS", '{"GigaChat":-1}'),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", "0"),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT", "-1"),
        ("GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT", "-1"),
    ],
)
def test_proxy_settings_invalid_model_max_connections(monkeypatch, env_name, env_value):
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_MODE", "prod")
    s = ProxySettings()
    assert s.mode == "PROD"


def test_proxy_settings_bool_cast_from_env(monkeypatch):
    # Проверяем, что строки из ENV приводятся к bool согласно pydantic
    monkeypatch.setenv("GPT2GIGA_USE_HTTPS", "true")
    s = ProxySettings()
    assert s.use_https is True


def test_proxy_settings_disable_reasoning_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_DISABLE_REASONING", "true")
    s = ProxySettings()
    assert s.disable_reasoning is True


def test_proxy_settings_structured_output_mode_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", "native")
    s = ProxySettings()
    assert s.structured_output_mode == "native"


def test_proxy_settings_structured_output_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", " NATIVE ")
    s = ProxySettings()
    assert s.structured_output_mode == "native"


def test_proxy_settings_invalid_structured_output_mode(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_STRUCTURED_OUTPUT_MODE", "unsupported")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_gigachat_api_mode_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", "v2")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v2"


def test_proxy_settings_modular_feature_flags_from_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER", "true")
    monkeypatch.setenv("GPT2GIGA_NORMALIZATION_MODE", " SHADOW ")
    monkeypatch.setenv("GPT2GIGA_LEGACY_CHAT_FALLBACK", "false")
    monkeypatch.setenv("GPT2GIGA_CONVERSATION_STITCHING_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_CONVERSATION_TTL_SECONDS", "90")
    monkeypatch.setenv("GPT2GIGA_CONVERSATION_MAX_MESSAGES", "8")
    monkeypatch.setenv("GPT2GIGA_CONVERSATION_USE_SESSION_ID", "true")
    monkeypatch.setenv("GPT2GIGA_CONVERSATION_ON_DIVERGENCE", " FORK ")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINK", " JSONL ")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINKS", "postgres, opensearch")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_JSONL_PATH", "/tmp/gpt2giga-traffic.jsonl")
    monkeypatch.setenv(
        "GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN",
        "postgresql://user:pass@localhost:5432/gpt2giga",
    )
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT", "true")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_QUEUE_SIZE", "123")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_BATCH_SIZE", "12")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_FLUSH_INTERVAL_MS", "345")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_DROP_ON_BACKPRESSURE", "false")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE", "false")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS", '["session_id"]')
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS", "14")
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS", "600")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_URL", "https://opensearch.example")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_USERNAME", "search-user")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_PASSWORD", "search-secret")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_INDEX", "gpt2giga-traffic-dev")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_DATA_STREAM", "false")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_BULK_SIZE", "25")
    monkeypatch.setenv("GPT2GIGA_OPENSEARCH_FLUSH_INTERVAL_MS", "789")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_BACKEND", " PHOENIX ")
    monkeypatch.setenv("GPT2GIGA_PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:4317")
    monkeypatch.setenv("GPT2GIGA_PHOENIX_PROJECT_NAME", "gpt2giga-dev")
    monkeypatch.setenv("GPT2GIGA_PHOENIX_API_KEY", "phoenix-secret")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SAMPLE_RATE", "0.25")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT", "true")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES", "true")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS", "true")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES", "true")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH", "512")
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED", "false")
    monkeypatch.setenv("GPT2GIGA_METRICS_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_METRICS_PATH", "internal/metrics/")
    monkeypatch.setenv("GPT2GIGA_UI_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_DEBUG_TRANSLATE_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GPT2GIGA_ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("GPT2GIGA_REPLAY_ENABLED", "true")

    s = ProxySettings()

    assert s.experimental_normalized_layer is True
    assert s.normalization_mode == "shadow"
    assert s.legacy_chat_fallback is False
    assert s.conversation_stitching_enabled is True
    assert s.conversation_ttl_seconds == 90
    assert s.conversation_max_messages == 8
    assert s.conversation_use_session_id is True
    assert s.conversation_on_divergence == "fork"
    assert s.traffic_log_enabled is True
    assert s.traffic_log_sink == "jsonl"
    assert s.traffic_log_sinks == ["postgres", "opensearch"]
    assert s.traffic_log_jsonl_path == "/tmp/gpt2giga-traffic.jsonl"
    assert (
        s.traffic_log_postgres_dsn == "postgresql://user:pass@localhost:5432/gpt2giga"
    )
    assert s.traffic_log_capture_content is True
    assert s.traffic_log_queue_size == 123
    assert s.traffic_log_batch_size == 12
    assert s.traffic_log_flush_interval_ms == 345
    assert s.traffic_log_drop_on_backpressure is False
    assert s.traffic_log_redact_sensitive is False
    assert s.traffic_log_redact_extra_keys == ["session_id"]
    assert s.traffic_log_retention_days == 14
    assert s.traffic_log_purge_interval_seconds == 600
    assert s.opensearch_url == "https://opensearch.example"
    assert s.opensearch_username == "search-user"
    assert s.opensearch_password == "search-secret"
    assert s.opensearch_index == "gpt2giga-traffic-dev"
    assert s.opensearch_data_stream is False
    assert s.opensearch_bulk_size == 25
    assert s.opensearch_flush_interval_ms == 789
    assert s.observability_enabled is True
    assert s.observability_backend == "phoenix"
    assert s.phoenix_collector_endpoint == "http://phoenix:4317"
    assert s.phoenix_project_name == "gpt2giga-dev"
    assert s.phoenix_api_key == "phoenix-secret"
    assert s.observability_sample_rate == 0.25
    assert s.observability_capture_content is True
    assert s.observability_capture_messages is True
    assert s.observability_capture_tool_args is True
    assert s.observability_capture_responses is True
    assert s.observability_max_content_length == 512
    assert s.observability_redaction_enabled is False
    assert s.metrics_enabled is True
    assert s.metrics_path == "/internal/metrics"
    assert s.ui_enabled is True
    assert s.debug_translate_enabled is True
    assert s.admin_api_enabled is True
    assert s.admin_api_key == "admin-secret"
    assert s.replay_enabled is True


def test_proxy_settings_invalid_traffic_log_sink(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINK", "unsupported")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_traffic_log_sinks_from_json_env(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINKS", '["postgres","opensearch"]')

    s = ProxySettings()

    assert s.traffic_log_sinks == ["postgres", "opensearch"]


def test_proxy_settings_invalid_traffic_log_sinks(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_TRAFFIC_LOG_SINKS", "postgres,unsupported")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_phoenix_env_fallback(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix-env:4317")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "env-project")
    monkeypatch.setenv("PHOENIX_API_KEY", "env-secret")

    s = ProxySettings()

    assert s.phoenix_collector_endpoint == "http://phoenix-env:4317"
    assert s.phoenix_project_name == "env-project"
    assert s.phoenix_api_key == "env-secret"


def test_proxy_settings_invalid_observability_backend(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_BACKEND", "unsupported")
    with pytest.raises(Exception):
        ProxySettings()


@pytest.mark.parametrize("sample_rate", ["-0.1", "1.1"])
def test_proxy_settings_invalid_observability_sample_rate(monkeypatch, sample_rate):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_SAMPLE_RATE", sample_rate)
    with pytest.raises(Exception):
        ProxySettings()


@pytest.mark.parametrize("max_length", ["0", "-1"])
def test_proxy_settings_invalid_observability_max_content_length(
    monkeypatch,
    max_length,
):
    monkeypatch.setenv("GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH", max_length)
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_invalid_normalization_mode(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_NORMALIZATION_MODE", "unsupported")
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_api_mode_normalized(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", " V2 ")
    s = ProxySettings()
    assert s.gigachat_api_mode == "v2"


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("GPT2GIGA_GIGACHAT_API_MODE", "inherit"),
        ("GPT2GIGA_GIGACHAT_API_MODE", "unsupported"),
    ],
)
def test_proxy_settings_invalid_api_modes(monkeypatch, env_name, env_value):
    monkeypatch.setenv(env_name, env_value)
    with pytest.raises(Exception):
        ProxySettings()


def test_proxy_settings_invalid_port(monkeypatch):
    # Невалидный порт должен вызвать ошибку парсинга pydantic
    monkeypatch.setenv("GPT2GIGA_PORT", "not_an_int")
    with pytest.raises(Exception):
        ProxySettings()


def test_api_key_hidden_from_repr():
    """api_key value must not appear in ProxySettings repr (visible in logs)."""
    s = ProxySettings(api_key="super-secret-key-12345")
    text = repr(s)
    assert "super-secret-key-12345" not in text
    assert "api_key=" not in text


def test_api_key_hidden_from_model_dump_exclude():
    """model_dump(exclude={'api_key'}) must not contain the key."""
    s = ProxySettings(api_key="super-secret-key-12345")
    dumped = s.model_dump(exclude={"api_key"})
    assert "api_key" not in dumped
    assert "super-secret-key-12345" not in str(dumped)


def test_admin_api_key_hidden_from_repr():
    """admin_api_key value must not appear in ProxySettings repr."""
    s = ProxySettings(admin_api_key="admin-secret-12345")
    text = repr(s)
    assert "admin-secret-12345" not in text
    assert "admin_api_key=" not in text


def test_opensearch_credentials_hidden_from_repr():
    """OpenSearch credential values must not appear in ProxySettings repr."""
    s = ProxySettings(
        opensearch_username="search-user",
        opensearch_password="search-secret",
    )
    text = repr(s)
    assert "search-user" not in text
    assert "search-secret" not in text
    assert "opensearch_username=" not in text
    assert "opensearch_password=" not in text


def test_phoenix_api_key_hidden_from_repr():
    """Phoenix API key value must not appear in ProxySettings repr."""
    s = ProxySettings(phoenix_api_key="phoenix-secret")
    text = repr(s)
    assert "phoenix-secret" not in text
    assert "phoenix_api_key=" not in text
