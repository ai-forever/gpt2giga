from types import SimpleNamespace

import pytest

from gpt2giga.app.telemetry import (
    PrometheusMetricsSink,
    _build_langfuse_attributes,
    _build_phoenix_attributes,
    _build_otlp_traces_payload,
    _build_otlp_traces_protobuf_payload,
    create_observability_hub,
)
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
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


def test_phoenix_attributes_mark_llm_span_and_input_output_columns():
    attributes = _build_phoenix_attributes(
        {
            "endpoint": "/chat/completions",
            "model": "GigaChat-2-Max",
            "session_id": "resp_123",
            "input_value": "Tell me a joke",
            "input_mime_type": "text/plain",
            "output_value": "Knock knock",
            "output_mime_type": "text/plain",
            "input_messages": [
                {"role": "system", "content": "Be concise."},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "function_name": "get_weather",
                            "function_arguments": '{"city":"Paris"}',
                        }
                    ],
                },
                {"role": "user", "content": "Tell me a joke"},
            ],
            "output_messages": [
                {"role": "assistant", "content": "Thinking..."},
                {"role": "assistant", "content": "Knock knock"},
            ],
            "available_tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "parameters": {"type": "object"},
                }
            ],
            "invocation_parameters": '{"reasoning":{"effort":"high"}}',
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }
    )

    assert attributes["openinference.span.kind"] == "LLM"
    assert attributes["session.id"] == "resp_123"
    assert attributes["input.value"] == "Tell me a joke"
    assert attributes["output.value"] == "Knock knock"
    assert attributes["llm.model_name"] == "GigaChat-2-Max"
    assert attributes["llm.input_messages.0.message.role"] == "system"
    assert (
        attributes["llm.input_messages.1.message.tool_calls.0.tool_call.function.name"]
        == "get_weather"
    )
    assert attributes["llm.output_messages.1.message.content"] == "Knock knock"
    assert attributes["llm.tools.0.tool.name"] == "get_weather"
    assert attributes["llm.invocation_parameters"] == '{"reasoning":{"effort":"high"}}'
    assert attributes["llm.token_count.total"] == 30


def test_otlp_protobuf_payload_contains_http_and_genai_attributes():
    payload = _build_otlp_traces_protobuf_payload(
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

    parsed = ExportTraceServiceRequest()
    parsed.ParseFromString(payload)
    span = parsed.resource_spans[0].scope_spans[0].spans[0]
    attributes = {item.key: item.value for item in span.attributes}

    assert span.name == "POST /chat/completions"
    assert attributes["http.request.method"].string_value == "POST"
    assert attributes["http.response.status_code"].int_value == 200
    assert attributes["gen_ai.request.model"].string_value == "GigaChat-2-Max"
    assert attributes["gen_ai.usage.total_tokens"].int_value == 30


def test_phoenix_sink_builds_otlp_endpoint_headers_and_project_name():
    config = SimpleNamespace(
        proxy_settings=SimpleNamespace(
            observability_sinks=["phoenix"],
            otlp_headers={"x-tenant": "team-a"},
            otlp_timeout_seconds=5.0,
            otlp_max_pending_requests=16,
            otlp_service_name="gpt2giga",
            runtime_store_namespace="test",
            mode="DEV",
            phoenix_base_url="http://phoenix:6006",
            phoenix_api_key="phx-secret",
            phoenix_project_name="gpt2giga-dev",
        )
    )

    hub = create_observability_hub(["phoenix"], config=config)
    sink = hub.get_sink("phoenix")

    assert sink is not None
    assert sink.name == "phoenix"
    assert sink._endpoint == "http://phoenix:6006/v1/traces"
    assert sink._content_type == "application/x-protobuf"
    assert sink._headers == {
        "x-tenant": "team-a",
        "authorization": "Bearer phx-secret",
    }
    assert sink._resource_attributes["openinference.project.name"] == "gpt2giga-dev"


def test_phoenix_sink_requires_base_url():
    config = SimpleNamespace(
        proxy_settings=SimpleNamespace(
            observability_sinks=["phoenix"],
            otlp_headers={},
            otlp_timeout_seconds=5.0,
            otlp_max_pending_requests=16,
            otlp_service_name="gpt2giga",
            runtime_store_namespace="test",
            mode="DEV",
            phoenix_base_url=None,
            phoenix_api_key=None,
            phoenix_project_name=None,
        )
    )

    with pytest.raises(RuntimeError, match="PHOENIX_BASE_URL"):
        create_observability_hub(["phoenix"], config=config)


def test_phoenix_sink_supports_grouped_proxy_settings():
    config = ProxyConfig(
        proxy=ProxySettings(
            observability_sinks=["phoenix"],
            otlp_headers={"x-tenant": "team-a"},
            otlp_timeout_seconds=5.0,
            otlp_max_pending_requests=16,
            otlp_service_name="gpt2giga",
            runtime_store_namespace="test",
            mode="DEV",
            phoenix_base_url="http://phoenix:6006",
            phoenix_api_key="phx-secret",
            phoenix_project_name="gpt2giga-dev",
        )
    )

    hub = create_observability_hub(["phoenix"], config=config)
    sink = hub.get_sink("phoenix")

    assert sink is not None
    assert sink._endpoint == "http://phoenix:6006/v1/traces"
    assert sink._headers == {
        "x-tenant": "team-a",
        "authorization": "Bearer phx-secret",
    }
    assert sink._resource_attributes["service.namespace"] == "test"
    assert sink._resource_attributes["openinference.project.name"] == "gpt2giga-dev"
