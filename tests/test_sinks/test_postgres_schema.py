from importlib.resources import files


def _migration_sql() -> str:
    return (
        files("gpt2giga.storage.postgres.migrations")
        .joinpath("0001_traffic_logs.sql")
        .read_text(encoding="utf-8")
    )


def test_postgres_traffic_logs_schema_contains_required_columns():
    sql = _migration_sql().lower()
    required_columns = [
        "id uuid primary key",
        "created_at timestamptz not null",
        "request_id text not null",
        "trace_id text",
        "span_id text",
        "protocol text not null",
        "route text not null",
        "method text not null",
        "status_code integer",
        "model_requested text",
        "model_effective text",
        "provider text",
        "upstream_status_code integer",
        "latency_ms integer",
        "upstream_latency_ms integer",
        "input_tokens integer",
        "output_tokens integer",
        "total_tokens integer",
        "error_type text",
        "error_message text",
        "api_key_hash text",
        "client_ip_hash text",
        "metadata jsonb not null default '{}'::jsonb",
        "request_headers jsonb",
        "request_body jsonb",
        "response_body jsonb",
    ]

    for column in required_columns:
        assert column in sql


def test_postgres_traffic_logs_schema_contains_required_indexes():
    sql = _migration_sql().lower()
    required_indexes = [
        "ix_gpt2giga_traffic_logs_created_at",
        "ix_gpt2giga_traffic_logs_request_id",
        "ix_gpt2giga_traffic_logs_trace_id",
        "ix_gpt2giga_traffic_logs_status_code",
        "ix_gpt2giga_traffic_logs_model_effective",
        "ix_gpt2giga_traffic_logs_provider",
        "ix_gpt2giga_traffic_logs_api_key_hash",
        "ix_gpt2giga_traffic_logs_metadata_gin",
    ]

    for index_name in required_indexes:
        assert index_name in sql

    assert "using gin (metadata)" in sql
