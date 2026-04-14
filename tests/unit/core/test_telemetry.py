from types import SimpleNamespace

import pytest

from gpt2giga.app.telemetry import (
    PrometheusMetricsSink,
    _build_langfuse_attributes,
    _build_otlp_traces_payload,
    create_observability_hub,
)


def test_prometheus_metrics_sink_renders_request_error_and_stream_metrics():
    sink = PrometheusMetricsSink()
    sink.record_request_event(
        {
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "status_code": 429,
            "duration_ms": 125.0,
            "stream_duration_ms": 500.0,
            "error_type": "RateLimitError",
        }
    )

    rendered = sink.render_prometheus_text()

    assert (
        'gpt2giga_http_requests_total{provider="openai",endpoint="/chat/completions",'
        'method="POST",status_code="429"} 1'
    ) in rendered
    assert (
        'gpt2giga_http_request_errors_total{provider="openai",'
        'endpoint="/chat/completions",method="POST",error_type="RateLimitError"} 1'
    ) in rendered
    assert "gpt2giga_http_request_duration_seconds_bucket" in rendered
    assert (
        'gpt2giga_http_stream_duration_seconds_sum{provider="openai",'
        'endpoint="/chat/completions",method="POST"} 0.5'
    ) in rendered


def test_otlp_payload_contains_http_and_genai_attributes():
    payload = _build_otlp_traces_payload(
        {
            "created_at": "2026-04-14T10:20:30+00:00",
            "provider": "openai",
            "endpoint": "/chat/completions",
            "path": "/v1/chat/completions",
            "method": "post",
            "status_code": 200,
            "duration_ms": 125.0,
            "model": "GigaChat-2-Max",
            "request_id": "req_123",
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        },
        resource_attributes={"service.name": "gpt2giga"},
        scope_name="gpt2giga.observability",
        scope_version="1.0.0",
    )

    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    attributes = {item["key"]: item["value"] for item in span["attributes"]}

    assert span["name"] == "POST /chat/completions"
    assert attributes["http.request.method"]["stringValue"] == "POST"
    assert attributes["http.response.status_code"]["intValue"] == "200"
    assert attributes["gen_ai.request.model"]["stringValue"] == "GigaChat-2-Max"
    assert attributes["gen_ai.usage.total_tokens"]["intValue"] == "30"


def test_langfuse_attributes_mark_generation_and_status_message():
    attributes = _build_langfuse_attributes(
        {
            "provider": "anthropic",
            "endpoint": "/messages",
            "method": "POST",
            "status_code": 429,
            "model": "GigaChat-2-Pro",
            "request_id": "req_456",
            "api_key_name": "integration",
            "error_type": "RateLimitError",
            "token_usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
            },
        }
    )

    assert attributes["langfuse.observation.type"] == "generation"
    assert attributes["langfuse.observation.level"] == "ERROR"
    assert attributes["langfuse.observation.status_message"] == "RateLimitError"
    assert attributes["langfuse.observation.model.name"] == "GigaChat-2-Pro"
    assert attributes["langfuse.observation.metadata.api_key_name"] == "integration"


def test_langfuse_sink_requires_base_url_and_keys():
    config = SimpleNamespace(
        proxy_settings=SimpleNamespace(
            observability_sinks=["langfuse"],
            otlp_headers={},
            otlp_timeout_seconds=5.0,
            otlp_max_pending_requests=16,
            otlp_service_name="gpt2giga",
            runtime_store_namespace="test",
            mode="DEV",
            langfuse_base_url="http://langfuse-web:3000",
            langfuse_public_key=None,
            langfuse_secret_key=None,
        )
    )

    with pytest.raises(RuntimeError, match="LANGFUSE_PUBLIC_KEY"):
        create_observability_hub(["langfuse"], config=config)
