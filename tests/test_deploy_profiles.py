from pathlib import Path

from gpt2giga.providers.profiles.loader import (
    ProviderPolicyCatalog,
    load_provider_profiles,
)


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
    assert (
        "../src/gpt2giga/storage/postgres/migrations:/gpt2giga-migrations:ro"
    ) in payload
    assert "migrate:up" in init_script
    assert "migrate:down" in init_script
    assert "psql --username" in init_script


def test_chat_completions_observability_uses_reverse_proxy_namespace():
    deployment = (ROOT / "deploy" / "chat-completions-observability.yaml").read_text(
        encoding="utf-8"
    )
    profile = (ROOT / "deploy" / "providers.chat-completions.example.yaml").read_text(
        encoding="utf-8"
    )

    assert 'network_mode: "service:mitmproxy"' in deployment
    assert (
        "reverse:${MITMPROXY_UPSTREAM_URL:-http://host.docker.internal:29999}"
        in deployment
    )
    assert "HTTP_PROXY" not in deployment
    assert "HTTPS_PROXY" not in deployment
    assert '"127.0.0.1:${GPT2GIGA_PORT:-8090}:${GPT2GIGA_PORT:-8090}"' in deployment
    assert '"127.0.0.1:${MITMPROXY_WEB_PORT:-8081}:8081"' in deployment
    assert "base_url: http://127.0.0.1:8080/v1/chat/completions" in profile
    assert "upstream_stream_mode: buffered" in profile

    loaded = load_provider_profiles(
        ROOT / "deploy" / "providers.chat-completions.example.yaml",
        environ={},
        policies=ProviderPolicyCatalog(
            network_policy_refs=frozenset({"loopback-development"}),
            tls_policy_refs=frozenset({"system-default"}),
        ),
    )
    assert loaded.config.profiles[0].models[0].public_alias == "my_model"
