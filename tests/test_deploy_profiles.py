from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phoenix_profile_keeps_payload_capture_disabled_by_default():
    payload = (ROOT / "deploy" / "phoenix.yaml").read_text(encoding="utf-8")

    assert (
        'GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT: "${GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT:-False}"'
        in payload
    )
    assert (
        'GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES: "${GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES:-False}"'
        in payload
    )
    assert (
        'GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS: "${GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS:-False}"'
        in payload
    )
    assert (
        'GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES: "${GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES:-False}"'
        in payload
    )


def test_postgres_profile_initializes_traffic_log_schema():
    payload = (ROOT / "deploy" / "postgres.yaml").read_text(encoding="utf-8")
    init_script = (
        ROOT / "deploy" / "postgres-init" / "001_apply_traffic_log_migration.sh"
    ).read_text(encoding="utf-8")

    assert (
        "./postgres-init/001_apply_traffic_log_migration.sh:/docker-entrypoint-initdb.d/001_apply_traffic_log_migration.sh:ro"
        in payload
    )
    assert "../gpt2giga/storage/postgres/migrations:/gpt2giga-migrations:ro" in payload
    assert "migrate:up" in init_script
    assert "migrate:down" in init_script
    assert "psql --username" in init_script
