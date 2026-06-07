-- gpt2giga traffic log storage schema.
-- Apply only when the optional Postgres traffic log backend is enabled.

-- migrate:up
CREATE TABLE IF NOT EXISTS gpt2giga_traffic_logs (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    request_id text NOT NULL,
    trace_id text,
    span_id text,
    protocol text NOT NULL,
    route text NOT NULL,
    method text NOT NULL,
    status_code integer,
    model_requested text,
    model_effective text,
    provider text,
    upstream_status_code integer,
    latency_ms integer,
    upstream_latency_ms integer,
    input_tokens integer,
    output_tokens integer,
    total_tokens integer,
    error_type text,
    error_message text,
    api_key_hash text,
    client_ip_hash text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    request_headers jsonb,
    request_body jsonb,
    response_body jsonb
);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_created_at
    ON gpt2giga_traffic_logs (created_at);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_request_id
    ON gpt2giga_traffic_logs (request_id);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_trace_id
    ON gpt2giga_traffic_logs (trace_id);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_status_code
    ON gpt2giga_traffic_logs (status_code);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_model_effective
    ON gpt2giga_traffic_logs (model_effective);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_provider
    ON gpt2giga_traffic_logs (provider);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_api_key_hash
    ON gpt2giga_traffic_logs (api_key_hash);

CREATE INDEX IF NOT EXISTS ix_gpt2giga_traffic_logs_metadata_gin
    ON gpt2giga_traffic_logs USING gin (metadata);

-- migrate:down
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_metadata_gin;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_api_key_hash;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_provider;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_model_effective;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_status_code;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_trace_id;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_request_id;
DROP INDEX IF EXISTS ix_gpt2giga_traffic_logs_created_at;
DROP TABLE IF EXISTS gpt2giga_traffic_logs;
